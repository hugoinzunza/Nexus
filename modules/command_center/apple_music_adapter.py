"""Adaptador headless de Apple Music para MediaController."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .media_controller import (
    MediaAck,
    MediaAckStatus,
    MediaAction,
    MediaCapability,
    MediaCommand,
    MediaCommandConflict,
    MediaHealth,
    MediaLifecycle,
    MediaLifecycleError,
    MediaState,
)
from .operations import (
    OperationCancelled,
    OperationContext,
    OperationDeadlineExceeded,
    await_operation,
)

OSASCRIPT = "/usr/bin/osascript"
OPEN = "/usr/bin/open"
MUSIC_APP = "Music"
_FIELD_SEPARATOR = chr(31)

_IS_RUNNING_SCRIPT = 'application "Music" is running'
_PLAYBACK_PROBE_SCRIPT = (
    'tell application "Music" to get player state as text'
)
_SNAPSHOT_SCRIPT = """
tell application "Music"
    set stateValue to (player state as text)
    set volumeValue to sound volume
    set positionValue to player position
    set trackId to ""
    try
        set trackId to persistent ID of current track
    end try
    return stateValue & (ASCII character 31) & (volumeValue as text) & ¬
        (ASCII character 31) & (positionValue as text) & ¬
        (ASCII character 31) & trackId
end tell
""".strip()

_ACTION_SCRIPTS = {
    MediaAction.PLAY: 'tell application "Music" to play',
    MediaAction.PAUSE: 'tell application "Music" to pause',
    MediaAction.NEXT: 'tell application "Music" to next track',
    MediaAction.PREVIOUS: 'tell application "Music" to previous track',
}


class AppleMusicPortError(RuntimeError):
    """Fallo estable en la frontera de automatizacion de macOS."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        ambiguous: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class AppleMusicSnapshot:
    playback: str
    volume: float
    position_seconds: float | None
    persistent_id: str | None


class AppleMusicPort(Protocol):
    async def is_running(self, context: OperationContext) -> bool: ...

    async def probe_playback_access(
        self, context: OperationContext
    ) -> None: ...

    async def current_state(
        self, context: OperationContext
    ) -> AppleMusicSnapshot: ...

    async def execute(
        self,
        action: MediaAction,
        arguments: Mapping[str, Any],
        context: OperationContext,
    ) -> None: ...

    async def open_app(self, context: OperationContext) -> None: ...


class OsaScriptAppleMusicPort:
    """Puerto real; usa argumentos fijos y nunca invoca un shell."""

    async def is_running(self, context: OperationContext) -> bool:
        output = await self._run(
            (OSASCRIPT, "-l", "AppleScript", "-e", _IS_RUNNING_SCRIPT),
            context,
        )
        normalized = output.strip().lower()
        if normalized not in {"true", "false"}:
            raise AppleMusicPortError(
                "apple-music.invalid-running-state",
                "osascript devolvio un estado de ejecucion invalido",
                retryable=True,
            )
        return normalized == "true"

    async def probe_playback_access(
        self, context: OperationContext
    ) -> None:
        output = await self._run(
            (
                OSASCRIPT,
                "-l",
                "AppleScript",
                "-e",
                _PLAYBACK_PROBE_SCRIPT,
            ),
            context,
        )
        if output.strip() not in {
            "stopped",
            "playing",
            "paused",
            "fast forwarding",
            "rewinding",
        }:
            raise AppleMusicPortError(
                "apple-music.invalid-playback-probe",
                "Apple Music devolvio un estado de reproduccion invalido",
                retryable=True,
            )

    async def current_state(
        self, context: OperationContext
    ) -> AppleMusicSnapshot:
        output = await self._run(
            (OSASCRIPT, "-l", "AppleScript", "-e", _SNAPSHOT_SCRIPT),
            context,
        )
        return self._parse_snapshot(output)

    async def execute(
        self,
        action: MediaAction,
        arguments: Mapping[str, Any],
        context: OperationContext,
    ) -> None:
        if action is MediaAction.SET_VOLUME:
            volume = arguments.get("volume")
            if type(volume) not in (int, float) or not 0 <= volume <= 1:
                raise ValueError("volume debe estar entre 0 y 1")
            script = (
                'tell application "Music" to set sound volume to '
                f"{round(float(volume) * 100)}"
            )
        else:
            try:
                script = _ACTION_SCRIPTS[action]
            except KeyError as exc:
                raise ValueError(
                    f"accion no soportada por Apple Music: {action.value}"
                ) from exc
        await self._run(
            (OSASCRIPT, "-l", "AppleScript", "-e", script),
            context,
        )

    async def open_app(self, context: OperationContext) -> None:
        await self._run((OPEN, "-gj", "-a", MUSIC_APP), context)

    @staticmethod
    def _parse_snapshot(output: str) -> AppleMusicSnapshot:
        fields = output.rstrip("\r\n").split(_FIELD_SEPARATOR)
        if len(fields) != 4:
            raise AppleMusicPortError(
                "apple-music.invalid-snapshot",
                "Apple Music devolvio un snapshot incompleto",
                retryable=True,
            )
        playback, volume_text, position_text, persistent_id = fields
        try:
            volume = int(volume_text) / 100
            position = (
                None
                if position_text == "missing value"
                else float(position_text)
            )
        except ValueError as exc:
            raise AppleMusicPortError(
                "apple-music.invalid-snapshot",
                "Apple Music devolvio numeros invalidos",
                retryable=True,
            ) from exc
        if playback not in {
            "stopped",
            "playing",
            "paused",
            "fast forwarding",
            "rewinding",
        }:
            raise AppleMusicPortError(
                "apple-music.invalid-snapshot",
                "Apple Music devolvio un estado de reproduccion invalido",
                retryable=True,
            )
        if not 0 <= volume <= 1 or (
            position is not None and position < 0
        ):
            raise AppleMusicPortError(
                "apple-music.invalid-snapshot",
                "Apple Music devolvio un snapshot fuera de rango",
                retryable=True,
            )
        return AppleMusicSnapshot(
            playback.replace(" ", "_"),
            volume,
            position,
            persistent_id or None,
        )

    @staticmethod
    async def _run(
        command: tuple[str, ...],
        context: OperationContext,
    ) -> str:
        context.raise_if_cancelled()
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await await_operation(
                process.communicate(),
                context,
            )
        except OperationCancelled:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        except OperationDeadlineExceeded as exc:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise AppleMusicPortError(
                "apple-music.timeout",
                "la automatizacion de Apple Music excedio el deadline",
                retryable=True,
                ambiguous=True,
            ) from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            if "-1743" in detail:
                code = "apple-music.permission-denied"
                retryable = False
            elif "-600" in detail:
                code = "apple-music.not-running"
                retryable = True
            else:
                code = "apple-music.script-failed"
                retryable = True
            raise AppleMusicPortError(
                code,
                detail or "fallo la automatizacion de Apple Music",
                retryable=retryable,
                ambiguous=False,
            )
        return stdout.decode("utf-8", errors="strict")


