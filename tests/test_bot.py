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
        "phase_id": "phase1_v2_2026-07-18",
        "entry_model": "midpoint_touch_v2",
        "activation_price": 100.02,
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
    assert trade["phase_id"] == "phase1_v2_2026-07-18"
    assert trade["entry_model"] == "midpoint_touch_v2"
    assert trade["activation_price"] == 100.02
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


def test_fundamental_guard_bloquea_solo_apertura(monkeypatch):
    from modules.trading import news

    class EmptyStore:
        @staticmethod
        def has_trade(_setup_id):
            return False

    logs = []
    ex = BotExecutor(store=EmptyStore(), log=logs.append, config={
        "enabled": True,
        "live": False,
        "pairs": ["BTCUSDT"],
        "entry_profiles": None,
        "quality_filter": False,
        "fundamental_guard_enabled": True,
    }, client=object())
    monkeypatch.setattr(news, "danger_window", lambda: {
        "title": "FOMC Press Conference",
        "active_until": 1_800_000_000,
    })

    # Se detiene antes de consultar el store o dimensionar/enviar una orden.
    ex._open({
        "key": "btc:fomc",
        "pair": "BTC_USDT",
        "dir": "long",
        "entry": 100.0,
        "sl": 99.0,
    }, 100.0)

    assert any("ALERTA FUNDAMENTAL" in line for line in logs)
    assert any("no abre BTCUSDT" in line for line in logs)


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


# --- órdenes ambiguas -------------------------------------------------------
#
# El libro real de junio-julio cerró en -129.03 USD con 27 trades live. El test
# pareado contra el Diario (mismo setup como control) dio -0.5545R por setup,
# IC95 [-0.961,-0.148]. Parte de esa brecha es esto: una orden que falla al VOLVER
# se ejecutó igual, y reintentarla con el mismo client_id rebota como "duplicate",
# que es indistinguible de un fallo real si uno solo mira el error.

class _CliFalso:
    """Cliente Binance mínimo con fallos programables."""

    def __init__(self, fallos=0, orden_real=None, get_order_rompe=False):
        self.fallos = fallos                # cuántos POST fallan antes de andar
        self.orden_real = orden_real        # qué contesta get_order tras el fallo
        self.get_order_rompe = get_order_rompe
        self.enviadas = 0
        self.consultas = 0

    def market_order(self, symbol, side, qty, client_id=None, reduce_only=False,
                     position_side=None):
        self.enviadas += 1
        if self.fallos > 0:
            self.fallos -= 1
            raise RuntimeError("HTTP 400: {'code':-4164,'msg':'duplicate client order id'}")
        return {"status": "FILLED", "executedQty": qty, "avgPrice": 100.0}

    def get_order(self, symbol, client_id):
        self.consultas += 1
        if self.get_order_rompe:
            raise RuntimeError("sin respuesta de Binance")
        return self.orden_real


def _ex():
    return BotExecutor(store=None, log=lambda _m: None, config={})


def test_orden_que_fallo_al_volver_se_reconoce_como_ejecutada(monkeypatch):
    """El POST falla pero Binance ya la tenía FILLED → NO es un fallo."""
    monkeypatch.setattr("time.sleep", lambda _s: None)
    cli = _CliFalso(fallos=3, orden_real={
        "status": "FILLED", "executed_qty": 2.0, "avg_price": 101.5,
        "orig_qty": 2.0, "side": "SELL", "position_side": "LONG", "client_id": "x",
    })
    resp = _ex()._ordenar(cli, "BTCUSDT", "SELL", 2.0, "x")
    assert resp is not None, "un cierre ya ejecutado no puede leerse como fallo"
    assert resp["executed_qty"] == 2.0
    assert resp["avg_price"] == 101.5
    assert cli.enviadas == 1, "no debe reintentar algo que ya se ejecutó"


def test_orden_que_nunca_llego_se_reintenta_con_el_mismo_id(monkeypatch):
    """get_order devuelve None (-2013) → el id sigue libre, se puede reintentar."""
    monkeypatch.setattr("time.sleep", lambda _s: None)
    cli = _CliFalso(fallos=2, orden_real=None)
    resp = _ex()._ordenar(cli, "BTCUSDT", "BUY", 1.0, "y")
    assert resp is not None and resp["executed_qty"] == 1.0
    assert cli.enviadas == 3, "debe reintentar mientras Binance diga que no la tiene"


def test_orden_indeterminable_no_permite_asumir_nada(monkeypatch):
    """Si no se puede preguntar, se levanta: NADIE debe tocar el store a ciegas."""
    monkeypatch.setattr("time.sleep", lambda _s: None)
    from modules.bot.executor import BinanceOrdenAmbigua
    cli = _CliFalso(fallos=99, get_order_rompe=True)
    try:
        _ex()._ordenar(cli, "BTCUSDT", "SELL", 1.0, "z")
    except BinanceOrdenAmbigua:
        pass
    else:
        raise AssertionError("un estado desconocido no puede devolver un resultado")


def test_orden_existente_sin_ejecutar_no_se_reintenta(monkeypatch):
    """CANCELED/EXPIRED: el id está quemado, reintentarlo solo daría 'duplicate'."""
    monkeypatch.setattr("time.sleep", lambda _s: None)
    cli = _CliFalso(fallos=99, orden_real={
        "status": "CANCELED", "executed_qty": 0.0, "avg_price": 0.0,
        "orig_qty": 1.0, "side": "BUY", "position_side": None, "client_id": "w",
    })
    assert _ex()._ordenar(cli, "BTCUSDT", "BUY", 1.0, "w") is None
    assert cli.enviadas == 1


