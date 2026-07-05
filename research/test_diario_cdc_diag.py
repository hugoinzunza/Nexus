"""Tests de la columna paralela diagnóstica del Diario (diario_cdc_diag).

Correr con:  .venv/bin/python3 -m pytest research/test_diario_cdc_diag.py -q
"""
from __future__ import annotations

import copy
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import diario_cdc_diag as dg  # noqa: E402

BAR = 3_600_000  # 1h


def candle(i, o, h, l, c):
    return {"t": i * BAR, "o": o, "h": h, "l": l, "c": c, "v": 1.0}


def zigzag_prefix(n0=0):
    """Historia previa con swings confirmables (para last_confirmed_arrays)."""
    cs = []
    seq = [(100, 101, 99, 100), (100, 102, 99.5, 101), (101, 105, 100, 104),
           (104, 104.5, 102, 103), (103, 103.5, 101, 102), (102, 103, 100.5, 101.5),
           (101.5, 102, 100, 101), (101, 102.5, 100.5, 102)]
    for k, (o, h, l, c) in enumerate(seq):
        cs.append(candle(n0 + k, o, h, l, c))
    return cs


# long: entry=101, sl=99 (risk=2), tp=109 (rr=4); toque en la vela 8
E, SL, TP = 101.0, 99.0, 109.0
TAP_MS = 8 * BAR + 60_000       # dentro de la vela 8


def test_cdc_a_tiempo_mantiene_plan():
    cs = zigzag_prefix()
    cs.append(candle(8, 101, 101.5, 100.5, 101))          # vela del toque
    cs.append(candle(9, 101, 106, 100.8, 105.5))          # cierre > swing 105: CDC
    cs.append(candle(10, 105.5, 109.5, 105, 109.2))       # TP
    sim = dg.sim_cap03_8(cs, TAP_MS, True, E, SL, TP)
    assert sim["ok"] and sim["cdc_confirmed_within_8"] is True
    assert sim["reason"] == "cdc_a_tiempo_tp"
    assert sim["sim_netR"] > 3.5                          # ~4R menos costos


def test_sin_cdc_apreta_stop_y_sale_en_cap():
    cs = zigzag_prefix()
    cs.append(candle(8, 101, 101.5, 100.5, 101))          # toque
    for k in range(9, 17):                                # 8 velas sin CDC, a favor
        cs.append(candle(k, 101.5, 102.4, 100.9, 101.8))  # nunca cierra > 105
    cs.append(candle(17, 101.8, 102, 100.2, 100.3))       # toca cap 100.4 -> fuera
    sim = dg.sim_cap03_8(cs, TAP_MS, True, E, SL, TP)
    assert sim["ok"] and sim["cdc_confirmed_within_8"] is False
    assert sim["reason"] == "abort_cap_stop"
    assert abs(sim["sim_netR"] - (-0.3)) < 0.2            # ~-0.3R menos costos


def test_sin_cdc_peor_que_cap_cierra_a_mercado():
    cs = zigzag_prefix()
    cs.append(candle(8, 101, 101.5, 100.5, 101))
    for k in range(9, 17):
        cs.append(candle(k, 100.5, 101, 99.7, 100.0))     # r_now = -0.5 < cap
    sim = dg.sim_cap03_8(cs, TAP_MS, True, E, SL, TP)
    assert sim["ok"] and sim["reason"] == "abort_mkt"
    assert sim["sim_netR"] < -0.4


def test_sl_dentro_de_la_vela_del_toque_cuenta():
    """El SL tocado en la MISMA vela de activación cuenta (conservador). Sin
    esto, el sim se saltaba la vela del toque y cabalgaba a TPs irreales."""
    cs = zigzag_prefix()
    cs.append(candle(8, 101, 101.5, 98.5, 100.5))         # toque Y barrida del SL
    cs.append(candle(9, 101, 106, 100.8, 105.5))
    cs.append(candle(10, 105.5, 109.5, 105, 109.2))
    sim = dg.sim_cap03_8(cs, TAP_MS, True, E, SL, TP)
    assert sim["ok"] and sim["reason"] == "sl_original"
    assert sim["sim_netR"] < -1.0


def test_tp_en_la_vela_del_toque_no_se_acredita():
    """El TP dentro de la vela del toque NO cuenta (pudo ocurrir antes de la
    activación); debe resolver con velas posteriores."""
    cs = zigzag_prefix()
    cs.append(candle(8, 101, 110, 100.5, 101))            # high 110 > TP en el toque
    for k in range(9, 17):
        cs.append(candle(k, 100.5, 101, 99.7, 100.0))     # luego cae: abort_mkt
    sim = dg.sim_cap03_8(cs, TAP_MS, True, E, SL, TP)
    assert sim["ok"] and sim["reason"] == "abort_mkt", \
        "el TP de la vela del toque no puede acreditarse"


