"""Tests del estudio abort-si-no-CDC (research/bta_visual_abort.py).

Correr con:  .venv/bin/python3 -m pytest research/test_bta_visual_abort.py -q
"""
from __future__ import annotations

import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import bta_visual_abort as ab  # noqa: E402

BAR = 900_000


def candle(i, o, h, l, c):
    return {"t": i * BAR, "o": o, "h": h, "l": l, "c": c, "v": 1.0}


# escenario base: long, entry=100, stop=98 (risk=2), tp=108 (rr=4)
E, SL, TP = 100.0, 98.0, 108.0


def _cs(closes_hl):
    """velas desde (h,l,c) empezando en i=1 (i=0 es la vela del toque)."""
    cs = [candle(0, 100, 100.5, 99.5, 100)]
    for k, (h, l, c) in enumerate(closes_hl):
        cs.append(candle(k + 1, c, h, l, c))
    return cs


def test_cdc_dentro_de_ventana_mantiene_plan_original():
    # CDC en la vela 2; el precio luego va al TP
    cs = _cs([(101, 99.5, 100.5), (102, 100, 101.5), (105, 101, 104), (109, 103, 108.5)])
    r = ab.sim_trade(cs, 0, True, E, SL, TP, i_cdc=2, N=4, mode="mkt")
    assert r == (TP - E) / 2.0, "con CDC a tiempo, manda el plan original"


def test_sin_cdc_mkt_cierra_en_vela_n():
    # sin CDC; en la vela 4 el close es 101 -> r = +0.5
    cs = _cs([(101, 99.5, 100.5), (101, 99.5, 100.2), (101, 99.5, 100.8),
              (101.5, 100, 101.0), (109, 103, 108.5)])
    r = ab.sim_trade(cs, 0, True, E, SL, TP, i_cdc=None, N=4, mode="mkt")
    assert abs(r - 0.5) < 1e-9, "mkt debe salir al close de la vela N (+0.5R)"


def test_sin_cdc_be_favorable_deja_correr_con_stop_en_entrada():
    # favorable en la vela N (close 101) -> stop a BE; luego toca 100 -> sale a 0R
    cs = _cs([(101, 99.5, 100.5), (101, 99.5, 100.2), (101, 99.5, 100.8),
              (101.5, 100.2, 101.0), (101, 99.9, 100.5)])
    r = ab.sim_trade(cs, 0, True, E, SL, TP, i_cdc=None, N=4, mode="be")
    assert r == 0.0, "BE: al volver a la entrada sale en 0R"
    # y si en vez de volver, va al TP, gana completo
    cs2 = _cs([(101, 99.5, 100.5), (101, 99.5, 100.2), (101, 99.5, 100.8),
               (101.5, 100.2, 101.0), (109, 100.5, 108.5)])
    r2 = ab.sim_trade(cs2, 0, True, E, SL, TP, i_cdc=None, N=4, mode="be")
    assert r2 == (TP - E) / 2.0


def test_sin_cdc_be_desfavorable_cierra_a_mercado():
    cs = _cs([(101, 99.5, 100.5), (100.5, 99, 99.5), (100.5, 99, 99.4),
              (100.5, 99, 99.0), (109, 103, 108.5)])
    r = ab.sim_trade(cs, 0, True, E, SL, TP, i_cdc=None, N=4, mode="be")
    assert abs(r - (-0.5)) < 1e-9, "BE desfavorable: cierre a mercado (-0.5R)"


def test_sin_cdc_cap03_apreta_el_stop():
    # favorable en la vela N -> stop a -0.3R (99.4); luego lo toca
    cs = _cs([(101, 99.5, 100.5), (101, 99.5, 100.2), (101, 99.5, 100.8),
              (101.5, 100, 101.0), (101, 99.3, 100.0)])
    r = ab.sim_trade(cs, 0, True, E, SL, TP, i_cdc=None, N=4, mode="cap03")
    assert abs(r - ab.CAP_R) < 1e-9, "cap03: sale en -0.3R al tocar el stop apretado"


def test_sl_original_antes_de_la_ventana_manda():
    cs = _cs([(101, 99.5, 100.5), (100, 97.5, 98.5)])   # toca 98 en la vela 2
    r = ab.sim_trade(cs, 0, True, E, SL, TP, i_cdc=None, N=4, mode="mkt")
    assert r == -1.0, "el SL original toca antes de la vela N: manda el original"


def test_resultados_committeados_con_marca():
    import json
    path = os.path.join(WT, "research", "bta_visual_abort_results.json")
    assert os.path.isfile(path), "falta el JSON; corre research/bta_visual_abort.py"
    d = json.load(open(path))
    assert d["meta"]["research_only"] is True
    assert "NO usar para activar live" in d["meta"]["aviso"]
    assert d["cortes"]["ALL"]["base"]["n"] > 0
    assert d["cortes"]["OOS"]["cap03_8"]["n"] > 0
    assert "winners_destruidos" in d
