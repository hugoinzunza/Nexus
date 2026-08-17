"""Bot3: la estrategia del curso Bitcoin Traders (playbook.v1) como bot PAPER
con libro virtual propio y aislado.

Mismo contrato de aislamiento que Bot2: solo lee OHLCV público/versionado y
ejecuta la simulación causal. No importa el ejecutor, clientes privados ni
credenciales; no expone endpoints de escritura; no toca el diario real, el Bot
ni ECON-COHORT-001.
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
MAX_BARS = 8_000


class Bot3Module(NexusModule):
    slug = "bot3"
    title = "Bot3 · Curso BTA"
    description = "Bot paper de la estrategia del curso (playbook.v1) con diario virtual aislado."
    icon = "B3"

    def __init__(self, context):
        super().__init__(context)
        self._lock = threading.Lock()
        self._cache = {}

    def public_dir(self):
        return os.path.join(os.path.dirname(__file__), "public")

    def _pairs(self):
        return list(self.config.get("pairs") or ["BTCUSDT", "ETHUSDT"])

    def _timeframes(self):
        return list(self.config.get("timeframes") or ["15m", "1h"])

    @staticmethod
    def _versioned(symbol, tf):
        path = os.path.join(ROOT, "data", f"klines_{symbol}_{tf}.json")
        try:
            with open(path, encoding="utf-8") as fh:
                rows = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return []
        return rows if isinstance(rows, list) else []

    def _candles(self, symbol, tf, window):
        historical = self._versioned(symbol, tf)
        pushed, meta = klines_push.serie_con_meta(ROOT, symbol, tf, 2_000)
        merged = {int(row["t"]): row for row in historical}
        merged.update({int(row["t"]): row for row in pushed})
        rows = [merged[t] for t in sorted(merged)][-window:]
        closed = P.velas_cerradas(rows, tf, int(time.time() * 1000))
        source = "historico+vps_binance" if pushed else "historico_versionado"
        return closed, source, meta

    def api(self, subpath, query, user=None):
        if subpath not in ("state", "book"):
            return None
        if subpath == "state":
            return self._json(200, {
                "research_only": True,
                "execution_enabled": False,
                "pairs": self._pairs(),
                "timeframes": self._timeframes(),
                "contrato": self.config.get("_contrato_nota"),
            })
        symbol = (query.get("symbol") or self._pairs()[0]).upper()
        tf = query.get("tf") or self._timeframes()[0]
        if symbol not in self._pairs() or tf not in self._timeframes():
            return self._json(400, {"error": "mercado no habilitado"})
        key = (symbol, tf)
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.time() - cached[0] < TTL:
                return self._json(200, cached[1])
        window = int(self.config.get("max_bars") or MAX_BARS)
        sel, source, meta = self._candles(symbol, tf, window)
        rector_tf = strategy.RECTOR_TF.get(tf)
        rector = []
        if rector_tf:
            rector, _, _ = self._candles(symbol, rector_tf, window)
        result = strategy.simulate(sel, rector, tf)
        result.update({
            "symbol": symbol, "tf": tf, "rector_tf": rector_tf,
            # Auditoría 2026-08-17 (docs/AUDITORIA_CURSO_BOT3_2026-08-17.md):
            # RECHAZADO por look-ahead HTF (C-1) y confirmación incompleta.
            # Las métricas v1 son PROTOTIPO INVÁLIDO: no acumulan forward ni
            # entran a la evaluación de octubre. Pendiente Bot3.v2.
            "estado_auditoria": "FORWARD INVÁLIDO — prototipo v1 rechazado (2026-08-17); no acumular",
            "research_only": True, "execution_enabled": False,
            "source": source, "source_meta": meta,
            "as_of": int(sel[-1]["t"]) if sel else None,
            "bars": len(sel),
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
    return Bot3Module(context)
