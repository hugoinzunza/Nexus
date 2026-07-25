#!/usr/bin/env python3
"""El backtest del pipeline REAL del bot, con costos y con el rr que opera el plan.

Los estudios de research detectan POIs sobre una sola serie. El bot no: usa
`smc_live.analyze`, que detecta POIs en 1D/4h/1h y los proyecta sobre una TF de
planeación (1h o 4h). El único backtest que reproduce eso es
`modules/trading/run_setup_backtest.py`, que reusa `smc_live.analyze` tal cual.

Pero sus números publicados no son comparables con nada de research por dos motivos
que hay que decir antes de mirar cualquier tabla:

  1. **No llevan costos.** El `cost_rate` sólo se aplica dentro de `_equity_sim`
     (la curva de capital); `avg_r`, `by_year` y `out_sample` son BRUTOS. Con el
     modelo maker-aware del Diario y la mediana de sl_pct (0,8%), el costo real
     ronda 0,05R por ganadora y 0,11R por perdedora — y en el decil de stops más
     ajustados (0,4%) sube a 0,10R y 0,23R. No es despreciable.
  2. **Miden rr>=2**, porque usan `smc_live.MIN_RR = 2.0`. El plan del Diario opera
     `SELECTIVE_MIN_RR = 5.0`. Son dos estrategias distintas.

Este script no re-corre el backtest: reagrega el volcado por-trade que el propio
`run_setup_backtest` deja en `data/setup_backtest_trades.json`, aplicando los
costos del Diario y separando por rr. Así se puede responder, sobre el universo que
efectivamente corre, la pregunta que quedó abierta: **¿el edge decae?**

El informe del 5-jul dijo que 1h x rr>=5 era DECAYENTE; el walk-forward de
`liq_tp_backtest` dice que las dos ventanas más recientes son las mejores. Los dos
usan pipelines distintos. Éste usa el del bot.

Corre:   .venv/bin/python3 research/universo_alineado.py
Escribe: research/universo_alineado_results.json
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading.setups_store import _cost_fraction  # noqa: E402

DUMP = os.path.join(WT, "data", "setup_backtest_trades.json")
OUT_JSON = os.path.join(WT, "research", "universo_alineado_results.json")
IS_FRAC = 0.70
VENTANAS = 5
# el plan opera 5.0; 2.0 es lo que corrio el backtest; los del medio, para ver forma
CORTES_RR = (2.0, 3.0, 5.0, 8.0)


def netR(t):
    """R neto con el modelo maker-aware del Diario, escalado por el % del stop.

    El costo se paga sobre el nocional, así que en unidades de R pesa MÁS cuando el
    stop es ajustado. Por eso se divide por sl_pct y no se resta un fijo.
    """
    slp = t.get("sl_pct")
    if not slp or slp <= 0:
        return None
    return t["r"] - _cost_fraction(t["r"] > 0) / slp


def bootstrap_bloques(netos, rng, bloque=40, remuestreos=2000):
    """CI del promedio por bloques contiguos.

    Es imprescindible acá y no un adorno: el payoff es de cola tan gorda que el
    promedio lo fijan un puñado de trades. Un CI normal (que asume independencia y
    varianza finita razonable) mentiría; el de bloques al menos respeta que los
    trades vecinos comparten régimen.
    """
    if len(netos) < bloque * 3:
        return None
    bloques = [netos[i:i + bloque] for i in range(0, len(netos), bloque)]
    bloques = [b for b in bloques if b]
    medias = []
    for _ in range(remuestreos):
        muestra = []
        for _ in range(len(bloques)):
            muestra.extend(bloques[rng.randrange(len(bloques))])
        medias.append(sum(muestra) / len(muestra))
    medias.sort()
    return {"ci95": [round(medias[int(0.025 * len(medias))], 3),
                     round(medias[int(0.975 * len(medias))], 3)],
            "cruza_cero": medias[int(0.025 * len(medias))] <= 0}


def sin_la_cola(netos, pct=0.01):
    """Promedio sacando el `pct` superior. Mide de cuánto depende el resultado de
    los pocos runners gigantes: si sin ellos se cae, no es una expectativa, es una
    lotería con sesgo favorable."""
    if not netos:
        return None
    k = max(1, int(len(netos) * pct))
    recortado = sorted(netos)[:-k]
    return round(sum(recortado) / len(recortado), 3) if recortado else None


def agrega(trades):
    if not trades:
        return {"n": 0}
    netos = [t["net"] for t in trades]
    n = len(netos)
    eq = pico = dd = 0.0
    ganancia = perdida = 0.0
    for v in netos:
        eq += v
        pico = max(pico, eq)
        dd = max(dd, pico - eq)
        if v > 0:
            ganancia += v
        else:
            perdida -= v
    return {
        "n": n,
        "win_pct": round(100 * sum(1 for t in trades if t["r"] > 0) / n, 1),
        "avg_netR": round(sum(netos) / n, 3),
        "total_netR": round(sum(netos), 1),
        "pf": round(ganancia / perdida, 2) if perdida > 0 else None,
        "dd_R": round(dd, 1),
        "rr_medio": round(sum(t["rr"] for t in trades) / n, 1),
        "avg_sin_top1pct": sin_la_cola(netos),
        "aporte_del_top1pct_pct": round(
            100 * sum(sorted(netos, reverse=True)[:max(1, n // 100)]) / sum(netos), 0
        ) if sum(netos) > 0 else None,
    }


def main():
    if not os.path.isfile(DUMP):
        print(f"falta {DUMP}\n"
              "Se genera con `python3 -m modules.trading.run_setup_backtest`\n"
              "o se copia del VPS (esta gitignoreado).")
        return

    rng = random.Random(20260725)
    with open(DUMP, encoding="utf-8") as fh:
        crudos = json.load(fh)

    # Sólo lo que realmente se activó: una "anulada" es un setup que el precio nunca
    # tocó, no un trade. Contarlas dilucría cualquier expectativa.
    trades = []
    sin_slpct = 0
    for t in crudos:
        if t.get("status") not in ("ganada", "perdida"):
            continue
        neto = netR(t)
        if neto is None:
            sin_slpct += 1
            continue
        t["net"] = neto
        t["year"] = dt.datetime.utcfromtimestamp(t["t"] / 1000).year
        trades.append(t)
    trades.sort(key=lambda t: t["t"])

    t0, t1 = trades[0]["t"], trades[-1]["t"]
    corte = t0 + IS_FRAC * (t1 - t0)
    for t in trades:
        t["oos"] = t["t"] > corte
    bordes = [t0 + (t1 - t0) * k / VENTANAS for k in range(VENTANAS + 1)]

    def f(ms):
        return dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m")

    salida = {
        "meta": {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "aviso": "Research only - No senal - No bot - NO usar para activar live",
            "pregunta": "el edge decae, sobre el pipeline REAL del bot y con costos",
            "pipeline": ("smc_live.analyze: POIs en 1D/4h/1h proyectados sobre TF de "
                         "planeacion 1h/4h (= lo que corre el Diario y el bot)"),
            "fuente": "data/setup_backtest_trades.json (volcado de run_setup_backtest)",
            "costos": ("maker-aware del Diario (_cost_fraction) dividido por sl_pct; "
                       "el backtest original NO los aplicaba fuera de _equity_sim"),
            "rr_del_backtest_original": 2.0,
            "rr_del_plan": 5.0,
            "activados": len(trades),
            "descartados_sin_sl_pct": sin_slpct,
            "span": [f(t0), f(t1)],
        },
        "por_rr": {},
    }

    for rr_min in CORTES_RR:
        sel = [t for t in trades if t["rr"] >= rr_min]
        bloque = {
            "TODO": {**agrega(sel),
                     "bootstrap": bootstrap_bloques([t["net"] for t in sel], rng)},
            "IS": agrega([t for t in sel if not t["oos"]]),
            "OOS": {**agrega([t for t in sel if t["oos"]]),
                    "bootstrap": bootstrap_bloques(
                        [t["net"] for t in sel if t["oos"]], rng)},
            "por_sel_tf": {tf: agrega([t for t in sel if t["sel_tf"] == tf])
                           for tf in ("1h", "4h")},
            "por_poi_tf": {tf: agrega([t for t in sel if t["poi_tf"] == tf])
                           for tf in ("1h", "4h", "1D")},
            "por_ano": {str(y): agrega([t for t in sel if t["year"] == y])
                        for y in sorted({t["year"] for t in sel})},
            "walk_forward": [
                {"desde": f(bordes[k]), "hasta": f(bordes[k + 1]),
                 **agrega([t for t in sel
                           if bordes[k] <= t["t"] < bordes[k + 1]])}
                for k in range(VENTANAS)
            ],
        }
        salida["por_rr"][str(rr_min)] = bloque

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, indent=1)

    print(f"resultados: {OUT_JSON}")
    m = salida["meta"]
    print(f"{m['activados']} trades activados · span {m['span'][0]} .. {m['span'][1]}")
    print("costos maker-aware aplicados (el backtest original los omitia)\n")

    for rr_min in CORTES_RR:
        b = salida["por_rr"][str(rr_min)]
        d = b["TODO"]
        print(f"=== rr >= {rr_min:g} ===  n={d['n']} avg={d['avg_netR']:+.3f} "
              f"PF={d['pf']} win={d['win_pct']}% rr_medio={d['rr_medio']}")
        for k in ("IS", "OOS"):
            o = b[k]
            print(f"   {k:4} n={o['n']:5} avg={o['avg_netR']:+.3f} PF={o['pf']} "
                  f"DD={o['dd_R']}")
        for tf in ("1h", "4h"):
            o = b["por_sel_tf"][tf]
            if o.get("n"):
                print(f"   sel {tf:3} n={o['n']:5} avg={o['avg_netR']:+.3f} PF={o['pf']}")
        print("   walk-forward:")
        for w in b["walk_forward"]:
            if not w.get("n"):
                continue
            print(f"     {w['desde']} .. {w['hasta']}  n={w['n']:5} "
                  f"avg={w['avg_netR']:+.3f}  PF={w['pf']}")
        print()


if __name__ == "__main__":
    main()
