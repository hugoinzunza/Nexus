import asyncio
import ast
from pathlib import Path

import pytest

from core.module_base import ModuleContext
from modules.command_center.module import CommandCenterModule
from modules.command_center.module_registry import (
    ManifestValidationError,
    ModuleLifecycle,
    ModuleManifest,
    RegistryActor,
    RegistryConfigurationError,
    RegistryLifecycleError,
    RuntimeReport,
    StaticModuleRegistry,
    command_center_module_registry,
)
from modules.command_center.operations import OperationContext

NOW = 1_785_430_000_000
ADMIN = RegistryActor("user:7", "admin")
BETA = RegistryActor("user:8", "beta")


def _run(coro):
    return asyncio.run(coro)


def _manifest(module_id, **changes):
    values = {
        "module_id": module_id,
        "version": "1.0.0",
        "capabilities": frozenset({f"{module_id}.read"}),
        "permissions": frozenset({f"{module_id}.use"}),
        "allowed_roles": frozenset({"admin", "beta"}),
        "enabled_by_default": True,
    }
    values.update(changes)
    return ModuleManifest(**values)


class FakeRuntime:
    def __init__(
        self,
        module_id,
        events,
        *,
        report=None,
        start_error=None,
        health_report=None,
        stop_error=None,
        gate=None,
    ):
        self.module_id = module_id
        self.events = events
        self.report = report or RuntimeReport(
            ModuleLifecycle.READY,
            f"{module_id}.ready",
        )
        self.start_error = start_error
        self.health_report = health_report or self.report
        self.stop_error = stop_error
        self.gate = gate

    async def start(self, context, operation):
        self.events.append(("start", self.module_id, context))
        if self.gate is not None:
            await self.gate.wait()
        if self.start_error:
            raise self.start_error
        return self.report

    async def health(self, context, operation):
        self.events.append(("health", self.module_id, context))
        return self.health_report

    async def stop(self, context, operation):
        self.events.append(("stop", self.module_id, context))
        if self.stop_error:
            raise self.stop_error


def _factories(events, *module_ids, **options):
    return {
        module_id: (
            lambda context, module_id=module_id: FakeRuntime(
                module_id,
                events,
                **options.get(module_id, {}),
            )
        )
        for module_id in module_ids
    }


def test_manifiesto_exige_formas_canonicas_y_colecciones_inmutables():
    with pytest.raises(ManifestValidationError, match="module_id"):
        _manifest("Chart Provider")
    with pytest.raises(ManifestValidationError, match="semver"):
        _manifest("chart", version="v1")
    with pytest.raises(ManifestValidationError, match="frozenset"):
        _manifest("chart", capabilities={"chart.read"})
    with pytest.raises(ManifestValidationError, match="required_topic"):
        _manifest("chart", required_topics=frozenset({"NO valido"}))


def test_registro_rechaza_duplicados_dependencias_ausentes_y_ciclos():
    with pytest.raises(ManifestValidationError, match="duplicado"):
        StaticModuleRegistry((_manifest("one"), _manifest("one")))
    with pytest.raises(ManifestValidationError, match="desconocido"):
        StaticModuleRegistry(
            (_manifest("one", dependencies=("missing",)),)
        )
    with pytest.raises(ManifestValidationError, match="ciclicas"):
        StaticModuleRegistry(
            (
                _manifest("one", dependencies=("two",)),
                _manifest("two", dependencies=("one",)),
            )
        )


def test_configuracion_desconocida_falla_antes_de_ejecutar_factories():
    events = []
    registry = StaticModuleRegistry(
        (_manifest("one"),),
        _factories(events, "one"),
    )
    with pytest.raises(RegistryConfigurationError, match="desconocidos"):
        _run(registry.initialize(ADMIN, enabled_modules={"missing"}))
    assert events == []


def test_inicializa_en_orden_topologico_y_entrega_solo_dependencias():
    events = []
    manifests = (
        _manifest("leaf", dependencies=("middle",)),
        _manifest("root"),
        _manifest("middle", dependencies=("root",)),
    )
    registry = StaticModuleRegistry(
        manifests,
        _factories(events, "root", "middle", "leaf"),
        clock_ms=lambda: NOW,
    )
    _run(registry.initialize(ADMIN))
    starts = [event for event in events if event[0] == "start"]
    assert [event[1] for event in starts] == ["root", "middle", "leaf"]
    assert dict(starts[0][2].dependencies) == {}
    assert set(starts[1][2].dependencies) == {"root"}
    assert set(starts[2][2].dependencies) == {"middle"}
    assert starts[0][2].actor == ADMIN
    assert not hasattr(starts[0][2].actor, "email")


