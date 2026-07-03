from modules.bot.bot_store import BotStore
from modules.bot.executor import BotExecutor
from modules.bot.sync import BotSync


def _trade_rec():
    return {
        "setup_id": "setup:1",
        "symbol": "BTCUSDT",
        "pair": "BTC_USDT",
        "dir": "long",
        "mode": "dry",
        "qty": 1.0,
        "entry_price": 100.0,
    }


def test_bot_store_partials_are_idempotent(tmp_path):
    store = BotStore(path=str(tmp_path / "bot_trades.json"))
    store.open_trade(_trade_rec())

    assert store.add_partial("setup:1", "TP1", 0.5, 110.0, fee_usd=1.0)
    assert not store.add_partial("setup:1", "TP1", 0.5, 111.0, fee_usd=1.0)

    trade = store.all()[0]
    assert trade["qty_open"] == 0.5
    assert len(trade["partials"]) == 1
    assert trade["fees_usd"] == 1.0


def test_bot_store_partial_qty_is_capped_to_open_remainder(tmp_path):
    store = BotStore(path=str(tmp_path / "bot_trades.json"))
    store.open_trade(_trade_rec())

    assert store.add_partial("setup:1", "TP1", 2.0, 110.0, fee_usd=1.0)

    trade = store.all()[0]
    assert trade["qty_open"] == 0.0
    assert trade["partials"][0]["qty"] == 1.0


def test_bot_store_keeps_quality_metadata(tmp_path):
    store = BotStore(path=str(tmp_path / "bot_trades.json"))
    rec = {
        **_trade_rec(),
        "quality": "A",
        "quality_reason": "1h + RR 7 + disciplina OK",
        "poi_tf": "1h",
        "rr": 7.0,
        "disc_ok": True,
        "sl_pct": 0.7,
        "risk_usd": 9.0,
        "risk_usd_est": 8.75,
        "risk_pct_account": 1.75,
        "margin_used": 250.0,
        "fee_est_roundtrip": 1.25,
        "notional": 1250.0,
    }

    trade = store.open_trade(rec)

    assert trade["quality"] == "A"
    assert trade["poi_tf"] == "1h"
    assert trade["rr"] == 7.0
    assert trade["disc_ok"] is True
    assert trade["sl_pct"] == 0.7
    assert trade["risk_usd_est"] == 8.75
    assert trade["risk_pct_account"] == 1.75
    assert trade["margin_used"] == 250.0
    assert trade["fee_est_roundtrip"] == 1.25


def test_snapshot_enriches_positions_with_book_risk_metadata(tmp_path):
    store = BotStore(path=str(tmp_path / "bot_trades.json"))
    store.open_trade({
        **_trade_rec(),
        "setup_entry": 100.0,
        "sl": 99.0,
        "tp": 103.0,
        "quality": "A",
        "quality_reason": "1h + RR 5 + disciplina OK",
        "sl_pct": 1.0,
        "risk_usd_est": 12.5,
        "risk_pct_account": 2.5,
        "margin_used": 250.0,
        "fee_est_roundtrip": 1.25,
    })

    class FakeClient:
        def balance_usdt(self):
            return {"balance": 1000.0, "available": 750.0, "unrealized_pnl": 10.0}

        def positions(self):
            return [{
                "symbol": "BTCUSDT",
                "side": "LONG",
                "position_side": "LONG",
                "qty": 1.0,
                "entry": 100.0,
            }]

        def open_orders(self):
            return []

    class FakeExecutor:
        live = True
        active = True
        cfg = {"pairs": ["BTCUSDT"]}

        def __init__(self):
            self.store = store
            self.cli = FakeClient()

        def client(self):
            return self.cli

    snap = BotSync(FakeExecutor(), lambda _msg: None).snapshot()
    pos = snap["positions"][0]

    assert pos["risk_usd_est"] == 12.5
    assert pos["risk_pct_account"] == 2.5
    assert pos["margin_used"] == 250.0
    assert pos["fee_est_roundtrip"] == 1.25
    assert pos["quality"] == "A"
    assert pos["sl"] == 99.0
    assert pos["tp1"] == 101.0
    assert pos["tp2"] == 102.0


