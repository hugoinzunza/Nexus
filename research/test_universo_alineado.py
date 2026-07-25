#!/usr/bin/env python3
"""Candado del look-ahead de la barra de activación (encontrado y corregido 2026-07-25).

`_resolve` marca `act_idx` en la barra que ENTRA a la zona. `_simulate_scaled` recorría
`range(act_idx, end)`, incluyéndola con su máximo completo. Para un long, activarse
significa que el MÍNIMO bajó a la zona — pero el MÁXIMO de esa misma barra pudo ocurrir
antes, mientras el precio venía cayendo. Contarlo como TP1 lleno era mirar hacia atrás.

Pegaba justo en los tramos parciales porque TP1 está a 1R (~0,8% con el sl_pct mediano),
distancia que el rango de una barra de 1h o 4h cubre casi siempre; el TP lejano
(rr mediano 9,9) casi nunca se llena intrabarra, así que la ruta de TP completo no
estaba afectada.

Estos tests fijan el comportamiento CORREGIDO. Si alguien vuelve a incluir la barra de
activación, el primero falla.
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


def test_no_se_cobra_TP1_con_un_maximo_previo_a_la_entrada():
    """El caso que destapó el sesgo: el máximo ya había pasado cuando se entró.

    Con `act_idx=0` el simulador debe IGNORAR esa barra y resolver con la siguiente,
    que va al stop. Si vuelve a dar +0,5 es que alguien reintrodujo el look-ahead.
    """
    # activación: el mínimo (99,5) entra a la zona; el máximo (101,5) fue antes
    sel = [{"h": 101.5, "l": 99.5}, {"h": 99.6, "l": 98.9}]

    assert _simulate_scaled(SETUP, sel, 0, len(sel), LEGS, BE, TRAIL) == -1.0

    # y el TP1 sí se cobra cuando el máximo ocurre en una barra POSTERIOR
    sel_ok = [{"h": 99.9, "l": 99.5}, {"h": 101.5, "l": 99.6}, {"h": 99.7, "l": 98.9}]
    assert _simulate_scaled(SETUP, sel_ok, 0, len(sel_ok), LEGS, BE, TRAIL) == 0.5


def test_el_sesgo_medido_era_de_1_5R_por_trade():
    """Deja constancia del tamaño del error, que es lo que justifica haber
    invalidado la medición del plan en vivo y re-corrido el backtest."""
    sel = [{"h": 101.5, "l": 99.5}, {"h": 99.6, "l": 98.9}]
    # act_idx = -1 hace que el recorrido arranque en la barra 0, o sea reproduce el
    # comportamiento viejo (incluir la barra de activación) sin revivir el bug
    con_sesgo = _simulate_scaled(SETUP, sel, -1, len(sel), LEGS, BE, TRAIL)
    sin_sesgo = _simulate_scaled(SETUP, sel, 0, len(sel), LEGS, BE, TRAIL)
    assert con_sesgo == 0.5 and sin_sesgo == -1.0
    assert con_sesgo - sin_sesgo == 1.5


def test_la_ruta_de_tp_completo_no_estaba_afectada():
    """Por eso la variante `actual` y su walk-forward siguieron siendo utilizables:
    el TP lejano (aca 110, rr=10) no cabe en el rango de la barra de activacion, asi
    que incluirla o no daba lo mismo."""
    solo_far = [("far", 1.0)]
    sel = [{"h": 101.5, "l": 99.5, "c": 100.0}, {"h": 99.6, "l": 98.9, "c": 99.0}]
    # con la barra de activacion incluida (comportamiento viejo) y sin ella: igual
    assert _simulate_scaled(SETUP, sel, -1, len(sel), solo_far, 99) == -1.0
    assert _simulate_scaled(SETUP, sel, 0, len(sel), solo_far, 99) == -1.0


def test_el_stop_sigue_pegando_antes_que_el_tp_en_la_misma_barra():
    """La regla conservadora SI existe — mi primera sospecha sobre el origen del
    sesgo estaba equivocada y conviene dejarlo fijado para no volver a acusarla."""
    sel = [
        {"h": 99.9, "l": 99.5, "c": 99.8},      # activacion, sin nada
        {"h": 101.5, "l": 98.5, "c": 99.0},     # toca TP1 (101) Y el stop (99)
    ]
    assert _simulate_scaled(SETUP, sel, 0, len(sel), LEGS, BE, TRAIL) == -1.0


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
