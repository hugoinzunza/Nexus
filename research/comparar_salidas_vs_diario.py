#!/usr/bin/env python3
"""¿Alguna variante de salida del backtest reproduce lo que le pasa al Diario?

Tras corregir el look-ahead de la barra de activación (2026-07-25), la pregunta que
decide la Fase 1 es si el plan de salida que corre en el bot —parciales 50% en 1R,
25% en 2R, break-even tras TP1— suma o resta. Antes no se podía responder: la única
medición de ese plan (`real_vivo`) estaba inflada.

El contraste con la realidad no es el promedio, que con 39 trades no distingue nada.
Es la **tasa de llegada a TP1**: es la métrica que gobierna todo el plan de salida,
porque si no se llega a 1R no se asegura la mitad ni se activa el break-even.

DOS ERRORES QUE COMETÍ ACÁ Y QUE ESTE SCRIPT YA NO COMETE:

1. **Binomial sobre trades.** Daba P = 1,4e-05 y la usé para decir que la brecha era
   decisiva. Es inválida: los 39 trades del Diario caen en **8 días**, y 31 de ellos
   en tres días seguidos. No son observaciones independientes. Lo correcto es
   remuestrear DÍAS, no trades — y ahí el intervalo se ensancha muchísimo.
2. **Comparar `actual` con el resto.** En esa variante no existe TP1: el único tramo
   es el TP lejano, así que su "tasa de acierto" mide otro evento (llegar a ~8,4% de
   distancia, no a 0,80%). Marcarla como "compatible" era comparar peras con manzanas.
   Queda excluida de la comparación y señalada como tal.

Corre:   .venv/bin/python3 research/comparar_salidas_vs_diario.py
Escribe: research/comparar_salidas_vs_diario_results.json
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import statistics as st
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading.setups_store import _cost_fraction  # noqa: E402

DUMP = os.path.join(WT, "data", "setup_backtest_trades.json")
SETUPS = os.path.join(WT, "data", "setups.json")
OUT_JSON = os.path.join(WT, "research", "comparar_salidas_vs_diario_results.json")


def diario():
    """Los trades REALES cerrados del forward-test. Es la vara."""
    with open(SETUPS, encoding="utf-8") as fh:
        rows = json.load(fh)
    rows = rows if isinstance(rows, list) else rows.get("setups", [])
    cerr = [r for r in rows
            if r.get("status") in ("ganada", "perdida")
            and r.get("result_r") is not None and r.get("ts_activated")]
    rs = [r["result_r"] for r in cerr]
    # "llegó a TP1" = terminó con R positivo: con este plan de salida es imposible
    # cerrar en verde sin haber tocado 1R (el primer parcial es lo único que asegura)
    llegaron = [r for r in rs if r > 0]
    por_dia = {}
    for r in cerr:
        d = dt.datetime.utcfromtimestamp(r["ts_activated"]).strftime("%Y-%m-%d")
        por_dia.setdefault(d, []).append(r["result_r"] > 0)
    return {
        "n": len(rs),
        "dias_distintos": len(por_dia),
        "concentracion": sorted((len(v) for v in por_dia.values()), reverse=True),
        "llego_a_tp1_pct": round(100 * len(llegaron) / len(rs), 1) if rs else None,
        "avg_R": round(sum(rs) / len(rs), 3) if rs else None,
        "ganadora_mediana_R": round(st.median(llegaron), 2) if llegaron else None,
        "ganadora_max_R": round(max(llegaron), 2) if llegaron else None,
        "_por_dia": list(por_dia.values()),
    }


def ci_por_dia(por_dia, rng, remuestreos=20000):
    """CI95 de la tasa de llegada a TP1 remuestreando DÍAS, no trades.

    Con 8 días el intervalo sale ancho y su propia cobertura es discutible — pero es
    honesto, y la alternativa (tratar 39 trades clusterizados como independientes)
    produce un p-valor de 1e-05 que no significa nada.
    """
    if len(por_dia) < 3:
        return None
    tasas = []
    for _ in range(remuestreos):
        m = [x for _ in por_dia for x in por_dia[rng.randrange(len(por_dia))]]
        tasas.append(sum(m) / len(m))
    tasas.sort()
    return [round(100 * tasas[int(0.025 * len(tasas))], 1),
            round(100 * tasas[int(0.975 * len(tasas))], 1)]


def backtest():
    with open(DUMP, encoding="utf-8") as fh:
        crudos = json.load(fh)
    t = [x for x in crudos if x.get("status") in ("ganada", "perdida") and x.get("sl_pct")]
    out = {}
    for var in sorted(t[0]["scaled"].keys()):
        rs, netos = [], []
        for x in t:
            r = x["scaled"].get(var)
            if r is None:
                continue
            rs.append(r)
            netos.append(r - _cost_fraction(r > 0) / x["sl_pct"])
        if not rs:
            continue
        g = [r for r in rs if r > 0]
        out[var] = {
            "n": len(rs),
            "llego_a_tp1_pct": round(100 * len(g) / len(rs), 1),
            "avg_R": round(sum(rs) / len(rs), 3),
            "avg_netR": round(sum(netos) / len(netos), 3),
            "ganadora_mediana_R": round(st.median(g), 2) if g else None,
        }
    return out


def main():
    if not os.path.isfile(DUMP):
        print(f"falta {DUMP}: correr `python3 -m modules.trading.run_setup_backtest`")
        return

    rng = random.Random(20260725)
    real = diario()
    bt = backtest()
    ci = ci_por_dia(real.pop("_por_dia"), rng)
    real["ci95_por_dia"] = ci

    for var, d in bt.items():
        if var == "actual":
            # sin TP1: su tasa mide llegar al TP lejano (~8,4%), no a 1R (~0,80%)
            d["comparable"] = False
            d["dentro_del_ci"] = None
            continue
        d["comparable"] = True
        d["dentro_del_ci"] = bool(ci and ci[0] <= d["llego_a_tp1_pct"] <= ci[1])

    salida = {
        "meta": {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "aviso": "Research only - No senal - No bot - NO usar para activar live",
            "pregunta": ("tras corregir el look-ahead de la barra de activacion, "
                         "alguna variante de salida reproduce la realidad del Diario"),
            "vara": "tasa de llegada a TP1, con CI remuestreando DIAS (no trades)",
            "por_que_no_binomial": ("los 39 trades caen en 8 dias y 31 en tres dias "
                                    "seguidos: no son independientes. La binomial "
                                    "daba 1,4e-05 y no significaba nada."),
            "limite": ("con 8 clusters el CI es ancho y su cobertura es discutible; "
                       "esto sugiere, no demuestra"),
        },
        "diario_real": real,
        "backtest": bt,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, indent=1)

    print(f"resultados: {OUT_JSON}\n")
    print(f"DIARIO REAL: n={real['n']} en {real['dias_distintos']} dias "
          f"(concentracion {real['concentracion']})")
    print(f"  llega a TP1 {real['llego_a_tp1_pct']}%  ·  CI95 remuestreando dias: "
          f"{ci[0]}% .. {ci[1]}%")
    print(f"  avg {real['avg_R']:+.3f}R · ganadora mediana "
          f"{real['ganadora_mediana_R']}R (max {real['ganadora_max_R']}R)\n")
    print(f"{'variante':14} {'n':>6} {'a TP1':>7} {'avg netR':>9} {'gana med':>9}   ")
    for var, d in sorted(bt.items(), key=lambda kv: kv[1]["llego_a_tp1_pct"]):
        if not d["comparable"]:
            marca = "(sin TP1: no comparable)"
        else:
            marca = "dentro del CI" if d["dentro_del_ci"] else "FUERA del CI real"
        print(f"{var:14} {d['n']:6} {d['llego_a_tp1_pct']:6.1f}% "
              f"{d['avg_netR']:+9.3f} {str(d['ganadora_mediana_R']):>8}R   {marca}")


if __name__ == "__main__":
    main()
