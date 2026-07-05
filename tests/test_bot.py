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


def test_quality_require_disc_false_ignores_disc_ok_completamente():
    """require_disc=False debe IGNORAR disc_ok, incluso disc_ok=False (Fase 1).

    Semántica corregida 2026-07-05: el veto por EQ global contradice la evidencia
    (dealing_range 06-12 + Diario: disc_ok=False +0.460R vs True +0.094R). Con el
    flag apagado, un setup rr>=5 en 1h con disc_ok=False tiene que pasar.
    """
    ex = BotExecutor(store=None, log=lambda _msg: None, config={
        "quality_filter": True,
        "quality_min_rr": 5.0,
        "quality_poi_tfs": ["1h", "4h", "1D"],
        "quality_require_disc": False,
    })

    q_false = ex._quality({"poi_tf": "1h", "rr": 5.0, "disc_ok": False})
    q_none = ex._quality({"poi_tf": "1h", "rr": 6.0, "disc_ok": None})
    q_true = ex._quality({"poi_tf": "4h", "rr": 7.0, "disc_ok": True})

    assert q_false["grade"] == "A"       # disc_ok=False ya NO bloquea
    assert q_none["grade"] == "A"
    assert q_true["grade"] == "A+"
    assert ex._quality_allowed({"source": "indicador"}, q_false)
    assert ex._quality_allowed({"source": "indicador"}, q_none)
    assert ex._quality_allowed({"source": "indicador"}, q_true)

    # Con require_disc=True la exigencia se mantiene (no rompimos el modo estricto).
    ex_strict = BotExecutor(store=None, log=lambda _msg: None, config={
        "quality_filter": True,
        "quality_min_rr": 5.0,
        "quality_poi_tfs": ["1h", "4h", "1D"],
        "quality_require_disc": True,
    })
    q_strict = ex_strict._quality({"poi_tf": "1h", "rr": 5.0, "disc_ok": False})
    assert q_strict["grade"] == "B"
    assert not ex_strict._quality_allowed({"source": "indicador"}, q_strict)


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


# --- Perfiles de entrada + guarda de slippage (flags, apagados por defecto) -------
from modules.bot.executor import _passes_entry_profiles, _entry_slippage_ok


def test_entry_profiles_off_lets_everything_pass():
    t = {"poi_tf": "1h", "dir": "long", "rr": 2.0}
    assert _passes_entry_profiles(t, None)
    assert _passes_entry_profiles(t, [])


def test_entry_profiles_any_profile_match_allows():
    profiles = [{"poi_tfs": ["4h", "1D"], "min_rr": 5},
                {"dirs": ["short"], "min_rr": 5}]
    assert _passes_entry_profiles({"poi_tf": "4h", "dir": "long", "rr": 6}, profiles)
    assert _passes_entry_profiles({"poi_tf": "1h", "dir": "short", "rr": 7}, profiles)
    # 1h-long queda fuera aunque tenga rr alto
    assert not _passes_entry_profiles({"poi_tf": "1h", "dir": "long", "rr": 9}, profiles)
    # rr bajo queda fuera en todos los perfiles
    assert not _passes_entry_profiles({"poi_tf": "4h", "dir": "long", "rr": 3}, profiles)
    assert not _passes_entry_profiles({"poi_tf": "1h", "dir": "short", "rr": 3}, profiles)


def test_entry_profiles_missing_fields_do_not_crash():
    assert not _passes_entry_profiles({}, [{"poi_tfs": ["4h"]}])
    assert _passes_entry_profiles({}, [{}])   # perfil vacío = sin condiciones = pasa


def test_entry_slippage_guard():
    # apagada (0/None) → siempre ok
    assert _entry_slippage_ok(100.0, 105.0, "long", 0)
    assert _entry_slippage_ok(100.0, 105.0, "long", None)
    # long: precio 0.5% por ENCIMA del plan con tope 0.3% → bloquea
    assert not _entry_slippage_ok(100.0, 100.5, "long", 0.3)
    assert _entry_slippage_ok(100.0, 100.2, "long", 0.3)
    # a favor (long entra más barato) nunca bloquea
    assert _entry_slippage_ok(100.0, 99.0, "long", 0.3)
    # short: adverso es precio POR DEBAJO del plan
    assert not _entry_slippage_ok(100.0, 99.5, "short", 0.3)
    assert _entry_slippage_ok(100.0, 100.5, "short", 0.3)
    # datos faltantes → no bloquea (no romper la apertura por metadata incompleta)
    assert _entry_slippage_ok(None, 100.0, "long", 0.3)
    assert _entry_slippage_ok(100.0, None, "long", 0.3)


def test_summary_splits_pnl_by_mode(tmp_path):
    store = BotStore(path=str(tmp_path / "bot_trades.json"))
    a = _trade_rec(); a["setup_id"] = "s:dry"; a["mode"] = "dry"
    b = _trade_rec(); b["setup_id"] = "s:live"; b["mode"] = "live"
    store.open_trade(a); store.open_trade(b)
    store.close_trade("s:dry", exit_price=110.0)    # dry gana
    store.close_trade("s:live", exit_price=90.0)    # live pierde
    s = store.summary()
    assert "by_mode" in s
    assert s["by_mode"]["dry"]["pnl_usd"] > 0
    assert s["by_mode"]["live"]["pnl_usd"] < 0
    # el total sigue existiendo para la UI vieja
    assert "pnl_usd" in s
