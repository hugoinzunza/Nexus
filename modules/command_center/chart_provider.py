"""Contrato headless y seleccion de adaptadores de graficos."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable, Protocol

from .operations import OperationContext, await_operation

CHART_PROVIDER_INTERFACE_VERSION = 1


class ChartProviderError(RuntimeError):
    """Error de contrato o ciclo de vida del proveedor."""


class ChartCapabilityError(ChartProviderError):
    """El adaptador no declara una capacidad solicitada."""


class ChartLifecycleError(ChartProviderError):
    """La operacion no es valida en el estado actual."""


class ChartSelectionError(ChartProviderError):
    """Ningun adaptador pudo satisfacer el montaje solicitado."""


class ChartMountFailed(ChartProviderError):
    """El adaptador no pudo completar un montaje recuperable."""


class ChartCapability(str, Enum):
    SET_SYMBOL = "set_symbol"
    SET_INTERVAL = "set_interval"
    SET_THEME = "set_theme"
    FULLSCREEN = "fullscreen"


class ChartLifecycle(str, Enum):
    DETACHED = "detached"
    MOUNTING = "mounting"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    DESTROYED = "destroyed"


@dataclass(frozen=True)
class ChartHealth:
    provider_id: str
    lifecycle: ChartLifecycle
    checked_at_ms: int
    code: str | None = None
    retryable: bool = False


@dataclass(frozen=True)
class ChartMountRequest:
    """Solicitud sin dimensiones ni decisiones de representacion."""

    target_ref: str
    symbol: str
    interval: str
    required_capabilities: frozenset[ChartCapability] = frozenset()
    theme_ref: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("target_ref", self.target_ref),
            ("symbol", self.symbol),
            ("interval", self.interval),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} debe ser string no vacio")
        if self.theme_ref is not None and not self.theme_ref.strip():
            raise ValueError("theme_ref no puede ser vacio")


@dataclass(frozen=True)
class ChartSession:
    provider_id: str
    target_ref: str
    symbol: str
    interval: str
    mounted_at_ms: int
    theme_ref: str | None = None


class ChartProvider(Protocol):
    provider_id: str

    def capabilities(self) -> frozenset[ChartCapability]: ...

    async def health(self, context: OperationContext) -> ChartHealth: ...

    async def mount(
        self,
        request: ChartMountRequest,
        context: OperationContext,
    ) -> ChartSession: ...

    async def set_symbol(
        self, symbol: str, context: OperationContext
    ) -> None: ...

    async def set_interval(
        self, interval: str, context: OperationContext
    ) -> None: ...

    async def set_theme(
        self, theme_ref: str, context: OperationContext
    ) -> None: ...

    async def fullscreen(self, context: OperationContext) -> None: ...

    async def destroy(self, context: OperationContext) -> None: ...


class ChartProviderRouter:
    """Selecciona al montar; no hace hot-swap implicito de una sesion viva."""

    interface_version = CHART_PROVIDER_INTERFACE_VERSION
    hot_swap_supported = False

    def __init__(self, providers: Iterable[ChartProvider]):
        ordered = tuple(providers)
        if not ordered:
            raise ValueError("se requiere al menos un ChartProvider")
        identifiers = [provider.provider_id for provider in ordered]
        if any(not value for value in identifiers) or len(set(identifiers)) != len(
            identifiers
        ):
            raise ValueError("provider_id debe ser unico y no vacio")
        self._providers = ordered
        self._active: ChartProvider | None = None
        self._session: ChartSession | None = None

    @property
    def session(self) -> ChartSession | None:
        return self._session

    @property
    def active_provider_id(self) -> str | None:
        return self._active.provider_id if self._active else None

    async def mount(
        self,
        request: ChartMountRequest,
        context: OperationContext | None = None,
    ) -> ChartSession:
        if self._session is not None:
            if (
                self._session.target_ref == request.target_ref
                and self._session.symbol == request.symbol
                and self._session.interval == request.interval
                and self._session.theme_ref == request.theme_ref
            ):
                return self._session
            raise ChartLifecycleError(
                "destruya la sesion activa antes de montar otra"
            )
        ctx = context or OperationContext()
        failures: list[str] = []
        for provider in self._providers:
            capabilities = provider.capabilities()
            if not request.required_capabilities.issubset(capabilities):
                continue
            try:
                health = await await_operation(provider.health(ctx), ctx)
                if health.provider_id != provider.provider_id:
                    raise ChartProviderError(
                        "health contradice al provider consultado"
                    )
                if health.lifecycle in {
                    ChartLifecycle.FAILED,
                    ChartLifecycle.DESTROYED,
                }:
                    failures.append(f"{provider.provider_id}:{health.lifecycle.value}")
                    continue
                session = await await_operation(provider.mount(request, ctx), ctx)
            except ChartMountFailed as exc:
                failures.append(f"{provider.provider_id}:{type(exc).__name__}")
                continue
            if session.provider_id != provider.provider_id:
                raise ChartProviderError("la sesion contradice al provider activo")
            self._active = provider
            self._session = session
            return session
        detail = ", ".join(failures) if failures else "sin capacidades compatibles"
        raise ChartSelectionError(f"no fue posible montar un grafico: {detail}")

    def _require(self, capability: ChartCapability) -> ChartProvider:
        if self._active is None or self._session is None:
            raise ChartLifecycleError("no existe una sesion montada")
        if capability not in self._active.capabilities():
            raise ChartCapabilityError(
                f"{self._active.provider_id} no soporta {capability.value}"
            )
        return self._active

    async def set_symbol(
        self, symbol: str, context: OperationContext | None = None
    ) -> None:
        provider = self._require(ChartCapability.SET_SYMBOL)
        if not symbol.strip():
            raise ValueError("symbol no puede ser vacio")
        ctx = context or OperationContext()
        await await_operation(provider.set_symbol(symbol, ctx), ctx)
        self._session = replace(self._session, symbol=symbol)

    async def set_interval(
        self, interval: str, context: OperationContext | None = None
    ) -> None:
        provider = self._require(ChartCapability.SET_INTERVAL)
        if not interval.strip():
            raise ValueError("interval no puede ser vacio")
        ctx = context or OperationContext()
        await await_operation(provider.set_interval(interval, ctx), ctx)
        self._session = replace(self._session, interval=interval)

    async def set_theme(
        self, theme_ref: str, context: OperationContext | None = None
    ) -> None:
        provider = self._require(ChartCapability.SET_THEME)
        if not theme_ref.strip():
            raise ValueError("theme_ref no puede ser vacio")
        ctx = context or OperationContext()
        await await_operation(provider.set_theme(theme_ref, ctx), ctx)
        self._session = replace(self._session, theme_ref=theme_ref)

    async def fullscreen(
        self, context: OperationContext | None = None
    ) -> None:
        provider = self._require(ChartCapability.FULLSCREEN)
        ctx = context or OperationContext()
        await await_operation(provider.fullscreen(ctx), ctx)

    async def destroy(
        self, context: OperationContext | None = None
    ) -> None:
        if self._active is None:
            return
        provider = self._active
        ctx = context or OperationContext()
        await await_operation(provider.destroy(ctx), ctx)
        self._active = None
        self._session = None
