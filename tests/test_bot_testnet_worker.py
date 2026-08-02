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


def test_snapshot_testnet_enriquece_posicion_con_plan_stop_nativo_y_parciales(tmp_path):
    data_dir = tmp_path / "testnet"
    data_dir.mkdir()
    store = BotStore(path=str(data_dir / "bot_trades.json"))
    opened = store.open_trade({
        "setup_id": "ada:demo:1", "symbol": "ADAUSDT", "pair": "ADA_USDT",
        "dir": "long", "mode": "live", "qty": 1000.0, "entry_price": 0.20,
        "setup_entry": 0.20, "sl": 0.19, "tp": 0.25, "leverage": 5,
        "risk_usd_est": 10.0, "ts": 200,
    })
    store.add_partial(opened["setup_id"], "TP1", 500.0, 0.21, realized_r=0.5)

    class _Client:
        def balance_usdt(self):
            return {"balance": 5000.0, "available": 4900.0, "unrealized_pnl": 7.0}

        def positions(self):
            return [{
                "symbol": "ADAUSDT", "side": "LONG", "position_side": "LONG",
                "qty": 500.0, "entry": 0.20, "mark": 0.214, "notional": 107.0,
                "margin": 21.4, "leverage": 5, "unrealized_pnl": 7.0,
                "liq_price": 0.12,
            }]

        def algo_open_orders(self, symbol):
            assert symbol == "ADAUSDT"
            return [
                {
                    "symbol": symbol, "side": "SELL", "position_side": "LONG",
                    "type": "STOP_MARKET", "trigger_price": 0.20,
                    "status": "NEW", "qty": 500.0,
                },
                {
                    "symbol": symbol, "side": "SELL", "position_side": "LONG",
                    "type": "TAKE_PROFIT_MARKET", "trigger_price": 0.24,
                    "status": "NEW", "qty": 500.0,
                },
            ]

    executor = SimpleNamespace(
        store=store, live=True, active=True, kill_file=str(data_dir / "kill"),
        data_dir=str(data_dir), client=lambda: _Client(),
    )

    snapshot = BotSync(executor, lambda _message: None, testnet_executor=executor)._testnet_snapshot()
    position = snapshot["positions"][0]

    assert position["tracking_status"] == "tracked"
    assert position["sl"] == 0.20
    assert position["sl_source"] == "binance_native"
    assert position["tp1"] == 0.21
    assert position["tp2"] == 0.22
    assert position["tp"] == 0.25
    assert position["partials"][0]["leg"] == "TP1"
    assert position["unrealized_pnl"] == 7.0


def test_snapshot_testnet_no_mezcla_lados_hedge_del_mismo_simbolo(tmp_path):
    data_dir = tmp_path / "testnet"
    data_dir.mkdir()
    store = BotStore(path=str(data_dir / "bot_trades.json"))
    store.open_trade({
        "setup_id": "btc:long:1", "symbol": "BTCUSDT", "pair": "BTC_USDT",
        "dir": "long", "mode": "live", "qty": 0.01, "entry_price": 60000,
        "setup_entry": 60000, "sl": 59000, "tp": 65000, "ts": 200,
    })

    class _Client:
        def balance_usdt(self):
            return {"balance": 5000.0, "available": 4900.0, "unrealized_pnl": 2.0}

        def positions(self):
            return [{
                "symbol": "BTCUSDT", "side": "SHORT", "position_side": "SHORT",
                "qty": 0.01, "entry": 61000, "mark": 60800, "notional": 608,
                "margin": 60.8, "leverage": 10, "unrealized_pnl": 2.0,
                "liq_price": 67000,
            }]

        def algo_open_orders(self, _symbol):
            return []

    executor = SimpleNamespace(
        store=store, live=True, active=True, kill_file=str(data_dir / "kill"),
        data_dir=str(data_dir), client=lambda: _Client(),
    )

    position = BotSync(
        executor, lambda _message: None, testnet_executor=executor
    )._testnet_snapshot()["positions"][0]

    assert position["tracking_status"] == "exchange_only"
    assert "sl" not in position
    assert "tp" not in position


def test_snapshot_testnet_publica_progreso_live_sin_autorizarlo(tmp_path):
    data_dir = tmp_path / "testnet"
    data_dir.mkdir()
    marker = {
        "phase": "testnet_live_readiness_v1",
        "started_at": 100,
        "deployed_commit": "abc1234",
        "required_new_closed": 5,
    }
    (data_dir / "live_readiness.json").write_text(__import__("json").dumps(marker))
    store = BotStore(path=str(data_dir / "bot_trades.json"))
    store.open_trade({
        "setup_id": "new:1", "symbol": "BTCUSDT", "pair": "BTC_USDT",
        "dir": "long", "mode": "live", "qty": 1.0, "entry_price": 100.0,
        "ts": 101,
    })
    ex = SimpleNamespace(store=store, data_dir=str(data_dir))

    readiness = BotSync._testnet_readiness(ex)

    assert readiness["closed_candidates"] == 0
    assert readiness["open_candidates"] == 1
    assert readiness["required"] == 5
    assert readiness["automatic_live"] is False


def test_panel_identifica_testnet_como_fondos_virtuales():
    root = Path(__file__).parents[1]
    html = (root / "modules/bot/public/index.html").read_text()
    js = (root / "modules/bot/public/app.js").read_text()

    assert "Binance Demo, fondos virtuales" in html
    assert "Órdenes reales contra saldo virtual" in js
    assert "function testnet(data)" in js
    assert "Validación live" in js
    assert "no activa live automáticamente" in js
    assert "Operaciones abiertas" in js
    assert "uPnL abierto" in js
    assert "SL confirmado en Binance" in js
    assert "TP final" in js
