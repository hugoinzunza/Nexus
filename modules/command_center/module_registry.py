"""Registro estatico y ciclo de vida de modulos headless."""

from __future__ import annotations

import asyncio
import inspect
import re
import time
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Protocol

from .chart_provider import ChartCapability
from .contracts import validate_topic_name
from .media_controller import MediaCapability
from .operations import OperationContext, await_operation

MODULE_REGISTRY_INTERFACE_VERSION = 1
_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_VERSION_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)


class ModuleRegistryError(RuntimeError):
    """Error de configuracion o ciclo de vida del registro."""


class ManifestValidationError(ModuleRegistryError):
    """Un manifiesto no cumple las reglas del registro."""


class RegistryConfigurationError(ModuleRegistryError):
    """La seleccion solicitada no corresponde al catalogo estatico."""


class RegistryLifecycleError(ModuleRegistryError):
    """La operacion contradice el ciclo de vida del registro."""


class ModuleLifecycle(str, Enum):
    DECLARED = "declared"
    DISABLED = "disabled"
    UNAUTHORIZED = "unauthorized"
    BLOCKED = "blocked"
    INITIALIZING = "initializing"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass(frozen=True)
class ModuleManifest:
    module_id: str
    version: str
    capabilities: frozenset[str]
    permissions: frozenset[str]
    allowed_roles: frozenset[str]
    dependencies: tuple[str, ...] = ()
    required_topics: frozenset[str] = frozenset()
    enabled_by_default: bool = False
    start_timeout_s: float = 5.0
    stop_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        if not _NAME_RE.fullmatch(self.module_id):
            raise ManifestValidationError("module_id no usa la forma canonica")
        if not _VERSION_RE.fullmatch(self.version):
            raise ManifestValidationError("version debe usar semver numerico")
        for label, values in (
            ("capability", self.capabilities),
            ("permission", self.permissions),
        ):
            if not isinstance(values, frozenset):
                raise ManifestValidationError(f"{label}s debe ser frozenset")
            if any(not _NAME_RE.fullmatch(value) for value in values):
                raise ManifestValidationError(
                    f"{label} no usa la forma canonica"
                )
        if (
            not isinstance(self.allowed_roles, frozenset)
            or not self.allowed_roles
            or any(not _ROLE_RE.fullmatch(role) for role in self.allowed_roles)
        ):
            raise ManifestValidationError("allowed_roles es invalido")
        if not isinstance(self.dependencies, tuple):
            raise ManifestValidationError("dependencies debe ser tuple")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ManifestValidationError("dependencies contiene duplicados")
        if self.module_id in self.dependencies:
            raise ManifestValidationError("un modulo no puede depender de si mismo")
        if any(not _NAME_RE.fullmatch(item) for item in self.dependencies):
            raise ManifestValidationError("dependency no usa la forma canonica")
        if not isinstance(self.required_topics, frozenset):
            raise ManifestValidationError("required_topics debe ser frozenset")
        for topic in self.required_topics:
            try:
                validate_topic_name(topic)
            except ValueError as exc:
                raise ManifestValidationError("required_topic invalido") from exc
        if type(self.enabled_by_default) is not bool:
            raise ManifestValidationError("enabled_by_default debe ser boolean")
        for name, value in (
            ("start_timeout_s", self.start_timeout_s),
            ("stop_timeout_s", self.stop_timeout_s),
        ):
            if type(value) not in (int, float) or value <= 0:
                raise ManifestValidationError(f"{name} debe ser positivo")


@dataclass(frozen=True)
class RegistryActor:
    subject: str
    role: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject:
            raise ValueError("subject debe ser string no vacio")
        if not _ROLE_RE.fullmatch(self.role):
            raise ValueError("role no usa la forma canonica")


@dataclass(frozen=True)
class RuntimeContext:
    """Contexto minimo entregado al factory despues de autorizar."""

    actor: RegistryActor
    manifest: ModuleManifest
    dependencies: Mapping[str, Any]


@dataclass(frozen=True)
class RuntimeReport:
    lifecycle: ModuleLifecycle
    code: str
    retryable: bool = False

    def __post_init__(self) -> None:
        if self.lifecycle not in {
            ModuleLifecycle.READY,
            ModuleLifecycle.DEGRADED,
        }:
            raise ValueError("runtime solo puede reportar ready o degraded")
        if not _NAME_RE.fullmatch(self.code):
            raise ValueError("code no usa la forma canonica")
        if type(self.retryable) is not bool:
            raise ValueError("retryable debe ser boolean")