def test_fill_parcial_devuelve_la_cantidad_real(monkeypatch):
    """Registrar la qty pedida en vez de la ejecutada deja el -1R apuntando mal."""
    monkeypatch.setattr("time.sleep", lambda _s: None)
    cli = _CliFalso(fallos=1, orden_real={
        "status": "PARTIALLY_FILLED", "executed_qty": 0.4, "avg_price": 99.0,
        "orig_qty": 1.0, "side": "BUY", "position_side": None, "client_id": "p",
    })
    resp = _ex()._ordenar(cli, "BTCUSDT", "BUY", 1.0, "p")
    assert resp["executed_qty"] == 0.4


# --- presupuesto de margen --------------------------------------------------

class _StoreFalso:
    def __init__(self, abiertas): self._a = abiertas
    def all(self): return self._a


def test_las_posiciones_en_trailing_ocupan_margen_aunque_no_ocupen_cupo():
    """`max_positions` cuenta solo posiciones EN RIESGO, y eso es correcto para el
    riesgo: tras TP1 el SL está en break-even. Pero el margen sigue inmovilizado.
    Tratar "riesgo ~0" como "margen ~0" dejó entrar 4 posiciones simultáneas pidiendo
    1.294,85 USDT sobre una cuenta de 897,61. En dry no se ve: no hay exchange que diga
    que no.
    """
    ex = BotExecutor(store=None, log=lambda _m: None,
                     config={"base_equity": 900.0, "base_equity_auto": False,
                             "max_margin_pct": 0.80, "max_positions": 2})
    # dos en trailing (con parcial tomado) ocupando 700 de margen
    trailing = [{"status": "abierta", "margin_used": 350.0, "partials": [{"leg": "TP1"}]},
                {"status": "abierta", "margin_used": 350.0, "partials": [{"leg": "TP1"}]}]
    # no ocupan cupo de riesgo...
    assert len([x for x in trailing if not x.get("partials")]) == 0
    # ...pero sí de margen: 700 ya está sobre el tope de 720 para cualquier orden nueva
    ocupado = sum(x["margin_used"] for x in trailing)
    tope = ex._equity_base() * 0.80
    assert ocupado == 700.0 and tope == 720.0
    assert ocupado + 100.0 > tope, "una orden nueva de 100 de margen ya no debe caber"


def test_equity_base_no_dimensiona_contra_cero_si_falla_la_lectura():
    """Un saldo 0 casi siempre es una lectura fallida, no una cuenta vacía.
    Dimensionar contra 0 sería peor que usar el último valor conocido."""
    ex = BotExecutor(store=None, log=lambda _m: None,
                     config={"base_equity": 897.61, "base_equity_auto": True})
    ex.client = lambda: None          # sin cliente → la lectura falla
    assert ex._equity_base() == 897.61


def test_equity_base_usa_el_saldo_real_del_exchange():
    """Fuente única: el mismo número para sizing, porcentaje mostrado y tope diario."""
    class _Cli:
        def balance_usdt(self): return {"balance": 1234.5, "available": 1000.0}
    ex = BotExecutor(store=None, log=lambda _m: None,
                     config={"base_equity": 897.61, "base_equity_auto": True})
    ex.client = lambda: _Cli()
    assert ex._equity_base() == 1234.5


def test_el_config_no_tiene_dos_capitales():
    """Hubo 450 para el sizing, 1000 para los porcentajes y 897.61 de saldo real.
    El panel mostraba 0.9% donde se arriesgaba 2%, y el tope diario del 15% era el 33%
    de la cuenta. Que no vuelvan a ser dos números."""
    import json as _json
    from pathlib import Path
    cfg = _json.loads((Path(__file__).resolve().parents[1] / "config/nexus.json").read_text())
    bot = cfg["modules"]["bot"]
    assert "capital" not in bot, "volvió un segundo capital que no existe en la cuenta"
    assert bot.get("base_equity_auto") is True
    assert bot["max_leverage"] >= bot["fixed_leverage"], \
        "max_leverage por debajo del fijo lo recorta en silencio"


# --- reconciliación bidireccional -------------------------------------------

class _CliRec:
    def __init__(self, posiciones, orden_cierre=None, marca=100.0):
        self._pos = posiciones
        self._orden = orden_cierre
        self._marca = marca
    def positions(self): return self._pos
    def mark_price(self, _s): return self._marca
    def get_order(self, _s, _cid): return self._orden


class _ExFalso:
    def __init__(self, store, cli):
        self.store = store; self._cli = cli
        self.cfg = {"pairs": ["BTCUSDT"]}
        self.live = True; self.hedge = False
    def client(self): return self._cli
    @staticmethod
    def _cid(sid, suffix): return f"nx{sid}{suffix}"


def _abierta_live(store, sid="s:1", qty=1.0):
    r = _trade_rec(); r["setup_id"] = sid; r["mode"] = "live"; r["qty"] = qty
    store.open_trade(r)


def test_trade_abierto_en_el_libro_sin_posicion_real_se_cierra(tmp_path):
    """La secuela del P0 del cierre: el cierre SÍ había entrado, se leyó como fallo y
    el libro quedó abierto contra un exchange plano. reconcile() solo recorría
    cli.positions(), así que este caso era invisible y nunca se reparaba."""
    store = BotStore(path=str(tmp_path / "b.json"))
    _abierta_live(store)
    cli = _CliRec(posiciones=[], orden_cierre={"status": "FILLED", "executed_qty": 1.0,
                                               "avg_price": 123.0})
    BotSync(_ExFalso(store, cli), lambda _m: None)._reconciliar_fantasmas(cli, hedge=False)
    t = store.all()[0]
    assert t["status"] == "cerrada"
    assert t["exit_price"] == 123.0, "debe usar el precio REAL del cierre ejecutado"