def test_bot_quality_filter_allows_a_and_blocks_b():
    ex = BotExecutor(store=None, log=lambda _msg: None, config={
        "quality_filter": True,
        "quality_min_rr": 5.0,
        "quality_poi_tfs": ["1h", "4h", "1D"],
        "quality_require_disc": True,
    })

    a = ex._quality({"poi_tf": "1h", "rr": 5.0, "disc_ok": True})
    ap = ex._quality({"poi_tf": "4h", "rr": 7.0, "disc_ok": True})
    b = ex._quality({"poi_tf": "1h", "rr": 4.9, "disc_ok": True})

    assert a["grade"] == "A"
    assert ap["grade"] == "A+"
    assert b["grade"] == "B"
    assert ex._quality_allowed({"source": "indicador"}, a)
    assert ex._quality_allowed({"source": "indicador"}, ap)
    assert not ex._quality_allowed({"source": "indicador"}, b)


def test_bot_quality_filter_does_not_block_manual_entries():
    ex = BotExecutor(store=None, log=lambda _msg: None, config={"quality_filter": True})
    b = ex._quality({"source": "profe", "poi_tf": "manual", "rr": 1.5, "disc_ok": None})

    assert b["grade"] == "B"
    assert ex._quality_allowed({"source": "profe"}, b)


def test_reconcile_does_not_close_orphans_by_default(monkeypatch, tmp_path):
    store = BotStore(path=str(tmp_path / "bot_trades.json"))
    store.open_trade(_trade_rec())

    class FakeClient:
        def __init__(self):
            self.closed = []

        def positions(self):
            return [{
                "symbol": "BTCUSDT",
                "side": "LONG",
                "position_side": "LONG",
                "qty": 1.0,
            }]

        def round_qty(self, symbol, qty):
            return qty

        def market_order(self, symbol, side, qty, **kwargs):
            self.closed.append((symbol, side, qty, kwargs))
            return {}

        def mark_price(self, symbol):
            return 99.0

    class FakeExecutor:
        live = True
        hedge = True
        cfg = {"pairs": ["BTCUSDT"]}

        def __init__(self):
            self.store = store
            self.cli = FakeClient()

        def client(self):
            return self.cli

    monkeypatch.setattr("modules.trading.setups_store.load_all", lambda: [{
        "status": "pendiente",
        "pair": "BTC_USDT",
        "dir": "long",
    }])

    ex = FakeExecutor()
    BotSync(ex, lambda _msg: None).reconcile()

    assert ex.cli.closed == []
    assert store.all()[0]["status"] == "abierta"


def test_reconcile_can_auto_close_orphans_when_explicitly_enabled(monkeypatch, tmp_path):
    store = BotStore(path=str(tmp_path / "bot_trades.json"))
    store.open_trade(_trade_rec())

    class FakeClient:
        def __init__(self):
            self.closed = []

        def positions(self):
            return [{
                "symbol": "BTCUSDT",
                "side": "LONG",
                "position_side": "LONG",
                "qty": 1.0,
            }]

        def round_qty(self, symbol, qty):
            return qty

        def market_order(self, symbol, side, qty, **kwargs):
            self.closed.append((symbol, side, qty, kwargs))
            return {}

        def mark_price(self, symbol):
            return 99.0

    class FakeExecutor:
        live = True
        hedge = True
        cfg = {"pairs": ["BTCUSDT"], "auto_close_orphans": True}

        def __init__(self):
            self.store = store
            self.cli = FakeClient()

        def client(self):
            return self.cli

    monkeypatch.setattr("modules.trading.setups_store.load_all", lambda: [{
        "status": "pendiente",
        "pair": "BTC_USDT",
        "dir": "long",
    }])

    ex = FakeExecutor()
    BotSync(ex, lambda _msg: None).reconcile()

    assert len(ex.cli.closed) == 1
    symbol, side, qty, kwargs = ex.cli.closed[0]
    assert (symbol, side, qty) == ("BTCUSDT", "SELL", 1.0)
    assert kwargs["reduce_only"] is True
    assert kwargs["position_side"] == "LONG"
    assert kwargs["client_id"].startswith("nxrec")
    assert store.all()[0]["status"] == "cerrada"
