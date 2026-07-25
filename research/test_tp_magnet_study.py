"""Tests del estudio de TP por imán (research)."""
from __future__ import annotations

import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import tp_magnet_study as tm  # noqa: E402

BAR = 3_600_000


def _piv(price, side, confirm_t, swept_t=None):
    return {"price": price, "side": side, "confirm_t": confirm_t, "swept_t": swept_t}


def test_imanes_solo_usa_niveles_visibles_y_no_barridos():
    """Un nivel que aún no confirma, o que ya fue barrido, no es un imán."""
    filas = [
        _piv(101.0, "high", confirm_t=1 * BAR),
        _piv(102.0, "high", confirm_t=50 * BAR),                    # futuro
        _piv(103.0, "high", confirm_t=1 * BAR, swept_t=2 * BAR),    # ya barrido
        _piv(104.0, "high", confirm_t=1 * BAR, swept_t=90 * BAR),   # se barre luego
        _piv(99.0, "low", confirm_t=1 * BAR),                       # otro lado
    ]
    vistos = tm.imanes(filas, True, 100.0, 10 * BAR, 100.0)

    assert vistos == [101.0, 104.0], "solo niveles confirmados, no barridos y arriba"


def test_imanes_respeta_el_radio():
    filas = [_piv(101.0, "high", 1 * BAR), _piv(200.0, "high", 1 * BAR)]
    assert tm.imanes(filas, True, 100.0, 10 * BAR, 100.0) == [101.0], \
        "un nivel a 100% de distancia no es alcanzable"


def test_cluster_prefiere_la_masa_y_ante_empate_lo_cercano():
    """El imán no es un nivel suelto: es donde se acumulan varios."""
    # dos sueltos cerca y un grupo de tres lejos -> gana el grupo de tres
    niveles = [101.0, 105.0, 109.90, 110.0, 110.1]
    centro = tm.cluster_mas_denso(niveles, 100.0)
    assert 109.8 < centro < 110.2

    # empate en cantidad -> gana el más cercano al precio
    empate = [101.0, 101.05, 120.0, 120.1]
    assert tm.cluster_mas_denso(empate, 100.0) < 110

    assert tm.cluster_mas_denso([], 100.0) is None


def test_percentil_alcance_devuelve_una_distancia_plausible():
    velas = [{"h": 100 + (i % 5), "l": 100 - (i % 5), "c": 100.0}
             for i in range(200)]
    d = tm.percentil_alcance(velas, 12, 0.35)

    assert d is not None and 0 < d < 10, "la distancia debe estar en % razonable"


def test_resultados_committeados_con_marca_research():
    import json
    path = os.path.join(WT, "research", "tp_magnet_study_results.json")
    assert os.path.isfile(path), "falta el JSON; corre research/tp_magnet_study.py"
    d = json.load(open(path))
    assert d["meta"]["research_only"] is True
    assert d["meta"]["execution_enabled"] is False
    assert "NO usar para activar live" in d["meta"]["aviso"]
    # la comparación tiene que ser pareada: mismo universo para todas las variantes
    todo = d["cortes"]["TODO"]
    assert todo["lejano|estructural"]["n"] > 1000
    assert todo["fijo_2r|estructural"]["n"] > 1000
