"""Proyección read-only de observaciones de IA para el Command Center."""

from __future__ import annotations

import time
from typing import Callable, Mapping


_SEVERITIES = {"normal", "info", "warning", "critical"}
_STATES = {"ready", "disabled", "degraded", "unknown"}
_FRESHNESS = {"live", "current", "stale", "unknown"}


class AiObservationInvalid(ValueError):
    """La observación no cumple el contrato local de Línea B."""


class AiContextService:
    """Normaliza evidencia existente sin invocar modelos externos."""

    def __init__(
        self,
        *,
        observation_loader: Callable[[], Mapping | None] | None = None,
        enabled_loader: Callable[[], bool] | None = None,
        clock_ms: Callable[[], int] | None = None,
    ):
        self._observation_loader = observation_loader or (lambda: None)
        self._enabled_loader = enabled_loader or (lambda: False)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def snapshot(self) -> dict:
        now_ms = self._clock_ms()
        enabled = bool(self._enabled_loader())
        try:
            source = self._observation_loader()
        except Exception as exc:  # noqa: BLE001
            return self._empty(
                now_ms,
                state="degraded",
                reason=f"observation-loader.{type(exc).__name__}",
            )
        if source is None:
            return self._empty(
                now_ms,
                state="unknown" if enabled else "disabled",
                reason=(
                    "ai-observation-unavailable"
                    if enabled
                    else "ai-disabled"
                ),
            )
        return self._normalize(source, now_ms)

    @staticmethod
    def _empty(now_ms: int, *, state: str, reason: str) -> dict:
        return {
            "generated_at_ms": now_ms,
            "state": state,
            "last_evaluation_ms": None,
            "severity": "normal",
            "summary": None,
            "freshness": "unknown",
            "source": None,
            "reason": reason,
        }

    @staticmethod
    def _normalize(source: Mapping, now_ms: int) -> dict:
        state = str(source.get("state", "ready"))
        severity = str(source.get("severity", "normal"))
        freshness = str(source.get("freshness", "unknown"))
        summary = str(source.get("summary", "")).strip()
        observed_at = source.get("last_evaluation_ms")
        provider = str(source.get("source", "")).strip()
        if state not in _STATES:
            raise AiObservationInvalid("state no permitido")
        if severity not in _SEVERITIES:
            raise AiObservationInvalid("severity no permitida")
        if freshness not in _FRESHNESS:
            raise AiObservationInvalid("freshness no permitida")
        if not summary or len(summary) > 180:
            raise AiObservationInvalid("summary debe tener 1-180 caracteres")
        if (
            type(observed_at) is not int
            or observed_at < 0
            or observed_at > now_ms + 60_000
        ):
            raise AiObservationInvalid("last_evaluation_ms invalido")
        if not provider:
            raise AiObservationInvalid("source es obligatorio")
        return {
            "generated_at_ms": now_ms,
            "state": state,
            "last_evaluation_ms": observed_at,
            "severity": severity,
            "summary": summary,
            "freshness": freshness,
            "source": provider,
            "reason": None,
        }
