#!/usr/bin/env python3
"""Tests de la re-lectura sobre el universo operable.

Lo que se protege es que nadie vuelva a citar un promedio dominado por 15m como si
fuera el resultado del bot. Ya pasó una vez: el informe del 5 de julio concluyó
"15m no tiene edge" y los estudios del 25 volvieron a encabezar con el agregado.
"""
from __future__ import annotations

import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

RESULTS = os.path.join(WT, "research", "universo_operable_results.json")


def _resultados():
    with open(RESULTS, encoding="utf-8") as fh:
        return json.load(fh)


def test_el_detector_del_bot_no_usa_15m():
    """Si esto cambia, toda la re-lectura deja de aplicar y hay que rehacerla."""
    src = open(os.path.join(WT, "modules/trading/smc_live.py"), encoding="utf-8").read()
    assert 'POI_TFS = ["1D", "4h", "1h"]' in src
    assert '"15m"' not in src.split("POI_TFS")[1].split("\n")[0]


def test_1h_gana_en_la_gran_mayoria_de_variantes():
    r = _resultados()["resumen"]
    total = r["de_un_total_de"]
    assert total >= 40, "el barrido perdio estudios; revisar los extractores"
    assert r["variantes_donde_1h_supera_a_15m"] >= 0.85 * total
    # y la asimetria de expectativa positiva es el punto, no el promedio
    assert r["variantes_con_expectativa_positiva_en_1h"] >= 25
    assert r["variantes_con_expectativa_positiva_en_15m"] <= 6


def test_el_filtro_promovido_es_el_mejor_en_el_universo_operable():
    """rr>=5 (LIQ20) es lo unico promovido al plan. Si deja de ser lo mejor en 1h,
    la Fase 1 esta apoyada en otra cosa y hay que saberlo."""
    filas = _resultados()["filas"]
    liq20 = next(f for f in filas
                 if f["estudio"] == "liq_tp" and f["variante"] == "LIQ20")
    assert liq20["1h"]["exp"] > 0.3
    assert liq20["1h"]["exp"] > liq20["15m"]["exp"]
    mejores = [f["1h"]["exp"] for f in filas if f["1h"]]
    assert liq20["1h"]["exp"] == max(mejores)


def test_capar_winners_pierde_en_ambos_timeframes():
    """La unica conclusion que NO dependia del universo: el control de RR fijo 2
    es negativo en 1h y en 15m. Sirve de ancla — si esto se volviera positivo en
    algun corte, el resto de la re-lectura seria sospechosa."""
    filas = _resultados()["filas"]
    rr2 = next(f for f in filas
               if f["estudio"] == "liq_tp" and f["variante"] == "RR2")
    assert rr2["1h"]["exp"] < 0
    assert rr2["15m"]["exp"] < 0


def test_la_correccion_quedo_escrita_en_el_informe_del_iman():
    """El informe del iman afirmaba que nada supera cero. Es falso en el universo
    operable y la correccion tiene que viajar con el documento."""
    txt = open(os.path.join(WT, "research/tp_magnet_study_2026-07-25.md"),
               encoding="utf-8").read()
    assert "CORRECCIÓN" in txt
    assert "universo_operable" in txt


def test_marcado_como_research():
    meta = _resultados()["meta"]
    assert meta["research_only"] is True
    assert meta["execution_enabled"] is False
    assert meta["validated"] is False
