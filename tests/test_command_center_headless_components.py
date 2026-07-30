import asyncio
import ast
from pathlib import Path

import pytest

from modules.command_center.chart_provider import (
    ChartCapability,
    ChartCapabilityError,
    ChartLifecycle,
    ChartMountFailed,
    ChartMountRequest,
    ChartProviderRouter,
)
from modules.command_center.conformance import (
    ConformanceViolation,
    HeadlessIntegrationHarness,
    verify_chart_provider,
    verify_media_controller,
)
from modules.command_center.fake_adapters import (
    FakeChartProvider,
    FakeMediaController,
)
from modules.command_center.headless_components import (
    ChartProviderComponent,
    HeadlessComponentUnavailable,
    MediaControllerComponent,
)
from modules.command_center.media_controller import (
    MediaAckStatus,
    MediaAction,
    MediaCapability,
    MediaCapabilityError,
    MediaCommand,
    MediaCommandConflict,
    MediaLifecycle,
)
from modules.command_center.module_registry import (
    ModuleLifecycle,
    ModuleManifest,
    RegistryActor,
    RuntimeContext,
)
from modules.command_center.operations import (
    OperationContext,
    OperationDeadlineExceeded,
)

NOW = 1_785_430_000_000
OPERATION = OperationContext()
ACTOR = RegistryActor("user:7", "admin")


def _run(coro):
    return asyncio.run(coro)


def _runtime_context(module_id):
    if module_id == "chart":
        capabilities = frozenset(
            f"chart.{item.value.replace('_', '-')}"
            for item in ChartCapability
        )
    elif module_id == "media":
        capabilities = frozenset(
            f"media.{item.value.replace('_', '-')}"
            for item in MediaCapability
        )
    else:
        capabilities = frozenset({f"{module_id}.read"})
    return RuntimeContext(
        ACTOR,
        ModuleManifest(
            module_id,
            "1.0.0",
            capabilities,
            frozenset({f"{module_id}.use"}),
            frozenset({"admin"}),
        ),
        {},
    )


def _request(**changes):
    values = {
        "target_ref": "test:chart",
        "symbol": "BTCUSDT",
        "interval": "1h",
    }
    values.update(changes)
    return ChartMountRequest(**values)


def _command(command_id="cmd-1", action=MediaAction.PLAY, **changes):
    values = {
        "command_id": command_id,
        "action": action,
        "issued_at_ms": NOW,
    }
    values.update(changes)
    return MediaCommand(**values)


def test_fake_chart_ejercita_ciclo_y_operaciones_sin_ui():
    async def scenario():
        provider = FakeChartProvider(clock_ms=lambda: NOW)
        assert (await provider.health(OPERATION)).lifecycle is ChartLifecycle.DETACHED
        session = await provider.mount(_request(), OPERATION)
        assert session.mounted_at_ms == NOW
        assert await provider.mount(_request(), OPERATION) == session
        await provider.set_symbol("ETHUSDT", OPERATION)
        await provider.set_interval("4h", OPERATION)
        await provider.set_theme("dark-ref", OPERATION)
        await provider.fullscreen(OPERATION)
        assert provider.session.symbol == "ETHUSDT"
        assert provider.session.interval == "4h"
        assert provider.session.theme_ref == "dark-ref"
        await provider.destroy(OPERATION)
        assert (await provider.health(OPERATION)).lifecycle is ChartLifecycle.DESTROYED

    _run(scenario())


def test_fake_chart_respeta_capacidades_y_fallos_programados():
    async def scenario():
        provider = FakeChartProvider(
            capabilities=[ChartCapability.SET_SYMBOL]
        )
        provider.fail_next("mount", ChartMountFailed("simulado"))
        with pytest.raises(ChartMountFailed, match="simulado"):
            await provider.mount(_request(), OPERATION)
        await provider.mount(_request(), OPERATION)
        with pytest.raises(ChartCapabilityError):
            await provider.set_interval("4h", OPERATION)

    _run(scenario())


def test_fake_chart_permite_probar_fallback_del_router():
    async def scenario():
        broken = FakeChartProvider("broken")
        broken.fail_next("mount", ChartMountFailed("caido"))
        fallback = FakeChartProvider("fallback")
        router = ChartProviderRouter([broken, fallback])
        session = await router.mount(_request())
        assert session.provider_id == "fallback"

    _run(scenario())


def test_fake_chart_honra_deadline():
    async def scenario():
        provider = FakeChartProvider(operation_delay_s=0.02)
        with pytest.raises(OperationDeadlineExceeded):
            await provider.health(OperationContext.with_timeout(0.001))

    _run(scenario())


