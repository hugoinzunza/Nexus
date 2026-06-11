"""Módulo Diario (journal): estadísticas de trading desde Binance — SOLO LECTURA.

Trae el PnL realizado de Futuros USDⓈ-M (neto de comisiones y funding), las
posiciones abiertas y los holdings de Spot, y arma un panel de estadísticas:
resumen, curva de equity y desgloses por par, sesión, día y hora.

REGLA DE ORO: solo lectura. Ver modules/journal/binance_client.py.

Si no hay credenciales (BINANCE_API_KEY / BINANCE_API_SECRET en el entorno), el
módulo no se rompe: responde "no configurado" y la vista muestra cómo conectarse.
"""
from __future__ import annotations

import json
import os
import threading
import time

from core.module_base import NexusModule
from . import binance_client as bc
from . import stats

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
INCOME_PATH = os.path.join(DATA_DIR, "journal_income.json")

STABLES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "USDP"}


class JournalModule(NexusModule):
    slug = "journal"
    title = "Diario"
    description = "Estadísticas de tu trading en Binance (solo lectura): PnL, win rate, horarios."
    icon = "📒"

    def __init__(self, context):
        super().__init__(context)
        cfg = self.config
        self.lookback_days = int(os.environ.get("BINANCE_LOOKBACK_DAYS",
                                                cfg.get("lookback_days", 365)))
        self.cache_ttl = int(cfg.get("cache_ttl_seconds", 180))
        self._lock = threading.Lock()
        self._payload = None
        self._payload_ts = 0

    # --- API -----------------------------------------------------------
    def api(self, subpath, query):
        if subpath == "status":
            return self._json(200, {"configured": bc.have_keys(),
                                    "lookback_days": self.lookback_days})
        if subpath == "stats":
            if not bc.have_keys():
                return self._json(200, {"configured": False})
            force = query.get("refresh") == "1"
            try:
                payload = self._get_payload(force)
                return self._json(200, payload)
            except Exception as exc:  # noqa: BLE001 - error ya saneado por el cliente
                self.context.log(f"journal: error armando panel: {type(exc).__name__}")
                return self._json(200, {"configured": True, "error": str(exc)})
        return None

    # --- Construcción del panel (con caché TTL) ------------------------
    def _get_payload(self, force=False):
        with self._lock:
            if (not force and self._payload is not None
                    and (time.time() - self._payload_ts) < self.cache_ttl):
                return self._payload
            payload = self._build()
            self._payload = payload
            self._payload_ts = time.time()
            return payload

    def _build(self):
        now = int(time.time() * 1000)
        payload = {"configured": True, "generated_at_ms": now,
                   "lookback_days": self.lookback_days,
                   "futures": {"ok": False}, "spot": {"ok": False}}

        # --- Futuros: income → trades cerrados + métricas ---
        try:
            income = self._load_income(now)
            trades = stats.reconstruct_trades(income)
            payload["futures"] = {
                "ok": True,
                "summary": stats.metrics(trades),
                "equity": stats.equity_curve(trades),
                **stats.breakdowns(trades),
                "trades_count": len(trades),
            }
            payload["futures"]["open_positions"] = self._open_positions()
            payload["futures"]["balance"] = self._futures_balance()
        except Exception as exc:  # noqa: BLE001
            payload["futures"] = {"ok": False, "error": str(exc)}

        # --- Spot: holdings valorizados ---
        try:
            payload["spot"] = self._spot_holdings()
        except Exception as exc:  # noqa: BLE001
            payload["spot"] = {"ok": False, "error": str(exc)}

        return payload

    # --- Income con persistencia incremental ---------------------------
    def _load_income(self, now):
        os.makedirs(DATA_DIR, exist_ok=True)
        cached = {"rows": [], "last_time": 0}
        if os.path.isfile(INCOME_PATH):
            try:
                with open(INCOME_PATH, "r", encoding="utf-8") as fh:
                    cached = json.load(fh)
            except Exception:  # noqa: BLE001
                cached = {"rows": [], "last_time": 0}

        lookback_start = now - self.lookback_days * 86_400_000
        since = max(int(cached.get("last_time", 0)) + 1, lookback_start)
        # Si la caché no llega tan atrás como el lookback, rebajamos desde el inicio.
        if not cached["rows"] or cached["rows"][0]["time"] > lookback_start:
            since = lookback_start
            cached = {"rows": [], "last_time": 0}

        new_rows = bc.futures_income(since, now)
        seen = {(r.get("tranId"), r.get("time"), r.get("incomeType")) for r in cached["rows"]}
        for r in new_rows:
            k = (r.get("tranId"), r.get("time"), r.get("incomeType"))
            if k not in seen:
                seen.add(k)
                cached["rows"].append(r)
        cached["rows"].sort(key=lambda x: int(x["time"]))
        # Recortamos al lookback para no crecer sin límite.
        cached["rows"] = [r for r in cached["rows"] if int(r["time"]) >= lookback_start]
        cached["last_time"] = cached["rows"][-1]["time"] if cached["rows"] else now
        with open(INCOME_PATH, "w", encoding="utf-8") as fh:
            json.dump(cached, fh)
        return cached["rows"]

    # --- Posiciones abiertas (futuros) ---------------------------------
    def _open_positions(self):
        out = []
        for p in bc.futures_positions():
            amt = float(p.get("positionAmt", 0))
            if amt == 0:
                continue
            out.append({
                "symbol": p.get("symbol"),
                "side": "LONG" if amt > 0 else "SHORT",
                "size": abs(amt),
                "entry": float(p.get("entryPrice", 0)),
                "mark": float(p.get("markPrice", 0)),
                "unrealized": round(float(p.get("unRealizedProfit", 0)), 2),
                "leverage": p.get("leverage"),
            })
        out.sort(key=lambda x: x["unrealized"])
        return out

    def _futures_balance(self):
        usdt = {"asset": "USDT", "wallet": 0.0, "available": 0.0, "unrealized": 0.0}
        for b in bc.futures_balances():
            if b.get("asset") == "USDT":
                usdt = {"asset": "USDT",
                        "wallet": round(float(b.get("balance", 0)), 2),
                        "available": round(float(b.get("availableBalance", 0)), 2),
                        "unrealized": round(float(b.get("crossUnPnl", 0)), 2)}
        return usdt

    # --- Holdings de Spot valorizados ----------------------------------
    def _spot_holdings(self):
        acct = bc.spot_account()
        prices = bc.all_prices()
        holdings = []
        total = 0.0
        for bal in acct.get("balances", []):
            qty = float(bal.get("free", 0)) + float(bal.get("locked", 0))
            if qty <= 0:
                continue
            asset = bal.get("asset")
            if asset in STABLES:
                value = qty
            else:
                p = prices.get(asset + "USDT") or prices.get(asset + "FDUSD") or prices.get(asset + "BUSD")
                value = qty * p if p else None
            if value is not None and value < 1:  # ignoramos polvo (<1 USD)
                continue
            holdings.append({"asset": asset, "qty": qty,
                             "value": round(value, 2) if value is not None else None})
            total += value or 0
        holdings.sort(key=lambda x: (x["value"] is None, -(x["value"] or 0)))
        return {"ok": True, "total_value": round(total, 2), "holdings": holdings}

    # --- Helpers -------------------------------------------------------
    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        return (status, "application/json; charset=utf-8", body)

    def health(self):
        return {"slug": self.slug, "status": "ok",
                "binance_configured": bc.have_keys()}


def get_module(context):
    return JournalModule(context)
