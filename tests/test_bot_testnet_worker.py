from pathlib import Path
from types import SimpleNamespace

from modules.bot.bot_store import BotStore
from modules.bot.executor import BotExecutor
from modules.bot.sync import BotSync
from modules.trading import module as trading_module


class _FakeClient:
    def position_mode(self):
        return True


def _bare_trading(logs):
    module = object.__new__(trading_module.TradingModule)
    module.context = SimpleNamespace(log=logs.append)
    return module


def test_testnet_rechaza_env_que_no_apunta_a_demo(monkeypatch, tmp_path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / "testnet.env").write_text(
        "NEXUS_TESTNET=1\n"
        "BINANCE_FAPI_BASE_URL=https://fapi.binance.com\n"
        "BINANCE_TRADE_API_KEY=x\n"
        "BINANCE_TRADE_API_SECRET=y\n"
    )
    monkeypatch.setenv("NEXUS_TESTNET_WORKER", "1")
    monkeypatch.setattr(trading_module, "_ROOT_REPO", str(tmp_path))
    logs = []

    executor = _bare_trading(logs)._make_testnet_executor()

    assert executor is None
    assert any("INERTE por seguridad" in line for line in logs)


def test_testnet_tiene_cliente_store_y_kill_aislados(monkeypatch, tmp_path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / "testnet.env").write_text(
        "NEXUS_TESTNET=1\n"
        "BINANCE_FAPI_BASE_URL=https://demo-fapi.binance.com\n"
        "BINANCE_TRADE_API_KEY=x\n"
        "BINANCE_TRADE_API_SECRET=y\n"
    )
    monkeypatch.setenv("NEXUS_TESTNET_WORKER", "1")
    monkeypatch.setattr(trading_module, "_ROOT_REPO", str(tmp_path))
    monkeypatch.setattr(trading_module, "_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        "modules.trading.binance_account.BinanceFutures",
        lambda **_kwargs: _FakeClient(),
    )
    production_kill = tmp_path / "data" / "bot_kill"
    production_kill.parent.mkdir()
    production_kill.touch()

    executor = _bare_trading([])._make_testnet_executor()

    assert executor is not None
    assert executor.live is True
    assert executor.client() is not None
    assert executor.store.path == str(tmp_path / "data/testnet/bot_trades.json")
    assert executor.kill_file == str(tmp_path / "data/testnet/bot_kill")
    assert not Path(executor.kill_file).exists()


def test_dispatch_envia_una_vez_a_cada_ejecutor():
    calls = []

    class _Executor:
        def __init__(self, name):
            self.name = name

        def on_transitions(self, label, transitions, price):
            calls.append((self.name, label, transitions, price))

    module = _bare_trading([])
    module._bot_executor = _Executor("production")
    module._testnet_executor = _Executor("testnet")
    transitions = [{"type": "activated", "pair": "ADA_USDT"}]

    module._dispatch_bot_transitions("ADA", transitions, 0.16)

    assert [call[0] for call in calls] == ["production", "testnet"]
    assert all(call[2] is transitions for call in calls)


def test_instancia_inerte_no_crea_sync_que_sobrescriba_al_vps():
    module = _bare_trading([])
    module._bot_executor = SimpleNamespace(active=False)

    assert module._make_bot_sync() is None


def test_comando_testnet_toca_solo_su_kill(monkeypatch, tmp_path):
    production_kill = tmp_path / "bot_kill"
    testnet_dir = tmp_path / "testnet"
    testnet_kill = testnet_dir / "bot_kill"
    testnet_dir.mkdir()
    production_kill.touch()
    executor = BotExecutor(
        BotStore(path=str(testnet_dir / "bot_trades.json")),
        lambda _message: None,
        config={"enabled": True, "live": True},
        client=_FakeClient(),
        data_dir=str(testnet_dir),
        kill_file=str(testnet_kill),
    )
    sync = BotSync(executor, lambda _message: None)

    sync.apply_command({"action": "kill"})
    assert production_kill.exists()
    assert testnet_kill.exists()

    sync.apply_command({"action": "resume"})
    assert production_kill.exists()
    assert not testnet_kill.exists()


def test_snapshot_publica_testnet_separado(monkeypatch, tmp_path):
    class _Client:
        def balance_usdt(self):
            return {"balance": 4999.0, "available": 4900.0, "unrealized_pnl": 1.5}

        def positions(self):
            return []

        def open_orders(self):
            return []

    def _executor(path, live):
        ex = SimpleNamespace(
            store=BotStore(path=str(path)),
            live=live,
            active=True,
            kill_file=str(path.parent / "kill"),
            data_dir=str(path.parent),
            cfg={"pairs": []},
            client=lambda: _Client(),
        )
        return ex

    production = _executor(tmp_path / "prod/trades.json", False)
    testnet = _executor(tmp_path / "testnet/trades.json", True)
    monkeypatch.setattr(BotSync, "_watching", lambda _self: [])

    snapshot = BotSync(
        production, lambda _message: None, testnet_executor=testnet
    ).snapshot()

    assert snapshot["live"] is False
    assert snapshot["testnet"]["live_virtual"] is True
    assert snapshot["testnet"]["account"]["balance"] == 4999.0
    assert snapshot["testnet"]["trades"] == []


def test_panel_identifica_testnet_como_fondos_virtuales():
    root = Path(__file__).parents[1]
    html = (root / "modules/bot/public/index.html").read_text()
    js = (root / "modules/bot/public/app.js").read_text()

    assert "Binance Demo, fondos virtuales" in html
    assert "Órdenes reales contra saldo virtual" in js
    assert "function testnet(data)" in js