def test_fake_media_aplica_estado_e_idempotencia():
    async def scenario():
        controller = FakeMediaController(clock_ms=lambda: NOW)
        command = _command()
        first = await controller.execute(command, OPERATION)
        second = await controller.execute(command, OPERATION)
        assert first is second
        assert len(controller.effects) == 1
        assert (await controller.current_state(OPERATION)).playback == "playing"
        volume = _command(
            "cmd-volume",
            MediaAction.SET_VOLUME,
            arguments={"volume": 0.2},
        )
        await controller.execute(volume, OPERATION)
        assert (await controller.current_state(OPERATION)).volume == 0.2

    _run(scenario())


def test_fake_media_idempotencia_concurrente_aplica_una_vez():
    async def scenario():
        controller = FakeMediaController(operation_delay_s=0.01)
        command = _command()
        results = await asyncio.gather(
            controller.execute(command, OPERATION),
            controller.execute(command, OPERATION),
        )
        assert results[0] == results[1]
        assert controller.effects == [("cmd-1", MediaAction.PLAY)]

    _run(scenario())


def test_fake_media_adopta_resultado_que_llega_despues_del_timeout():
    async def scenario():
        controller = FakeMediaController(operation_delay_s=0.01)
        command = _command()
        with pytest.raises(OperationDeadlineExceeded):
            await controller.execute(
                command,
                OperationContext.with_timeout(0.001),
            )
        await asyncio.sleep(0.02)
        result = await controller.execute(command, OPERATION)
        assert result.status is MediaAckStatus.APPLIED
        assert controller.effects == [("cmd-1", MediaAction.PLAY)]

    _run(scenario())


def test_fake_media_detecta_conflicto_y_unknown_se_reconcilia():
    async def scenario():
        controller = FakeMediaController()
        controller.return_next(MediaAckStatus.UNKNOWN)
        command = _command()
        first = await controller.execute(command, OPERATION)
        second = await controller.execute(command, OPERATION)
        assert first.status is MediaAckStatus.UNKNOWN
        assert second.status is MediaAckStatus.APPLIED
        assert len(controller.effects) == 1
        with pytest.raises(MediaCommandConflict):
            await controller.execute(
                _command(action=MediaAction.PAUSE),
                OPERATION,
            )

    _run(scenario())


def test_fake_media_no_simula_capacidades_ausentes():
    async def scenario():
        controller = FakeMediaController(
            capabilities=[MediaCapability.CURRENT_STATE]
        )
        with pytest.raises(MediaCapabilityError, match="no soportado"):
            await controller.execute(_command(), OPERATION)

    _run(scenario())


def test_chart_component_traduce_salud_y_shutdown():
    async def scenario():
        provider = FakeChartProvider()
        component = ChartProviderComponent(provider)
        context = _runtime_context("chart")
        report = await component.start(context, OPERATION)
        assert report.lifecycle is ModuleLifecycle.READY
        provider.set_health(
            ChartLifecycle.DEGRADED,
            code="chart.partial",
            retryable=True,
        )
        report = await component.health(context, OPERATION)
        assert report.lifecycle is ModuleLifecycle.DEGRADED
        assert report.code == "chart.partial"
        await component.stop(context, OPERATION)
        assert (await provider.health(OPERATION)).lifecycle is ChartLifecycle.DESTROYED

    _run(scenario())


def test_componentes_fallan_cerrado_con_provider_no_disponible():
    async def scenario():
        chart = FakeChartProvider()
        chart.set_health(ChartLifecycle.FAILED)
        with pytest.raises(HeadlessComponentUnavailable):
            await ChartProviderComponent(chart).start(
                _runtime_context("chart"),
                OPERATION,
            )
        media = FakeMediaController()
        media.set_health(MediaLifecycle.REVOKED)
        with pytest.raises(HeadlessComponentUnavailable):
            await MediaControllerComponent(media).start(
                _runtime_context("media"),
                OPERATION,
            )

    _run(scenario())


def test_componentes_rechazan_capacidades_distintas_al_manifiesto():
    async def scenario():
        chart = FakeChartProvider(
            capabilities=[ChartCapability.SET_SYMBOL]
        )
        with pytest.raises(
            HeadlessComponentUnavailable,
            match="capacidades",
        ):
            await ChartProviderComponent(chart).start(
                _runtime_context("chart"),
                OPERATION,
            )
        media = FakeMediaController(
            capabilities=[MediaCapability.CURRENT_STATE]
        )
        with pytest.raises(
            HeadlessComponentUnavailable,
            match="capacidades",
        ):
            await MediaControllerComponent(media).start(
                _runtime_context("media"),
                OPERATION,
            )

    _run(scenario())


