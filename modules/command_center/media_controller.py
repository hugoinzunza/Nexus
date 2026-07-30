"""Contrato headless para control multimedia mediante adaptadores."""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Protocol

from .operations import OperationContext, await_operation

MEDIA_CONTROLLER_INTERFACE_VERSION = 1
_COMMAND_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class MediaControllerError(RuntimeError):
    """Error de contrato o ciclo de vida multimedia."""


class MediaCapabilityError(MediaControllerError):
    """El controlador activo no soporta la accion."""


class MediaCommandConflict(MediaControllerError):
    """Un command_id fue reutilizado con otra operacion."""


class MediaAckInvalid(MediaControllerError):
    """El ACK no corresponde al comando o controlador que lo emitio."""


class MediaLifecycleError(MediaControllerError):
    """La operacion no es valida en el estado actual."""


class MediaCapability(str, Enum):
    CURRENT_STATE = "current_state"
    PLAY = "play"
    PAUSE = "pause"
    NEXT = "next"
    PREVIOUS = "previous"
    SET_VOLUME = "set_volume"
    OPEN_APP = "open_app"


class MediaAction(str, Enum):
    PLAY = "play"
    PAUSE = "pause"
    NEXT = "next"
    PREVIOUS = "previous"
    SET_VOLUME = "set_volume"
    OPEN_APP = "open_app"


