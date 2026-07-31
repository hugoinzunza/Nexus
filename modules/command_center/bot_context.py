"""Proyección mínima y read-only del estado del Bot."""

from __future__ import annotations

import time
from typing import Callable, Mapping


class BotContextService:
    """Reduce el snapshot operativo sin exponer cuenta, órdenes ni P&L."""

    def __init__(
        self,
        *,
        clock_ms: Callable[[], int] | None = None,
        max_current_age_ms: int = 120_000,
    ):
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._max_current_age_ms = max_current_age_ms

    def project(self, source: Mapping) -> dict:
        now_ms = self._clock_ms()
        source_age_ms = self._source_age_ms(source, now_ms)
        stale = (
            source_age_ms is not None
            and source_age_ms > self._max_current_age_ms
        )
        mode, state, severity = self._operational(source, stale)
        latest = self._latest_signal(source.get("trades") or [], now_ms)
        return {
            "generated_at_ms": now_ms,
            "state": state,
            "mode": mode,
            "severity": severity,
            "source": str(source.get("source") or "unknown"),
            "source_age_seconds": (
                round(source_age_ms / 1000, 1)
                if source_age_ms is not None
                else None
            ),
            "latest_signal": latest,
            "read_only": True,
        }

    @staticmethod
    def _source_age_ms(source: Mapping, now_ms: int) -> int | None:
        if type(source.get("age_seconds")) in (int, float):
            return max(0, int(float(source["age_seconds"]) * 1000))
        received = source.get("_received_at_ms") or source.get("ts")
        if type(received) is int and received >= 0:
            return max(0, now_ms - received)
        return None

    @staticmethod
    def _operational(source: Mapping, stale: bool) -> tuple[str, str, str]:
        live = bool(source.get("live"))
        active = bool(source.get("active"))
        kill = bool(source.get("kill"))
        if stale:
            return ("live" if live else "dry-run", "degraded", "warning")
        if kill:
            return ("live" if live else "dry-run", "paused", "warning")
        if live and active:
            return ("live", "ready", "normal")
        if live and not active:
            return ("live", "degraded", "warning")
        return ("dry-run", "ready", "info")

    @staticmethod
    def _latest_signal(trades, now_ms: int) -> dict | None:
        candidates = [trade for trade in trades if isinstance(trade, Mapping)]
        if not candidates:
            return None

        def timestamp(trade: Mapping, key: str) -> int:
            try:
                value = int(trade.get(key) or 0)
            except (TypeError, ValueError):
                return 0
            return max(0, value)

        latest = max(
            candidates,
            key=lambda trade: max(
                timestamp(trade, "closed_at"),
                timestamp(trade, "opened_at"),
            ),
        )
        occurred_s = timestamp(latest, "closed_at") or timestamp(
            latest, "opened_at"
        )
        occurred_ms = occurred_s * 1000 if occurred_s else None
        pair = str(latest.get("pair") or latest.get("symbol") or "Activo")
        pair = pair.replace("_USDT", "").replace("USDT", "")
        direction = str(latest.get("dir") or "unknown")
        status = str(latest.get("status") or "unknown")
        mode = str(latest.get("mode") or "unknown")
        return {
            "pair": pair,
            "direction": direction,
            "status": status,
            "mode": mode,
            "occurred_at_ms": occurred_ms,
            "age_seconds": (
                round(max(0, now_ms - occurred_ms) / 1000, 1)
                if occurred_ms is not None
                else None
            ),
        }
