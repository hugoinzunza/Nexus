import importlib.util
from pathlib import Path

import pytest

from modules.trading.binance_account import BinanceFutures, FAPI


def _client(monkeypatch, base_url=None):
    monkeypatch.setenv("BINANCE_TRADE_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_TRADE_API_SECRET", "test-secret")
    return BinanceFutures(base_url=base_url)


def test_binance_usa_produccion_por_defecto(monkeypatch):
    monkeypatch.delenv("BINANCE_FAPI_BASE_URL", raising=False)

    assert _client(monkeypatch).base_url == FAPI


def test_binance_permite_endpoint_demo_por_entorno(monkeypatch):
    monkeypatch.setenv("BINANCE_FAPI_BASE_URL", "https://demo-fapi.binance.com/")

    assert _client(monkeypatch).base_url == "https://demo-fapi.binance.com"


def test_base_url_explicita_gana_al_entorno(monkeypatch):
    monkeypatch.setenv("BINANCE_FAPI_BASE_URL", "https://demo-fapi.binance.com")

    assert _client(monkeypatch, "https://example.invalid/").base_url == (
        "https://example.invalid"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(False, False), (True, True), ("false", False), ("true", True), (None, False)],
)
def test_normaliza_close_position_sin_truthiness_de_strings(raw, expected):
    normalized = BinanceFutures._norm_algo({"closePosition": raw})

    assert normalized["close_position"] is expected


def test_smoke_test_rechaza_cualquier_endpoint_que_no_sea_demo(monkeypatch):
    path = Path(__file__).parents[1] / "deploy" / "binance_testnet_smoke.py"
    spec = importlib.util.spec_from_file_location("binance_testnet_smoke", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    monkeypatch.setenv("NEXUS_TESTNET", "1")
    monkeypatch.setenv("BINANCE_FAPI_BASE_URL", FAPI)

    with pytest.raises(SystemExit, match="ABORTADO"):
        module._require_demo()
