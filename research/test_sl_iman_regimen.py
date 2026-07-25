#!/usr/bin/env python3
"""Tests del diagnóstico del SL tras-imán.

Lo que se protege acá no es un número, es la validez del argumento: si la
identidad contable no cierra o el placebo no iguala el ancho, la conclusión del
informe deja de estar sostenida por los datos.
"""
from __future__ import annotations

import json
import os
import random
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import sl_iman_regimen as est  # noqa: E402

RESULTS = os.path.join(WT, "research", "sl_iman_regimen_results.json")


def _resultados():
    with open(RESULTS, encoding="utf-8") as fh:
        return json.load(fh)


def test_ensanchar_nunca_convierte_ganador_en_perdedor():
    """El camino de precios es el mismo y el stop nuevo está más lejos, así que
    un TP que se llenaba con el stop estrecho tiene que llenarse con el ancho.
    Si aparece un solo caso, el modelo de resolución tiene un error y toda la
    descomposición rescate/dilución queda sin piso."""
    meta = _resultados()["meta"]
    assert meta["anomalias_ganador_a_perdedor"] == 0


def test_la_identidad_contable_cierra():
    """delta total == rescate + dilucion + ahorro + sin_cambio, exactamente.

    Es la columna vertebral del informe: permite decir "falla porque la dilución
    le gana a los rescates" en vez de "falla". Si no cierra, hay P&L que la
    descomposición no explica.
    """
    datos = _resultados()
    revisados = 0
    for nombre, bloque in datos["cortes"].items():
        for clave, des in bloque.items():
            if not clave.endswith("|desglose"):
                continue
            suma = sum(des["aporte_R"].values())
            assert abs(suma - des["delta_total_R"]) < 0.05, (
                f"{nombre}/{clave}: partes {suma:.2f} != total "
                f"{des['delta_total_R']:.2f}")
            revisados += 1
    assert revisados >= 20


def test_los_excluidos_se_reportan_por_motivo():
    """`descartado_rr` es selección (el ensanche mata el rr) y `sin_resolver` es
    truncamiento de la simulación. Mezclarlos esconde el sesgo de selección."""
    datos = _resultados()
    des = datos["cortes"]["TODO"]["lejano|tras_iman|desglose"]["conteo"]
    assert "descartado_rr" in des
    assert "sin_resolver" in des
    # y no pueden estar contados como si hubieran aportado R
    aporte = datos["cortes"]["TODO"]["lejano|tras_iman|desglose"]["aporte_R"]
    assert aporte.get("descartado_rr", 0.0) == 0.0
    assert aporte.get("sin_resolver", 0.0) == 0.0


def test_el_placebo_conserva_la_distribucion_de_ancho():
    """El placebo tiene que medir UBICACIÓN, no ancho. Si su ensanche promedio
    no iguala al del imán, la comparación mide otra cosa.
    """
    rng = random.Random(1)
    filas = []
    for i in range(200):
        entry, estr = 100.0, 99.0
        # mezcla de setups sin mover y con ensanches variados
        ensanche = 1.0 if i % 4 == 0 else 1.0 + (i % 7) * 0.4
        filas.append({
            "entry": entry, "long": True, "ensanche": ensanche,
            "sl": {"estructural": estr,
                   "tras_iman": entry - (entry - estr) * ensanche},
        })

    movidos = est.asignar_placebo(filas, rng)
    assert movidos == sum(1 for f in filas if f["ensanche"] > 1.0)

    def factores(clave):
        out = []
        for f in filas:
            if f["ensanche"] <= 1.0:
                continue
            out.append((f["entry"] - f["sl"][clave]) / (f["entry"] - f["sl"]["estructural"]))
        return sorted(round(v, 6) for v in out)

    # mismo multiset de ensanches, solo repartido distinto entre setups
    assert factores("placebo") == factores("tras_iman")

    # y los setups que el imán no movió tampoco los mueve el placebo
    for f in filas:
        if f["ensanche"] <= 1.0:
            assert f["sl"]["placebo"] == f["sl"]["estructural"]


def test_el_placebo_no_hereda_los_ceros():
    """Bug evitable: si se barajaran también los factores 1.0, el placebo quedaría
    más estrecho en promedio que el imán y ganaría/perdería por ancho."""
    rng = random.Random(2)
    filas = [{"entry": 100.0, "long": True, "ensanche": 1.0 if i < 90 else 3.0,
              "sl": {"estructural": 99.0}} for i in range(100)]
    est.asignar_placebo(filas, rng)
    movidos = [f for f in filas if f["ensanche"] > 1.0]
    for f in movidos:
        factor = (f["entry"] - f["sl"]["placebo"]) / 1.0
        assert abs(factor - 3.0) < 1e-9


def test_clasificar_etiqueta_las_cuatro_ramas():
    def fila(ensanche, a_gano, b_gano, netR_a, netR_b):
        return {
            "ensanche": ensanche,
            "res": {
                "lejano|estructural": {"netR": netR_a, "gano": a_gano, "rr": 5.0},
                "lejano|tras_iman": {"netR": netR_b, "gano": b_gano, "rr": 4.0},
            },
            "falta": {},
        }

    assert est.clasificar(fila(2.0, False, True, -1.0, 4.0), "lejano",
                          "tras_iman")[0] == "rescate"
    assert est.clasificar(fila(2.0, True, True, 5.0, 4.0), "lejano",
                          "tras_iman")[0] == "dilucion"
    assert est.clasificar(fila(2.0, False, False, -1.0, -0.9), "lejano",
                          "tras_iman")[0] == "ahorro"
    assert est.clasificar(fila(1.0, True, True, 5.0, 5.0), "lejano",
                          "tras_iman")[0] == "sin_cambio"
    # ganador -> perdedor es imposible por construcción; se etiqueta, no se promedia
    assert est.clasificar(fila(2.0, True, False, 5.0, -1.0), "lejano",
                          "tras_iman")[0] == "imposible"


def test_el_signo_del_efecto_sigue_a_la_tasa_de_stopout():
    """El hallazgo central: no es alpha, es régimen. Se fija el umbral observado
    (~87-88% de stop-out) porque de ahí sale la recomendación de NO aplicarlo."""
    reg = _resultados()["regimen"]
    assert reg["spearman_stopout_vs_delta"] >= 0.7
    for p in reg["puntos"]:
        if p["stopout_pct"] < 86.0:
            assert p["delta_avg_R"] < 0, f"{p['corte']} rompe el patron"
        if p["stopout_pct"] > 88.0:
            assert p["delta_avg_R"] > 0, f"{p['corte']} rompe el patron"


def test_en_1h_el_baseline_gana_y_el_iman_resta():
    """El patrón que mata la idea: ayuda donde la estrategia no sirve y estorba
    donde sí sirve. 1h es el único timeframe con baseline positivo."""
    cortes = _resultados()["cortes"]
    base_1h = cortes["tf_1h"]["lejano|estructural"]["avg_netR"]
    iman_1h = cortes["tf_1h"]["lejano|tras_iman"]["avg_netR"]
    assert base_1h > 0
    assert iman_1h < base_1h
    base_15m = cortes["tf_15m"]["lejano|estructural"]["avg_netR"]
    iman_15m = cortes["tf_15m"]["lejano|tras_iman"]["avg_netR"]
    assert base_15m < 0
    assert iman_15m > base_15m


def test_marcado_como_research():
    meta = _resultados()["meta"]
    assert meta["research_only"] is True
    assert meta["execution_enabled"] is False
    assert meta["validated"] is False
