"""Harness reutilizable para validar providers headless reales o falsos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .chart_provider import (
    ChartCapability,
    ChartMountRequest,
    ChartProvider,
)
from .fake_adapters import FakeChartProvider, FakeMediaController
from .headless_components import (
    ChartProviderComponent,
    MediaControllerComponent,
)
from .media_controller import (
    MediaAck,
    MediaAckStatus,
    MediaAction,
    MediaCapability,
    MediaCommand,
    MediaController,
)
from .module_registry import (
    ModuleFactory,
    ModuleLifecycle,
    RegistryActor,
    RuntimeContext,
    StaticModuleRegistry,
    command_center_module_registry,
)
from .operations import OperationContext


class ConformanceViolation(AssertionError):
    """Un adaptador no satisface el contrato headless."""


@dataclass(frozen=True)
class ConformanceReport:
    adapter_id: str
    interface: str
    operations: tuple[str, ...]


async def verify_chart_provider(
    provider: ChartProvider,
    *,
    request: ChartMountRequest | None = None,
    context: OperationContext | None = None,
) -> ConformanceReport:
    """Prueba salud, montaje y capacidades declaradas; destruye al terminar."""

    ctx = context or OperationContext()
    operations = ["health", "mount"]
    health = await provider.health(ctx)
    if health.provider_id != provider.provider_id:
        raise ConformanceViolation("ChartHealth contradice provider_id")
    capabilities = provider.capabilities()
    mount_request = request or ChartMountRequest(
        "conformance:chart",
        "BTCUSDT",
        "1h",
        capabilities,
        "conformance-theme"
        if ChartCapability.SET_THEME in capabilities
        else None,
    )
    try:
        session = await provider.mount(mount_request, ctx)
        if (
            session.provider_id != provider.provider_id
            or session.target_ref != mount_request.target_ref
            or session.symbol != mount_request.symbol
            or session.interval != mount_request.interval
        ):
            raise ConformanceViolation("ChartSession contradice mount")
        repeated = await provider.mount(mount_request, ctx)
        if repeated != session:
            raise ConformanceViolation("mount identico no es idempotente")
        operations.append("mount-idempotent")
        if ChartCapability.SET_SYMBOL in capabilities:
            await provider.set_symbol("ETHUSDT", ctx)
            operations.append("set_symbol")
        if ChartCapability.SET_INTERVAL in capabilities:
            await provider.set_interval("4h", ctx)
            operations.append("set_interval")
        if ChartCapability.SET_THEME in capabilities:
            await provider.set_theme("conformance-alt", ctx)
            operations.append("set_theme")
        if ChartCapability.FULLSCREEN in capabilities:
            await provider.fullscreen(ctx)
            operations.append("fullscreen")
    finally:
        await provider.destroy(ctx)
        operations.append("destroy")
    return ConformanceReport(
        provider.provider_id,
        "chart-provider-v1",
        tuple(operations),
    )


async def verify_media_controller(
    controller: MediaController,
    *,
    include_commands: bool = False,
    context: OperationContext | None = None,
) -> ConformanceReport:
    """La prueba por defecto es read-only; los comandos requieren opt-in."""

    ctx = context or OperationContext()
    operations = ["health"]
    health = await controller.health(ctx)
    if health.controller_id != controller.controller_id:
        raise ConformanceViolation("MediaHealth contradice controller_id")
    capabilities = controller.capabilities()
    if MediaCapability.CURRENT_STATE in capabilities:
        state = await controller.current_state(ctx)
        if state.controller_id != controller.controller_id:
            raise ConformanceViolation("MediaState contradice controller_id")
        operations.append("current_state")
    if include_commands:
        for index, action in enumerate(MediaAction, start=1):
            capability = MediaCapability(action.value)
            if capability not in capabilities:
                continue
            arguments = (
                {"volume": 0.25}
                if action is MediaAction.SET_VOLUME
                else None
            )
            command = MediaCommand(
                f"conformance-{index}",
                action,
                index,
                arguments,
            )
            first = await controller.execute(command, ctx)
            second = await controller.execute(command, ctx)
            _verify_ack(controller, command, first)
            _verify_ack(controller, command, second)
            if (
                first.status is not MediaAckStatus.UNKNOWN
                and second != first
            ):
                raise ConformanceViolation(
                    "reintento no devuelve el mismo ACK terminal"
                )
            if (
                first.status is MediaAckStatus.UNKNOWN
                and second.status is not MediaAckStatus.UNKNOWN
            ):
                terminal = await controller.execute(command, ctx)
                if terminal != second:
                    raise ConformanceViolation(
                        "ACK reconciliado no permanece idempotente"
                    )
            operations.append(action.value)
    return ConformanceReport(
        controller.controller_id,
        "media-controller-v1",
        tuple(operations),
    )


def _verify_ack(
    controller: MediaController,
    command: MediaCommand,
    ack: MediaAck,
) -> None:
    if (
        ack.controller_id != controller.controller_id
        or ack.command_id != command.command_id
        or ack.action is not command.action
    ):
        raise ConformanceViolation("MediaAck contradice el comando")


class HeadlessIntegrationHarness:
    """Compone fakes mediante el mismo registro que usaran adaptadores reales."""

    def __init__(
        self,
        *,
        chart_factory: Callable[[], ChartProvider] | None = None,
        media_factory: Callable[[], MediaController] | None = None,
        chart_capabilities: frozenset[ChartCapability] | None = None,
        media_capabilities: frozenset[MediaCapability] | None = None,
    ):
        self._chart_factory = chart_factory or FakeChartProvider
        self._media_factory = media_factory or FakeMediaController
        self.chart_component: ChartProviderComponent | None = None
        self.media_component: MediaControllerComponent | None = None
        factories: dict[str, ModuleFactory] = {
            "chart.provider": self._build_chart,
            "media.controller": self._build_media,
        }
        self.registry: StaticModuleRegistry = command_center_module_registry(
            factories,
            chart_capabilities=chart_capabilities,
            media_capabilities=media_capabilities,
        )

    @property
    def chart(self) -> ChartProvider:
        if self.chart_component is None:
            raise RuntimeError("el harness no esta iniciado")
        return self.chart_component.provider

    @property
    def media(self) -> MediaController:
        if self.media_component is None:
            raise RuntimeError("el harness no esta iniciado")
        return self.media_component.controller

    def _build_chart(
        self, context: RuntimeContext
    ) -> ChartProviderComponent:
        component = ChartProviderComponent(self._chart_factory())
        self.chart_component = component
        return component

    def _build_media(
        self, context: RuntimeContext
    ) -> MediaControllerComponent:
        component = MediaControllerComponent(self._media_factory())
        self.media_component = component
        return component

    async def start(
        self,
        actor: RegistryActor | None = None,
        context: OperationContext | None = None,
    ) -> None:
        statuses = await self.registry.initialize(
            actor or RegistryActor("test:headless", "admin"),
            enabled_modules={"chart.provider", "media.controller"},
            context=context,
        )
        failures = [
            status
            for status in statuses
            if status.lifecycle
            not in {ModuleLifecycle.READY, ModuleLifecycle.DEGRADED}
        ]
        if failures:
            detail = ", ".join(
                f"{item.module_id}:{item.lifecycle.value}" for item in failures
            )
            raise RuntimeError(f"fallo el harness headless: {detail}")

    async def shutdown(
        self, context: OperationContext | None = None
    ) -> None:
        await self.registry.shutdown(context)