def test_autorizacion_ocurre_antes_del_factory_y_bloquea_dependiente():
    calls = []
    manifests = (
        _manifest("admin-core", allowed_roles=frozenset({"admin"})),
        _manifest("consumer", dependencies=("admin-core",)),
        _manifest("independent"),
    )

    def factory(module_id):
        def create(context):
            calls.append(("factory", module_id))
            return FakeRuntime(module_id, calls)

        return create

    registry = StaticModuleRegistry(
        manifests,
        {item.module_id: factory(item.module_id) for item in manifests},
    )
    statuses = {
        item.module_id: item
        for item in _run(registry.initialize(BETA))
    }
    assert statuses["admin-core"].lifecycle is ModuleLifecycle.UNAUTHORIZED
    assert statuses["consumer"].lifecycle is ModuleLifecycle.BLOCKED
    assert statuses["independent"].lifecycle is ModuleLifecycle.READY
    assert ("factory", "admin-core") not in calls
    assert ("factory", "consumer") not in calls
    assert ("factory", "independent") in calls


def test_modulo_deshabilitado_no_construye_runtime():
    events = []
    registry = StaticModuleRegistry(
        (_manifest("one", enabled_by_default=False),),
        _factories(events, "one"),
    )
    status = _run(registry.initialize(ADMIN))[0]
    assert status.lifecycle is ModuleLifecycle.DISABLED
    assert events == []


def test_habilitar_modulo_incluye_dependencias_explicitas():
    events = []
    registry = StaticModuleRegistry(
        (
            _manifest("base", enabled_by_default=False),
            _manifest(
                "feature",
                enabled_by_default=False,
                dependencies=("base",),
            ),
        ),
        _factories(events, "base", "feature"),
    )
    _run(registry.initialize(ADMIN, enabled_modules={"feature"}))
    assert [event[1] for event in events] == ["base", "feature"]


def test_factory_ausente_falla_visible_y_no_simula_adaptador():
    registry = StaticModuleRegistry((_manifest("chart"),))
    status = _run(registry.initialize(ADMIN))[0]
    assert status.lifecycle is ModuleLifecycle.FAILED
    assert status.code == "registry.factory-missing"
    assert registry.stats()["start_failures"] == 1


def test_fallo_de_inicio_bloquea_dependiente_pero_no_independiente():
    events = []
    registry = StaticModuleRegistry(
        (
            _manifest("broken"),
            _manifest("dependent", dependencies=("broken",)),
            _manifest("healthy"),
        ),
        _factories(
            events,
            "broken",
            "dependent",
            "healthy",
            broken={"start_error": RuntimeError("boom")},
        ),
    )
    statuses = {
        item.module_id: item
        for item in _run(registry.initialize(ADMIN))
    }
    assert statuses["broken"].lifecycle is ModuleLifecycle.FAILED
    assert statuses["dependent"].lifecycle is ModuleLifecycle.BLOCKED
    assert statuses["healthy"].lifecycle is ModuleLifecycle.READY


def test_degradacion_es_estado_explicito_y_observable():
    events = []
    degraded = RuntimeReport(
        ModuleLifecycle.DEGRADED,
        "provider.partial",
        True,
    )
    registry = StaticModuleRegistry(
        (_manifest("media"),),
        _factories(events, "media", media={"report": degraded}),
    )
    status = _run(registry.initialize(ADMIN))[0]
    assert status.lifecycle is ModuleLifecycle.DEGRADED
    assert status.code == "provider.partial"
    assert status.retryable is True


def test_initialize_es_idempotente_para_runtime_iniciado():
    events = []
    registry = StaticModuleRegistry(
        (_manifest("one"),),
        _factories(events, "one"),
    )
    _run(registry.initialize(ADMIN))
    _run(registry.initialize(ADMIN))
    assert [event[0] for event in events] == ["start"]
    assert registry.stats()["started"] == 1


def test_una_instancia_no_se_reutiliza_entre_actores():
    events = []
    registry = StaticModuleRegistry(
        (_manifest("one"),),
        _factories(events, "one"),
    )
    _run(registry.initialize(ADMIN))
    with pytest.raises(RegistryLifecycleError, match="un solo actor"):
        _run(registry.initialize(BETA))


def test_refresh_health_actualiza_degradacion_y_captura_fallo():
    events = []
    degraded = RuntimeReport(
        ModuleLifecycle.DEGRADED,
        "source.stale",
        True,
    )
    registry = StaticModuleRegistry(
        (_manifest("one"),),
        _factories(events, "one", one={"health_report": degraded}),
    )
    _run(registry.initialize(ADMIN))
    status = _run(registry.refresh_health())[0]
    assert status.lifecycle is ModuleLifecycle.DEGRADED
    assert status.code == "source.stale"
    assert [event[0] for event in events] == ["start", "health"]


