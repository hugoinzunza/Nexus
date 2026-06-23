"""Sincronizador del bot VPS → Railway (espejo + cola de comandos).

El VPS es el único que toca Binance; la web pública corre en Railway. Para que el
panel NexUX BOT muestre el estado real sin que Hugo entre a Binance, el VPS EMPUJA
periódicamente un snapshot (balance, posiciones, órdenes, libro) a Railway, y en la
RESPUESTA recibe los comandos que dejó la web (parar / reanudar / cerrar posición),
que ejecuta en Binance. Mismo patrón que el colector del Diario, pero bidireccional.

Se invoca desde el poller del módulo trading cada N ticks (no cada 2s). Si no hay
token/URL de ingesta o no hay cliente de subcuenta, no hace nada.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .executor import KILL_FILE, TRADE_ENV  # noqa: F401  (rutas compartidas)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COLLECTOR_ENV = os.path.join(ROOT, "deploy", "collector.env")


def _from_env_or_file(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if v:
        return v
    if os.path.exists(COLLECTOR_ENV):
        try:
            with open(COLLECTOR_ENV, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith(name + "="):
                        return line.split("=", 1)[1].strip()
        except OSError:
            pass
    return ""


class BotSync:
    def __init__(self, executor, log):
        self.executor = executor
        self.log = log

    # --- destino -------------------------------------------------------
    @staticmethod
    def _token() -> str:
        return _from_env_or_file("NEXUS_INGEST_TOKEN")

    @staticmethod
    def _ingest_url() -> str:
        base = _from_env_or_file("NEXUS_INGEST_URL")  # .../m/journal/api/ingest
        if not base:
            return ""
        return base.split("/m/")[0] + "/m/bot/api/ingest"

    # --- snapshot ------------------------------------------------------
    def snapshot(self) -> dict:
        ex = self.executor
        cli = ex.client()
        account, positions, orders = {}, [], []
        if cli:
            try:
                b = cli.balance_usdt()
                account = {"balance": b["balance"], "available": b["available"],
                           "upnl": b["unrealized_pnl"]}
            except Exception as exc:  # noqa: BLE001
                account = {"error": str(exc)}
            try:
                positions = cli.positions()
            except Exception:  # noqa: BLE001
                pass
            try:
                orders = cli.open_orders()
            except Exception:  # noqa: BLE001
                pass
        return {
            "ts": int(time.time() * 1000),
            "live": ex.live, "active": ex.active, "kill": os.path.exists(KILL_FILE),
            "account": account, "positions": positions, "open_orders": orders,
            "summary": ex.store.summary(),
            "trades": sorted(ex.store.all(), key=lambda t: t.get("opened_at", 0), reverse=True),
            "watching": self._watching(),
        }

    def _watching(self) -> list:
        """Setups del diario EN VIGILANCIA (pendientes/activos) en los pares del bot:
        lo que el bot está esperando que se active para operar."""
        try:
            from modules.trading.setups_store import load_all
        except Exception:  # noqa: BLE001
            return []
        pairs = set(self.executor.cfg.get("pairs", []))
        out = []
        for s in load_all():
            if s.get("status") not in ("pendiente", "activo"):
                continue
            sym = (s.get("pair") or "").replace("_", "").upper()
            if pairs and sym not in pairs:
                continue
            out.append({
                "pair": s.get("pair"), "dir": s.get("dir"), "status": s.get("status"),
                "entry": s.get("entry"), "entry_lo": s.get("entry_lo"),
                "entry_hi": s.get("entry_hi"), "sl": s.get("sl"), "tp": s.get("tp"),
                "rr": s.get("rr"), "poi_tf": s.get("poi_tf"), "source": s.get("source"),
                "ts_created": s.get("ts_created"),
            })
        out.sort(key=lambda x: (x["status"] != "pendiente", -(x.get("ts_created") or 0)))
        return out

    # --- reconciliación (red de seguridad) -----------------------------
    def reconcile(self) -> None:
        """Cierra posiciones REALES de pares del bot que ya no tienen un setup ABIERTO
        en el diario (huérfanas): el setup cerró pero la posición quedó viva (p.ej. por
        divergencia de feed o un cierre que no se reflejó). Backup del cierre normal."""
        cli = self.executor.client()
        if not cli or not self.executor.live:
            return
        from modules.trading.setups_store import load_all
        open_syms = set()
        for s in load_all():
            if s.get("status") in ("pendiente", "activo"):
                open_syms.add((s.get("pair") or "").replace("_", "").upper())
        pairs = set(self.executor.cfg.get("pairs", []))
        for p in cli.positions():
            sym = p["symbol"]
            if sym not in pairs or sym in open_syms:
                continue
            side = "SELL" if p["side"] == "LONG" else "BUY"
            cli.market_order(sym, side, cli.round_qty(sym, p["qty"]), reduce_only=True,
                             client_id="nxrec" + str(int(time.time()))[-7:])
            try:
                cli.cancel_all_orders(sym)
            except Exception:  # noqa: BLE001
                pass
            px = cli.mark_price(sym)
            for t in self.executor.store.all():
                if t["symbol"] == sym and t["status"] == "abierta":
                    self.executor.store.close_trade(
                        t["setup_id"], round(px, 8), result_r=None,
                        fee_usd=round(px * p["qty"] * t.get("fee_rate", 0.0005), 4))
                    break
            self.log(f"bot: 🔧 reconciliación cerró posición huérfana {sym} (sin setup abierto en el diario)")

    def confirm_pnls(self) -> None:
        """Reemplaza el P&L estimado de las operaciones cerradas por el REAL de Binance
        (income: realized pnl + comisiones). Honestidad: el libro reporta lo de verdad."""
        cli = self.executor.client()
        if not cli:
            return
        for t in self.executor.store.all():
            if t["status"] != "cerrada" or t.get("pnl_confirmed"):
                continue
            start = int(t.get("opened_at", 0)) * 1000
            end = (int(t.get("closed_at", 0)) + 5) * 1000 if t.get("closed_at") else None
            if not start:
                continue
            try:
                r = cli.realized_pnl(t["symbol"], start, end)
                self.executor.store.confirm_pnl(t["setup_id"], r["neto"], r["commission"])
                self.log(f"bot: P&L REAL {t['symbol']}: {r['neto']:+.4f} USD "
                         f"(bruto {r['pnl_bruto']:+.4f}, comisión {r['commission']:.4f})")
            except Exception as exc:  # noqa: BLE001
                self.log(f"bot: no se pudo confirmar P&L real de {t['symbol']}: {exc}")

    # --- ciclo ---------------------------------------------------------
    def push_and_pull(self) -> None:
        try:
            self.reconcile()
        except Exception as exc:  # noqa: BLE001
            self.log(f"bot-sync: reconciliación falló: {exc}")
        try:
            self.confirm_pnls()
        except Exception as exc:  # noqa: BLE001
            self.log(f"bot-sync: confirmación de P&L falló: {exc}")
        url, token = self._ingest_url(), self._token()
        if not url or not token:
            return
        payload = json.dumps(self.snapshot()).encode()
        req = urllib.request.Request(url, data=payload, method="POST", headers={
            "Content-Type": "application/json", "X-Nexus-Token": token,
            "User-Agent": "Nexus-bot-sync/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                resp = json.load(r)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            self.log(f"bot-sync: no se pudo empujar a Railway: {exc}")
            return
        for c in (resp.get("commands") or []):
            try:
                self.apply_command(c)
            except Exception as exc:  # noqa: BLE001
                self.log(f"bot-sync: error aplicando comando {c}: {exc}")

    # --- comandos desde la web -----------------------------------------
    def apply_command(self, c: dict) -> None:
        action = (c or {}).get("action")
        if action == "kill":
            open(KILL_FILE, "w").close()
            self.log("bot-sync: 🛑 KILL-SWITCH activado desde la web")
        elif action == "resume":
            try:
                os.remove(KILL_FILE)
            except FileNotFoundError:
                pass
            self.log("bot-sync: ▶️ bot reanudado desde la web")
        elif action == "close":
            self._close_position(c.get("symbol"))

    def _close_position(self, symbol: str | None) -> None:
        cli = self.executor.client()
        if not cli or not symbol:
            return
        pos = cli.positions([symbol])
        if not pos:
            self.log(f"bot-sync: no hay posición en {symbol} para cerrar")
            return
        p = pos[0]
        side = "SELL" if p["side"] == "LONG" else "BUY"
        cli.market_order(symbol, side, cli.round_qty(symbol, p["qty"]), reduce_only=True,
                         client_id="nxman" + str(int(time.time()))[-7:])
        try:
            cli.cancel_all_orders(symbol)
        except Exception:  # noqa: BLE001
            pass
        # Reflejar el cierre manual en el libro (si había un trade abierto de ese par).
        px = p["entry"]
        try:
            px = cli.mark_price(symbol)
        except Exception:  # noqa: BLE001
            pass
        for t in self.executor.store.all():
            if t["symbol"] == symbol and t["status"] == "abierta":
                fee = px * p["qty"] * t.get("fee_rate", 0.0005)
                self.executor.store.close_trade(t["setup_id"], round(px, 8),
                                                result_r=None, fee_usd=round(fee, 4))
                t["note"] = "cierre manual desde la web"
                break
        self.log(f"bot-sync: ✋ posición {symbol} cerrada manualmente desde la web")
