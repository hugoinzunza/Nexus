#!/usr/bin/env python3
"""Tests del contraste backtest vs Diario.

Protegen dos errores estadísticos que cometí el 2026-07-25 y que son fáciles de
repetir porque los dos producen números que se ven convincentes.
"""
from __future__ import annotations

import json
import os
import random
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import comparar_salidas_vs_diario as cmp  # noqa: E402

RESULTS = os.path.join(WT, "research", "comparar_salidas_vs_diario_results.json")


def _resultados():
    with open(RESULTS, encoding="utf-8") as fh:
        return json.load(fh)


def test_el_ci_remuestrea_dias_no_trades():
    """Con trades agrupados, remuestrear trades finge independencia y estrecha el
    intervalo hasta volverlo mentira. El de días tiene que salir MUCHO más ancho.
    """
    rng = random.Random(1)
    # 40 observaciones en 4 dias: dentro de cada dia el resultado es casi el mismo,
    # que es exactamente la forma que tienen los datos del Diario
    por_dia = [[True] * 10, [False] * 10, [False] * 10, [True] * 10]
    ci = cmp.ci_por_dia(por_dia, rng)
    ancho_dias = ci[1] - ci[0]

    planas = [x for d in por_dia for x in d]
    tasas = []
    for _ in range(4000):
        m = [planas[rng.randrange(len(planas))] for _ in planas]
        tasas.append(100 * sum(m) / len(m))
    tasas.sort()
    ancho_trades = tasas[int(.975 * len(tasas))] - tasas[int(.025 * len(tasas))]

    assert ancho_dias > 2 * ancho_trades, (
        f"el CI por dias ({ancho_dias:.0f}) deberia ser mucho mas ancho que el de "
        f"trades ({ancho_trades:.0f}); si no, no esta capturando el agrupamiento")


def test_ci_por_dia_necesita_clusters_suficientes():
    assert cmp.ci_por_dia([[True], [False]], random.Random(2)) is None


def test_la_variante_sin_tp1_queda_excluida():
    """`actual` no tiene primer parcial: su tasa mide llegar al TP lejano (~8,4% de
    distancia), no a 1R (~0,80%). Compararla era comparar otro evento."""
    bt = _resultados()["backtest"]
    assert bt["actual"]["comparable"] is False
    assert bt["actual"]["dentro_del_ci"] is None
    for var in ("real_vivo", "tu_idea", "runner_agres", "be_tardio"):
        assert bt[var]["comparable"] is True


def test_queda_registrado_que_los_trades_del_diario_estan_agrupados():
    """El dato que invalida cualquier binomial sobre estos 39 trades."""
    real = _resultados()["diario_real"]
    assert real["dias_distintos"] <= 12
    # el dia mas cargado concentra una fraccion enorme de la muestra
    assert max(real["concentracion"]) / real["n"] > 0.25
    meta = _resultados()["meta"]
    assert "no son independientes" in meta["por_que_no_binomial"]
    assert "sugiere, no demuestra" in meta["limite"]


def test_el_plan_del_bot_sigue_fuera_del_intervalo_real():
    """Es el hallazgo vivo: el fix del look-ahead redujo el sesgo pero no cerró la
    brecha, asi que queda una segunda fuente de optimismo sin encontrar."""
    d = _resultados()
    assert d["backtest"]["real_vivo"]["dentro_del_ci"] is False
    lo, hi = d["diario_real"]["ci95_por_dia"]
    assert lo < d["diario_real"]["llego_a_tp1_pct"] < hi
    assert d["backtest"]["real_vivo"]["llego_a_tp1_pct"] > hi


def test_marcado_como_research():
    meta = _resultados()["meta"]
    assert meta["research_only"] is True
    assert meta["execution_enabled"] is False
    assert meta["validated"] is False


def test_los_cerrados_del_diario_usan_la_misma_regla_de_entrada_que_el_backtest():
    """Refuta la hipotesis del llenado. Si esto cambiara -si el grueso de los
    cerrados pasara a `midpoint_touch_v2`- la comparacion dejaria de ser
    apples-to-apples y habria que rehacerla, porque el backtest usa V1.
    """
    with open(os.path.join(WT, "data/setups.json"), encoding="utf-8") as fh:
        rows = json.load(fh)
    cerr = [r for r in rows
            if r.get("status") in ("ganada", "perdida") and r.get("result_r") is not None]
    v1 = [r for r in cerr if not r.get("entry_model")]
    assert len(v1) / len(cerr) > 0.8, (
        "el grueso de los cerrados ya no es V1: la comparacion contra el backtest "
        "(que activa por toque de zona) hay que rehacerla")
    g = [r for r in v1 if r["result_r"] > 0]
    # misma regla de entrada y aun asi la mitad de la tasa del backtest
    assert 0.25 < len(g) / len(v1) < 0.50
