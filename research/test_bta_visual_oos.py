"""Tests del estudio OOS del modelo visual (research/bta_visual_oos.py).

Correr con:  .venv/bin/python3 -m pytest research/test_bta_visual_oos.py -q
"""
from __future__ import annotations

import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import bta_visual_oos as oos  # noqa: E402

BAR = 900_000


def candle(i, o, h, l, c):
    return {"t": i * BAR, "o": o, "h": h, "l": l, "c": c, "v": 1.0}


def test_resolve_tp_sl_y_conservador():
    cs = [candle(0, 100, 101, 99, 100),
          candle(1, 100, 102, 99.5, 101),
          candle(2, 101, 105, 100.5, 104),   # toca TP 104.5? h=105 sí
          ]
    r, j = oos.resolve(cs, 0, True, 100.0, 98.0, 104.5)
    assert j == 2 and r == (104.5 - 100.0) / 2.0
    # SL primero
    cs2 = [candle(0, 100, 101, 99, 100), candle(1, 100, 100.5, 97.5, 98)]
    r, j = oos.resolve(cs2, 0, True, 100.0, 98.0, 104.0)
    assert r == -1.0 and j == 1
    # ambos en la misma vela => SL (conservador)
    cs3 = [candle(0, 100, 101, 99, 100), candle(1, 100, 105, 97, 100)]
    r, _ = oos.resolve(cs3, 0, True, 100.0, 98.0, 104.0)
    assert r == -1.0, "si SL y TP caen en la misma vela debe contar SL"
    # sin resolución => None
    cs4 = [candle(0, 100, 101, 99, 100), candle(1, 100, 100.5, 99.5, 100)]
    r, j = oos.resolve(cs4, 0, True, 100.0, 98.0, 104.0)
    assert r is None and j is None


def test_netr_descuenta_costos():
    bruto = 2.0
    neto = oos.netR(bruto, entry=100.0, sl=99.0)   # slf = 1%
    assert neto < bruto
    assert abs((bruto - neto) - oos._cost_fraction(True) / 0.01) < 1e-9


def test_sweep_times_causal():
    cs = [candle(0, 100, 101, 99, 100), candle(1, 100, 102, 99.5, 101),
          candle(2, 101, 105, 100.5, 104),   # pivote high 105 en idx=2
          candle(3, 104, 104.5, 102, 103), candle(4, 103, 103.5, 101, 102),
          candle(5, 102, 103, 101, 102),
          candle(6, 102, 106, 101.5, 105.5),  # barre el 105
          ]
    piv = [{"idx": 2, "price": 105, "confirm_idx": 4}]
    sw = oos.sweep_times(cs, piv, "high")
    assert sw[(2, 105)] == 6 * BAR, "debe barrerse en la vela 6 (primer high>105)"
    piv2 = [{"idx": 2, "price": 200, "confirm_idx": 4}]
    assert oos.sweep_times(cs, piv2, "high")[(2, 200)] is None


def test_liquidity_target_respeta_confirm_y_sweep():
    rows = [
        {"price": 110, "side": "high", "confirm_t": 5 * BAR, "swept_t": None},
        {"price": 108, "side": "high", "confirm_t": 20 * BAR, "swept_t": None},  # futuro
        {"price": 106, "side": "high", "confirm_t": 2 * BAR, "swept_t": 8 * BAR},  # barrido
    ]
    # en t=10: el 108 aún no confirma y el 106 ya fue barrido -> target = 110
    assert oos.liquidity_target(rows, True, 100.0, 10 * BAR) == 110
    # en t=6: el 106 sigue vivo (swept_t=8>6) y es el más cercano
    assert oos.liquidity_target(rows, True, 100.0, 6 * BAR) == 106
    # sin candidatos
    assert oos.liquidity_target(rows, True, 120.0, 10 * BAR) is None


def test_last_confirmed_arrays_sin_lookahead():
    cs = [candle(0, 100, 101, 99, 100), candle(1, 100, 102, 99.5, 101),
          candle(2, 101, 105, 100.5, 104),   # swing high 105, confirma en idx=4
          candle(3, 104, 104.5, 102, 103), candle(4, 103, 103.5, 101, 102),
          candle(5, 102, 103, 101, 102)]
    lh, _ = oos.last_confirmed_arrays(cs, 2)
    assert lh[3] is None, "en idx=3 el swing aún no confirma"
    assert lh[4] == 105 and lh[5] == 105


def test_resultados_committeados_con_marca():
    import json
    path = os.path.join(WT, "research", "bta_visual_oos_results.json")
    assert os.path.isfile(path), "falta el JSON; corre research/bta_visual_oos.py"
    d = json.load(open(path))
    assert d["meta"]["research_only"] is True
    assert "NO usar para activar live" in d["meta"]["aviso"]
    for var in ("touch", "cdc_post", "retest_cont"):
        assert d["cortes"][var]["ALL"]["n"] > 0
