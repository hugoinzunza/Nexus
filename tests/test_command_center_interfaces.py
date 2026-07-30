import asyncio
import ast
from dataclasses import replace
from pathlib import Path

import pytest

from core.module_base import ModuleContext
from modules.command_center.chart_provider import (
    ChartCapability,
    ChartCapabilityError,
    ChartHealth,
    ChartLifecycle,
    ChartLifecycleError,
    ChartMountFailed,
    ChartMountRequest,
    ChartProviderRouter,
    ChartSelectionError,
    ChartSession,
)
from modules.command_center.media_controller import (
    MediaAck,
    MediaAckInvalid,
    MediaAckStatus,
    MediaAction,
    MediaCapability,
    MediaCapabilityError,
    MediaCommand,
    MediaCommandConflict,
    MediaControllerRouter,
    MediaHealth,
    MediaLifecycle,
    MediaLifecycleError,
    MediaState,
)
from modules.command_center.module import CommandCenterModule
from modules.command_center.operations import (
    OperationCancelled,
    OperationContext,
    OperationDeadlineExceeded,
    await_operation,
)

NOW = 1_785_430_000_000


def _run(coro):
    return asyncio.run(coro)


class FakeChart:
    def __init__(
        self,
        provider_id,
        capabilities=(),
        *,
        lifecycle=ChartLifecycle.READY,
        mount_error=None,
    ):
        self.provider_id = provider_id
        self._capabilities = frozenset(capabilities)
        self.lifecycle = lifecycle
        self.mount_error = mount_error
        self.calls = []

    def capabilities(self):
        return self._capabilities

    async def health(self, context):
        self.calls.append("health")
        return ChartHealth(self.provider_id, self.lifecycle, NOW)

    async def mount(self, request, context):
        self.calls.append(("mount", request))
        if self.mount_error:
            raise self.mount_error
        return ChartSession(
            self.provider_id,
            request.target_ref,
            request.symbol,
            request.interval,
            NOW,
            request.theme_ref,
        )

    async def set_symbol(self, symbol, context):
        self.calls.append(("symbol", symbol))

    async def set_interval(self, interval, context):
        self.calls.append(("interval", interval))

    async def set_theme(self, theme_ref, context):
        self.calls.append(("theme", theme_ref))

    async def fullscreen(self, context):
        self.calls.append("fullscreen")

    async def destroy(self, context):
        self.calls.append("destroy")


class FakeMedia:
    def __init__(
        self,
        controller_id,
        capabilities=(),
        *,
        gate=None,
    ):
        self.controller_id = controller_id
        self._capabilities = frozenset(capabilities)
        self.gate = gate
        self.executions = []
        self.closed = False

    def capabilities(self):
        return self._capabilities

    async def health(self, context):
        return MediaHealth(self.controller_id, MediaLifecycle.READY, NOW)

    async def current_state(self, context):
        return MediaState(
            self.controller_id,
            MediaLifecycle.READY,
            NOW,
            "paused",
            0.5,
        )

    async def execute(self, command, context):
        self.executions.append(command)
        if self.gate is not None:
            await self.gate.wait()
        return MediaAck(
            command.command_id,
            self.controller_id,
            command.action,
            MediaAckStatus.APPLIED,
            NOW,
            "media.applied",
            False,
        )

    async def close(self, context):
        self.closed = True


