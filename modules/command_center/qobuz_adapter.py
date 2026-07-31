"""Adaptador headless y capability-limited para Qobuz Desktop."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
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
_CAPABILITIES = frozenset({MediaCapability.OPEN_APP})


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


class OsaScriptQobuzPort:
    """Puerto real sin shell, API privada ni automatizacion de playback."""

    provider_name = "Qobuz"
    code_prefix = "qobuz"

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
    """MediaController real, limitado a salud y apertura de la app."""

    controller_id = "qobuz"
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
        self._metrics = {
            "health_checks": 0,
            "app_probes": 0,
            "commands": 0,
            "command_failures": 0,
            "unknown_results": 0,
            "cache_hits": 0,
            "last_error_code": None,
            "app_version": None,
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
        context.raise_if_cancelled()
        raise MediaCapabilityError(
            f"{self.provider_name} Desktop no expone current_state a terceros"
        )

    async def execute(
        self,
        command: MediaCommand,
        context: OperationContext,
    ) -> MediaAck:
        self._require_open()
        if command.action is not MediaAction.OPEN_APP:
            raise MediaCapabilityError(
                f"{self.provider_name} no expone "
                f"{command.action.value} a terceros"
            )
        lock = self._get_command_lock()
        await await_operation(lock.acquire(), context)
        try:
            self._require_open()
            return await self._open_locked(command, context)
        finally:
            lock.release()

    async def _open_locked(
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
            await self._port.open_app(context)
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
