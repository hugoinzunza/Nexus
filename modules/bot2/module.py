"""Bot2: laboratorio visible de acción del precio.

Este módulo solo lee OHLCV público/versionado y ejecuta simulaciones. No importa
el ejecutor, clientes privados ni credenciales, y no expone endpoints de escritura.
"""
from __future__ import annotations

import json
import os
import threading
import time

from core import klines_push
from core.module_base import NexusModule
from modules.inteligencia import precio as P
from . import strategy

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TTL = 300
MAX_BARS = 40_000


class Bot2Module(NexusModule):
    slug = "bot2"
    title = "Bot2 · Acción del precio"
    description = "Laboratorio causal de fases, entradas y gestión virtual."
    icon = "B2"

    def __init__(self, context):
        super().__init__(context)
        self._lock = threading.Lock()
        self._cache = {}

    def public_dir(self):
        return os.path.join(os.path.dirname(__file__), "public")

    def _pairs(self):
        return list(self.config.get("pairs") or ["BTCUSDT", "ETHUSDT"])

    def _timeframes(self):
        return list(self.config.get("timeframes") or ["1h", "4h", "1d"])

    @staticmethod
    def _versioned(symbol, tf):
        path = os.path.join(ROOT, "data", f"klines_{symbol}_{tf}.json")
        try:
            with open(path, encoding="utf-8") as fh:
                rows = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return []
        return rows if isinstance(rows, list) else []

    def _candles(self, symbol, tf):
        historical = self._versioned(symbol, tf)
        pushed, meta = klines_push.serie_con_meta(ROOT, symbol, tf, 2_000)
        merged = {int(row["t"]): row for row in historical}
        merged.update({int(row["t"]): row for row in pushed})
        # La vista corre en el handler síncrono del servidor: con piv=3 el análisis
        # sobre 35k velas de 1h tarda minutos y estrangula el event loop entero
        # (quedó demostrado el 2026-08-15 con el panel completo bloqueado). El visor
        # usa una ventana acotada; los estudios de historial completo van offline.
        window = int(self.config.get("max_bars") or MAX_BARS)
        rows = [merged[t] for t in sorted(merged)][-window:]
        closed = P.velas_cerradas(rows, tf, int(time.time() * 1000))
        source = "historico+vps_binance" if pushed else "historico_versionado"
        return closed, source, meta

    def api(self, subpath, query, user=None):
        if subpath not in ("state", "analysis"):
            return None
        if subpath == "state":
            return self._json(200, {
                "research_only": True,
                "execution_enabled": False,
                "pairs": self._pairs(),
                "timeframes": self._timeframes(),
                "variants": list(strategy.VARIANTS),
                "target_policies": list(strategy.TARGET_POLICIES),
            })
        symbol = (query.get("symbol") or self._pairs()[0]).upper()
        tf = query.get("tf") or self._timeframes()[0]
        variant = query.get("variant") or strategy.VARIANTS[0]
        target_policy = query.get("target") or "projection"
        if symbol not in self._pairs() or tf not in self._timeframes():
            return self._json(400, {"error": "mercado no habilitado"})
        if variant not in strategy.VARIANTS:
            return self._json(400, {"error": "variante no habilitada"})
        if target_policy not in strategy.TARGET_POLICIES:
            return self._json(400, {"error": "política de target no habilitada"})
        key = (symbol, tf, variant, target_policy)
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.time() - cached[0] < TTL:
                return self._json(200, cached[1])
        candles, source, meta = self._candles(symbol, tf)
        result = strategy.analyze(
            candles, tf, variant,
            piv=int(self.config.get("piv") or strategy.PIV),
            min_net_rr=float(self.config.get("min_net_rr") or strategy.MIN_NET_RR),
            target_policy=target_policy,
        )
        result.update({
            "symbol": symbol,
            "source": source,
            "source_meta": meta,
            "candles": candles[-1_800:],
            "as_of": int(candles[-1]["t"]) if candles else None,
        })
        with self._lock:
            self._cache[key] = (time.time(), result)
        return self._json(200, result)

    @staticmethod
    def _json(status, data):
        return status, "application/json; charset=utf-8", \
            json.dumps(data, ensure_ascii=False).encode()

    def health(self):
        return {"slug": self.slug, "status": "ok", "mode": "research",
                "execution": False}


def get_module(context):
    return Bot2Module(context)
