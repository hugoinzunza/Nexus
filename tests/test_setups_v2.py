from modules.trading.setups_store import (
    CURRENT_PHASE_ID,
    ENTRY_MODEL_V2,
    SetupStore,
)


def _plan(state="pendiente"):
    return {
        "tf": "1h",
        "dir": "long",
        "entry": 100.0,
        "entry_lo": 99.0,
        "entry_hi": 102.0,
        "sl": 98.0,
        "tp": 110.0,
        "rr": 5.0,
        "state": state,
    }


def test_v2_tocar_borde_no_activa_hasta_cruzar_midpoint(tmp_path):
    store = SetupStore(path=str(tmp_path / "setups.json"))
    created = store.record(_plan(state="activo"), "BTC_USDT", "1h", 101.5, 1000)

    assert created["status"] == "pendiente"
    assert created["entry_model"] == ENTRY_MODEL_V2
    assert created["phase_id"] == CURRENT_PHASE_ID
    assert created["entry_armed"] is True

    assert store.track("BTC_USDT", 101.0, 1001) == []
    events = store.track("BTC_USDT", 100.04, 1002)

    assert [e["type"] for e in events] == ["activated"]
    setup = store.all()[0]
    assert setup["status"] == "activo"
    assert setup["activation_price"] == 100.04
    assert events[0]["entry_model"] == ENTRY_MODEL_V2
    assert events[0]["phase_id"] == CURRENT_PHASE_ID


def test_v2_plan_nacido_despues_del_cruce_exige_rearme(tmp_path):
    path = str(tmp_path / "setups.json")
    store = SetupStore(path=path)
    created = store.record(_plan(state="activo"), "BTC_USDT", "1h", 99.5, 1000)

    assert created["status"] == "pendiente"
    assert created["entry_armed"] is False
    assert store.track("BTC_USDT", 99.4, 1001) == []
    assert store.track("BTC_USDT", 100.2, 1002) == []  # solo rearma

    # El rearme no genera una transicion visible, pero debe sobrevivir reinicios.
    store = SetupStore(path=path)
    assert store.all()[0]["entry_armed"] is True
    events = store.track("BTC_USDT", 100.0, 1003)

    assert [e["type"] for e in events] == ["activated"]
    assert store.all()[0]["ts_activated"] == 1003


def test_setup_legacy_sin_version_conserva_activacion_por_zona():
    legacy = {
        "activated": False,
        "status": "pendiente",
        "dir": "long",
        "entry": 100.0,
        "entry_lo": 99.0,
        "entry_hi": 102.0,
        "sl": 98.0,
        "tp": 110.0,
        "poi_tf": "1h",
        "ts_created": 1000,
    }

    events = SetupStore._update(legacy, 101.5, 1001)

    assert [e["type"] for e in events] == ["activated"]
    assert legacy["activation_price"] == 101.5


def test_rollover_archiva_solo_pendientes_v1(tmp_path):
    store = SetupStore(path=str(tmp_path / "setups.json"))
    legacy_pending = {"status": "pendiente", "entry_model": None}
    legacy_active = {"status": "activo", "entry_model": None}
    v2_pending = {"status": "pendiente", "entry_model": ENTRY_MODEL_V2}
    store._setups = [legacy_pending, legacy_active, v2_pending]

    assert store.archive_legacy_pending(now_s=2000) == 1

    assert legacy_pending["status"] == "anulada"
    assert legacy_pending["close_reason"] == "phase1_v2_rollover"
    assert legacy_active["status"] == "activo"
    assert v2_pending["status"] == "pendiente"


def _cerrado(key, pair, dir_, entry, sl, r, t_open, t_close):
    return {"key": key, "pair": pair, "dir": dir_, "poi_tf": "1h",
            "entry": entry, "sl": sl, "entry_lo": entry, "entry_hi": entry,
            "result_r": r, "status": "ganada" if r > 0 else "perdida",
            "ts_created": t_open, "ts_closed": t_close}


def test_paper_account_dimensiona_con_el_capital_al_abrir():
    """Dos trades que se SOLAPAN: el segundo abre antes de que cierre el primero,
    así que no puede dimensionarse con las ganancias del primero (auditoría
    2026-07-24). Antes se usaba el equity al cierre y eso inflaba el resultado.
    """
    from modules.trading import setups_store as ss

    base = 10_000.0
    setups = [
        _cerrado("a", "BTC_USDT", "long", 100.0, 99.0, 4.0, t_open=0, t_close=100),
        # abre en t=50, cuando A seguía abierto -> mismo capital base que A
        _cerrado("b", "ETH_USDT", "long", 200.0, 198.0, 4.0, t_open=50, t_close=200),
    ]
    acc = ss.paper_account(setups, capital=base, risk_pct=0.02, cost_rate=0.0)

    riesgo = 0.02 * base
    esperado = base + 4.0 * riesgo + 4.0 * riesgo    # ambos sobre el capital inicial
    assert abs(acc["equity"] - esperado) < 1e-6, \
        "el segundo trade se dimensionó con ganancias de uno que seguía abierto"


