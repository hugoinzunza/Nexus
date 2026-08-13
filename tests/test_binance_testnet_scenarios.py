import importlib.util
from pathlib import Path

import pytest

from modules.bot.testnet_evidence import DEMO_URL


def _module():
    path = Path(__file__).parents[1] / "deploy" / "binance_testnet_scenarios.py"
    spec = importlib.util.spec_from_file_location("binance_testnet_scenarios", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runner_rechaza_endpoint_productivo(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setenv("NEXUS_TESTNET", "1")
    monkeypatch.setenv("BINANCE_FAPI_BASE_URL", "https://fapi.binance.com")

    with pytest.raises(SystemExit, match="ABORTADO"):
        module.require_demo(tmp_path / "testnet")


def test_runner_rechaza_directorio_productivo(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setenv("NEXUS_TESTNET", "1")
    monkeypatch.setenv("BINANCE_FAPI_BASE_URL", DEMO_URL)

    with pytest.raises(SystemExit, match="data-dir"):
        module.require_demo(tmp_path / "data")


def test_respuesta_perdida_solo_envia_un_post_y_recupera_por_id():
    module = _module()

    class _Real:
        posts = 0

        def market_order(self, *_args, **_kwargs):
            self.posts += 1
            return {"status": "FILLED"}

        def get_order(self, _symbol, client_id):
            return {"status": "FILLED", "executed_qty": 2.0,
                    "avg_price": 100.0, "client_id": client_id}

    real = _Real()
    result = module.ordenar_resuelto(
        module.LostResponseClient(real), "ADAUSDT", "SELL", 2.0, "nx-test",
        position_side="LONG", intentos=1, log=lambda _message: None,
    )

    assert real.posts == 1
    assert result["executed_qty"] == 2.0


def test_cleanup_cancela_solo_ids_del_escenario():
    module = _module()

    class _Client:
        canceled = []

        def cancel_algo_order(self, *, client_algo_id):
            self.canceled.append(client_algo_id)

    cli = _Client()
    module.cancel_own_algos(cli, ["own-1", "own-2"])

    assert cli.canceled == ["own-1", "own-2"]


def test_observe_current_es_solo_lectura_y_acredita_stop_y_parcial(tmp_path):
    module = _module()
    data_dir = tmp_path / "testnet"
    data_dir.mkdir()
    store = module.BotStore(path=str(data_dir / "bot_trades.json"))
    store.open_trade({
        "setup_id": "demo:1", "symbol": "BTCUSDT", "pair": "BTC_USDT",
        "dir": "short", "mode": "live", "qty": 2.0, "entry_price": 100.0,
        "sl": 105.0, "ts": 1,
    })
    store.add_partial("demo:1", "TP1", 1.0, 95.0)

    class _Client:
        writes = 0

        def positions(self):
            return [{"symbol": "BTCUSDT", "side": "SHORT",
                     "position_side": "SHORT", "qty": 1.0}]

        def algo_open_orders(self, _symbol):
            return [{"algo_id": "a1", "status": "NEW", "symbol": "BTCUSDT",
                     "position_side": "SHORT", "qty": 1.0}]

    cli = _Client()
    module.observe_current(cli, data_dir)

    marker = __import__("json").loads(
        (data_dir / "live_readiness.json").read_text()
    )
    assert set(marker["scenario_evidence"]) == {
        "native_stop_confirmed", "partial_stop_resized",
    }
    assert cli.writes == 0