@dataclass(frozen=True)
class ModuleStatus:
    module_id: str
    lifecycle: ModuleLifecycle
    changed_at_ms: int
    code: str
    retryable: bool = False


class ModuleRuntime(Protocol):
    async def start(
        self,
        context: RuntimeContext,
        operation: OperationContext,
    ) -> RuntimeReport: ...

    async def health(
        self,
        context: RuntimeContext,
        operation: OperationContext,
    ) -> RuntimeReport: ...

    async def stop(
        self,
        context: RuntimeContext,
        operation: OperationContext,
    ) -> None: ...


ModuleFactory = Callable[[RuntimeContext], ModuleRuntime]


class StaticModuleRegistry:
    """Catalogo inmutable; no descubre, registra ni sustituye modulos en runtime."""

    interface_version = MODULE_REGISTRY_INTERFACE_VERSION
    dynamic_discovery_supported = False
    hot_plug_supported = False
    hot_swap_supported = False

    def __init__(
        self,
        manifests: Iterable[ModuleManifest],
        factories: Mapping[str, ModuleFactory] | None = None,
        *,
        clock_ms=None,
    ):
        ordered = tuple(manifests)
        if not ordered:
            raise ManifestValidationError("el registro requiere manifiestos")
        identifiers = [manifest.module_id for manifest in ordered]
        if len(set(identifiers)) != len(identifiers):
            raise ManifestValidationError("module_id duplicado")
        self._manifests = MappingProxyType(
            {manifest.module_id: manifest for manifest in ordered}
        )
        provided = dict(factories or {})
        unknown_factories = set(provided) - set(self._manifests)
        if unknown_factories:
            raise RegistryConfigurationError(
                "factory sin manifiesto: " + ", ".join(sorted(unknown_factories))
            )
        if any(not callable(factory) for factory in provided.values()):
            raise RegistryConfigurationError("todo factory debe ser callable")
        self._factories = MappingProxyType(provided)
        self._order = self._resolve_order(ordered)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        now = self._clock_ms()
        self._statuses = {
            item.module_id: ModuleStatus(
                item.module_id,
                ModuleLifecycle.DECLARED,
                now,
                "registry.declared",
            )
            for item in ordered
        }
        self._runtimes: dict[str, ModuleRuntime] = {}
        self._contexts: dict[str, RuntimeContext] = {}
        self._started_order: list[str] = []
        self._actor: RegistryActor | None = None
        self._lock: asyncio.Lock | None = None
        self._shutdown_started = False
        self._starts = 0
        self._start_failures = 0
        self._authorization_rejections = 0
        self._shutdown_failures = 0

    def _resolve_order(
        self, manifests: tuple[ModuleManifest, ...]
    ) -> tuple[str, ...]:
        known = {item.module_id for item in manifests}
        for manifest in manifests:
            missing = set(manifest.dependencies) - known
            if missing:
                raise ManifestValidationError(
                    f"{manifest.module_id} depende de modulo desconocido"
                )
        state: dict[str, int] = {}
        result: list[str] = []

        def visit(module_id: str) -> None:
            marker = state.get(module_id, 0)
            if marker == 1:
                raise ManifestValidationError("dependencias ciclicas")
            if marker == 2:
                return
            state[module_id] = 1
            for dependency in self._manifests[module_id].dependencies:
                visit(dependency)
            state[module_id] = 2
            result.append(module_id)

        for manifest in manifests:
            visit(manifest.module_id)
        return tuple(result)

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def manifests(self) -> tuple[ModuleManifest, ...]:
        return tuple(self._manifests[module_id] for module_id in self._order)

    def status(self, module_id: str) -> ModuleStatus:
        try:
            return self._statuses[module_id]
        except KeyError as exc:
            raise RegistryConfigurationError("modulo desconocido") from exc

    def _set_status(
        self,
        module_id: str,
        lifecycle: ModuleLifecycle,
        code: str,
        retryable: bool = False,
    ) -> None:
        self._statuses[module_id] = ModuleStatus(
            module_id,
            lifecycle,
            self._clock_ms(),
            code,
            retryable,
        )

    def _selection(
        self, enabled_modules: Iterable[str] | None
    ) -> frozenset[str]:
        if enabled_modules is None:
            selected = {
                item.module_id
                for item in self._manifests.values()
                if item.enabled_by_default
            }
        else:
            selected = set(enabled_modules)
            unknown = selected - set(self._manifests)
            if unknown:
                raise RegistryConfigurationError(
                    "configuracion contiene modulos desconocidos: "
                    + ", ".join(sorted(unknown))
                )
        pending = list(selected)
        while pending:
            module_id = pending.pop()
            for dependency in self._manifests[module_id].dependencies:
                if dependency not in selected:
                    selected.add(dependency)
                    pending.append(dependency)
        return frozenset(selected)

    @staticmethod
    def _child_context(
        parent: OperationContext,
        timeout: float,
    ) -> OperationContext:
        own_deadline = time.monotonic() + timeout
        deadline = (
            own_deadline
            if parent.deadline is None
            else min(parent.deadline, own_deadline)
        )
        return OperationContext(deadline, parent.cancel_event)

    @staticmethod
    def _validate_runtime(runtime: Any) -> ModuleRuntime:
        if not all(
            callable(getattr(runtime, method, None))
            for method in ("start", "health", "stop")
        ):
            raise RegistryConfigurationError(
                "factory no implementa el ciclo de vida comun"
            )
        return runtime

    async def initialize(
        self,
        actor: RegistryActor,
        *,
        enabled_modules: Iterable[str] | None = None,
        context: OperationContext | None = None,
    ) -> tuple[ModuleStatus, ...]:
        selected = self._selection(enabled_modules)
        async with self._get_lock():
            if self._shutdown_started:
                raise RegistryLifecycleError("el registro ya inicio shutdown")
            if self._actor is not None and self._actor != actor:
                raise RegistryLifecycleError(
                    "una instancia del registro pertenece a un solo actor"
                )
            self._actor = actor
            parent = context or OperationContext()
            for module_id in self._order:
                current = self._statuses[module_id].lifecycle
                if current in {
                    ModuleLifecycle.READY,
                    ModuleLifecycle.DEGRADED,
                }:
                    continue
                manifest = self._manifests[module_id]
                if module_id not in selected:
                    self._set_status(
                        module_id,
                        ModuleLifecycle.DISABLED,
                        "registry.disabled",
                    )
                    continue
                if actor.role not in manifest.allowed_roles:
                    self._authorization_rejections += 1
                    self._set_status(
                        module_id,
                        ModuleLifecycle.UNAUTHORIZED,
                        "registry.unauthorized",
                    )
                    continue
                unavailable_dependencies = [
                    dependency
                    for dependency in manifest.dependencies
                    if self._statuses[dependency].lifecycle
                    not in {ModuleLifecycle.READY, ModuleLifecycle.DEGRADED}
                ]
                if unavailable_dependencies:
                    self._set_status(
                        module_id,
                        ModuleLifecycle.BLOCKED,
                        "registry.dependency-unavailable",
                    )
                    continue
                factory = self._factories.get(module_id)
                if factory is None:
                    self._start_failures += 1
                    self._set_status(
                        module_id,
                        ModuleLifecycle.FAILED,
                        "registry.factory-missing",
                    )
                    continue
                dependencies = MappingProxyType(
                    {
                        dependency: self._runtimes[dependency]
                        for dependency in manifest.dependencies
                    }
                )
                runtime_context = RuntimeContext(
                    actor,
                    manifest,
                    dependencies,
                )
                self._set_status(
                    module_id,
                    ModuleLifecycle.INITIALIZING,
                    "registry.initializing",
                )
                try:
                    parent.raise_if_cancelled()
                    runtime = self._validate_runtime(factory(runtime_context))
                    operation = self._child_context(
                        parent, manifest.start_timeout_s
                    )
                    report = await await_operation(
                        runtime.start(runtime_context, operation),
                        operation,
                    )
                    if not isinstance(report, RuntimeReport):
                        raise RegistryConfigurationError(
                            "start debe devolver RuntimeReport"
                        )
                except Exception as exc:  # noqa: BLE001
                    self._start_failures += 1
                    self._set_status(
                        module_id,
                        ModuleLifecycle.FAILED,
                        f"registry.start-{_exception_code(exc)}",
                        retryable=True,
                    )
                    continue
                self._runtimes[module_id] = runtime
                self._contexts[module_id] = runtime_context
                self._started_order.append(module_id)
                self._starts += 1
                self._set_status(
                    module_id,
                    report.lifecycle,
                    report.code,
                    report.retryable,
                )
            return self.statuses()

    async def refresh_health(
        self,
        context: OperationContext | None = None,
    ) -> tuple[ModuleStatus, ...]:
        async with self._get_lock():
            parent = context or OperationContext()
            for module_id in tuple(self._started_order):
                current = self._statuses[module_id].lifecycle
                if current not in {
                    ModuleLifecycle.READY,
                    ModuleLifecycle.DEGRADED,
                    ModuleLifecycle.FAILED,
                }:
                    continue
                manifest = self._manifests[module_id]
                operation = self._child_context(
                    parent, manifest.start_timeout_s
                )
                try:
                    report = await await_operation(
                        self._runtimes[module_id].health(
                            self._contexts[module_id],
                            operation,
                        ),
                        operation,
                    )
                    if not isinstance(report, RuntimeReport):
                        raise RegistryConfigurationError(
                            "health debe devolver RuntimeReport"
                        )
                except Exception as exc:  # noqa: BLE001
                    self._set_status(
                        module_id,
                        ModuleLifecycle.FAILED,
                        f"registry.health-{_exception_code(exc)}",
                        retryable=True,
                    )
                    continue
                self._set_status(
                    module_id,
                    report.lifecycle,
                    report.code,
                    report.retryable,
                )
            return self.statuses()

    async def shutdown(
        self,
        context: OperationContext | None = None,
    ) -> tuple[ModuleStatus, ...]:
        async with self._get_lock():
            self._shutdown_started = True
            parent = context or OperationContext()
            for module_id in reversed(self._started_order):
                if self._statuses[module_id].lifecycle is ModuleLifecycle.STOPPED:
                    continue
                manifest = self._manifests[module_id]
                self._set_status(
                    module_id,
                    ModuleLifecycle.STOPPING,
                    "registry.stopping",
                )
                operation = self._child_context(
                    parent, manifest.stop_timeout_s
                )
                try:
                    result = self._runtimes[module_id].stop(
                        self._contexts[module_id],
                        operation,
                    )
                    if not inspect.isawaitable(result):
                        raise RegistryConfigurationError(
                            "stop debe ser awaitable"
                        )
                    await await_operation(result, operation)
                except Exception as exc:  # noqa: BLE001
                    self._shutdown_failures += 1
                    self._set_status(
                        module_id,
                        ModuleLifecycle.FAILED,
                        f"registry.stop-{_exception_code(exc)}",
                        retryable=True,
                    )
                    continue
                self._set_status(
                    module_id,
                    ModuleLifecycle.STOPPED,
                    "registry.stopped",
                )
            return self.statuses()

    def statuses(self) -> tuple[ModuleStatus, ...]:
        return tuple(self._statuses[module_id] for module_id in self._order)

    def stats(self) -> dict[str, Any]:
        counts = {state.value: 0 for state in ModuleLifecycle}
        for status in self._statuses.values():
            counts[status.lifecycle.value] += 1
        modules = [
            {
                "module_id": module_id,
                "version": self._manifests[module_id].version,
                "lifecycle": self._statuses[module_id].lifecycle.value,
                "code": self._statuses[module_id].code,
                "retryable": self._statuses[module_id].retryable,
                "factory_attached": module_id in self._factories,
            }
            for module_id in self._order
        ]
        return {
            "backend": "static",
            "status": "ready",
            "interface_version": self.interface_version,
            "declared_modules": len(self._manifests),
            "attached_factories": len(self._factories),
            "started": self._starts,
            "start_failures": self._start_failures,
            "authorization_rejections": self._authorization_rejections,
            "shutdown_failures": self._shutdown_failures,
            "states": counts,
            "modules": modules,
            "dynamic_discovery": False,
            "hot_plug": False,
            "hot_swap": False,
        }