def test_media_component_traduce_degradacion_y_cierra():
    async def scenario():
        controller = FakeMediaController()
        controller.set_health(
            MediaLifecycle.DEGRADED,
            code="media.partial",
            retryable=True,
        )
        component = MediaControllerComponent(controller)
        context = _runtime_context("media")
        report = await component.start(context, OPERATION)
        assert report.lifecycle is ModuleLifecycle.DEGRADED
        await component.stop(context, OPERATION)
        assert (await controller.health(OPERATION)).lifecycle is MediaLifecycle.CLOSED

    _run(scenario())


def test_harness_no_construye_adaptadores_antes_de_autorizar():
    created = []

    def chart_factory():
        created.append("chart")
        return FakeChartProvider()

    def media_factory():
        created.append("media")
        return FakeMediaController()

    harness = HeadlessIntegrationHarness(
        chart_factory=chart_factory,
        media_factory=media_factory,
    )
    assert created == []
    with pytest.raises(RuntimeError, match="fallo el harness"):
        _run(harness.start(RegistryActor("guest:1", "guest")))
    assert created == []


def test_harness_integra_registro_componentes_y_shutdown():
    async def scenario():
        harness = HeadlessIntegrationHarness()
        await harness.start()
        assert isinstance(harness.chart, FakeChartProvider)
        assert isinstance(harness.media, FakeMediaController)
        assert harness.registry.stats()["attached_factories"] == 2
        assert harness.registry.stats()["states"]["ready"] == 2
        await harness.shutdown()
        assert harness.registry.stats()["states"]["stopped"] == 2

    _run(scenario())


def test_harness_admite_subconjunto_solo_si_manifiesto_lo_declara():
    async def scenario():
        chart_caps = frozenset({ChartCapability.SET_SYMBOL})
        media_caps = frozenset({MediaCapability.CURRENT_STATE})
        harness = HeadlessIntegrationHarness(
            chart_factory=lambda: FakeChartProvider(
                capabilities=chart_caps
            ),
            media_factory=lambda: FakeMediaController(
                capabilities=media_caps
            ),
            chart_capabilities=chart_caps,
            media_capabilities=media_caps,
        )
        await harness.start()
        assert harness.registry.stats()["states"]["ready"] == 2
        await harness.shutdown()

    _run(scenario())


def test_probe_chart_valida_todas_las_capacidades_del_fake():
    report = _run(
        verify_chart_provider(
            FakeChartProvider(clock_ms=lambda: NOW)
        )
    )
    assert report.interface == "chart-provider-v1"
    assert set(report.operations) == {
        "health",
        "mount",
        "mount-idempotent",
        "set_symbol",
        "set_interval",
        "set_theme",
        "fullscreen",
        "destroy",
    }


def test_probe_media_es_read_only_por_defecto():
    controller = FakeMediaController()
    report = _run(verify_media_controller(controller))
    assert report.operations == ("health", "current_state")
    assert controller.effects == []


def test_probe_media_con_comandos_valida_ack_e_idempotencia():
    controller = FakeMediaController()
    report = _run(
        verify_media_controller(controller, include_commands=True)
    )
    assert set(report.operations) == {
        "health",
        "current_state",
        "play",
        "pause",
        "next",
        "previous",
        "set_volume",
        "open_app",
    }
    assert len(controller.effects) == 6


def test_probe_media_acepta_unknown_si_mismo_id_reconcilia_terminal():
    controller = FakeMediaController()
    controller.return_next(MediaAckStatus.UNKNOWN)
    report = _run(
        verify_media_controller(controller, include_commands=True)
    )
    assert "play" in report.operations
    assert controller.effects[0] == (
        "conformance-1",
        MediaAction.PLAY,
    )


def test_probe_chart_intenta_destroy_aunque_mount_falle():
    provider = FakeChartProvider()
    provider.fail_next("mount", ChartMountFailed("simulado"))
    with pytest.raises(ChartMountFailed):
        _run(verify_chart_provider(provider))
    assert ("destroy", None) in provider.calls


def test_probe_detecta_identidad_inconsistente():
    class BrokenChart(FakeChartProvider):
        async def health(self, context):
            return await FakeChartProvider("other").health(context)

    with pytest.raises(ConformanceViolation, match="provider_id"):
        _run(verify_chart_provider(BrokenChart()))


def test_componentes_y_fakes_no_importan_ui_dominios_o_servicios_reales():
    root = Path(__file__).parents[1]
    imports = []
    for relative in (
        "modules/command_center/fake_adapters.py",
        "modules/command_center/headless_components.py",
        "modules/command_center/conformance.py",
    ):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
    forbidden = (
        "fastapi",
        "starlette",
        "selenium",
        "playwright",
        "modules.bot",
        "modules.trading",
        "spotipy",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imports
        for prefix in forbidden
    )
