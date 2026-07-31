"""Adaptador headless y capability-limited para Qobuz Desktop."""

from __future__ import annotations

import asyncio
import json
import os
import select
import subprocess
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .media_controller import (
    MediaAck,
    MediaAckStatus,
    MediaAction,
    MediaCapability,
    MediaCapabilityError,
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
QOBUZ_APP = "Qobuz"

_IS_RUNNING_SCRIPT = 'application "Qobuz" is running'
_VERSION_PROBE_SCRIPT = 'tell application "Qobuz" to get version'
_CAPABILITIES = frozenset(
    {
        MediaCapability.CURRENT_STATE,
        MediaCapability.PLAY,
        MediaCapability.PAUSE,
        MediaCapability.NEXT,
        MediaCapability.PREVIOUS,
        MediaCapability.OPEN_APP,
    }
)
_DEFAULT_AGENT = (
    Path(__file__).resolve().parents[2]
    / "agents"
    / "macos"
    / "NexusAgent"
    / ".build"
    / "release"
    / "nexus-agent"
)


@dataclass(frozen=True)
class DesktopPlaybackSnapshot:
    playback: str
    track: str | None
    artist: str | None
    album: str | None
    item_ref: str | None


class QobuzPortError(RuntimeError):
    """Fallo estable en la frontera local de Qobuz Desktop."""

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


class QobuzPort(Protocol):
    async def is_running(self, context: OperationContext) -> bool: ...

    async def probe_app(self, context: OperationContext) -> str: ...

    async def open_app(self, context: OperationContext) -> None: ...

    async def current_state(
        self, context: OperationContext
    ) -> DesktopPlaybackSnapshot: ...

    async def execute(
        self,
        action: MediaAction,
        context: OperationContext,
        known_playback: str | None = None,
    ) -> None: ...

    def helper_available(self) -> bool: ...


class OsaScriptQobuzPort:
    """Puerto local hacia el agente macOS y su puente de Accesibilidad."""

    provider_name = "Qobuz"
    code_prefix = "qobuz"

    def __init__(self, agent_path: str | Path | None = None):
        configured = agent_path or os.environ.get("NEXUX_MACOS_AGENT_BIN")
        self.agent_path = Path(configured) if configured else _DEFAULT_AGENT
        self._agent_process: subprocess.Popen[bytes] | None = None
        self._agent_lock = threading.Lock()

    def helper_available(self) -> bool:
        return self.agent_path.is_file() and os.access(self.agent_path, os.X_OK)

    async def is_running(self, context: OperationContext) -> bool:
        output = await self._run(
            (OSASCRIPT, "-l", "AppleScript", "-e", _IS_RUNNING_SCRIPT),
            context,
        )
        normalized = output.strip().lower()
        if normalized not in {"true", "false"}:
            raise QobuzPortError(
                "qobuz.invalid-running-state",
                "Qobuz devolvio un estado de ejecucion invalido",
                retryable=True,
            )
        return normalized == "true"

    async def probe_app(self, context: OperationContext) -> str:
        output = await self._run(
            (
                OSASCRIPT,
                "-l",
                "AppleScript",
                "-e",
                _VERSION_PROBE_SCRIPT,
            ),
            context,
        )
        version = output.strip()
        if not version or len(version) > 64 or any(
            character.isspace() for character in version
        ):
            raise QobuzPortError(
                "qobuz.invalid-version",
                "Qobuz devolvio una version invalida",
                retryable=True,
            )
        return version

    async def open_app(self, context: OperationContext) -> None:
        await self._run((OPEN, "-gj", "-a", QOBUZ_APP), context)

    async def current_state(
        self, context: OperationContext
    ) -> DesktopPlaybackSnapshot:
        payload = await self._agent_json(
            {"kind": "state", "provider": self.code_prefix},
            context,
        )
        playback = payload.get("playback")
        if playback not in {"playing", "paused", "stopped", "unknown"}:
            raise QobuzPortError(
                f"{self.code_prefix}.invalid-state",
                f"{self.provider_name} devolvio playback invalido",
                retryable=True,
            )
        fields = {
            key: self._optional_text(payload.get(key), key)
            for key in ("track", "artist", "album", "item_ref")
        }
        return DesktopPlaybackSnapshot(playback, **fields)

    async def execute(
        self,
        action: MediaAction,
        context: OperationContext,
        known_playback: str | None = None,
    ) -> None:
        if action not in {
            MediaAction.PLAY,
            MediaAction.PAUSE,
            MediaAction.NEXT,
            MediaAction.PREVIOUS,
        }:
            raise QobuzPortError(
                f"{self.code_prefix}.action-unavailable",
                f"{self.provider_name} no soporta {action.value}",
                retryable=False,
            )
        request = {
            "kind": "command",
            "provider": self.code_prefix,
            "action": action.value,
        }
        if known_playback in {"playing", "paused"}:
            request["known_playback"] = known_playback
        payload = await self._agent_json(request, context, command=True)
        if payload.get("status") != "applied":
            raise QobuzPortError(
                str(payload.get("code") or f"{self.code_prefix}.rejected"),
                f"{self.provider_name} rechazo {action.value}",
                retryable=bool(payload.get("retryable", True)),
            )

    async def _agent_json(
        self,
        request: dict[str, str],
        context: OperationContext,
        *,
        command: bool = False,
    ) -> dict:
        if not self.helper_available():
            raise QobuzPortError(
                f"{self.code_prefix}.helper-unavailable",
                "el agente macOS no esta compilado o no es ejecutable",
                retryable=False,
            )
        operation_context = context
        if operation_context.deadline is None:
            operation_context = OperationContext.with_timeout(
                8.0,
                cancel_event=context.cancel_event,
            )
        try:
            output = await asyncio.to_thread(
                self._agent_request,
                request,
                operation_context,
                command,
            )
            payload = json.loads(output.decode("utf-8", errors="strict"))
        except json.JSONDecodeError as exc:
            await self.close_helper()
            raise QobuzPortError(
                f"{self.code_prefix}.invalid-output",
                "el agente macOS devolvio JSON invalido",
                retryable=True,
            ) from exc
        except UnicodeDecodeError as exc:
            await self.close_helper()
            raise QobuzPortError(
                f"{self.code_prefix}.invalid-output",
                f"{self.provider_name} devolvio una salida no UTF-8",
                retryable=True,
            ) from exc
        if not isinstance(payload, dict):
            raise QobuzPortError(
                f"{self.code_prefix}.invalid-output",
                "el agente macOS devolvio un payload invalido",
                retryable=True,
            )
        if payload.get("status") == "rejected":
            raise QobuzPortError(
                str(payload.get("code") or f"{self.code_prefix}.rejected"),
                f"el agente macOS no pudo operar {self.provider_name}",
                retryable=bool(payload.get("retryable", True)),
            )
        return payload

    async def close_helper(self) -> None:
        await asyncio.to_thread(self._close_helper_sync)

    def _agent_request(
        self,
        request: dict[str, str],
        context: OperationContext,
        command: bool,
    ) -> bytes:
        with self._agent_lock:
            if context.cancel_event is not None and context.cancel_event.is_set():
                raise OperationCancelled("operacion cancelada")
            if context.remaining() == 0:
                raise QobuzPortError(
                    f"{self.code_prefix}.timeout",
                    f"la automatizacion de {self.provider_name} excedio el deadline",
                    retryable=True,
                    ambiguous=command,
                )
            process = self._ensure_agent()
            assert process.stdin is not None
            assert process.stdout is not None
            encoded = json.dumps(
                request,
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            try:
                process.stdin.write(encoded)
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._reset_agent_locked()
                raise QobuzPortError(
                    f"{self.code_prefix}.helper-stopped",
                    "el agente macOS termino antes de recibir la solicitud",
                    retryable=True,
                    ambiguous=command,
                ) from exc
            while True:
                if (
                    context.cancel_event is not None
                    and context.cancel_event.is_set()
                ):
                    self._reset_agent_locked()
                    raise OperationCancelled("operacion cancelada")
                remaining = context.remaining()
                if remaining == 0:
                    self._reset_agent_locked()
                    raise QobuzPortError(
                        f"{self.code_prefix}.timeout",
                        f"la automatizacion de {self.provider_name} excedio el deadline",
                        retryable=True,
                        ambiguous=command,
                    )
                wait_for = 0.1 if remaining is None else min(0.1, remaining)
                ready, _, _ = select.select(
                    [process.stdout],
                    [],
                    [],
                    wait_for,
                )
                if ready:
                    output = process.stdout.readline()
                    if output:
                        return output
                    self._reset_agent_locked()
                    raise QobuzPortError(
                        f"{self.code_prefix}.helper-stopped",
                        "el agente macOS termino sin responder",
                        retryable=True,
                        ambiguous=command,
                    )

    def _ensure_agent(self) -> subprocess.Popen[bytes]:
        process = self._agent_process
        if process is not None and process.poll() is None:
            return process
        self._agent_process = subprocess.Popen(
            (str(self.agent_path), "--media-server"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        return self._agent_process

    def _close_helper_sync(self) -> None:
        with self._agent_lock:
            self._reset_agent_locked()

    def _reset_agent_locked(self) -> None:
        process = self._agent_process
        self._agent_process = None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def _optional_text(self, value, field: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip() or len(value) > 512:
            raise QobuzPortError(
                f"{self.code_prefix}.invalid-state",
                f"{self.provider_name} devolvio {field} invalido",
                retryable=True,
            )
        return value.strip()

    @classmethod
    async def _run(
        cls,
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
            raise QobuzPortError(
                f"{cls.code_prefix}.timeout",
                f"la automatizacion de {cls.provider_name} excedio el deadline",
                retryable=True,
                ambiguous=True,
            ) from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            if "-1743" in detail:
                code = f"{cls.code_prefix}.permission-denied"
                retryable = False
            elif "-600" in detail:
                code = f"{cls.code_prefix}.not-running"
                retryable = True
            else:
                code = f"{cls.code_prefix}.probe-failed"
                retryable = True
            raise QobuzPortError(
                code,
                detail or f"fallo la automatizacion local de {cls.provider_name}",
                retryable=retryable,
            )
        try:
            return stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise QobuzPortError(
                f"{cls.code_prefix}.invalid-output",
                f"{cls.provider_name} devolvio una salida no UTF-8",
                retryable=True,
            ) from exc


class QobuzAdapter:
    """MediaController local respaldado por Accesibilidad de macOS."""

    controller_id = "qobuz"
    commands_self_verified = True
    provider_name = "Qobuz"
    code_prefix = "qobuz"

    def __init__(
        self,
        port: QobuzPort | None = None,
        *,
        clock_ms=None,
        max_cached_commands: int = 1024,
    ):
        if type(max_cached_commands) is not int or max_cached_commands <= 0:
            raise ValueError("max_cached_commands debe ser positivo")
        self._port = port or OsaScriptQobuzPort()
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._max_cached = max_cached_commands
        self._closed = False
        self._command_lock: asyncio.Lock | None = None
        self._fingerprints: OrderedDict[str, tuple[Any, ...]] = OrderedDict()
        self._results: OrderedDict[str, MediaAck] = OrderedDict()
        self._metadata: dict[str, str] | None = None
        self._last_playback: str | None = None
        self._last_playback_at_ms: int | None = None
        self._metrics = {
            "health_checks": 0,
            "app_probes": 0,
            "commands": 0,
            "command_failures": 0,
            "unknown_results": 0,
            "cache_hits": 0,
            "last_error_code": None,
            "app_version": None,
            "state_reads": 0,
        }

    def capabilities(self) -> frozenset[MediaCapability]:
        return _CAPABILITIES

    async def health(self, context: OperationContext) -> MediaHealth:
        self._metrics["health_checks"] += 1
        if self._closed:
            return self._health(
                MediaLifecycle.CLOSED,
                f"{self.code_prefix}.closed",
            )
        try:
            running = await self._port.is_running(context)
            if not running:
                self._metrics["last_error_code"] = None
                self._metrics["app_version"] = None
                return self._health(
                    MediaLifecycle.UNAVAILABLE,
                f"{self.code_prefix}.not-running",
                    retryable=True,
                )
            self._metrics["app_probes"] += 1
            self._metrics["app_version"] = await self._port.probe_app(context)
            if not self._port.helper_available():
                raise QobuzPortError(
                    f"{self.code_prefix}.helper-unavailable",
                    "el agente macOS no esta disponible",
                    retryable=False,
                )
        except QobuzPortError as exc:
            self._metrics["last_error_code"] = exc.code
            self._metrics["app_version"] = None
            lifecycle = (
                MediaLifecycle.REVOKED
                if exc.code == f"{self.code_prefix}.permission-denied"
                else MediaLifecycle.DEGRADED
            )
            return self._health(
                lifecycle,
                exc.code,
                retryable=exc.retryable,
            )
        self._metrics["last_error_code"] = None
        return self._health(MediaLifecycle.READY)

    async def current_state(
        self, context: OperationContext
    ) -> MediaState:
        self._require_open()
        self._metrics["state_reads"] += 1
        if not await self._port.is_running(context):
            self._metadata = None
            self._last_playback = None
            self._last_playback_at_ms = None
            return MediaState(
                self.controller_id,
                MediaLifecycle.UNAVAILABLE,
                self._clock_ms(),
                "stopped",
            )
        try:
            snapshot = await self._port.current_state(context)
        except QobuzPortError as exc:
            self._metrics["last_error_code"] = exc.code
            raise
        self._metrics["last_error_code"] = None
        observed_at_ms = self._clock_ms()
        self._last_playback = snapshot.playback
        self._last_playback_at_ms = observed_at_ms
        self._metadata = (
            {
                "item_ref": snapshot.item_ref,
                "track": snapshot.track or "",
                "artist": snapshot.artist or "",
                "album": snapshot.album or "",
            }
            if snapshot.item_ref
            else None
        )
        return MediaState(
            self.controller_id,
            MediaLifecycle.READY,
            observed_at_ms,
            snapshot.playback,
            None,
            snapshot.item_ref,
        )

    def metadata(self, item_ref: str) -> dict[str, str] | None:
        if not self._metadata or self._metadata.get("item_ref") != item_ref:
            return None
        return dict(self._metadata)

    async def execute(
        self,
        command: MediaCommand,
        context: OperationContext,
    ) -> MediaAck:
        self._require_open()
        if MediaCapability(command.action.value) not in self.capabilities():
            raise MediaCapabilityError(
                f"{self.provider_name} no expone "
                f"{command.action.value} a terceros"
            )
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
                return self._remember(
                    self._ack(
                        command,
                        MediaAckStatus.REJECTED,
                        f"{self.code_prefix}.not-running",
                        retryable=True,
                    )
                )
            else:
                known_playback = None
                if (
                    command.action in {MediaAction.PLAY, MediaAction.PAUSE}
                    and self._last_playback in {"playing", "paused"}
                    and self._last_playback_at_ms is not None
                    and 0
                    <= self._clock_ms() - self._last_playback_at_ms
                    <= 3_000
                ):
                    known_playback = self._last_playback
                await self._port.execute(
                    command.action,
                    context,
                    known_playback=known_playback,
                )
        except OperationCancelled:
            self._fingerprints.pop(command.command_id, None)
            raise
        except QobuzPortError as exc:
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
                f"{self.code_prefix}.applied",
                retryable=False,
            )
        )

    async def close(self, context: OperationContext) -> None:
        context.raise_if_cancelled()
        lock = self._get_command_lock()
        await await_operation(lock.acquire(), context)
        try:
            self._closed = True
            self._metrics["app_version"] = None
            close_helper = getattr(self._port, "close_helper", None)
            if close_helper is not None:
                await await_operation(close_helper(), context)
        finally:
            lock.release()

    def stats(self) -> dict[str, Any]:
        return {
            "controller_id": self.controller_id,
            "closed": self._closed,
            "cached_commands": len(self._results),
            "max_cached_commands": self._max_cached,
            "capabilities": tuple(
                sorted(item.value for item in self.capabilities())
            ),
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
            raise MediaLifecycleError(
                f"{self.provider_name}Adapter esta cerrado"
            )

    def _get_command_lock(self) -> asyncio.Lock:
        if self._command_lock is None:
            self._command_lock = asyncio.Lock()
        return self._command_lock
