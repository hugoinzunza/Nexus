"""Proyección de UI para MediaController sin activar adaptadores productivos."""

from __future__ import annotations

import time
from typing import Callable, Mapping

from .media_controller import (
    MediaAckStatus,
    MediaAction,
    MediaCapability,
    MediaCommand,
    MediaController,
)
from .operations import OperationContext


class MediaCommandsDisabled(RuntimeError):
    """La superficie no fue autorizada para producir efectos."""


class MediaSurfaceService:
    """Adapta MediaController a una lectura compacta y auditable."""

    def __init__(
        self,
        controller: MediaController | None = None,
        *,
        commands_enabled: bool = False,
        clock_ms: Callable[[], int] | None = None,
        metadata_resolver: Callable[[str], Mapping | None] | None = None,
        timeout_seconds: float = 0.75,
    ):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds debe ser positivo")
        self._controller = controller
        self._commands_enabled = bool(commands_enabled)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._metadata_resolver = metadata_resolver or (lambda _ref: None)
        self._timeout_seconds = timeout_seconds

    def inactive_snapshot(self) -> dict:
        """Estado síncrono usado mientras no exista una factory autorizada."""
        return {
            "generated_at_ms": self._clock_ms(),
            "provider": None,
            "lifecycle": "unavailable",
            "playback": "unknown",
            "freshness": "unknown",
            "observed_at_ms": None,
            "track": None,
            "artist": None,
            "album": None,
            "item_ref": None,
            "capabilities": [],
            "commands_enabled": False,
            "read_only": True,
            "code": "media.factory-inactive",
        }

    async def snapshot(self) -> dict:
        if self._controller is None:
            return self.inactive_snapshot()
        context = OperationContext.with_timeout(self._timeout_seconds)
        health = await self._controller.health(context)
        capabilities = self._controller.capabilities()
        result = {
            "generated_at_ms": self._clock_ms(),
            "provider": self._controller.controller_id,
            "lifecycle": health.lifecycle.value,
            "playback": "unknown",
            "freshness": "unknown",
            "observed_at_ms": None,
            "track": None,
            "artist": None,
            "album": None,
            "item_ref": None,
            "capabilities": sorted(item.value for item in capabilities),
            "commands_enabled": self._commands_enabled,
            "read_only": not self._commands_enabled,
            "code": health.code,
        }
        if MediaCapability.CURRENT_STATE not in capabilities:
            return result
        state = await self._controller.current_state(
            OperationContext.with_timeout(self._timeout_seconds)
        )
        result.update(
            {
                "lifecycle": state.lifecycle.value,
                "playback": str(state.playback or "unknown"),
                "freshness": self._freshness(state.observed_at_ms),
                "observed_at_ms": state.observed_at_ms,
                "item_ref": state.item_ref,
            }
        )
        if state.item_ref:
            metadata = self._metadata_resolver(state.item_ref)
            if isinstance(metadata, Mapping):
                for field in ("track", "artist", "album"):
                    value = metadata.get(field)
                    if isinstance(value, str) and value.strip():
                        result[field] = value.strip()[:160]
        return result

    async def execute(
        self,
        *,
        command_id: str,
        action: MediaAction,
        issued_at_ms: int | None = None,
        arguments: Mapping | None = None,
    ) -> dict:
        if not self._commands_enabled or self._controller is None:
            raise MediaCommandsDisabled(
                "los comandos multimedia no están habilitados"
            )
        command = MediaCommand(
            command_id,
            action,
            self._clock_ms() if issued_at_ms is None else issued_at_ms,
            arguments,
        )
        ack = await self._controller.execute(
            command,
            OperationContext.with_timeout(self._timeout_seconds),
        )
        result = {
            "command_id": ack.command_id,
            "provider": ack.controller_id,
            "action": ack.action.value,
            "status": ack.status.value,
            "completed_at_ms": ack.completed_at_ms,
            "code": ack.code,
            "retryable": ack.retryable,
            "reconciled_state": None,
        }
        if ack.status is MediaAckStatus.UNKNOWN:
            result["reconciled_state"] = await self.snapshot()
        return result

    def _freshness(self, observed_at_ms: int) -> str:
        age_ms = max(0, self._clock_ms() - observed_at_ms)
        if age_ms <= 15_000:
            return "live"
        if age_ms <= 60_000:
            return "current"
        return "stale"