def test_paper_account_dimensiona_compuesto_cuando_no_hay_solape():
    """Sin solape sí corresponde componer: el segundo abre después del cierre."""
    from modules.trading import setups_store as ss

    base = 10_000.0
    setups = [
        _cerrado("a", "BTC_USDT", "long", 100.0, 99.0, 4.0, t_open=0, t_close=100),
        _cerrado("b", "ETH_USDT", "long", 200.0, 198.0, 4.0, t_open=150, t_close=200),
    ]
    acc = ss.paper_account(setups, capital=base, risk_pct=0.02, cost_rate=0.0)

    tras_a = base + 4.0 * (0.02 * base)
    esperado = tras_a + 4.0 * (0.02 * tras_a)
    assert abs(acc["equity"] - esperado) < 1e-6


def test_paper_account_reporta_riesgo_simultaneo_correlacionado():
    """El DD secuencial no puede mostrar varias posiciones abiertas a la vez."""
    from modules.trading import setups_store as ss

    setups = [
        _cerrado("a", "BTC_USDT", "long", 100.0, 99.0, 1.0, t_open=0, t_close=300),
        _cerrado("b", "ETH_USDT", "long", 200.0, 198.0, 1.0, t_open=10, t_close=300),
        _cerrado("c", "SOL_USDT", "long", 50.0, 49.0, 1.0, t_open=20, t_close=300),
        _cerrado("d", "XRP_USDT", "short", 2.0, 2.02, 1.0, t_open=30, t_close=300),
    ]
    acc = ss.paper_account(setups, capital=10_000.0, risk_pct=0.02, cost_rate=0.0)

    assert acc["max_concurrentes"] == 4
    assert acc["max_concurrentes_misma_dir"] == 3          # los tres long
    assert acc["riesgo_simultaneo_pct"] == 6.0             # 3 × 2%


def _plan_short(entry=100.0, tf="1h"):
    return {"dir": "short", "tf": tf, "entry": entry, "entry_lo": entry - 0.5,
            "entry_hi": entry + 0.5, "sl": entry * 1.02, "tp": entry * 0.9,
            "rr": 5.0, "tp_label": "t", "disc_ok": True}


def test_be_defensivo_no_toca_los_brazos_de_seguimiento_simple(tmp_path):
    """Regresión del gemelo BTC del 2026-08-12: protect_to_be estampaba un
    break-even sobre setups paper/profe que _update_simple jamás ejecuta,
    dejándolos vivos con el precio más allá de su BE. Su plan es su plan."""
    store = SetupStore(path=str(tmp_path / "setups.json"))
    store.record(_plan_short(), "BTC_USDT", "1h", last_price=101.0, now_s=1000.0)
    paper = dict(_plan_short(tf="15m"), paper_only=True, bta_paper=True)
    store.record(paper, "BTC_USDT", "15m", last_price=101.0, now_s=1000.0)
    # modelo V2: armar cruzando bajo el midpoint y activar al tocarlo de vuelta
    store.track("BTC_USDT", 99.9, 1050.0)   # arma (short: precio bajo entry-tol)
    store.track("BTC_USDT", 100.0, 1100.0)  # activa al tocar el midpoint
    activos = [s for s in store.all() if s["status"] == "activo"]
    assert len(activos) == 2

    # risk-off con ambos en ganancia (short: precio bajo la entrada)
    transiciones = store.protect_to_be("BTC_USDT", 99.0, 1200.0, reason="volatilidad")

    protegidos = {s["key"]: s for s in store.all() if s["status"] == "activo"}
    indicador = next(s for s in protegidos.values() if not s.get("paper_only"))
    gemelo = next(s for s in protegidos.values() if s.get("paper_only"))
    # el brazo NexUX SÍ se protege
    assert indicador.get("sl_be") is True and indicador["sl_cur"] == indicador["entry"]
    # el brazo paper queda TAL CUAL su plan: sin BE estampado
    assert gemelo.get("sl_be") is not True
    assert gemelo.get("sl_cur", gemelo["sl"]) == gemelo["sl"]
    assert all(t["key"] != gemelo["key"] for t in transiciones)

    # y si el precio vuelve a la entrada: el indicador cierra en BE (R=0),
    # el paper sigue vivo porque su SL original no fue tocado
    store.track("BTC_USDT", 100.2, 1300.0)
    indicador_final = next(s for s in store.all() if not s.get("paper_only"))
    gemelo_final = next(s for s in store.all() if s.get("paper_only"))
    assert indicador_final["status"] in ("ganada", "perdida")
    assert abs(indicador_final["result_r"]) < 1e-9   # cierre en break-even
    assert gemelo_final["status"] == "activo"