class AppleMusicAdapter:
    """MediaController real, sin factory productiva ni efectos al construirlo."""

    controller_id = "apple-music"

    def __init__(
        self,
        port: AppleMusicPort | None = None,
        *,
        clock_ms=None,
        max_cached_commands: int = 1024,
    ):
        if type(max_cached_commands) is not int or max_cached_commands <= 0:
            raise ValueError("max_cached_commands debe ser positivo")
        self._port = port or OsaScriptAppleMusicPort()
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._max_cached = max_cached_commands
        self._closed = False
        self._command_lock: asyncio.Lock | None = None
        self._fingerprints: OrderedDict[str, tuple[Any, ...]] = OrderedDict()
        self._results: OrderedDict[str, MediaAck] = OrderedDict()
        self._metrics = {
            "health_checks": 0,
            "permission_probes": 0,
            "state_reads": 0,
            "commands": 0,
            "command_failures": 0,
            "unknown_results": 0,
            "cache_hits": 0,
            "last_error_code": None,
        }

    def capabilities(self) -> frozenset[MediaCapability]:
        return frozenset(MediaCapability)

    async def health(self, context: OperationContext) -> MediaHealth:
        self._metrics["health_checks"] += 1
        if self._closed:
            return self._health(MediaLifecycle.CLOSED, "apple-music.closed")
        try:
            running = await self._port.is_running(context)
        except AppleMusicPortError as exc:
            self._metrics["last_error_code"] = exc.code
            lifecycle = (
                MediaLifecycle.REVOKED
                if exc.code == "apple-music.permission-denied"
                else MediaLifecycle.DEGRADED
            )
            return self._health(
                lifecycle,
                exc.code,
                retryable=exc.retryable,
            )
        self._metrics["last_error_code"] = None
        if not running:
            return self._health(
                MediaLifecycle.UNAVAILABLE,
                "apple-music.not-running",
                retryable=True,
            )
        self._metrics["permission_probes"] += 1
        try:
            await self._port.probe_playback_access(context)
        except AppleMusicPortError as exc:
            self._metrics["last_error_code"] = exc.code
            lifecycle = (
                MediaLifecycle.REVOKED
                if exc.code == "apple-music.permission-denied"
                else MediaLifecycle.DEGRADED
            )
            return self._health(
                lifecycle,
                exc.code,
                retryable=exc.retryable,
            )
        return self._health(MediaLifecycle.READY)

    async def current_state(
        self, context: OperationContext
    ) -> MediaState:
        self._require_open()
        self._metrics["state_reads"] += 1
        if not await self._port.is_running(context):
            return MediaState(
                self.controller_id,
                MediaLifecycle.UNAVAILABLE,
                self._clock_ms(),
                "stopped",
            )
        try:
            snapshot = await self._port.current_state(context)
        except AppleMusicPortError as exc:
            self._metrics["last_error_code"] = exc.code
            if exc.code == "apple-music.not-running":
                return MediaState(
                    self.controller_id,
                    MediaLifecycle.UNAVAILABLE,
                    self._clock_ms(),
                    "stopped",
                )
            raise
        self._metrics["last_error_code"] = None
        item_ref = (
            f"music:{snapshot.persistent_id}"
            if snapshot.persistent_id
            else None
        )
        return MediaState(
            self.controller_id,
            MediaLifecycle.READY,
            self._clock_ms(),
            snapshot.playback,
            snapshot.volume,
            item_ref,
        )

    async def execute(
        self,
        command: MediaCommand,
        context: OperationContext,
    ) -> MediaAck:
        self._require_open()
        lock = self._get_command_lock()
        await await_operation(lock.acquire(), context)
        try:
            self._require_open()
            return await self._execute_locked(command, context)
        finally:
            lock.release()

    async def _execute_locked(
        self,
        command: MediaCommand,
        context: OperationContext,
    ) -> MediaAck:
        fingerprint = command.fingerprint()
        known = self._fingerprints.get(command.command_id)
        if known is not None and known != fingerprint:
            raise MediaCommandConflict(
                "command_id ya fue usado con otra operacion"
            )
        cached = self._results.get(command.command_id)
        if cached is not None:
            self._metrics["cache_hits"] += 1
            self._results.move_to_end(command.command_id)
            return cached

        self._fingerprints[command.command_id] = fingerprint
        self._metrics["commands"] += 1
        try:
            if command.action is MediaAction.OPEN_APP:
                await self._port.open_app(context)
            elif not await self._port.is_running(context):
                ack = self._ack(
                    command,
                    MediaAckStatus.REJECTED,
                    "apple-music.not-running",
                    retryable=True,
                )
                return self._remember(ack)
            else:
                await self._port.execute(
                    command.action,
                    command.arguments or {},
                    context,
                )
        except OperationCancelled:
            self._fingerprints.pop(command.command_id, None)
            raise
        except AppleMusicPortError as exc:
            self._metrics["command_failures"] += 1
            self._metrics["last_error_code"] = exc.code
            status = (
                MediaAckStatus.UNKNOWN
                if exc.ambiguous
                else MediaAckStatus.REJECTED
            )
            if status is MediaAckStatus.UNKNOWN:
                self._metrics["unknown_results"] += 1
            return self._remember(
                self._ack(
                    command,
                    status,
                    exc.code,
                    retryable=exc.retryable,
                )
            )

        self._metrics["last_error_code"] = None
        return self._remember(
            self._ack(
                command,
                MediaAckStatus.APPLIED,
                "apple-music.applied",
                retryable=False,
            )
        )

    async def close(self, context: OperationContext) -> None:
        context.raise_if_cancelled()
        lock = self._get_command_lock()
        await await_operation(lock.acquire(), context)
        try:
            self._closed = True
        finally:
            lock.release()

    def stats(self) -> dict[str, Any]:
        return {
            "controller_id": self.controller_id,
            "closed": self._closed,
            "cached_commands": len(self._results),
            "max_cached_commands": self._max_cached,
            **self._metrics,
        }

    def _health(
        self,
        lifecycle: MediaLifecycle,
        code: str | None = None,
        *,
        retryable: bool = False,
    ) -> MediaHealth:
        return MediaHealth(
            self.controller_id,
            lifecycle,
            self._clock_ms(),
            code,
            retryable,
        )

    def _ack(
        self,
        command: MediaCommand,
        status: MediaAckStatus,
        code: str,
        *,
        retryable: bool,
    ) -> MediaAck:
        return MediaAck(
            command.command_id,
            self.controller_id,
            command.action,
            status,
            self._clock_ms(),
            code,
            retryable,
        )

    def _remember(self, ack: MediaAck) -> MediaAck:
        self._results[ack.command_id] = ack
        self._results.move_to_end(ack.command_id)
        while len(self._results) > self._max_cached:
            expired_id, _ = self._results.popitem(last=False)
            self._fingerprints.pop(expired_id, None)
        return ack

    def _require_open(self) -> None:
        if self._closed:
            raise MediaLifecycleError("AppleMusicAdapter esta cerrado")

    def _get_command_lock(self) -> asyncio.Lock:
        if self._command_lock is None:
            self._command_lock = asyncio.Lock()
        return self._command_lock
