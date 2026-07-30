"""Adaptadores deterministas para probar contratos sin servicios externos."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import replace
from typing import Any, Iterable

from .chart_provider import (
    ChartCapability,
    ChartCapabilityError,
    ChartHealth,
    ChartLifecycle,
    ChartLifecycleError,
    ChartMountFailed,
    ChartMountRequest,
    ChartSession,
)
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
from .operations import OperationContext, await_operation


class FakeChartProvider:
    """ChartProvider en memoria con reloj, latencia y fallos controlables."""

    def __init__(
        self,
        provider_id: str = "fake-chart",
        *,
        capabilities: Iterable[ChartCapability] | None = None,
        clock_ms=None,
        operation_delay_s: float = 0.0,
    ):
        if not provider_id:
            raise ValueError("provider_id no puede ser vacio")
        if operation_delay_s < 0:
            raise ValueError("operation_delay_s no puede ser negativo")
        self.provider_id = provider_id
        self._capabilities = frozenset(
            ChartCapability if capabilities is None else capabilities
        )
        self._clock_ms = clock_ms or (lambda: 0)
        self._delay = operation_delay_s
        self._lifecycle = ChartLifecycle.DETACHED
        self._health_code: str | None = None
        self._health_retryable = False
        self._session: ChartSession | None = None
        self._failures: dict[str, deque[Exception]] = defaultdict(deque)
        self.calls: list[tuple[str, Any]] = []

    @property
    def session(self) -> ChartSession | None:
        return self._session

    def capabilities(self) -> frozenset[ChartCapability]:
        return self._capabilities

    def set_health(
        self,
        lifecycle: ChartLifecycle,
        *,
        code: str | None = None,
        retryable: bool = False,
    ) -> None:
        self._lifecycle = lifecycle
        self._health_code = code
        self._health_retryable = retryable

    def fail_next(self, operation: str, error: Exception) -> None:
        if operation not in {
            "health",
            "mount",
            "set_symbol",
            "set_interval",
            "set_theme",
            "fullscreen",
            "destroy",
        }:
            raise ValueError("operacion fake desconocida")
        self._failures[operation].append(error)

    async def _before(
        self, operation: str, context: OperationContext
    ) -> None:
        context.raise_if_cancelled()
        if self._delay:
            await await_operation(asyncio.sleep(self._delay), context)
        if self._failures[operation]:
            raise self._failures[operation].popleft()

    def _require_session(self, capability: ChartCapability) -> ChartSession:
        if capability not in self._capabilities:
            raise ChartCapabilityError(
                f"{self.provider_id} no soporta {capability.value}"
            )
        if self._session is None or self._lifecycle is not ChartLifecycle.READY:
            raise ChartLifecycleError("el fake no tiene una sesion activa")
        return self._session

    async def health(self, context: OperationContext) -> ChartHealth:
        await self._before("health", context)
        self.calls.append(("health", None))
        return ChartHealth(
            self.provider_id,
            self._lifecycle,
            self._clock_ms(),
            self._health_code,
            self._health_retryable,
        )

    async def mount(
        self,
        request: ChartMountRequest,
        context: OperationContext,
    ) -> ChartSession:
        await self._before("mount", context)
        self.calls.append(("mount", request))
        if not request.required_capabilities.issubset(self._capabilities):
            raise ChartMountFailed("el fake no satisface las capacidades")
        if self._lifecycle in {
            ChartLifecycle.FAILED,
            ChartLifecycle.DESTROYED,
        }:
            raise ChartMountFailed("el fake no esta disponible")
        if self._session is not None:
            expected = (
                self._session.target_ref,
                self._session.symbol,
                self._session.interval,
                self._session.theme_ref,
            )
            received = (
                request.target_ref,
                request.symbol,
                request.interval,
                request.theme_ref,
            )
            if expected == received:
                return self._session
            raise ChartLifecycleError(
                "destruya la sesion fake antes de montar otra"
            )
        self._lifecycle = ChartLifecycle.MOUNTING
        self._session = ChartSession(
            self.provider_id,
            request.target_ref,
            request.symbol,
            request.interval,
            self._clock_ms(),
            request.theme_ref,
        )
        self._lifecycle = ChartLifecycle.READY
        return self._session

    async def set_symbol(
        self, symbol: str, context: OperationContext
    ) -> None:
        await self._before("set_symbol", context)
        session = self._require_session(ChartCapability.SET_SYMBOL)
        if not symbol.strip():
            raise ValueError("symbol no puede ser vacio")
        self.calls.append(("set_symbol", symbol))
        self._session = replace(session, symbol=symbol)

    async def set_interval(
        self, interval: str, context: OperationContext
    ) -> None:
        await self._before("set_interval", context)
        session = self._require_session(ChartCapability.SET_INTERVAL)
        if not interval.strip():
            raise ValueError("interval no puede ser vacio")
        self.calls.append(("set_interval", interval))
        self._session = replace(session, interval=interval)

    async def set_theme(
        self, theme_ref: str, context: OperationContext
    ) -> None:
        await self._before("set_theme", context)
        session = self._require_session(ChartCapability.SET_THEME)
        if not theme_ref.strip():
            raise ValueError("theme_ref no puede ser vacio")
        self.calls.append(("set_theme", theme_ref))
        self._session = replace(session, theme_ref=theme_ref)

    async def fullscreen(self, context: OperationContext) -> None:
        await self._before("fullscreen", context)
        self._require_session(ChartCapability.FULLSCREEN)
        self.calls.append(("fullscreen", None))

    async def destroy(self, context: OperationContext) -> None:
        await self._before("destroy", context)
        if self._lifecycle is ChartLifecycle.DESTROYED:
            return
        self.calls.append(("destroy", None))
        self._session = None
        self._lifecycle = ChartLifecycle.DESTROYED


class FakeMediaController:
    """MediaController idempotente y observable, sin tocar reproductores."""

    def __init__(
        self,
        controller_id: str = "fake-media",
        *,
        capabilities: Iterable[MediaCapability] | None = None,
        clock_ms=None,
        operation_delay_s: float = 0.0,
    ):
        if not controller_id:
            raise ValueError("controller_id no puede ser vacio")
        if operation_delay_s < 0:
            raise ValueError("operation_delay_s no puede ser negativo")
        self.controller_id = controller_id
        self._capabilities = frozenset(
            MediaCapability if capabilities is None else capabilities
        )
        self._clock_ms = clock_ms or (lambda: 0)
        self._delay = operation_delay_s
        self._lifecycle = MediaLifecycle.READY
        self._health_code: str | None = None
        self._health_retryable = False
        self._state = MediaState(
            controller_id,
            MediaLifecycle.READY,
            self._clock_ms(),
            "paused",
            0.5,
            "fake:item:1",
        )
        self._failures: dict[str, deque[Exception]] = defaultdict(deque)
        self._ack_statuses: deque[MediaAckStatus] = deque()
        self._fingerprints: dict[str, tuple[Any, ...]] = {}
        self._results: dict[str, MediaAck] = {}
        self._inflight: dict[str, asyncio.Task[MediaAck]] = {}
        self.calls: list[tuple[str, Any]] = []
        self.effects: list[tuple[str, MediaAction]] = []

    def capabilities(self) -> frozenset[MediaCapability]:
        return self._capabilities

    def set_health(
        self,
        lifecycle: MediaLifecycle,
        *,
        code: str | None = None,
        retryable: bool = False,
    ) -> None:
        self._lifecycle = lifecycle
        self._health_code = code
        self._health_retryable = retryable
        self._state = replace(
            self._state,
            lifecycle=lifecycle,
            observed_at_ms=self._clock_ms(),
        )

    def fail_next(self, operation: str, error: Exception) -> None:
        if operation not in {"health", "current_state", "execute", "close"}:
            raise ValueError("operacion fake desconocida")
        self._failures[operation].append(error)

    def return_next(self, status: MediaAckStatus) -> None:
        self._ack_statuses.append(status)

    async def _before(
        self, operation: str, context: OperationContext
    ) -> None:
        context.raise_if_cancelled()
        if self._delay:
            await await_operation(asyncio.sleep(self._delay), context)
        if self._failures[operation]:
            raise self._failures[operation].popleft()

    async def health(self, context: OperationContext) -> MediaHealth:
        await self._before("health", context)
        self.calls.append(("health", None))
        return MediaHealth(
            self.controller_id,
            self._lifecycle,
            self._clock_ms(),
            self._health_code,
            self._health_retryable,
        )

    async def current_state(
        self, context: OperationContext
    ) -> MediaState:
        if MediaCapability.CURRENT_STATE not in self._capabilities:
            raise MediaCapabilityError("current_state no soportado")
        await self._before("current_state", context)
        self.calls.append(("current_state", None))
        return replace(self._state, observed_at_ms=self._clock_ms())

    async def execute(
        self,
        command: MediaCommand,
        context: OperationContext,
    ) -> MediaAck:
        if self._lifecycle is not MediaLifecycle.READY:
            raise MediaLifecycleError("el fake media no esta listo")
        capability = MediaCapability(command.action.value)
        if capability not in self._capabilities:
            raise MediaCapabilityError(
                f"{command.action.value} no soportado"
            )
        fingerprint = command.fingerprint()
        known = self._fingerprints.get(command.command_id)
        if known is not None and known != fingerprint:
            raise MediaCommandConflict(
                "command_id ya fue usado con otra operacion"
            )
        cached = self._results.get(command.command_id)
        if cached is not None:
            return cached
        task = self._inflight.get(command.command_id)
        if task is None:
            self._fingerprints[command.command_id] = fingerprint
            task = asyncio.create_task(self._apply(command))
            self._inflight[command.command_id] = task
            task.add_done_callback(
                lambda done, command_id=command.command_id: self._complete(
                    command_id, done
                )
            )
        return await await_operation(
            asyncio.shield(task),
            context,
            cancel_work=False,
        )

    def _complete(
        self, command_id: str, task: asyncio.Task[MediaAck]
    ) -> None:
        self._inflight.pop(command_id, None)
        if not task.cancelled():
            task.exception()

    async def _apply(self, command: MediaCommand) -> MediaAck:
        await self._before("execute", OperationContext())
        self.calls.append(("execute", command))
        status = (
            self._ack_statuses.popleft()
            if self._ack_statuses
            else MediaAckStatus.APPLIED
        )
        if status is MediaAckStatus.APPLIED:
            self._apply_effect(command)
        ack = MediaAck(
            command.command_id,
            self.controller_id,
            command.action,
            status,
            self._clock_ms(),
            f"fake.{status.value}",
            status is MediaAckStatus.UNKNOWN,
        )
        if status is not MediaAckStatus.UNKNOWN:
            self._results[command.command_id] = ack
        return ack

    def _apply_effect(self, command: MediaCommand) -> None:
        playback = self._state.playback
        volume = self._state.volume
        item_ref = self._state.item_ref
        if command.action is MediaAction.PLAY:
            playback = "playing"
        elif command.action is MediaAction.PAUSE:
            playback = "paused"
        elif command.action in {MediaAction.NEXT, MediaAction.PREVIOUS}:
            item_ref = f"fake:item:{len(self.effects) + 2}"
        elif command.action is MediaAction.SET_VOLUME:
            volume = float(command.arguments["volume"])
        self.effects.append((command.command_id, command.action))
        self._state = replace(
            self._state,
            playback=playback,
            volume=volume,
            item_ref=item_ref,
            observed_at_ms=self._clock_ms(),
        )

    async def close(self, context: OperationContext) -> None:
        if self._inflight:
            raise MediaLifecycleError(
                "no se puede cerrar con comandos pendientes"
            )
        await self._before("close", context)
        if self._lifecycle is MediaLifecycle.CLOSED:
            return
        self.calls.append(("close", None))
        self.set_health(MediaLifecycle.CLOSED, code="fake.closed")