def _exception_code(exc: Exception) -> str:
    name = type(exc).__name__
    pieces = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+", name)
    return "-".join(piece.lower() for piece in pieces) or "error"


def command_center_module_registry(
    factories: Mapping[str, ModuleFactory] | None = None,
    *,
    chart_capabilities: Iterable[ChartCapability] | None = None,
    media_capabilities: Iterable[MediaCapability] | None = None,
) -> StaticModuleRegistry:
    """Catalogo oficial; los adaptadores permanecen sin factory y apagados."""

    chart_capabilities = frozenset(
        f"chart.{capability.value.replace('_', '-')}"
        for capability in (
            ChartCapability
            if chart_capabilities is None
            else chart_capabilities
        )
    )
    media_capabilities = frozenset(
        f"media.{capability.value.replace('_', '-')}"
        for capability in (
            MediaCapability
            if media_capabilities is None
            else media_capabilities
        )
    )
    return StaticModuleRegistry(
        (
            ModuleManifest(
                module_id="chart.provider",
                version="1.0.0",
                capabilities=chart_capabilities,
                permissions=frozenset({"chart.read", "chart.control"}),
                allowed_roles=frozenset({"admin", "beta"}),
            ),
            ModuleManifest(
                module_id="media.controller",
                version="1.0.0",
                capabilities=media_capabilities,
                permissions=frozenset({"media.read", "media.control"}),
                allowed_roles=frozenset({"admin", "beta"}),
            ),
        ),
        factories,
    )
