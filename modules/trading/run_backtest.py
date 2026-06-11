"""Laboratorio de estrategias (Fase 2).

Prueba SISTEMÁTICAMENTE varias familias de estrategias sobre muchos pares y deja
pasar solo las que tengan edge robusto FUERA DE MUESTRA. Para cada estrategia:

  1. Corre toda su grilla de parámetros sobre cada par/timeframe.
  2. Combina los trades, divide IN-SAMPLE (70% antiguo) / OUT-OF-SAMPLE (30%),
     y optimiza los parámetros SOLO en in-sample.
  3. Reporta in-sample vs out-of-sample por separado + walk-forward anclado.
  4. Marca como NO confiable lo que tenga poca muestra OOS (<30 trades).

Produce un RANKING ordenado por desempeño OUT-OF-SAMPLE (no in-sample) y un
veredicto honesto: qué estrategia(s), si alguna, superan el umbral de robustez.
Comisiones (0.05%/lado) y slippage (0.02%) incluidos.

Guarda `backtest_results.json` (commiteado) y lo imprime.
Uso:  python3 -m modules.trading.run_backtest
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.trading import binance, smc, strategies
from modules.trading.backtest import metrics, equity_curve
from modules.trading.strategies import STRATEGIES, describe

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
DATA_DIR = os.path.join(ROOT, "data")

# Timeframe superior inmediato (para la estructura SMC) y la lista de TF superiores
# para la confluencia multi-temporalidad (estrategia B). Todo con velas YA cerradas.
HTF = {"15m": "1h", "1h": "4h", "4h": "1d"}
HTF_OF = {"15m": ["1h", "4h"], "1h": ["4h", "1d"], "4h": ["1d"]}


def _have_tf(tf):
    return all(os.path.isfile(os.path.join(DATA_DIR, f"klines_{s}_{tf}.json")) for s in PAIRS)


# 1h y 4h sí o sí (donde opera Hugo); 15m solo si la data está descargada.
TIMEFRAMES = (["15m"] if _have_tf("15m") else []) + ["1h", "4h"]
ALL_TFS = sorted(set(TIMEFRAMES) | {h for t in TIMEFRAMES for h in HTF_OF[t]})

YEARS = 4.0
IS_FRACTION = 0.70
MIN_TRADES_OPT = 40
MIN_OOS_TRADES = 30          # umbral de muestra para confiar
MIN_OOS_PF = 1.1             # umbral de robustez
RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_results.json")


def _json_safe(obj):
    """Reemplaza Infinity / -Infinity / NaN por None de forma recursiva para que
    el JSON sea válido y el navegador pueda parsearlo (JSON.parse no acepta inf)."""
    import math
    if isinstance(obj, float):
        return None if (math.isinf(obj) or math.isnan(obj)) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def log(m):
    print(m, flush=True)


def gmt(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def window(trades, lo, hi):
    return [t for t in trades if lo <= t["entry_time"] < hi]


def pick_best(by_cfg, lo, hi, min_trades=MIN_TRADES_OPT):
    """Mejor índice de config por expectativa en la ventana, con mínimo de trades."""
    for thresh in (min_trades, 20, 1):
        cand = []
        for ci, trades in by_cfg.items():
            m = metrics(window(trades, lo, hi))
            if m["trades"] >= thresh:
                cand.append((ci, m))
        if cand:
            cand.sort(key=lambda x: (x[1]["expectancy_R"], x[1]["total_R"]), reverse=True)
            return cand[0][0]
    return None


def main():
    # 1) Cargar TODOS los timeframes (base + superiores) y precomputar HTF.
    allseries = {}
    for sym in PAIRS:
        for tf in ALL_TFS:
            allseries[(sym, tf)] = binance.fetch_klines(sym, tf, years=YEARS, data_dir=DATA_DIR, log=log)

    series, htf_dir, htf_series, coverage = {}, {}, {}, []
    for sym in PAIRS:
        for tf in TIMEFRAMES:
            c = allseries[(sym, tf)]
            series[(sym, tf)] = c
            coverage.append({"symbol": sym, "timeframe": tf, "bars": len(c),
                             "from": gmt(c[0]["t"]), "to": gmt(c[-1]["t"])})
            # Estructura del TF superior inmediato (para SMC), con velas ya cerradas.
            hc = allseries[(sym, HTF[tf])]
            hd = smc.structure_direction(hc, lookback=2)
            htf_dir[(sym, tf)] = smc.map_htf_direction(c, hc, hd, binance.INTERVAL_MS[HTF[tf]])
            # Series de los TF superiores (para la confluencia MTF de la estrategia B).
            htf_series[(sym, tf)] = {h: allseries[(sym, h)] for h in HTF_OF[tf]}

    t0 = min(series[(s, t)][0]["t"] for s in PAIRS for t in TIMEFRAMES)
    t1 = max(series[(s, t)][-1]["t"] for s in PAIRS for t in TIMEFRAMES)
    split = t0 + int(IS_FRACTION * (t1 - t0))
    span = t1 - t0
    qs = [t0 + int(span * f) for f in (0.25, 0.5, 0.75)] + [t1 + 1]

    log(f"\nProbando {len(STRATEGIES)} estrategias × {len(PAIRS)} pares × {len(TIMEFRAMES)} TF…")

    ranking = []
    best_combos = []
    equity_best = []

    for strat in STRATEGIES:
        grid = strat["grid"]
        # combined[ci] = trades de esa config en TODOS los pares/timeframes
        combined = {ci: [] for ci in range(len(grid))}
        per_ds = {}  # (sym,tf) -> {ci: trades}
        for sym in PAIRS:
            for tf in TIMEFRAMES:
                ctx = {"symbol": sym, "timeframe": tf, "htf_dir": htf_dir[(sym, tf)],
                       "htf": htf_series[(sym, tf)]}
                ds = {}
                for ci, params in enumerate(grid):
                    tr = strat["run"](series[(sym, tf)], params, ctx)
                    ds[ci] = tr
                    combined[ci].extend(tr)
                per_ds[(sym, tf)] = ds

        # Mejor config combinada, optimizada SOLO en in-sample.
        best_ci = pick_best(combined, t0, split)
        if best_ci is None:
            continue
        bt = combined[best_ci]
        is_m = metrics(window(bt, t0, split))
        oos_m = metrics(window(bt, split, t1 + 1))
        full_m = metrics(bt)

        # Walk-forward (config re-optimizada por ventana).
        wfo_oos = []
        for i in range(3):
            ci = pick_best(combined, t0, qs[i])
            if ci is None:
                continue
            wfo_oos.extend(window(combined[ci], qs[i], qs[i + 1]))
        wfo_m = metrics(wfo_oos)

        confident = oos_m["trades"] >= MIN_OOS_TRADES
        # Robustez exigente: rentable en AMBAS ventanas (in-sample Y out-of-sample),
        # PF OOS ≥ umbral, muestra suficiente y walk-forward positivo. Pedir IS>0
        # evita premiar configs que solo "brillan" en el período OOS por régimen.
        robust = (confident and is_m["expectancy_R"] > 0 and oos_m["expectancy_R"] > 0
                  and oos_m["profit_factor"] >= MIN_OOS_PF
                  and wfo_m["trades"] >= MIN_OOS_TRADES and wfo_m["expectancy_R"] > 0)

        ranking.append({
            "key": strat["key"], "name": strat["name"], "family": strat["family"],
            "label": describe(strat["key"], grid[best_ci]),
            "config": grid[best_ci],
            "in_sample": is_m, "out_sample": oos_m, "full": full_m, "wfo_oos": wfo_m,
            "confident": confident, "robust": robust,
        })

        # Mejor combo por par/timeframe (diagnóstico).
        for sym in PAIRS:
            for tf in TIMEFRAMES:
                ds = per_ds[(sym, tf)]
                ci = pick_best(ds, t0, split, min_trades=15)
                if ci is None:
                    continue
                tr = ds[ci]
                o = metrics(window(tr, split, t1 + 1))
                best_combos.append({
                    "strategy": strat["name"], "key": strat["key"],
                    "symbol": sym, "timeframe": tf,
                    "label": describe(strat["key"], grid[ci]),
                    "in_sample": metrics(window(tr, t0, split)), "out_sample": o,
                })

    # Ranking por OOS (expectativa, luego PF).
    ranking.sort(key=lambda r: (r["out_sample"]["expectancy_R"],
                                r["out_sample"]["profit_factor"]), reverse=True)
    best_combos.sort(key=lambda r: (r["out_sample"]["expectancy_R"],
                                    r["out_sample"]["profit_factor"]), reverse=True)

    # Equity OOS de la estrategia top (si hay).
    if ranking:
        top = ranking[0]
        # Reconstruimos sus trades OOS combinados.
        # (recalcular es barato; usamos la config ganadora)
        equity_best = _equity_for(top, series, htf_dir, split, t1)

    winners = [r for r in ranking if r["robust"]]
    verdict = {
        "any_robust": bool(winners),
        "winners": [{"name": w["name"], "label": w["label"],
                     "oos_expectancy": w["out_sample"]["expectancy_R"],
                     "oos_pf": w["out_sample"]["profit_factor"],
                     "oos_trades": w["out_sample"]["trades"]} for w in winners],
        "text": _verdict(ranking, winners, best_combos),
    }

    results = {
        "generated_at_ms": int(time.time() * 1000),
        "phase": "2",
        "costs": {"commission_per_side": 0.0005, "slippage": 0.0002},
        "data": coverage,
        "pairs": PAIRS, "timeframes": TIMEFRAMES,
        "split": {"is_fraction": IS_FRACTION, "is_until": gmt(split), "oos_from": gmt(split)},
        "robustness_rule": {"min_oos_trades": MIN_OOS_TRADES, "min_pf": MIN_OOS_PF,
                            "rule": "expectativa>0 in-sample Y out-of-sample, PF OOS≥1.1, "
                                    "≥30 trades OOS y walk-forward>0"},
        "ranking": ranking,
        "best_combos": best_combos[:12],
        "equity_best": equity_best,
        "verdict": verdict,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as fh:
        # allow_nan=False + saneo: Infinity/NaN no son JSON válido para el navegador
        # (JSON.parse falla). Convertimos a null; el frontend ya lo muestra como "∞".
        json.dump(_json_safe(results), fh, ensure_ascii=False, allow_nan=False)

    _print(results)
    log(f"\n💾 Guardado en {RESULTS_PATH}\n   Vista web: /m/trading/backtest")


def _equity_for(top, series, htf_dir, split, t1):
    strat = next(s for s in STRATEGIES if s["key"] == top["key"])
    allt = []
    for sym in PAIRS:
        for tf in TIMEFRAMES:
            ctx = {"symbol": sym, "timeframe": tf, "htf_dir": htf_dir[(sym, tf)]}
            allt.extend(strat["run"](series[(sym, tf)], top["config"], ctx))
    oos = [t for t in allt if split <= t["entry_time"] < t1 + 1]
    return equity_curve(oos)


def _verdict(ranking, winners, best_combos):
    if not ranking:
        return "No se pudo evaluar ninguna estrategia (datos insuficientes)."
    top = ranking[0]
    if winners:
        names = ", ".join(w["name"] for w in winners)
        return (f"{len(winners)} estrategia(s) superan el umbral de robustez fuera de muestra: "
                f"{names}. La mejor es {top['name']} ({top['label']}): expectativa OOS "
                f"{top['out_sample']['expectancy_R']}R, PF {top['out_sample']['profit_factor']}, "
                f"{top['out_sample']['trades']} trades; walk-forward {top['wfo_oos']['expectancy_R']}R. "
                "Edge modesto y sensible a costos: tratar como hipótesis, no como certeza.")
    # Nadie pasa: buscamos lo menos malo y lo decimos claro.
    promising = [c for c in best_combos
                 if c["out_sample"]["trades"] >= 15 and c["out_sample"]["expectancy_R"] > 0.1
                 and c["out_sample"]["profit_factor"] >= 1.2]
    extra = ""
    if promising:
        b = promising[0]
        extra = (f" El combo más prometedor (no concluyente por muestra) es "
                 f"{b['strategy']} en {b['symbol']} {b['timeframe']}: "
                 f"{b['out_sample']['expectancy_R']}R, PF {b['out_sample']['profit_factor']} "
                 f"en {b['out_sample']['trades']} trades OOS.")
    why = ""
    if top["out_sample"]["expectancy_R"] > 0 and top["in_sample"]["expectancy_R"] <= 0:
        why = (f" Ojo: {top['name']} tiene la mejor expectativa OOS "
               f"({top['out_sample']['expectancy_R']}R) pero su in-sample es negativo "
               f"({top['in_sample']['expectancy_R']}R) y su walk-forward es ~0 "
               f"({top['wfo_oos']['expectancy_R']}R): la ganancia OOS es casi seguro régimen del "
               "período reciente, no un edge estable. Por eso no califica.")
    return ("NINGUNA estrategia supera el umbral de robustez (rentable en in-sample Y "
            "out-of-sample, PF≥1.1, muestra suficiente y walk-forward>0). Conclusión honesta: "
            "sobre este universo de 7 pares y con estos costos, no hay edge mecánico demostrable "
            "que generalice. No conectar señales en vivo." + why + extra)


def _pf(v):
    return "∞" if v == float("inf") else v


def _row(m):
    return (f"trades={m['trades']:<5} win={m['win_rate']}%  exp={m['expectancy_R']}R  "
            f"PF={_pf(m['profit_factor'])}  DD={m['max_drawdown_R']}R")


def _print(r):
    line = "─" * 74
    log("\n" + line)
    log("  LABORATORIO DE ESTRATEGIAS · Fase 2")
    log(line)
    log(f"  Costos: comisión 0.05%/lado, slippage 0.02% · {len(r['pairs'])} pares × "
        f"{len(r['timeframes'])} TF · {len(r['ranking'])} estrategias")
    log(f"  Umbral robustez: {r['robustness_rule']['rule']}")
    log(f"  Corte: in-sample hasta {r['split']['is_until']} · OOS desde ahí "
        f"({r['data'][0]['from']} → {r['data'][0]['to']})")

    log("\n  RANKING POR OUT-OF-SAMPLE (expectativa R):")
    log(f"    {'#':<3}{'estrategia':<26}{'IS exp':>8}{'OOS exp':>9}{'OOS PF':>8}"
        f"{'OOS n':>7}{'WFO exp':>9}  robusto")
    for idx, s in enumerate(r["ranking"], 1):
        flag = "✅" if s["robust"] else ("·" if s["confident"] else "⚠ pocos")
        log(f"    {idx:<3}{s['name'][:25]:<26}{s['in_sample']['expectancy_R']:>8}"
            f"{s['out_sample']['expectancy_R']:>9}{_pf(s['out_sample']['profit_factor']):>8}"
            f"{s['out_sample']['trades']:>7}{s['wfo_oos']['expectancy_R']:>9}  {flag}")

    log("\n  DETALLE POR ESTRATEGIA (mejor config, in-sample vs out-of-sample):")
    for s in r["ranking"]:
        log(f"    {s['name']}  [{s['label']}]")
        log(f"        IS : {_row(s['in_sample'])}")
        log(f"        OOS: {_row(s['out_sample'])}    {'✅ ROBUSTA' if s['robust'] else ('muestra OK' if s['confident'] else '⚠ muestra chica')}")

    log("\n  MEJORES COMBOS POR PAR/TIMEFRAME (por OOS):")
    for c in r["best_combos"][:8]:
        o = c["out_sample"]
        tag = "" if o["trades"] >= 30 else "  ⚠ pocos trades"
        log(f"    {c['strategy'][:22]:<23} {c['symbol']:<8}{c['timeframe']:<3} "
            f"OOS exp={o['expectancy_R']}R PF={_pf(o['profit_factor'])} n={o['trades']}{tag}")

    log("\n  VEREDICTO:")
    log(f"    {'✅ HAY EDGE ROBUSTO' if r['verdict']['any_robust'] else '⚠️  SIN EDGE ROBUSTO'}")
    for chunk in _wrap(r["verdict"]["text"], 70):
        log(f"    {chunk}")
    log(line)


def _wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


if __name__ == "__main__":
    main()