def test_sin_lectura_confiable_no_se_declara_nada_fantasma(tmp_path):
    """Una caída de la API borraría del libro posiciones perfectamente vivas."""
    store = BotStore(path=str(tmp_path / "b.json"))
    _abierta_live(store)

    class _Roto(_CliRec):
        def positions(self): raise RuntimeError("sin respuesta")

    cli = _Roto(posiciones=[])
    BotSync(_ExFalso(store, cli), lambda _m: None)._reconciliar_fantasmas(cli, hedge=False)
    assert store.all()[0]["status"] == "abierta", "no se toca el libro sin datos"


def test_posicion_viva_no_se_toca(tmp_path):
    store = BotStore(path=str(tmp_path / "b.json"))
    _abierta_live(store)
    cli = _CliRec(posiciones=[{"symbol": "BTCUSDT", "side": "LONG", "qty": 1.0}])
    BotSync(_ExFalso(store, cli), lambda _m: None)._reconciliar_fantasmas(cli, hedge=False)
    assert store.all()[0]["status"] == "abierta"


def test_exchange_con_menos_cantidad_ajusta_el_libro(tmp_path):
    """Un parcial que salió en el exchange y no se registró: el libro cree que le
    queda más de lo que le queda, y el -1R apunta al lugar errado."""
    store = BotStore(path=str(tmp_path / "b.json"))
    _abierta_live(store, qty=1.0)
    cli = _CliRec(posiciones=[{"symbol": "BTCUSDT", "side": "LONG", "qty": 0.4}])
    BotSync(_ExFalso(store, cli), lambda _m: None)._reconciliar_fantasmas(cli, hedge=False)
    t = store.all()[0]
    assert t["status"] == "abierta"
    assert abs(t["qty_open"] - 0.4) < 1e-9, "el libro debe quedar en lo que el exchange tiene"


# --- filtros de símbolo -----------------------------------------------------

