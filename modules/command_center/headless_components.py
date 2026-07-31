"""Componentes concretos que conectan providers al ciclo de vida del registro."""

from __future__ import annotations

from dataclasses import dataclass

from .chart_provider import (
    ChartLifecycle,
    ChartProvider,
    ChartProviderError,
)
from .media_controller import (
    MediaController,
    MediaControllerError,
    MediaLifecycle,
)
from .module_registry import (
    ModuleLifecycle,
    RuntimeContext,
    RuntimeReport,
)
from .operations import OperationContext


class HeadlessComponentUnavailable(RuntimeError):
    """El provider no puede cumplir el ciclo de vida del componente."""


@dataclass
class ChartProviderComponent:
    provider: ChartProvider

    async def start(
        self,
        context: RuntimeContext,
        operation: OperationContext,
    ) -> RuntimeReport:
        actual = frozenset(
            f"chart.{capability.value.replace('_', '-')}"
            for capability in self.provider.capabilities()
        )
        if actual != context.manifest.capabilities:
            raise HeadlessComponentUnavailable(
                "capacidades de ChartProvider contradicen el manifiesto"
            )
        return await self._report(operation)

    async def health(
        self,
        context: RuntimeContext,
        operation: OperationContext,
    ) -> RuntimeReport:
        return await self._report(operation)

    async def _report(self, operation: OperationContext) -> RuntimeReport:
        health = await self.provider.health(operation)
        if health.provider_id != self.provider.provider_id:
            raise ChartProviderError("health contradice al ChartProvider")
        if health.lifecycle is ChartLifecycle.DEGRADED:
            return RuntimeReport(
                ModuleLifecycle.DEGRADED,
                health.code or "chart.degraded",
                health.retryable,
            )
        if health.lifecycle in {
            ChartLifecycle.DETACHED,
            ChartLifecycle.MOUNTING,
            ChartLifecycle.READY,
        }:
            return RuntimeReport(ModuleLifecycle.READY, "chart.available")
        raise HeadlessComponentUnavailable(
            f"ChartProvider {health.lifecycle.value}"
        )

    async def stop(
        self,
        context: RuntimeContext,
        operation: OperationContext,
    ) -> None:
        await self.provider.destroy(operation)


@dataclass
class MediaControllerComponent:
    controller: MediaController

    async def start(
        self,
        context: RuntimeContext,
        operation: OperationContext,
    ) -> RuntimeReport:
        actual = frozenset(
            f"media.{capability.value.replace('_', '-')}"
            for capability in self.controller.capabilities()
        )
        if actual != context.manifest.capabilities:
            raise HeadlessComponentUnavailable(
                "capacidades de MediaController contradicen el manifiesto"
            )
        return await self._report(operation)

    async def health(
        self,
        context: RuntimeContext,
        operation: OperationContext,
    ) -> RuntimeReport:
        return await self._report(operation)

    async def _report(self, operation: OperationContext) -> RuntimeReport:
        health = await self.controller.health(operation)
        if health.controller_id != self.controller.controller_id:
            raise MediaControllerError("health contradice al MediaController")
        if health.lifecycle in {
            MediaLifecycle.CONNECTING,
            MediaLifecycle.DEGRADED,
            MediaLifecycle.DISCONNECTED,
            MediaLifecycle.UNAVAILABLE,
        }:
            return RuntimeReport(
                ModuleLifecycle.DEGRADED,
                health.code or "media.degraded",
                health.retryable,
            )
        if health.lifecycle is MediaLifecycle.READY:
            return RuntimeReport(ModuleLifecycle.READY, "media.available")
        raise HeadlessComponentUnavailable(
            f"MediaController {health.lifecycle.value}"
        )

    async def stop(
        self,
        context: RuntimeContext,
        operation: OperationContext,
    ) -> None:
        await self.controller.close(operation)