class MediaLifecycle(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    REVOKED = "revoked"
    CLOSED = "closed"


class MediaAckStatus(str, Enum):
    APPLIED = "applied"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


_ACTION_CAPABILITY = {
    MediaAction.PLAY: MediaCapability.PLAY,
    MediaAction.PAUSE: MediaCapability.PAUSE,
    MediaAction.NEXT: MediaCapability.NEXT,
    MediaAction.PREVIOUS: MediaCapability.PREVIOUS,
    MediaAction.SET_VOLUME: MediaCapability.SET_VOLUME,
    MediaAction.OPEN_APP: MediaCapability.OPEN_APP,
}


@dataclass(frozen=True)
class MediaHealth:
    controller_id: str
    lifecycle: MediaLifecycle
    checked_at_ms: int
    code: str | None = None
    retryable: bool = False


@dataclass(frozen=True)
class MediaState:
    controller_id: str
    lifecycle: MediaLifecycle
    observed_at_ms: int
    playback: str
    volume: float | None = None
    item_ref: str | None = None


@dataclass(frozen=True)
class MediaCommand:
    command_id: str
    action: MediaAction
    issued_at_ms: int
    arguments: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not _COMMAND_ID_RE.fullmatch(self.command_id):
            raise ValueError("command_id no usa la forma canonica")
        if type(self.issued_at_ms) is not int or self.issued_at_ms < 0:
            raise ValueError("issued_at_ms debe ser entero no negativo")
        arguments = dict(self.arguments or {})
        if self.action is MediaAction.SET_VOLUME:
            volume = arguments.get("volume")
            if type(volume) not in (int, float) or not 0 <= volume <= 1:
                raise ValueError("set_volume exige volume entre 0 y 1")
        elif arguments:
            raise ValueError(f"{self.action.value} no acepta arguments")
        object.__setattr__(self, "arguments", arguments)

    def fingerprint(self) -> tuple[Any, ...]:
        return (
            self.action.value,
            self.issued_at_ms,
            tuple(sorted((self.arguments or {}).items())),
        )


@dataclass(frozen=True)
class MediaAck:
    command_id: str
    controller_id: str
    action: MediaAction
    status: MediaAckStatus
    completed_at_ms: int
    code: str
    retryable: bool


class MediaController(Protocol):
    controller_id: str

    def capabilities(self) -> frozenset[MediaCapability]: ...

    async def health(self, context: OperationContext) -> MediaHealth: ...

    async def current_state(
        self, context: OperationContext
    ) -> MediaState: ...

    async def execute(
        self,
        command: MediaCommand,
        context: OperationContext,
    ) -> MediaAck: ...

    async def close(self, context: OperationContext) -> None: ...


class MediaControllerRouter:
    """Coordina adaptadores y conserva idempotencia ante respuestas ambiguas."""

    interface_version = MEDIA_CONTROLLER_INTERFACE_VERSION
    hot_swap_while_inflight_supported = False

    def __init__(
        self,
        controllers: Iterable[MediaController],
        *,
        max_cached_commands: int = 1024,
    ):
        ordered = tuple(controllers)
        if not ordered:
            raise ValueError("se requiere al menos un MediaController")
        identifiers = [controller.controller_id for controller in ordered]
        if any(not value for value in identifiers) or len(set(identifiers)) != len(
            identifiers
        ):
            raise ValueError("controller_id debe ser unico y no vacio")
        if type(max_cached_commands) is not int or max_cached_commands <= 0:
            raise ValueError("max_cached_commands debe ser positivo")
        self._controllers = {item.controller_id: item for item in ordered}
        self._active = ordered[0]
        self._max_cached = max_cached_commands
        self._fingerprints: OrderedDict[str, tuple[Any, ...]] = OrderedDict()
        self._results: OrderedDict[str, MediaAck] = OrderedDict()
        self._inflight: dict[str, asyncio.Task[MediaAck]] = {}

    @property
    def active_controller_id(self) -> str:
        return self._active.controller_id

    def activate(self, controller_id: str) -> None:
        if self._inflight:
            raise MediaLifecycleError(
                "no se puede sustituir el controlador con comandos pendientes"
            )
        try:
            self._active = self._controllers[controller_id]
        except KeyError as exc:
            raise MediaLifecycleError("controlador no registrado") from exc

    async def health(
        self, context: OperationContext | None = None
    ) -> MediaHealth:
        ctx = context or OperationContext()
        return await await_operation(self._active.health(ctx), ctx)

    async def current_state(
        self, context: OperationContext | None = None
    ) -> MediaState:
        if MediaCapability.CURRENT_STATE not in self._active.capabilities():
            raise MediaCapabilityError("current_state no soportado")
        ctx = context or OperationContext()
        return await await_operation(self._active.current_state(ctx), ctx)

    async def execute(
        self,
        command: MediaCommand,
        context: OperationContext | None = None,
    ) -> MediaAck:
        capability = _ACTION_CAPABILITY[command.action]
        if capability not in self._active.capabilities():
            raise MediaCapabilityError(f"{command.action.value} no soportado")
        fingerprint = command.fingerprint()
        known = self._fingerprints.get(command.command_id)
        if known is not None and known != fingerprint:
            raise MediaCommandConflict(
                "command_id ya fue usado con otra operacion"
            )
        cached = self._results.get(command.command_id)
        if cached is not None:
            self._results.move_to_end(command.command_id)
            return cached
        task = self._inflight.get(command.command_id)
        if task is None:
            self._fingerprints[command.command_id] = fingerprint
            provider_context = OperationContext()
            task = asyncio.create_task(
                self._dispatch(self._active, command, provider_context)
            )
            self._inflight[command.command_id] = task
            task.add_done_callback(
                lambda done, command_id=command.command_id: self._complete(
                    command_id, done
                )
            )
        ctx = context or OperationContext()
        return await await_operation(
            asyncio.shield(task),
            ctx,
            cancel_work=False,
        )

    @staticmethod
    async def _dispatch(
        controller: MediaController,
        command: MediaCommand,
        context: OperationContext,
    ) -> MediaAck:
        ack = await controller.execute(command, context)
        if (
            not isinstance(ack, MediaAck)
            or ack.command_id != command.command_id
            or ack.controller_id != controller.controller_id
            or ack.action is not command.action
        ):
            raise MediaAckInvalid(
                "el ACK contradice al comando o controlador activo"
            )
        return ack

    def _complete(
        self, command_id: str, task: asyncio.Task[MediaAck]
    ) -> None:
        self._inflight.pop(command_id, None)
        if task.cancelled() or task.exception() is not None:
            return
        result = task.result()
        if result.command_id != command_id:
            self._fingerprints.pop(command_id, None)
            return
        if result.status is MediaAckStatus.UNKNOWN:
            return
        self._results[command_id] = result
        self._results.move_to_end(command_id)
        while len(self._results) > self._max_cached:
            expired_id, _ = self._results.popitem(last=False)
            self._fingerprints.pop(expired_id, None)

    async def close(
        self, context: OperationContext | None = None
    ) -> None:
        if self._inflight:
            raise MediaLifecycleError(
                "no se puede cerrar con comandos pendientes"
            )
        ctx = context or OperationContext()
        for controller in self._controllers.values():
            await await_operation(controller.close(ctx), ctx)