def _chart_request(**changes):
    values = {
        "target_ref": "surface:primary",
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


def test_contexto_cancela_y_agota_deadline_sin_confundir_causas():
    async def scenario():
        cancel = asyncio.Event()
        cancel.set()
        with pytest.raises(OperationCancelled):
            await await_operation(
                asyncio.sleep(0),
                OperationContext(cancel_event=cancel),
            )
        with pytest.raises(OperationDeadlineExceeded):
            await await_operation(
                asyncio.sleep(0.1),
                OperationContext.with_timeout(0.001),
            )

    _run(scenario())


def test_chart_request_no_contiene_layout_dimensiones_colores_o_viewport():
    fields = set(ChartMountRequest.__dataclass_fields__)
    assert fields == {
        "target_ref",
        "symbol",
        "interval",
        "required_capabilities",
        "theme_ref",
    }
    assert not fields & {"width", "height", "layout", "color", "viewport"}


def test_chart_selecciona_por_capacidades_y_hace_fallback_al_montar():
    async def scenario():
        first = FakeChart(
            "tradingview",
            [ChartCapability.SET_SYMBOL],
            mount_error=ChartMountFailed("provider caido"),
        )
        second = FakeChart(
            "lightweight",
            [ChartCapability.SET_SYMBOL],
        )
        router = ChartProviderRouter([first, second])
        request = _chart_request(
            required_capabilities=frozenset([ChartCapability.SET_SYMBOL])
        )
        session = await router.mount(request)
        assert session.provider_id == "lightweight"
        assert router.active_provider_id == "lightweight"
        assert ("mount", request) in first.calls

    _run(scenario())


def test_chart_no_finge_paridad_ni_prueba_provider_incompatible():
    async def scenario():
        basic = FakeChart("basic", [ChartCapability.SET_SYMBOL])
        full = FakeChart("full", [ChartCapability.FULLSCREEN])
        router = ChartProviderRouter([basic, full])
        await router.mount(
            _chart_request(
                required_capabilities=frozenset([ChartCapability.FULLSCREEN])
            )
        )
        assert basic.calls == []
        assert router.active_provider_id == "full"

    _run(scenario())


def test_chart_rechaza_hot_swap_implicito_y_mount_identico_es_idempotente():
    async def scenario():
        provider = FakeChart("chart")
        router = ChartProviderRouter([provider])
        request = _chart_request()
        first = await router.mount(request)
        assert await router.mount(request) is first
        assert len([call for call in provider.calls if isinstance(call, tuple)]) == 1
        with pytest.raises(ChartLifecycleError):
            await router.mount(replace(request, symbol="ETHUSDT"))
        assert router.hot_swap_supported is False

    _run(scenario())


def test_chart_operaciones_exigen_capacidad_y_actualizan_sesion_despues_del_ack():
    async def scenario():
        provider = FakeChart("chart", [ChartCapability.SET_SYMBOL])
        router = ChartProviderRouter([provider])
        await router.mount(_chart_request())
        await router.set_symbol("ETHUSDT")
        assert router.session.symbol == "ETHUSDT"
        with pytest.raises(ChartCapabilityError):
            await router.set_interval("4h")
        assert router.session.interval == "1h"

    _run(scenario())


def test_chart_destroy_es_idempotente_y_habilita_nuevo_mount():
    async def scenario():
        provider = FakeChart("chart")
        router = ChartProviderRouter([provider])
        await router.mount(_chart_request())
        await router.destroy()
        await router.destroy()
        await router.mount(_chart_request(symbol="ETHUSDT"))
        assert provider.calls.count("destroy") == 1

    _run(scenario())


def test_chart_reporta_seleccion_fallida_sin_adapter_compatible():
    async def scenario():
        router = ChartProviderRouter([FakeChart("chart")])
        with pytest.raises(ChartSelectionError, match="sin capacidades"):
            await router.mount(
                _chart_request(
                    required_capabilities=frozenset(
                        [ChartCapability.FULLSCREEN]
                    )
                )
            )

    _run(scenario())


def test_media_valida_argumentos_y_command_id():
    with pytest.raises(ValueError, match="command_id"):
        _command("con espacios")
    with pytest.raises(ValueError, match="volume"):
        _command(
            action=MediaAction.SET_VOLUME,
            arguments={"volume": 1.5},
        )
    valid = _command(
        action=MediaAction.SET_VOLUME,
        arguments={"volume": 0.25},
    )
    assert valid.arguments == {"volume": 0.25}


def test_media_reintento_devuelve_mismo_ack_sin_repetir_efecto():
    async def scenario():
        provider = FakeMedia("apple", [MediaCapability.PLAY])
        router = MediaControllerRouter([provider])
        command = _command()
        first = await router.execute(command)
        second = await router.execute(command)
        assert first is second
        assert provider.executions == [command]

    _run(scenario())


def test_media_reintentos_concurrentes_comparten_una_ejecucion():
    async def scenario():
        gate = asyncio.Event()
        provider = FakeMedia("apple", [MediaCapability.PLAY], gate=gate)
        router = MediaControllerRouter([provider])
        command = _command()
        first = asyncio.create_task(router.execute(command))
        await asyncio.sleep(0)
        second = asyncio.create_task(router.execute(command))
        await asyncio.sleep(0)
        assert provider.executions == [command]
        gate.set()
        assert await first == await second

    _run(scenario())


def test_media_timeout_no_cancela_orden_ambigua_y_retry_adopta_resultado():
    async def scenario():
        gate = asyncio.Event()
        provider = FakeMedia("apple", [MediaCapability.PLAY], gate=gate)
        router = MediaControllerRouter([provider])
        command = _command()
        with pytest.raises(OperationDeadlineExceeded):
            await router.execute(
                command,
                OperationContext.with_timeout(0.001),
            )
        assert provider.executions == [command]
        gate.set()
        await asyncio.sleep(0)
        result = await router.execute(command)
        assert result.status is MediaAckStatus.APPLIED
        assert provider.executions == [command]

    _run(scenario())


def test_media_detecta_command_id_reutilizado_con_otro_payload():
    async def scenario():
        provider = FakeMedia(
            "apple",
            [MediaCapability.PLAY, MediaCapability.PAUSE],
        )
        router = MediaControllerRouter([provider])
        await router.execute(_command())
        with pytest.raises(MediaCommandConflict):
            await router.execute(_command(action=MediaAction.PAUSE))

    _run(scenario())


def test_media_rechaza_ack_que_no_corresponde_al_comando():
    class BrokenMedia(FakeMedia):
        async def execute(self, command, context):
            return MediaAck(
                "otro-id",
                self.controller_id,
                command.action,
                MediaAckStatus.APPLIED,
                NOW,
                "media.applied",
                False,
            )

    async def scenario():
        router = MediaControllerRouter(
            [BrokenMedia("apple", [MediaCapability.PLAY])]
        )
        with pytest.raises(MediaAckInvalid):
            await router.execute(_command())

    _run(scenario())


def test_media_ack_unknown_no_se_cachea_y_permite_reconciliar_mismo_id():
    class UnknownThenApplied(FakeMedia):
        async def execute(self, command, context):
            self.executions.append(command)
            status = (
                MediaAckStatus.UNKNOWN
                if len(self.executions) == 1
                else MediaAckStatus.APPLIED
            )
            return MediaAck(
                command.command_id,
                self.controller_id,
                command.action,
                status,
                NOW,
                f"media.{status.value}",
                status is MediaAckStatus.UNKNOWN,
            )

    async def scenario():
        provider = UnknownThenApplied("apple", [MediaCapability.PLAY])
        router = MediaControllerRouter([provider])
        command = _command()
        first = await router.execute(command)
        second = await router.execute(command)
        third = await router.execute(command)
        assert first.status is MediaAckStatus.UNKNOWN
        assert second.status is MediaAckStatus.APPLIED
        assert third is second
        assert provider.executions == [command, command]

    _run(scenario())


def test_media_no_finge_capacidad_y_estado_tambien_es_capability():
    async def scenario():
        provider = FakeMedia("apple", [MediaCapability.PLAY])
        router = MediaControllerRouter([provider])
        with pytest.raises(MediaCapabilityError, match="current_state"):
            await router.current_state()
        with pytest.raises(MediaCapabilityError, match="pause"):
            await router.execute(_command(action=MediaAction.PAUSE))

    _run(scenario())


def test_media_impide_sustitucion_y_cierre_con_comando_en_vuelo():
    async def scenario():
        gate = asyncio.Event()
        first = FakeMedia("apple", [MediaCapability.PLAY], gate=gate)
        second = FakeMedia("spotify", [MediaCapability.PLAY])
        router = MediaControllerRouter([first, second])
        pending = asyncio.create_task(router.execute(_command()))
        await asyncio.sleep(0)
        with pytest.raises(MediaLifecycleError, match="sustituir"):
            router.activate("spotify")
        with pytest.raises(MediaLifecycleError, match="cerrar"):
            await router.close()
        gate.set()
        await pending
        router.activate("spotify")
        assert router.active_controller_id == "spotify"

    _run(scenario())


def test_media_cache_acotada_permita_reusar_id_expirado():
    async def scenario():
        provider = FakeMedia(
            "apple",
            [MediaCapability.PLAY, MediaCapability.PAUSE],
        )
        router = MediaControllerRouter([provider], max_cached_commands=1)
        await router.execute(_command("cmd-1"))
        await router.execute(_command("cmd-2"))
        await router.execute(_command("cmd-1", action=MediaAction.PAUSE))
        assert [item.action for item in provider.executions] == [
            MediaAction.PLAY,
            MediaAction.PLAY,
            MediaAction.PAUSE,
        ]

    _run(scenario())


def test_health_expone_interfaces_como_contratos_sin_adaptadores():
    module = CommandCenterModule(
        ModuleContext(
            "command_center",
            "modules/command_center",
            {},
            lambda message: None,
        )
    )
    interfaces = module.health()["interfaces"]
    assert interfaces == {
        "chart_provider": {"version": 1, "status": "contract-only"},
        "media_controller": {"version": 1, "status": "contract-only"},
    }


def test_interfaces_no_importan_ui_fastapi_bot_o_ejecutores():
    root = Path(__file__).parents[1]
    imports = []
    for relative in (
        "modules/command_center/operations.py",
        "modules/command_center/chart_provider.py",
        "modules/command_center/media_controller.py",
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
