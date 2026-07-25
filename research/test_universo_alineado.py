#!/usr/bin/env python3
"""Fija el look-ahead de la barra de activación encontrado el 2026-07-25.

`_resolve` marca `act_idx` en la barra que ENTRA a la zona y `_simulate_scaled`
recorre `range(act_idx, end)`, incluyéndola con su máximo y su mínimo completos.
Para un long, activarse significa que el MÍNIMO bajó a la zona — pero el MÁXIMO de
esa misma barra pudo ocurrir antes, mientras el precio venía cayendo. Contarlo como
TP1 lleno es mirar hacia atrás.

Pega justo en los tramos parciales porque TP1 está a 1R (~0,8% con el sl_pct
mediano), una distancia que el rango de una barra de 1h o 4h cubre casi siempre; el
TP lejano (rr mediano 9,9) casi nunca se llena intrabarra, por eso la ruta de TP
completo no está afectada.

Estos tests documentan el comportamiento ACTUAL. Cuando se corrija el arranque a
`act_idx + 1`, van a fallar: eso es intencional, obliga a actualizar el informe y a
re-correr el backtest en vez de que el cambio pase inadvertido.
"""
from __future__ import annotations

import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading.run_setup_backtest import _simulate_scaled  # noqa: E402

RESULTS = os.path.join(WT, "research", "universo_alineado_results.json")
# TP1 1R/50%, TP2 2R/25%, break-even tras TP1 (= setups_store.PARTIAL_LEGS)
LEGS, BE, TRAIL = [(1.0, 0.5), (2.0, 0.25)], 1, 1.0
SETUP = {"dir": "long", "entry": 100.0, "sl": 99.0, "tp": 110.0, "rr": 10.0}


def test_la_barra_de_activacion_regala_medio_R():
    """El caso reproducible: el máximo ya había pasado cuando se entró."""
    # activación: el mínimo (99,5) entra a la zona; el máximo (101,5) fue antes
    sel = [{"h": 101.5, "l": 99.5}, {"h": 99.6, "l": 98.9}]

    contando_la_barra = _simulate_scaled(SETUP, sel, 0, len(sel), LEGS, BE, TRAIL)
    desde_la_siguiente = _simulate_scaled(SETUP, sel, 1, len(sel), LEGS, BE, TRAIL)

    assert contando_la_barra == 0.5, "hoy cobra TP1 con un maximo previo a la entrada"
    assert desde_la_siguiente == -1.0, "sin ese maximo, el trade muere en el stop"
    assert contando_la_barra - desde_la_siguiente == 1.5


def test_la_ruta_de_tp_completo_no_esta_afectada():
    """El TP lejano casi nunca cae dentro de la barra de activación, así que la
    variante `actual` (y su walk-forward) siguen siendo utilizables."""
    solo_far = [("far", 1.0)]
    sel = [{"h": 101.5, "l": 99.5}, {"h": 99.6, "l": 98.9}]
    a = _simulate_scaled(SETUP, sel, 0, len(sel), solo_far, 99)
    b = _simulate_scaled(SETUP, sel, 1, len(sel), solo_far, 99)
    assert a == b == -1.0


def test_el_stop_sigue_pegando_antes_que_el_tp_en_la_misma_barra():
    """La regla conservadora SI existe — mi primera sospecha estaba equivocada y
    conviene que quede fijada para no volver a acusarla."""
    # barra que toca TP1 (101) y tambien el stop (99): debe ganar el stop
    sel = [{"h": 101.5, "l": 98.5}]
    r = _simulate_scaled(SETUP, sel, 0, len(sel), LEGS, BE, TRAIL)
    assert r == -1.0


def test_el_informe_declara_que_real_vivo_quedo_invalido():
    """`real_vivo` es la unica variante que modela el plan que corre en el bot. Si
    el informe deja de decir que esta invalidado, alguien va a volver a citarlo."""
    txt = open(os.path.join(WT, "research/universo_alineado_2026-07-25.md"),
               encoding="utf-8").read()
    assert "real_vivo" in txt and "Inválido" in txt
    assert "act_idx + 1" in txt, "el paso siguiente concreto debe quedar escrito"


def test_marcado_como_research():
    with open(RESULTS, encoding="utf-8") as fh:
        meta = json.load(fh)["meta"]
    assert meta["research_only"] is True
    assert meta["execution_enabled"] is False
    assert meta["validated"] is False
