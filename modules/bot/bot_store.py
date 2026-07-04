"""Libro de operaciones REALES del bot espejo (NexUX BOT).

Gemelo honesto del forward-test del diario (`setups_store.py`), pero en vez de
simular, registra lo que el bot EJECUTÓ en Binance Futuros real: entrada, qty,
apalancamiento, parciales, cierre, comisiones y P&L. Cada registro queda atado al
setup del diario que lo originó (`setup_id = key:ts_created`), para comparar luego
"lo que el diario dijo" vs "lo que pasó de verdad".

Persistencia atómica en `data/bot_trades.json` (gitignored, como el resto del
estado vivo). Thread-safe (lo escribe el poller del módulo trading).

Campo `mode`: "dry" (simulado, sin tocar Binance) o "live" (orden real enviada).
El P&L y las comisiones en modo "dry" son ESTIMADOS; en "live" se calculan con los
precios de fill reales (las comisiones exactas se reconcilian aparte).
"""
from __future__ import annotations

import json
import os
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
TRADES_PATH = os.path.join(DATA_DIR, "bot_trades.json")

_OPEN = "abierta"
_CLOSED = "cerrada"


def load_all(path: str = TRADES_PATH) -> list:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


class BotStore:
    """Libro de operaciones reales del bot. Thread-safe, persistencia atómica."""

    def __init__(self, path: str = TRADES_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._trades = load_all(path)

    def _save(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._trades, fh, ensure_ascii=False)
        os.replace(tmp, self.path)

    # --- escritura -----------------------------------------------------
    def get_open(self, setup_id: str) -> dict | None:
        """Operación ABIERTA atada a ese setup (o None). No bloquea: uso interno
        bajo el lock del caller, o lectura best-effort."""
        for t in self._trades:
            if t["setup_id"] == setup_id and t["status"] == _OPEN:
                return t
        return None

    def has_trade(self, setup_id: str) -> bool:
        """¿Ya existe CUALQUIER operación (abierta o cerrada) para ese setup?
        Clave para la idempotencia: no abrir dos veces el mismo setup."""
        with self._lock:
            return any(t["setup_id"] == setup_id for t in self._trades)

    def open_trade(self, rec: dict) -> dict:
        """Registra una apertura. `rec` ya trae todo calculado por el ejecutor.
        Idempotente: si ya hay una operación para ese setup, no la duplica."""
        with self._lock:
            for t in self._trades:
                if t["setup_id"] == rec["setup_id"]:
                    return t  # ya registrada (idempotencia)
            t = {
                "setup_id": rec["setup_id"],
                "key": rec.get("key"),
                "symbol": rec["symbol"],
                "pair": rec.get("pair"),
                "dir": rec["dir"],
                "source": rec.get("source"),
                "mode": rec.get("mode", "dry"),
                "leverage": rec.get("leverage"),
                "qty": rec["qty"],
                "qty_open": rec["qty"],          # cantidad aún abierta (baja con parciales)
                "entry_price": rec["entry_price"],
                "setup_entry": rec.get("setup_entry"),  # entry del setup (para TP1/TP2)
                "sl": rec.get("sl"),
                "tp": rec.get("tp"),
                "poi_tf": rec.get("poi_tf"),
                "rr": rec.get("rr"),
                "disc_ok": rec.get("disc_ok"),
                "quality": rec.get("quality"),
                "quality_reason": rec.get("quality_reason"),
                "sl_pct": rec.get("sl_pct"),
                "risk_usd": rec.get("risk_usd"),
                "risk_usd_est": rec.get("risk_usd_est"),
                "risk_pct_account": rec.get("risk_pct_account"),
                "margin_used": rec.get("margin_used"),
                "fee_est_roundtrip": rec.get("fee_est_roundtrip"),
                "notional": rec.get("notional"),
                "fee_rate": rec.get("fee_rate", 0.0005),
                "fees_usd": rec.get("entry_fee_usd", 0.0),
                "opened_at": int(rec.get("ts", time.time())),
                "partials": [],
                "status": _OPEN,
                "closed_at": None,
                "exit_price": None,
                "result_r": None,
                "pnl_usd": None,
                "note": rec.get("note", ""),
            }
            self._trades.append(t)
            self._save()
            return t

    def add_partial(self, setup_id: str, leg: str, qty: float, price: float,
                    realized_r=None, fee_usd: float = 0.0) -> bool:
        """Anota un cierre PARCIAL (TP1/TP2): reduce qty_open y suma comisión.

        Idempotente por `leg`: si Binance/API/poller reintenta el mismo parcial, el
        libro no descuenta dos veces el remanente ni duplica comisiones estimadas.
        """
        with self._lock:
            t = self.get_open(setup_id)
            if not t:
                return False
            if any(p.get("leg") == leg for p in t.get("partials", [])):
                return False
            qty = round(min(max(float(qty or 0.0), 0.0), float(t.get("qty_open") or 0.0)), 8)
            if qty <= 0:
                return False
            t["partials"].append({
                "leg": leg, "qty": qty, "price": price,
                "realized_r": realized_r, "ts": int(time.time())})
            t["qty_open"] = round(max(0.0, t["qty_open"] - qty), 8)
            t["fees_usd"] = round(t["fees_usd"] + fee_usd, 4)
            self._save()
            return True

    def close_trade(self, setup_id: str, exit_price: float, result_r=None,
                    fee_usd: float = 0.0) -> dict | None:
        """Cierra la operación: calcula P&L con los parciales + el remanente."""
        with self._lock:
            t = self.get_open(setup_id)
            if not t:
                return None
            sign = 1.0 if t["dir"] == "long" else -1.0
            entry = t["entry_price"]
            # P&L bruto = suma de (precio - entry)*qty por cada tramo cerrado.
            gross = 0.0
            for p in t["partials"]:
                gross += sign * (p["price"] - entry) * p["qty"]
            gross += sign * (exit_price - entry) * t["qty_open"]
            t["fees_usd"] = round(t["fees_usd"] + fee_usd, 4)
            t["exit_price"] = exit_price
            t["result_r"] = result_r
            t["pnl_usd"] = round(gross - t["fees_usd"], 4)
            t["qty_open"] = 0.0
            t["status"] = _CLOSED
            t["closed_at"] = int(time.time())
            self._save()
            return t

    def confirm_pnl(self, setup_id: str, pnl_neto: float, commission: float) -> bool:
        """Reemplaza el P&L/comisiones ESTIMADOS por los REALES de Binance (income).
        Marca pnl_confirmed para no volver a consultarlo."""
        with self._lock:
            for t in self._trades:
                if t["setup_id"] == setup_id and t["status"] == _CLOSED:
                    t["pnl_usd"] = round(pnl_neto, 4)
                    t["fees_usd"] = round(abs(commission), 4)
                    t["pnl_confirmed"] = True
                    self._save()
                    return True
        return False

    # --- lectura -------------------------------------------------------
    def all(self) -> list:
        with self._lock:
            return list(self._trades)

    def realized_pnl_since(self, ts_from: float) -> float:
        """P&L realizado de operaciones cerradas desde `ts_from` (para el tope
        de pérdida diaria)."""
        with self._lock:
            return round(sum((t.get("pnl_usd") or 0.0) for t in self._trades
                             if t["status"] == _CLOSED and (t.get("closed_at") or 0) >= ts_from), 4)

    def summary(self) -> dict:
        with self._lock:
            trades = list(self._trades)
        closed = [t for t in trades if t["status"] == _CLOSED]
        openn = [t for t in trades if t["status"] == _OPEN]
        wins = [t for t in closed if (t.get("pnl_usd") or 0) > 0]
        losses = [t for t in closed if (t.get("pnl_usd") or 0) < 0]
        pnl = round(sum((t.get("pnl_usd") or 0.0) for t in closed), 2)
        fees = round(sum((t.get("fees_usd") or 0.0) for t in trades), 2)
        return {
            "total": len(trades),
            "abiertas": len(openn),
            "cerradas": len(closed),
            "ganadas": len(wins),
            "perdidas": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
            "pnl_usd": pnl,
            "fees_usd": fees,
            "modes": sorted({t.get("mode", "dry") for t in trades}),
            # Desglose por modo (honestidad: no mezclar P&L real con simulado en un
            # solo número). Aditivo: la UI vieja sigue funcionando con pnl_usd total.
            "by_mode": {
                m: {
                    "cerradas": len([t for t in closed if t.get("mode", "dry") == m]),
                    "pnl_usd": round(sum((t.get("pnl_usd") or 0.0)
                                         for t in closed if t.get("mode", "dry") == m), 2),
                } for m in sorted({t.get("mode", "dry") for t in trades})
            },
        }