class _CliInfo:
    """Reproduce el comportamiento REAL del endpoint: ignora `symbol` y devuelve todo."""

    def __init__(self):
        self._filters_cache = {}
        self.descargas = 0

    def _request(self, _m, _p, _params=None, signed=False):
        self.descargas += 1
        return {"symbols": [
            {"symbol": "BTCUSDT", "quantityPrecision": 3, "pricePrecision": 2,
             "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                         {"filterType": "MIN_NOTIONAL", "notional": "50"}]},
            {"symbol": "ADAUSDT", "quantityPrecision": 0, "pricePrecision": 5,
             "filters": [{"filterType": "LOT_SIZE", "stepSize": "1", "minQty": "1"},
                         {"filterType": "MIN_NOTIONAL", "notional": "5"}]},
        ]}


def _cliente_con_info():
    from modules.trading.binance_account import BinanceFutures
    cli = _CliInfo()
    cli.symbol_filters = BinanceFutures.symbol_filters.__get__(cli)
    cli.round_qty = BinanceFutures.round_qty.__get__(cli)
    return cli


def test_los_filtros_son_del_simbolo_pedido_no_del_primero():
    """/fapi/v1/exchangeInfo IGNORA el parámetro `symbol` y devuelve los 848 símbolos.
    Tomar syms[0] daba SIEMPRE BTCUSDT, así que todos los pares heredaban su precisión.
    ADA se opera en unidades enteras: el bot habría mandado 7287.292 y Binance lo
    rechaza con -1111. Nunca se vio porque los 27 trades live fueron ETH y BTC, que sí
    comparten la precisión de BTC; V2 opera ADA, XRP y SOL.
    """
    cli = _cliente_con_info()
    ada = cli.symbol_filters("ADAUSDT")
    assert ada["qty_step"] == 1.0, "ADA se opera en unidades enteras"
    assert ada["qty_precision"] == 0
    assert ada["price_precision"] == 5, "con la de BTC (2) el SL queda 0.8% corrido"
    assert ada["min_notional"] == 5.0
    btc = cli.symbol_filters("BTCUSDT")
    assert btc["qty_step"] == 0.001 and btc["price_precision"] == 2
    assert ada != btc, "dos símbolos no pueden tener los mismos filtros por accidente"


def test_round_qty_respeta_el_step_del_simbolo():
    cli = _cliente_con_info()
    assert cli.round_qty("ADAUSDT", 7287.292) == 7287.0
    assert cli.round_qty("BTCUSDT", 0.0195) == 0.019


def test_un_simbolo_ausente_falla_en_vez_de_heredar_otra_precision():
    """Mejor fallar que dimensionar con la precisión de otro símbolo."""
    from modules.trading.binance_account import BinanceError
    cli = _cliente_con_info()
    try:
        cli.symbol_filters("DOGEUSDT")
    except BinanceError:
        pass
    else:
        raise AssertionError("un símbolo desconocido no puede devolver filtros ajenos")


def test_los_filtros_se_cachean_todos_de_una():
    """La respuesta trae los 848 igual: descargarla por par era pagarla cinco veces."""
    cli = _cliente_con_info()
    cli.symbol_filters("ADAUSDT")
    cli.symbol_filters("BTCUSDT")
    assert cli.descargas == 1


# --- watchdog del stop ------------------------------------------------------
#
# La subcuenta rechaza STOP_MARKET con -4120 en las DOS variantes (verificado contra
# la API el 2026-07-29). Sin stop nativo, el -1R lo sostiene el polling del bot, y el
# libro real mostró 8 de 11 stops pasados, peor -4.17R.

def _wd():
    import importlib.util, pathlib
    ruta = pathlib.Path(__file__).resolve().parents[1] / "deploy/bot_watchdog.py"
    spec = importlib.util.spec_from_file_location("bot_watchdog", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_excedido_mide_cuanto_se_paso_del_sl_en_R():
    wd = _wd()
    # long: entrada 100, SL 98 → riesgo 2. A 97 se pasó 1 punto = 0.5R más allá.
    largo = {"entry_price": 100.0, "sl": 98.0, "dir": "long"}
    assert wd._excedido(largo, 97.0) == 0.5
    assert wd._excedido(largo, 98.0) is None, "justo en el SL todavía no se pasó"
    assert wd._excedido(largo, 99.0) is None, "antes del SL no es asunto del watchdog"
    # short: entrada 100, SL 102 → a 103 se pasó 0.5R
    corto = {"entry_price": 100.0, "sl": 102.0, "dir": "short"}
    assert wd._excedido(corto, 103.0) == 0.5
    assert wd._excedido(corto, 101.0) is None


def test_excedido_no_divide_por_cero_ni_revienta_con_datos_malos():
    wd = _wd()
    assert wd._excedido({"entry_price": 100.0, "sl": 100.0, "dir": "long"}, 99.0) is None
    assert wd._excedido({"dir": "long"}, 99.0) is None
    assert wd._excedido({"entry_price": "x", "sl": 1, "dir": "long"}, 99.0) is None


def test_la_tolerancia_deja_actuar_al_bot_en_el_caso_normal():
    """Los stops que el bot cierra bien no debe tocarlos: si el watchdog compite en
    el caso normal, se convierte él mismo en una fuente de cierres equivocados.
    De los 8 stops pasados, 6 lo hicieron por más de 0.13R."""
    wd = _wd()
    largo = {"entry_price": 100.0, "sl": 98.0, "dir": "long"}
    # -1.05R: el bot todavía tiene la palabra
    assert wd._excedido(largo, 97.9) < wd.TOLERANCIA_R
    # -1.30R: ya se pasó de largo, entra el watchdog
    assert wd._excedido(largo, 97.4) > wd.TOLERANCIA_R
    # el peor caso real (-4.17R) queda muy por encima
    assert wd._excedido(largo, 100 - 2 * 4.17) > wd.TOLERANCIA_R


def test_nunca_live_sin_watchdog():
    """La combinación prohibida: dinero real sin nada que haga cumplir el -1R.

    El test original fijaba "el watchdog arranca apagado", pensando que un proceso que
    cierra posiciones no debe encenderse solo. Pero encenderlo ANTES del live es
    justamente lo correcto —con el bot en dry no cierra nada y ejercita el camino de
    lectura—, así que ese test bloqueaba lo bueno y no protegía de lo malo.

    Lo peligroso es al revés: live=true con el watchdog apagado. Sin stop nativo
    (-4120 en las dos variantes), ahí el -1R no lo sostiene nadie, y eso ya costó
    -129.03 USD con 8 de 11 stops pasados.
    """
    import json as _json
    from pathlib import Path
    cfg = _json.loads((Path(__file__).resolve().parents[1] / "config/nexus.json").read_text())
    bot = cfg["modules"]["bot"]
    wd = bot.get("watchdog") or {}
    if bot.get("live"):
        assert wd.get("enabled") is True, \
            "live=true sin watchdog: el -1R no lo sostiene nadie"
        assert float(wd.get("tolerancia_r", 1)) <= 0.30, \
            "una tolerancia alta deja pasar justo los stops que hay que atrapar"


class _CliWd:
    """Cliente falso: posiciones y precio programables, órdenes registradas."""

    def __init__(self, precio, posiciones=None, rompe_posiciones=False,
                 rompe_precio=False):
        self.precio = precio
        self._pos = posiciones if posiciones is not None else [
            {"symbol": "ADAUSDT", "side": "LONG", "qty": 100.0, "position_side": "LONG"}]
        self.rompe_posiciones = rompe_posiciones
        self.rompe_precio = rompe_precio
        self.ordenes = []

    def positions(self):
        if self.rompe_posiciones:
            from modules.trading.binance_account import BinanceError
            raise BinanceError("sin respuesta")
        return self._pos

    def mark_price(self, _s):
        if self.rompe_precio:
            from modules.trading.binance_account import BinanceError
            raise BinanceError("sin precio")
        return self.precio

    def round_qty(self, _s, q): return q

    def market_order(self, symbol, side, qty, **kw):
        self.ordenes.append({"symbol": symbol, "side": side, "qty": qty, **kw})
        return {"status": "FILLED", "executedQty": qty, "avgPrice": self.precio}


_TRADE_WD = [{"setup_id": "s:wd", "symbol": "ADAUSDT", "dir": "long", "mode": "live",
              "status": "abierta", "entry_price": 0.20, "sl": 0.19,
              "qty": 100.0, "qty_open": 100.0, "fee_rate": 0.0005}]
_CFG_WD = {"enabled": True, "tolerancia_r": 0.15, "hedge": True}


def test_el_watchdog_cierra_cuando_el_stop_se_paso():
    """El caso que ya cobró: 8 de 11 stops se pasaron del -1R, peor -4.17R."""
    wd = _wd()
    cli = _CliWd(precio=0.185)   # SL 0.19, riesgo 0.01 → se pasó 0.5R = -1.5R
    n = wd.ciclo(cli=cli, abiertos=list(_TRADE_WD), cfg=_CFG_WD, log=lambda _m: None)
    assert n == 1 and len(cli.ordenes) == 1
    o = cli.ordenes[0]
    assert o["symbol"] == "ADAUSDT" and o["side"] == "SELL", "un long se cierra vendiendo"
    assert o["qty"] == 100.0


def test_el_watchdog_no_compite_con_el_bot_dentro_de_la_tolerancia():
    wd = _wd()
    cli = _CliWd(precio=0.1895)  # se pasó solo 0.05R → el bot todavía manda
    assert wd.ciclo(cli=cli, abiertos=list(_TRADE_WD), cfg=_CFG_WD,
                    log=lambda _m: None) == 0
    assert cli.ordenes == []


def test_el_watchdog_no_toca_nada_antes_del_sl():
    wd = _wd()
    cli = _CliWd(precio=0.195)
    assert wd.ciclo(cli=cli, abiertos=list(_TRADE_WD), cfg=_CFG_WD,
                    log=lambda _m: None) == 0


def test_sin_lecturas_confiables_el_watchdog_no_actua():
    """Un watchdog que actúa a ciegas es peor que no tenerlo."""
    wd = _wd()
    for kw in ({"rompe_posiciones": True}, {"rompe_precio": True}):
        cli = _CliWd(precio=0.185, **kw)
        assert wd.ciclo(cli=cli, abiertos=list(_TRADE_WD), cfg=_CFG_WD,
                        log=lambda _m: None) == 0
        assert cli.ordenes == []


def test_el_watchdog_ignora_lo_que_ya_no_existe_en_binance():
    wd = _wd()
    cli = _CliWd(precio=0.185, posiciones=[])
    assert wd.ciclo(cli=cli, abiertos=list(_TRADE_WD), cfg=_CFG_WD,
                    log=lambda _m: None) == 0


def test_apagado_no_hace_nada_aunque_el_stop_este_pasado():
    wd = _wd()
    cli = _CliWd(precio=0.10)   # -10R
    assert wd.ciclo(cli=cli, abiertos=list(_TRADE_WD),
                    cfg={"enabled": False}, log=lambda _m: None) == 0
    assert cli.ordenes == []


def test_el_watchdog_cierra_shorts_por_arriba():
    wd = _wd()
    corto = [{**_TRADE_WD[0], "dir": "short", "entry_price": 0.20, "sl": 0.21}]
    cli = _CliWd(precio=0.215,
                 posiciones=[{"symbol": "ADAUSDT", "side": "SHORT", "qty": 100.0,
                              "position_side": "SHORT"}])
    assert wd.ciclo(cli=cli, abiertos=corto, cfg=_CFG_WD, log=lambda _m: None) == 1
    assert cli.ordenes[0]["side"] == "BUY", "un short se cierra comprando"


def test_el_watchdog_reintenta_ante_cuota_de_IP():
    """-1003 es la cuota de la IP, transitoria y ajena: el watchdog pide 4 veces por
    minuto. Lo único que sostiene el -1R no puede quedar ciego porque otro proceso se
    pasó de cuota."""
    wd = _wd()

    class _CliCuota(_CliWd):
        def __init__(self, fallos, **kw):
            super().__init__(**kw)
            self.fallos = fallos
            self.lecturas = 0

        def positions(self):
            self.lecturas += 1
            if self.fallos > 0:
                self.fallos -= 1
                from modules.trading.binance_account import BinanceError
                raise BinanceError('{"code":-1003,"msg":"Too many requests"}')
            return self._pos

    import time as _t
    orig, _t.sleep = _t.sleep, lambda _s: None
    try:
        cli = _CliCuota(fallos=2, precio=0.185)
        assert wd.ciclo(cli=cli, abiertos=list(_TRADE_WD), cfg=_CFG_WD,
                        log=lambda _m: None) == 1, "debe cerrar tras reintentar"
        assert cli.lecturas == 3
        # pero un error que NO es de cuota no se reintenta: se aborta y no se toca nada
        class _CliOtro(_CliWd):
            def positions(self):
                from modules.trading.binance_account import BinanceError
                raise BinanceError('{"code":-2015,"msg":"Invalid API-key"}')
        c2 = _CliOtro(precio=0.185)
        assert wd.ciclo(cli=c2, abiertos=list(_TRADE_WD), cfg=_CFG_WD,
                        log=lambda _m: None) == 0
        assert c2.ordenes == []
    finally:
        _t.sleep = orig


# --- stop nativo + watchdog corregido ---------------------------------------
#
# Binance movió las condicionales a /fapi/v1/algoOrder el 2025-12-09. La versión previa
# de este trabajo concluyó "no hay stop nativo" leyendo el -4120 del endpoint viejo, que
# literalmente apuntaba al nuevo. El stop nativo estuvo disponible todo el tiempo.

def test_el_watchdog_distingue_long_de_short_en_el_mismo_simbolo():
    """La cuenta es HEDGE. Indexar por símbolo hacía que un lado pisara al otro y el
    watchdog podía cerrar el lado equivocado."""
    wd = _wd()
    # BTC long sano (SL 98, precio 99) y BTC short pasado (SL 102, precio 103.5)
    abiertos = [
        {"setup_id": "s:l", "symbol": "BTCUSDT", "dir": "long", "mode": "live",
         "status": "abierta", "entry_price": 100.0, "sl": 98.0, "qty_open": 1.0},
        {"setup_id": "s:s", "symbol": "BTCUSDT", "dir": "short", "mode": "live",
         "status": "abierta", "entry_price": 100.0, "sl": 102.0, "qty_open": 2.0},
    ]
    cli = _CliWd(precio=103.5, posiciones=[
        {"symbol": "BTCUSDT", "side": "LONG", "qty": 1.0, "position_side": "LONG"},
        {"symbol": "BTCUSDT", "side": "SHORT", "qty": 2.0, "position_side": "SHORT"},
    ])
    assert wd.ciclo(cli=cli, abiertos=abiertos, cfg=_CFG_WD, log=lambda _m: None) == 1
    o = cli.ordenes[0]
    assert o["position_side"] == "SHORT", "cerró el lado equivocado"
    assert o["side"] == "BUY"
    assert o["qty"] == 2.0


def test_el_watchdog_usa_la_cantidad_de_binance_no_la_del_libro():
    """Si el libro está desincronizado —que es justo cuando el watchdog hace falta—
    cerrar por qty_open deja un resto abierto o intenta cerrar de más."""
    wd = _wd()
    t = [{**_TRADE_WD[0], "qty_open": 100.0}]
    cli = _CliWd(precio=0.18, posiciones=[
        {"symbol": "ADAUSDT", "side": "LONG", "qty": 37.0, "position_side": "LONG"}])
    wd.ciclo(cli=cli, abiertos=t, cfg=_CFG_WD, log=lambda _m: None)
    assert cli.ordenes[0]["qty"] == 37.0, "debe cerrar lo que Binance dice que hay"


def test_el_watchdog_usa_un_id_determinista():
    """Un id con timestamp generaba uno nuevo cada ciclo: un timeout podía terminar en
    dos órdenes de cierre."""
    wd = _wd()
    ids = []
    for _ in range(2):
        cli = _CliWd(precio=0.18)
        wd.ciclo(cli=cli, abiertos=list(_TRADE_WD), cfg=_CFG_WD, log=lambda _m: None)
        ids.append(cli.ordenes[0]["client_id"])
    assert ids[0] == ids[1], "el mismo trade debe reintentar con el mismo id"
    assert not ids[0].startswith("sl"), "no puede chocar con el espacio de clientAlgoId"


def test_un_sl_del_lado_equivocado_no_dispara_al_watchdog():
    """Un registro con el SL invertido haría que el exceso salga positivo con el precio
    A FAVOR, y el watchdog cerraría una posición ganadora."""
    wd = _wd()
    # long con SL POR ENCIMA de la entrada: incoherente
    malo = {"entry_price": 100.0, "sl": 102.0, "dir": "long"}
    assert wd._excedido(malo, 101.0) is None
    # short con SL POR DEBAJO: incoherente
    malo2 = {"entry_price": 100.0, "sl": 98.0, "dir": "short"}
    assert wd._excedido(malo2, 99.0) is None
    # dir desconocido
    assert wd._excedido({"entry_price": 100.0, "sl": 98.0, "dir": "?"}, 97.0) is None


def test_el_watchdog_es_respaldo_no_ejecutor():
    """Con stop nativo puesto por el exchange, este proceso es emergencia. La tolerancia
    de 0.15R estaba ajustada a la misma muestra que motivó construirlo: circular."""
    wd = _wd()
    assert wd.TOLERANCIA_R >= 0.25, "un ejecutor primario disfrazado de emergencia"


def test_market_order_pide_RESULT():
    """El default de Binance es ACK: contesta antes de saber el fill, con executedQty=0
    y avgPrice=0. Con ACK el bot no distingue un fill total de uno parcial."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "modules/trading/binance_account.py").read_text()
    i = src.index("def market_order")
    assert '"newOrderRespType": "RESULT"' in src[i:i + 1200]


def test_el_stop_nativo_usa_los_nombres_del_endpoint_nuevo():
    """triggerPrice (no stopPrice), clientAlgoId (no newClientOrderId), y reduceOnly
    NO se admite en HEDGE. Equivocar cualquiera devuelve un error de parámetros que se
    ve igual que un stop prohibido — que es exactamente cómo se concluyó mal la primera vez."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "modules/trading/binance_account.py").read_text()
    i = src.index("def algo_stop_market")
    j = src.index("def algo_open_orders")
    cuerpo = src[i:j]
    assert '"/fapi/v1/algoOrder"' in cuerpo
    assert '"algoType": "CONDITIONAL"' in cuerpo
    assert '"triggerPrice"' in cuerpo and '"stopPrice"' not in cuerpo
    assert "clientAlgoId" in cuerpo
    assert "if not position_side" in cuerpo, "reduceOnly es inválido en HEDGE"


def test_los_ids_de_stop_y_de_orden_no_se_pisan():
    """clientAlgoId y newClientOrderId son espacios distintos: confundirlos cancela lo
    que no era o deja stops huérfanos."""
    ex = BotExecutor(store=None, log=lambda _m: None, config={})
    sid = "algo:123"
    assert ex._aid(sid) != ex._cid(sid, "o")
    assert ex._aid(sid) != ex._cid(sid, "c")
    assert ex._aid(sid) == ex._aid(sid), "el id del stop debe ser determinista"


def _llamadas(ruta):
    """Nombres de método efectivamente LLAMADOS en un archivo.

    Con AST y no con `in src`: los comentarios que explican por qué NO se usa algo
    hacían saltar la aserción. Ya van varias veces en este repo.
    """
    import ast
    from pathlib import Path
    arbol = ast.parse((Path(__file__).resolve().parents[1] / ruta).read_text())
    return {n.func.attr for n in ast.walk(arbol)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


def test_no_se_cancela_todo_el_simbolo_al_cerrar():
    """cancel_all_orders(symbol) en HEDGE se lleva el stop del lado opuesto."""
    llamadas = _llamadas("modules/bot/executor.py")
    assert "cancel_all_orders" not in llamadas, \
        "volvió un barrido por símbolo; usar cancel_algo_order(client_algo_id=...)"
    assert "cancel_algo_order" in llamadas


def test_el_watchdog_no_manda_ordenes_crudas():
    """Se construyó `ordenar_resuelto` para las órdenes ambiguas y el watchdog —el
    código que cierra posiciones SOLO— seguía llamando a market_order pelado."""
    llamadas = _llamadas("deploy/bot_watchdog.py")
    assert "market_order" not in llamadas


# --- los cuatro P0 del fail-closed (auditoría de Codex, 2026-07-29) ----------

def test_si_el_cierre_de_emergencia_no_sale_la_posicion_se_REGISTRA():
    """Antes: si el stop no se confirmaba se intentaba cerrar, y si ese cierre devolvía
    None se daba por cerrada y se hacía `return` sin registrar nada. La posición podía
    quedar viva, sin stop del exchange, sin gestión del bot y sin que el watchdog la
    viera — porque el watchdog lee el LIBRO. Es el peor estado posible."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "modules/bot/executor.py").read_text()
    i = src.index("abierto SIN stop confirmado")
    bloque = src[i:i + 1800]
    assert "cerrada = bool(resp_c)" in bloque, "no se mira si el cierre realmente salió"
    assert "sin_stop = True" in bloque, "debe registrarse marcada, no descartarse"
    assert '"sin_stop_nativo": sin_stop' in src


def test_el_stop_nuevo_se_pone_antes_de_retirar_el_viejo():
    """Cancelar primero y poner después dejaba la posición sin stop si el reemplazo
    fallaba, que contradice el fail-closed. Por eso `_aid` numera generaciones."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "modules/bot/executor.py").read_text()
    i = src.index("ORDEN IMPORTANTE")
    bloque = src[i:i + 1800]
    proteger = bloque.index("_proteger(")
    cancelar = bloque.index("_cancelar_stops_anteriores(")
    assert proteger < cancelar, "sigue cancelando antes de confirmar el reemplazo"
    ex = BotExecutor(store=None, log=lambda _m: None, config={})
    assert ex._aid("s:1", 0) != ex._aid("s:1", 1), "las generaciones deben poder coexistir"


def test_proteger_verifica_lado_cantidad_y_precio_no_solo_el_id():
    """Un stop que existe pero cubre el lado equivocado, la mitad de la posición o un
    precio distinto es peor que ninguno: se ve como protección."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "modules/bot/executor.py").read_text()
    i = src.index("def _proteger")
    j = src.index("_EQUITY_TTL_S")
    cuerpo = src[i:j]
    for señal in ('o.get("side") != lado', "position_side", "abs(cubre - qty)", "trigger_price"):
        assert señal in cuerpo, f"_proteger no verifica {señal}"


def test_proteger_rechaza_stop_sobredimensionado():
    class Client:
        def algo_stop_market(self, *_args, **_kwargs):
            return {}

        def get_algo_order(self, client_id):
            return {
                "client_algo_id": client_id,
                "status": "NEW",
                "side": "SELL",
                "position_side": "LONG",
                "qty": 2.0,
                "trigger_price": 90.0,
            }

    logs = []
    ex = BotExecutor(store=None, log=logs.append, config={})

    assert not ex._proteger(Client(), "BTCUSDT", "long", 90.0, 1.0,
                            "setup:oversized", "LONG")
    assert any("cantidad no coincide" in line for line in logs)


def test_parcial_con_be_invalido_deja_stop_exacto_en_sl_original(tmp_path):
    sid = "setup:partial:1"
    store = BotStore(path=str(tmp_path / "bot_trades.json"))
    store.open_trade({
        **_trade_rec(),
        "setup_id": sid,
        "mode": "live",
        "qty": 2.0,
        "entry_price": 100.0,
        "sl": 90.0,
    })

    class Client:
        def __init__(self):
            self.orders = {
                BotExecutor._aid(sid): {
                    "client_algo_id": BotExecutor._aid(sid),
                    "algo_id": 1,
                    "status": "NEW",
                    "side": "SELL",
                    "position_side": "LONG",
                    "qty": 2.0,
                    "trigger_price": 90.0,
                }
            }
            self.cancelled = []

        def mark_price(self, _symbol):
            return 99.0

        def round_qty(self, _symbol, qty):
            return qty

        def algo_stop_market(self, _symbol, side, trigger, *, qty,
                             position_side, client_algo_id):
            if trigger == 100.0:
                raise RuntimeError("Order would immediately trigger")
            self.orders[client_algo_id] = {
                "client_algo_id": client_algo_id,
                "algo_id": 2,
                "status": "NEW",
                "side": side,
                "position_side": position_side,
                "qty": qty,
                "trigger_price": trigger,
            }

        def get_algo_order(self, client_id):
            return self.orders.get(client_id)

        def algo_open_orders(self, _symbol):
            return list(self.orders.values())

        def cancel_algo_order(self, *, algo_id=None, client_algo_id=None):
            target = client_algo_id
            if algo_id is not None:
                target = next((cid for cid, order in self.orders.items()
                               if order.get("algo_id") == algo_id), None)
            self.cancelled.append(target)
            if target:
                self.orders.pop(target, None)

    client = Client()
    logs = []
    ex = BotExecutor(store, logs.append, config={"live": True, "hedge": True},
                     client=client)
    ex._ordenar = lambda *_args, **_kwargs: {"executed_qty": 1.0, "avg_price": 99.0}

    ex._reduce({
        "key": "setup:partial",
        "ts_created": 1,
        "leg": "TP1",
        "frac_closed": 0.5,
        "realized_r": 0.5,
        "be": True,
    }, 99.0)

    trade = store.get_open(sid)
    assert trade["qty_open"] == 1.0
    assert len(client.orders) == 1
    stop = next(iter(client.orders.values()))
    assert stop["qty"] == 1.0
    assert stop["trigger_price"] == 90.0
    assert BotExecutor._aid(sid) in client.cancelled
    assert any("respaldo exacto" in line for line in logs)


def test_ajustar_qty_corrige_sin_inventar_una_salida(tmp_path):
    """El exchange tenía MÁS que el libro (un parcial que terminó de llenarse). Eso se
    corrige, no se registra como si hubiera salido algo."""
    store = BotStore(path=str(tmp_path / "b.json"))
    r = _trade_rec(); r["setup_id"] = "s:aj"; r["qty"] = 1.0
    store.open_trade(r)
    assert store.ajustar_qty("s:aj", 1.6)
    t = store.all()[0]
    assert t["qty_open"] == 1.6
    assert t["partials"] == [], "no puede inventar un parcial que no ocurrió"
    assert t["ajustes"][0]["qty_open"] == 1.6
    # y tras un parcial real, el ajuste respeta lo ya cerrado
    store.add_partial("s:aj", "TP1", 0.6, 110.0)
    assert store.all()[0]["qty_open"] == 1.0
    store.ajustar_qty("s:aj", 1.2)
    t = store.all()[0]
    assert t["qty_open"] == 1.2 and t["qty"] == 1.8


def test_adoptar_ambiguas_adopta_en_vez_de_borrar_la_evidencia():
    """Solo avisaba y después vaciaba el archivo, incluso con la posición viva: se
    perdía la única pista de una posición fuera del libro y sin stop."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "modules/bot/sync.py").read_text()
    i = src.index("def _adoptar_ambiguas")
    cuerpo = src[i:i + 3000]
    assert "open_trade(" in cuerpo, "no crea el trade"
    assert "_proteger(" in cuerpo, "no le pone stop"
    assert "quedan[sid] = info" in cuerpo, "borra el rastro aunque no se resuelva"


def test_real_mayor_que_libro_amplia_el_stop():
    """Detectarlo y solo loguear deja la exposición sin stop mientras nadie mire."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "modules/bot/sync.py").read_text()
    i = src.index("real_qty > libro_qty * 1.02")
    bloque = src[i:i + 2400]
    assert "_proteger(" in bloque, "no amplía el stop a la cantidad real"
    assert "ajustar_qty(" in bloque, "no corrige el libro"


def test_reconciliacion_repara_stop_sobredimensionado(tmp_path):
    sid = "setup:reconcile"
    store = BotStore(path=str(tmp_path / "bot_trades.json"))
    store.open_trade({
        **_trade_rec(), "setup_id": sid, "mode": "live", "qty": 2.0,
        "entry_price": 100.0, "sl": 90.0,
    })
    store.add_partial(sid, "TP1", 1.0, 105.0)

    class Client:
        def __init__(self):
            self.orders = [{
                "client_algo_id": BotExecutor._aid(sid), "algo_id": 1,
                "status": "NEW", "side": "SELL", "position_side": "LONG",
                "qty": 2.0, "trigger_price": 90.0,
            }]

        def algo_open_orders(self, _symbol):
            return list(self.orders)

        def round_qty(self, _symbol, qty):
            return qty

        def algo_stop_market(self, _symbol, side, trigger, *, qty,
                             position_side, client_algo_id):
            self.orders.append({
                "client_algo_id": client_algo_id, "algo_id": 2,
                "status": "NEW", "side": side, "position_side": position_side,
                "qty": qty, "trigger_price": trigger,
            })

        def get_algo_order(self, client_id):
            return next((o for o in self.orders
                         if o["client_algo_id"] == client_id), None)

        def cancel_algo_order(self, *, algo_id=None, client_algo_id=None):
            self.orders = [o for o in self.orders
                           if not ((algo_id and o.get("algo_id") == algo_id)
                                  or (client_algo_id and
                                      o.get("client_algo_id") == client_algo_id))]

    client = Client()
    ex = BotExecutor(store, lambda _msg: None,
                     config={"live": True, "hedge": True}, client=client)
    sync = BotSync(ex, lambda _msg: None)

    assert sync._asegurar_stop_exacto(client, store.get_open(sid), 1.0, True)
    assert len(client.orders) == 1
    assert client.orders[0]["qty"] == 1.0
    assert client.orders[0]["trigger_price"] == 90.0


def test_el_path_de_los_algo_orders_es_el_que_responde_no_el_de_la_doc():
    """La documentación de Binance dice `/fapi/v1/algoOpenOrders` y ese path devuelve
    404. El real es `/fapi/v1/openAlgoOrders`, verificado contra la API el 2026-07-29.

    Es la TERCERA vez en este trabajo que la doc no coincide con lo que responde
    Binance —antes fueron los filtros de exchangeInfo y el propio -4120— y las tres
    solo se vieron llamando. Este test fija el path medido, no el documentado."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "modules/trading/binance_account.py").read_text()
    assert '"/fapi/v1/openAlgoOrders"' in src
    assert '"/fapi/v1/algoOpenOrders"' not in src, "volvió el path que da 404"


def test_proteger_pregunta_por_el_id_exacto():
    """Listar y buscar es más frágil y más caro que preguntar por el clientAlgoId."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "modules/bot/executor.py").read_text()
    i = src.index("def _proteger")
    cuerpo = src[i:i + 2600]
    assert "get_algo_order(aid)" in cuerpo
    assert "algo_open_orders" in cuerpo, "debe quedar el listado como respaldo"
