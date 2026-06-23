"""Módulo NexUX BOT — libro de la operación REAL en Binance Futuros.

Gemelo del Diario, pero en vez del forward-test (paper) muestra lo que el bot
EJECUTÓ de verdad: operaciones reales atadas a cada setup, con su P&L y comisiones.

Este módulo solo LEE el libro (`data/bot_trades.json`); quien escribe es el ejecutor
(`executor.py`), invocado desde el poller del módulo trading. Lee fresco del disco en
cada request para reflejar lo último que ejecutó el bot.

Endpoints:
  GET /m/bot/api/trades   operaciones + resumen + estado (live/dry, activo).
"""
from __future__ import annotations

import json

from core.module_base import NexusModule


class BotModule(NexusModule):
    slug = "bot"
    title = "NexUX BOT"
    description = "Operación real del bot espejo en Binance Futuros: trades, P&L y comisiones de verdad."
    icon = "🤖"

    def api(self, subpath, query, user=None):
        if subpath == "trades":
            from .bot_store import BotStore
            from .executor import load_config, _trade_creds
            store = BotStore()
            cfg = load_config()
            key, _sec = _trade_creds()
            trades = sorted(store.all(), key=lambda t: t.get("opened_at", 0), reverse=True)
            return self._json(200, {
                "has_data": bool(trades),
                "summary": store.summary(),
                "trades": trades,
                "live": bool(cfg.get("live")),
                "active": bool(cfg.get("enabled")) and bool(key),
                "base_equity": cfg.get("base_equity"),
                "risk_pct": cfg.get("risk_pct"),
                "pairs": cfg.get("pairs"),
            })
        return None

    def _json(self, status, obj):
        return (status, "application/json; charset=utf-8",
                json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def health(self):
        from .executor import _trade_creds
        key, _ = _trade_creds()
        return {"slug": self.slug, "status": "ok", "has_keys": bool(key)}


def get_module(context):
    return BotModule(context)