def test_shutdown_es_inverso_idempotente_y_solo_para_iniciados():
    events = []
    registry = StaticModuleRegistry(
        (
            _manifest("base"),
            _manifest("feature", dependencies=("base",)),
            _manifest("off", enabled_by_default=False),
        ),
        _factories(events, "base", "feature", "off"),
    )
    _run(registry.initialize(ADMIN))
    _run(registry.shutdown())
    _run(registry.shutdown())
    stops = [event[1] for event in events if event[0] == "stop"]
    assert stops == ["feature", "base"]
    assert registry.status("off").lifecycle is ModuleLifecycle.DISABLED


def test_shutdown_continua_si_un_runtime_falla():
    events = []
    registry = StaticModuleRegistry(
        (_manifest("first"), _manifest("second")),
        _factories(
            events,
            "first",
            "second",
            second={"stop_error": RuntimeError("boom")},
        ),
    )
    _run(registry.initialize(ADMIN))
    statuses = {
        item.module_id: item
        for item in _run(registry.shutdown())
    }
    assert statuses["second"].lifecycle is ModuleLifecycle.FAILED
    assert statuses["first"].lifecycle is ModuleLifecycle.STOPPED
    assert registry.stats()["shutdown_failures"] == 1


def test_timeout_de_inicio_falla_y_no_arranca_dependiente():
    async def scenario():
        gate = asyncio.Event()
        events = []
        registry = StaticModuleRegistry(
            (
                _manifest("slow", start_timeout_s=0.001),
                _manifest("consumer", dependencies=("slow",)),
            ),
            _factories(
                events,
                "slow",
                "consumer",
                slow={"gate": gate},
            ),
        )
        statuses = {
            item.module_id: item
            for item in await registry.initialize(ADMIN)
        }
        assert statuses["slow"].lifecycle is ModuleLifecycle.FAILED
        assert statuses["consumer"].lifecycle is ModuleLifecycle.BLOCKED
        assert statuses["slow"].code == (
            "registry.start-operation-deadline-exceeded"
        )

    _run(scenario())


def test_contexto_cancelado_no_deja_factory_ejecutado():
    async def scenario():
        events = []
        factory_calls = []

        def factory(context):
            factory_calls.append(context)
            return FakeRuntime("one", events)

        registry = StaticModuleRegistry(
            (_manifest("one"),),
            {"one": factory},
        )
        cancel = asyncio.Event()
        cancel.set()
        status = (
            await registry.initialize(
                ADMIN,
                context=OperationContext(cancel_event=cancel),
            )
        )[0]
        assert status.lifecycle is ModuleLifecycle.FAILED
        assert status.code == "registry.start-operation-cancelled"
        assert factory_calls == []
        assert events == []

    _run(scenario())


def test_registro_no_tiene_api_de_descubrimiento_hot_plug_o_swap():
    registry = command_center_module_registry()
    assert registry.dynamic_discovery_supported is False
    assert registry.hot_plug_supported is False
    assert registry.hot_swap_supported is False
    assert not hasattr(registry, "discover")
    assert not hasattr(registry, "register")
    assert not hasattr(registry, "replace")


def test_catalogo_oficial_declara_interfaces_sin_factories_y_apagadas():
    registry = command_center_module_registry()
    manifests = {item.module_id: item for item in registry.manifests()}
    assert set(manifests) == {"chart.provider", "media.controller"}
    assert all(not item.enabled_by_default for item in manifests.values())
    assert registry.stats()["attached_factories"] == 0
    assert registry.stats()["declared_modules"] == 2
    assert registry.stats()["states"]["declared"] == 2
    assert registry.stats()["modules"] == [
        {
            "module_id": "chart.provider",
            "version": "1.0.0",
            "lifecycle": "declared",
            "code": "registry.declared",
            "retryable": False,
            "factory_attached": False,
        },
        {
            "module_id": "media.controller",
            "version": "1.0.0",
            "lifecycle": "declared",
            "code": "registry.declared",
            "retryable": False,
            "factory_attached": False,
        },
    ]


def test_health_del_modulo_expone_registro_estatico_sin_adaptadores():
    module = CommandCenterModule(
        ModuleContext(
            "command_center",
            "modules/command_center",
            {},
            lambda _message: None,
        )
    )
    stats = module.health()["module_registry"]
    assert stats["backend"] == "static"
    assert stats["attached_factories"] == 0
    assert stats["dynamic_discovery"] is False


def test_registro_no_importa_ui_fastapi_bot_o_dominios():
    path = (
        Path(__file__).parents[1]
        / "modules"
        / "command_center"
        / "module_registry.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    forbidden = (
        "fastapi",
        "starlette",
        "modules.bot",
        "modules.trading",
        "selenium",
        "playwright",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imports
        for prefix in forbidden
    )