def test_sl_original_antes_de_la_ventana_manda():
    cs = zigzag_prefix()
    cs.append(candle(8, 101, 101.5, 100.5, 101))
    cs.append(candle(9, 100.5, 100.8, 98.5, 98.8))        # toca 99
    sim = dg.sim_cap03_8(cs, TAP_MS, True, E, SL, TP)
    assert sim["ok"] and sim["reason"] == "sl_original"
    assert sim["sim_netR"] < -1.0


def test_no_usa_velas_anteriores_al_toque():
    """Cambiar los PRECIOS previos al toque (sin tocar la estructura de swings
    confirmados) no puede cambiar el resultado: solo importan las velas
    posteriores. Además, velas FUTURAS truncadas => sin_resolucion, no invento."""
    base = zigzag_prefix()
    cs1 = base + [candle(8, 101, 101.5, 100.5, 101),
                  candle(9, 101, 106, 100.8, 105.5),
                  candle(10, 105.5, 109.5, 105, 109.2)]
    cs2 = copy.deepcopy(cs1)
    cs2[0]["o"] = cs2[0]["h"] = cs2[0]["l"] = cs2[0]["c"] = 95.0  # vela 0 distinta
    s1 = dg.sim_cap03_8(cs1, TAP_MS, True, E, SL, TP)
    s2 = dg.sim_cap03_8(cs2, TAP_MS, True, E, SL, TP)
    assert s1["sim_netR"] == s2["sim_netR"] and s1["reason"] == s2["reason"]
    # sin velas posteriores al toque -> sin_datos (jamás resultado inventado)
    s3 = dg.sim_cap03_8(base + [candle(8, 101, 101.5, 100.5, 101)], TAP_MS,
                        True, E, SL, TP)
    assert s3["ok"] is False


def _fake_fetch_factory(cs):
    def _fetch(symbol, tf, start_ms, limit=1000):
        return copy.deepcopy(cs)
    return _fetch


def _setup(ts_act):
    return {"key": "BTC_USDT:1h:long:101", "pair": "BTC_USDT", "dir": "long",
            "poi_tf": "1h", "cdc_tf": "1h", "entry": E, "sl": SL, "tp": TP,
            "rr": 4.0, "status": "activo", "result_r": None,
            "ts_created": ts_act - 100, "ts_activated": ts_act}


def test_diagnose_no_muta_setups_y_marca_research():
    cs = zigzag_prefix() + [candle(8, 101, 101.5, 100.5, 101),
                            candle(9, 101, 106, 100.8, 105.5),
                            candle(10, 105.5, 109.5, 105, 109.2)]
    setups = [_setup(TAP_MS // 1000)]
    antes = copy.deepcopy(setups)
    recs, resumen = dg.diagnose(setups, fetch=_fake_fetch_factory(cs))
    assert setups == antes, "diagnose NO puede mutar los setups"
    assert len(recs) == 1
    r = recs[0]
    assert r["research_only"] is True
    assert r["cdc_post_touch_window_8"] == 8
    assert r["cdc_confirmed_within_8"] is True
    assert isinstance(r["abort_cap03_8_sim_result"], float)
    assert resumen["research_only"] is True
    assert "No es gate" in resumen["nota"] or "no es gate" in resumen["nota"].lower()


def test_salida_separada_y_sin_contacto_con_bot_ni_store():
    """Estructural: el módulo no importa modules.bot, no escribe setups.json,
    y su salida vive en data/diagnostics/ (separada del estado oficial)."""
    src = open(os.path.join(WT, "research", "diario_cdc_diag.py")).read()
    assert "from modules.bot" not in src and "import modules.bot" not in src, \
        "el diagnóstico no puede importar el bot"
    assert "SETUPS_PATH" not in src, "no debe usar la ruta de escritura del store"
    # el único json.dump del módulo escribe en OUT_PATH (data/diagnostics/),
    # nunca sobre el archivo de setups
    assert src.count("json.dump(") == 1 and "OUT_PATH" in src.split("json.dump(")[1][:200]
    assert dg.OUT_PATH.endswith(os.path.join("diagnostics", "cdc_abort_diag.json"))
    assert dg.OUT_PATH != dg.SETUPS_DEFAULT
    assert os.path.basename(os.path.dirname(dg.OUT_PATH)) == "diagnostics"