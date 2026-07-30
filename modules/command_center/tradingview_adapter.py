"""Spike del widget publico de TradingView detras de ChartProvider."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol

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
from .operations import OperationContext

TRADINGVIEW_WIDGET_SCRIPT = (
    "https://s3.tradingview.com/external-embedding/"
    "embed-widget-advanced-chart.js"
)

DEFAULT_SYMBOL_MAP = {
    "BTCUSDT": "BINANCE:BTCUSDT.P",
    "ETHUSDT": "BINANCE:ETHUSDT.P",
    "SOLUSDT": "BINANCE:SOLUSDT.P",
    "ADAUSDT": "BINANCE:ADAUSDT.P",
    "XRPUSDT": "BINANCE:XRPUSDT.P",
}

DEFAULT_INTERVAL_MAP = {
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "1D": "D",
    "1W": "W",
}


class TradingViewPortLifecycle(str, Enum):
    DETACHED = "detached"
    MOUNTING = "mounting"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    DESTROYED = "destroyed"


@dataclass(frozen=True)
class TradingViewWidgetSpec:
    target_ref: str
    symbol: str
    interval: str
    theme: str | None
    script_url: str = TRADINGVIEW_WIDGET_SCRIPT


@dataclass(frozen=True)
class TradingViewPortHealth:
    lifecycle: TradingViewPortLifecycle
    checked_at_ms: int
    code: str | None = None
    retryable: bool = False


@dataclass(frozen=True)
class TradingViewMountResult:
    mounted_at_ms: int


class TradingViewWidgetPort(Protocol):
    """Frontera DOM; la implementacion real vive en el navegador."""

    async def health(
        self, context: OperationContext
    ) -> TradingViewPortHealth: ...

    async def mount(
        self,
        spec: TradingViewWidgetSpec,
        context: OperationContext,
    ) -> TradingViewMountResult: ...

    async def destroy(self, context: OperationContext) -> None: ...


class TradingViewWidgetAdapter:
    """Adapter del widget iframe gratuito; no finge la API Advanced Charts."""

    provider_id = "tradingview-widget"

    def __init__(
        self,
        port: TradingViewWidgetPort,
        *,
        symbol_map: Mapping[str, str] | None = None,
        interval_map: Mapping[str, str] | None = None,
        clock_ms=None,
    ):
        self._port = port
        self._symbol_map = dict(symbol_map or DEFAULT_SYMBOL_MAP)
        self._interval_map = dict(interval_map or DEFAULT_INTERVAL_MAP)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._request: ChartMountRequest | None = None
        self._session: ChartSession | None = None
        self._mount_attempts = 0
        self._mount_failures = 0
        self._last_mount_latency_ms: int | None = None
        self._last_error_code: str | None = None

    def capabilities(self) -> frozenset[ChartCapability]:
        # El widget publico requiere reinicializacion para cambiar config.
        return frozenset()

    async def health(self, context: OperationContext) -> ChartHealth:
        port_health = await self._port.health(context)
        lifecycle = {
            TradingViewPortLifecycle.DETACHED: ChartLifecycle.DETACHED,
            TradingViewPortLifecycle.MOUNTING: ChartLifecycle.MOUNTING,
            TradingViewPortLifecycle.READY: ChartLifecycle.READY,
            TradingViewPortLifecycle.DEGRADED: ChartLifecycle.DEGRADED,
            TradingViewPortLifecycle.FAILED: ChartLifecycle.FAILED,
            TradingViewPortLifecycle.DESTROYED: ChartLifecycle.DESTROYED,
        }[port_health.lifecycle]
        return ChartHealth(
            self.provider_id,
            lifecycle,
            port_health.checked_at_ms,
            port_health.code,
            port_health.retryable,
        )

    async def mount(
        self,
        request: ChartMountRequest,
        context: OperationContext,
    ) -> ChartSession:
        if request.required_capabilities:
            raise ChartMountFailed(
                "el widget publico no satisface capacidades mutables"
            )
        if self._session is not None:
            if request == self._request:
                return self._session
            raise ChartLifecycleError(
                "destruya el widget antes de cambiar su configuracion"
            )
        try:
            symbol = self._symbol_map[request.symbol]
        except KeyError as exc:
            raise ChartMountFailed("simbolo TradingView no mapeado") from exc
        try:
            interval = self._interval_map[request.interval]
        except KeyError as exc:
            raise ChartMountFailed("intervalo TradingView no mapeado") from exc
        if request.theme_ref not in {None, "light", "dark"}:
            raise ChartMountFailed("theme_ref no soportado por el widget")

        spec = TradingViewWidgetSpec(
            request.target_ref,
            symbol,
            interval,
            request.theme_ref,
        )
        started = self._clock_ms()
        self._mount_attempts += 1
        try:
            result = await self._port.mount(spec, context)
        except Exception as exc:
            self._mount_failures += 1
            self._last_error_code = type(exc).__name__
            raise
        self._last_mount_latency_ms = max(0, self._clock_ms() - started)
        self._last_error_code = None
        self._request = request
        self._session = ChartSession(
            self.provider_id,
            request.target_ref,
            request.symbol,
            request.interval,
            result.mounted_at_ms,
            request.theme_ref,
        )
        return self._session

    async def set_symbol(
        self, symbol: str, context: OperationContext
    ) -> None:
        raise ChartCapabilityError(
            "set_symbol exige reinicializar el widget publico"
        )

    async def set_interval(
        self, interval: str, context: OperationContext
    ) -> None:
        raise ChartCapabilityError(
            "set_interval exige reinicializar el widget publico"
        )

    async def set_theme(
        self, theme_ref: str, context: OperationContext
    ) -> None:
        raise ChartCapabilityError(
            "set_theme exige reinicializar el widget publico"
        )

    async def fullscreen(self, context: OperationContext) -> None:
        raise ChartCapabilityError(
            "fullscreen no es capacidad del widget publico"
        )

    async def destroy(self, context: OperationContext) -> None:
        await self._port.destroy(context)
        self._request = None
        self._session = None

    def stats(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "product": "advanced-real-time-chart-widget",
            "mount_attempts": self._mount_attempts,
            "mount_failures": self._mount_failures,
            "last_mount_latency_ms": self._last_mount_latency_ms,
            "last_error_code": self._last_error_code,
            "runtime_mutation": False,
            "advanced_charts_library": False,
        }
