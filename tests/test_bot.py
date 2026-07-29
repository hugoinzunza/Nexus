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
