import asyncio
import ast
from pathlib import Path

import pytest

from core.module_base import ModuleContext
from modules.command_center import TradingViewWidgetAdapter as PublicAdapter
from modules.command_center.chart_provider import (
    ChartCapabilityError,
    ChartLifecycle,
    ChartMountFailed,
    ChartMountRequest,
)
from modules.command_center.conformance import verify_chart_provider
from modules.command_center.module import CommandCenterModule
from modules.command_center.operations import OperationContext
from modules.command_center.tradingview_adapter import (
    DEFAULT_INTERVAL_MAP,
    DEFAULT_SYMBOL_MAP,
    TRADINGVIEW_WIDGET_SCRIPT,
    TradingViewMountResult,
    TradingViewPortHealth,
    TradingViewPortLifecycle,
    TradingViewWidgetAdapter,
)

NOW = 1_785_430_000_000


def _run(coro):
    return asyncio.run(coro)


class RecordingPort:
    def __init__(self):
        self.lifecycle = TradingViewPortLifecycle.DETACHED
        self.specs = []
        self.destroy_calls = 0
        self.error = None

    async def health(self, context):
        return TradingViewPortHealth(self.lifecycle, NOW)

    async def mount(self, spec, context):
        self.specs.append(spec)
        if self.error:
            raise self.error
        self.lifecycle = TradingViewPortLifecycle.READY
        return TradingViewMountResult(NOW)

    async def destroy(self, context):
        self.destroy_calls += 1
        self.lifecycle = TradingViewPortLifecycle.DESTROYED


def _request(**changes):
    values = {
        "target_ref": "spike:chart",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "theme_ref": "dark",
    }
    values.update(changes)
    return ChartMountRequest(**values)


def test_adapter_declara_solo_capacidades_reales_del_widget_publico():
    adapter = TradingViewWidgetAdapter(RecordingPort())
    assert PublicAdapter is TradingViewWidgetAdapter
    assert adapter.capabilities() == frozenset()
    assert adapter.stats()["runtime_mutation"] is False
    assert adapter.stats()["advanced_charts_library"] is False


def test_adapter_mapea_simbolo_intervalo_y_script_oficial():
    async def scenario():
        port = RecordingPort()
        adapter = TradingViewWidgetAdapter(port)
        session = await adapter.mount(_request(), OperationContext())
        assert session.provider_id == "tradingview-widget"
        assert session.mounted_at_ms == NOW
        spec = port.specs[0]
        assert spec.symbol == "BINANCE:BTCUSDT.P"
        assert spec.interval == "60"
        assert spec.theme == "dark"
        assert spec.script_url == TRADINGVIEW_WIDGET_SCRIPT

    _run(scenario())


def test_mapeo_estatico_cubre_pares_y_temporalidades_nexux():
    assert set(DEFAULT_SYMBOL_MAP) == {
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "ADAUSDT",
        "XRPUSDT",
    }
    assert DEFAULT_INTERVAL_MAP == {
        "15m": "15",
        "1h": "60",
        "4h": "240",
        "1D": "D",
        "1W": "W",
    }


def test_mount_es_idempotente_y_cambio_exige_destroy():
    async def scenario():
        port = RecordingPort()
        adapter = TradingViewWidgetAdapter(port)
        first = await adapter.mount(_request(), OperationContext())
        assert await adapter.mount(_request(), OperationContext()) is first
        assert len(port.specs) == 1
        with pytest.raises(Exception, match="destruya"):
            await adapter.mount(
                _request(symbol="ETHUSDT"),
                OperationContext(),
            )
        await adapter.destroy(OperationContext())
        assert port.destroy_calls == 1

    _run(scenario())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"symbol": "DOGEUSDT"}, "simbolo"),
        ({"interval": "5m"}, "intervalo"),
        ({"theme_ref": "nexux-purple"}, "theme_ref"),
    ],
)
def test_configuracion_no_mapeada_falla_cerrado(changes, message):
    adapter = TradingViewWidgetAdapter(RecordingPort())
    with pytest.raises(ChartMountFailed, match=message):
        _run(adapter.mount(_request(**changes), OperationContext()))


def test_capacidades_mutables_no_se_simulan():
    async def scenario():
        adapter = TradingViewWidgetAdapter(RecordingPort())
        with pytest.raises(ChartCapabilityError, match="reinicializar"):
            await adapter.set_symbol("ETHUSDT", OperationContext())
        with pytest.raises(ChartCapabilityError, match="reinicializar"):
            await adapter.set_interval("4h", OperationContext())
        with pytest.raises(ChartCapabilityError, match="reinicializar"):
            await adapter.set_theme("light", OperationContext())
        with pytest.raises(ChartCapabilityError, match="no es capacidad"):
            await adapter.fullscreen(OperationContext())

    _run(scenario())


def test_health_traduce_degradacion_del_puerto():
    async def scenario():
        port = RecordingPort()
        port.lifecycle = TradingViewPortLifecycle.DEGRADED
        adapter = TradingViewWidgetAdapter(port)
        health = await adapter.health(OperationContext())
        assert health.lifecycle is ChartLifecycle.DEGRADED

    _run(scenario())


def test_observabilidad_registra_fallo_sin_inventar_sesion():
    async def scenario():
        port = RecordingPort()
        port.error = RuntimeError("red caida")
        adapter = TradingViewWidgetAdapter(port)
        with pytest.raises(RuntimeError, match="red caida"):
            await adapter.mount(_request(), OperationContext())
        stats = adapter.stats()
        assert stats["mount_attempts"] == 1
        assert stats["mount_failures"] == 1
        assert stats["last_error_code"] == "RuntimeError"

    _run(scenario())


def test_adapter_supera_harness_chart_sin_capacidades_fingidas():
    port = RecordingPort()
    report = _run(
        verify_chart_provider(
            TradingViewWidgetAdapter(port),
            request=_request(),
        )
    )
    assert report.operations == (
        "health",
        "mount",
        "mount-idempotent",
        "destroy",
    )
    assert port.destroy_calls == 1


def test_spike_estatico_usa_script_constante_atribucion_y_sin_advanced_api():
    root = Path(__file__).parents[1]
    script = (
        root
        / "modules"
        / "command_center"
        / "public"
        / "tradingview-spike.js"
    ).read_text(encoding="utf-8")
    page = (
        root
        / "modules"
        / "command_center"
        / "public"
        / "tradingview-spike.html"
    ).read_text(encoding="utf-8")
    assert TRADINGVIEW_WIDGET_SCRIPT in script
    assert "Chart by TradingView" in script
    assert "runtimeMutation: false" in script
    assert "activeChart(" not in script
    assert "changeTheme(" not in script
    assert ".setSymbol(" not in script
    assert 'new URLSearchParams(location.search).get("autorun")' in page


def test_pagina_spike_queda_detras_del_gate_del_modulo():
    module = CommandCenterModule(
        ModuleContext(
            "command_center",
            "modules/command_center",
            {},
            lambda _message: None,
        )
    )
    assert module.public_dir().endswith("modules/command_center/public")


def test_adapter_python_no_importa_ui_browser_bot_o_dominio():
    root = Path(__file__).parents[1]
    path = (
        root
        / "modules"
        / "command_center"
        / "tradingview_adapter.py"
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
        "selenium",
        "playwright",
        "modules.bot",
        "modules.trading",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imports
        for prefix in forbidden
    )
