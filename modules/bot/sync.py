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
        }

    # --- ciclo ---------------------------------------------------------
    def push_and_pull(self) -> None:
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
