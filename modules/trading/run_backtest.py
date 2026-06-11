"""CLI de backtest SMC — Fase 1.5: filtros de calidad + validación fuera de muestra.

Qué hace:
  1. Baja (o lee de caché) histórico de Binance: pares en 1h y 4h, más el
     timeframe SUPERIOR (4h para 1h, 1d para 4h) para la estructura de tendencia.
  2. Corre una grilla de configuraciones (objetivo R × filtro de tendencia ×
     displacement × premium/discount × sesión) sobre cada par/timeframe.
  3. Divide la data en IN-SAMPLE (70% antiguo) y OUT-OF-SAMPLE (30% reciente):
       - optimiza la config SOLO en in-sample,
       - reporta esa misma config en in-sample y en out-of-sample por separado.
  4. Walk-forward anclado (3 folds): re-optimiza por ventana y agrega el OOS.
  5. Ablación: mide el impacto de cada filtro uno por uno.
  6. Compara filtro de tendencia por ESTRUCTURA vs EMA vs ninguno.

Guarda todo en `backtest_results.json` (commiteado) y lo imprime. Honesto: si el
edge no sobrevive fuera de muestra, el veredicto lo dice. Comisiones (0.05%/lado)
y slippage (0.02%) incluidos.

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

from modules.trading import binance, smc, backtest
from modules.trading.backtest import Params, metrics, breakdown, equity_curve

PAIRS = ["BTCUSDT", "ETHUSDT"]
TIMEFRAMES = ["1h", "4h"]
HTF = {"1h": "4h", "4h": "1d"}        # timeframe superior para la estructura
YEARS = 3.0
IS_FRACTION = 0.70                     # 70% in-sample / 30% out-of-sample
MIN_TRADES_OPT = 40                    # mínimo de trades para considerar una config

# Grilla de optimización (acotada a propósito, para no sobreajustar).
RR_GRID = [2.0, 3.0]
TREND_GRID = ["none", "ema", "structure"]
DISP_GRID = [False, True]
PD_GRID = [False, True]
SESS_GRID = [None, ["Londres"]]

RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_results.json")


def log(m):
    print(m, flush=True)


def gmt(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def cfg_key(c):
    return (c["rr"], c["trend"], c["disp"], c["pd"],
            tuple(c["sess"]) if c["sess"] else None)


def make_params(c):
    return Params(rr=c["rr"], trend_filter_mode=c["trend"],
                  use_displacement=c["disp"], use_premium_discount=c["pd"],
                  session_filter=c["sess"])


def cfg_label(c):
    parts = [f"{c['rr']}R", {"none": "sin tendencia", "ema": "EMA",
                              "structure": "estructura"}[c["trend"]]]
    if c["disp"]:
        parts.append("displacement")
    if c["pd"]:
        parts.append("premium/discount")
    if c["sess"]:
        parts.append("sesión " + "/".join(c["sess"]))
    return " · ".join(parts)


def build_grid():
    grid = []
    for rr in RR_GRID:
        for trend in TREND_GRID:
            for disp in DISP_GRID:
                for pd in PD_GRID:
                    for sess in SESS_GRID:
                        grid.append({"rr": rr, "trend": trend, "disp": disp,
                                     "pd": pd, "sess": sess})
    return grid


def window(trades, lo, hi):
    return [t for t in trades if lo <= t["entry_time"] < hi]


def pick_best(combined, lo, hi, grid, min_trades=MIN_TRADES_OPT):
    """Elige la config con mayor expectativa en la ventana [lo,hi), exigiendo un
    mínimo de trades. Si ninguna lo cumple, relaja el mínimo."""
    best = None
    for thresh in (min_trades, 20, 1):
        cand = []
        for c in grid:
            tr = window(combined[cfg_key(c)], lo, hi)
            m = metrics(tr)
            if m["trades"] >= thresh:
                cand.append((c, m))
        if cand:
            cand.sort(key=lambda x: (x[1]["expectancy_R"], x[1]["total_R"]), reverse=True)
            best = cand[0]
            break
    return best  # (config, metrics_in_window) o None


def main():
    # 1) Cargar data LTF y HTF.
    series, htf_dir, coverage = {}, {}, []
    for sym in PAIRS:
        for tf in TIMEFRAMES:
            candles = binance.fetch_klines(sym, tf, years=YEARS, data_dir=os.path.join(ROOT, "data"), log=log)
            series[(sym, tf)] = candles
            coverage.append({"symbol": sym, "timeframe": tf, "bars": len(candles),
                             "from": gmt(candles[0]["t"]), "to": gmt(candles[-1]["t"])})
            htf_tf = HTF[tf]
            htf_c = binance.fetch_klines(sym, htf_tf, years=YEARS + 0.3, data_dir=os.path.join(ROOT, "data"), log=log)
            hdir_full = smc.structure_direction(htf_c, lookback=2)
            htf_dir[(sym, tf)] = smc.map_htf_direction(
                candles, htf_c, hdir_full, binance.INTERVAL_MS[htf_tf])

    grid = build_grid()
    log(f"\nCorriendo grilla de {len(grid)} configs sobre {len(series)} datasets…")

    # 2) Correr cada config sobre cada dataset (una sola vez, full).
    cache = {}  # (sym,tf) -> {cfg_key: trades}
    for sym in PAIRS:
        for tf in TIMEFRAMES:
            ds = {}
            for c in grid:
                tr = backtest.run(series[(sym, tf)], sym, tf, make_params(c), htf_dir[(sym, tf)])
                ds[cfg_key(c)] = tr
            cache[(sym, tf)] = ds
        log(f"  {sym} listo")

    # Combinado por config (todos los pares/timeframes).
    combined = {}
    for c in grid:
        k = cfg_key(c)
        allt = []
        for sym in PAIRS:
            for tf in TIMEFRAMES:
                allt.extend(cache[(sym, tf)][k])
        combined[k] = allt

    # Línea de tiempo global y corte IS/OOS.
    t0 = min(series[(s, t)][0]["t"] for s in PAIRS for t in TIMEFRAMES)
    t1 = max(series[(s, t)][-1]["t"] for s in PAIRS for t in TIMEFRAMES)
    split = t0 + int(IS_FRACTION * (t1 - t0))

    # 3) Mejor config global: optimizada SOLO en in-sample.
    best_c, best_is_m = pick_best(combined, t0, split, grid)
    best_trades = combined[cfg_key(best_c)]
    is_trades = window(best_trades, t0, split)
    oos_trades = window(best_trades, split, t1 + 1)

    best_overall = {
        "config": best_c, "label": cfg_label(best_c),
        "in_sample": metrics(is_trades),
        "out_sample": metrics(oos_trades),
        "full": metrics(best_trades),
    }

    # 4) Walk-forward anclado (3 folds OOS).
    span = t1 - t0
    qs = [t0 + int(span * f) for f in (0.25, 0.5, 0.75)] + [t1 + 1]
    folds = []
    wfo_oos, wfo_is = [], []
    for i in range(3):
        train_lo, train_hi = t0, qs[i]
        test_lo, test_hi = qs[i], qs[i + 1]
        picked = pick_best(combined, train_lo, train_hi, grid)
        if not picked:
            continue
        pc, pis = picked
        ptr = combined[cfg_key(pc)]
        otr = window(ptr, test_lo, test_hi)
        folds.append({
            "train_from": gmt(train_lo), "train_to": gmt(train_hi),
            "test_from": gmt(test_lo), "test_to": gmt(test_hi),
            "config": pc, "label": cfg_label(pc),
            "in_sample": pis, "out_sample": metrics(otr),
        })
        wfo_oos.extend(otr)
        wfo_is.extend(window(ptr, train_lo, train_hi))
    walkforward = {"folds": folds, "oos_aggregate": metrics(wfo_oos),
                   "is_aggregate": metrics(wfo_is)}

    # 5) Comparación de filtro de tendencia (rr=3, sin otros filtros), full y OOS.
    trend_comparison = []
    for trend in TREND_GRID:
        c = {"rr": 3.0, "trend": trend, "disp": False, "pd": False, "sess": None}
        tr = combined[cfg_key(c)]
        trend_comparison.append({
            "mode": trend, "full": metrics(tr),
            "out_sample": metrics(window(tr, split, t1 + 1)),
        })

    # 6) Ablación: desde una base (3R + tendencia por estructura) sumamos un filtro
    #    a la vez y medimos el impacto en full sample.
    base = {"rr": 3.0, "trend": "structure", "disp": False, "pd": False, "sess": None}
    ablation = {"base": {"label": cfg_label(base), "metrics": metrics(combined[cfg_key(base)])},
                "steps": []}
    toggles = [
        ("+ displacement", {**base, "disp": True}),
        ("+ premium/discount", {**base, "pd": True}),
        ("+ sesión Londres", {**base, "sess": ["Londres"]}),
    ]
    for name, c in toggles:
        ablation["steps"].append({"name": name, "label": cfg_label(c),
                                  "metrics": metrics(combined[cfg_key(c)])})
    # Filtro de tamaño de FVG (no está en la grilla): corrida aparte.
    p_minfvg = make_params(base)
    p_minfvg.use_min_fvg = True
    mf = []
    for sym in PAIRS:
        for tf in TIMEFRAMES:
            mf.extend(backtest.run(series[(sym, tf)], sym, tf, p_minfvg, htf_dir[(sym, tf)]))
    ablation["steps"].append({"name": "+ tamaño mín. FVG", "label": cfg_label(base) + " · FVG≥0.25·ATR",
                              "metrics": metrics(mf)})

    # 7) Por par/timeframe con holdout (config óptima de cada uno en su in-sample).
    per_dataset = []
    for sym in PAIRS:
        for tf in TIMEFRAMES:
            ds_comb = {cfg_key(c): cache[(sym, tf)][cfg_key(c)] for c in grid}
            picked = pick_best(ds_comb, t0, split, grid, min_trades=20)
            if not picked:
                continue
            pc, pis = picked
            tr = ds_comb[cfg_key(pc)]
            per_dataset.append({
                "symbol": sym, "timeframe": tf,
                "config": pc, "label": cfg_label(pc),
                "in_sample": pis, "out_sample": metrics(window(tr, split, t1 + 1)),
            })

    # 8) Veredicto honesto (se apoya sobre todo en el walk-forward, que tiene más
    #    muestra OOS que el holdout simple).
    oos = best_overall["out_sample"]
    wfo = walkforward["oos_aggregate"]
    robust = (wfo["trades"] >= 40 and wfo["expectancy_R"] > 0 and wfo["profit_factor"] >= 1.0
              and oos["expectancy_R"] > 0)
    verdict = {
        "robust": robust,
        "text": _verdict_text(best_overall, walkforward, per_dataset),
    }

    results = {
        "generated_at_ms": int(time.time() * 1000),
        "phase": "1.5",
        "costs": {"commission_per_side": 0.0005, "slippage": 0.0002},
        "data": coverage,
        "split": {"is_fraction": IS_FRACTION, "is_until": gmt(split), "oos_from": gmt(split)},
        "grid_size": len(grid),
        "best_overall": best_overall,
        "walkforward": walkforward,
        "trend_comparison": trend_comparison,
        "ablation": ablation,
        "per_dataset": per_dataset,
        "by_session_best": breakdown(best_trades, "session"),
        "equity_oos": equity_curve(oos_trades),
        "equity_full": equity_curve(best_trades),
        "verdict": verdict,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False)

    _print(results)
    log(f"\n💾 Guardado en {RESULTS_PATH}\n   Vista web: /m/trading/backtest")


def _verdict_text(best, wfo, per_dataset):
    oos = best["out_sample"]
    is_ = best["in_sample"]
    wo = wfo["oos_aggregate"]

    # Punto relativamente sólido: algún par/timeframe que aguante OOS con muestra decente.
    bright = [d for d in per_dataset
              if d["out_sample"]["trades"] >= 10 and d["out_sample"]["expectancy_R"] > 0.1
              and d["out_sample"]["profit_factor"] >= 1.2]
    bright_txt = ""
    if bright:
        b = max(bright, key=lambda d: d["out_sample"]["trades"])
        bo = b["out_sample"]
        bright_txt = (f" El único foco que aguanta fuera de muestra es {b['symbol']} "
                      f"{b['timeframe']} ({b['label']}): {bo['expectancy_R']}R, "
                      f"PF {bo['profit_factor']} en {bo['trades']} trades — prometedor, "
                      "pero con muestra chica.")

    if oos["expectancy_R"] > 0 and oos["profit_factor"] >= 1.0 and wo["expectancy_R"] > 0:
        return (f"El edge SOBREVIVE fuera de muestra, aunque modesto: expectativa "
                f"in-sample {is_['expectancy_R']}R vs out-of-sample {oos['expectancy_R']}R "
                f"(PF {oos['profit_factor']}); walk-forward agregado {wo['expectancy_R']}R en "
                f"{wo['trades']} trades. Señal real pero margen chico y sensible a costos." + bright_txt)

    return (f"El edge NO es robusto fuera de muestra. La mejor config in-sample "
            f"({is_['expectancy_R']}R, PF {best['in_sample']['profit_factor']}) cae a "
            f"{oos['expectancy_R']}R (PF {oos['profit_factor']}) en out-of-sample: sobreajuste. "
            f"El walk-forward lo confirma: {wo['expectancy_R']}R en {wo['trades']} trades OOS "
            f"(PF {wo['profit_factor']}). Conclusión honesta: la estrategia, tal cual, NO tiene "
            "ventaja demostrable después de costos; no se justifica operarla con dinero real." + bright_txt)


def _pf(v):
    return "∞" if v == float("inf") else v


def _row(m):
    return (f"trades={m['trades']:<5} win={m['win_rate']}%  exp={m['expectancy_R']}R  "
            f"PF={_pf(m['profit_factor'])}  DD={m['max_drawdown_R']}R  totalR={m['total_R']}")


def _print(r):
    line = "─" * 70
    log("\n" + line)
    log("  BACKTEST SMC · Fase 1.5 (filtros de calidad + validación fuera de muestra)")
    log(line)
    log(f"  Costos: comisión 0.05%/lado, slippage 0.02% · grilla {r['grid_size']} configs")
    for d in r["data"]:
        log(f"    {d['symbol']:<8} {d['timeframe']:<3} {d['bars']:>6} velas  {d['from']} → {d['to']}")
    log(f"  Corte: in-sample hasta {r['split']['is_until']} · out-of-sample desde ahí")

    b = r["best_overall"]
    log(f"\n  ★ MEJOR CONFIG (optimizada solo en in-sample): {b['label']}")
    log(f"      IN-SAMPLE : {_row(b['in_sample'])}")
    log(f"      OUT-SAMPLE: {_row(b['out_sample'])}")
    log(f"      FULL      : {_row(b['full'])}")

    w = r["walkforward"]
    log("\n  WALK-FORWARD (3 folds anclados, config re-optimizada por ventana):")
    for f in w["folds"]:
        log(f"    test {f['test_from']}→{f['test_to']}  [{f['label']}]")
        log(f"        IS : {_row(f['in_sample'])}")
        log(f"        OOS: {_row(f['out_sample'])}")
    log(f"    OOS AGREGADO: {_row(w['oos_aggregate'])}")

    log("\n  FILTRO DE TENDENCIA (3R, sin otros filtros):")
    for t in r["trend_comparison"]:
        name = {"none": "ninguno", "ema": "EMA", "structure": "estructura HTF"}[t["mode"]]
        log(f"    {name:<16} full: {_row(t['full'])}")
        log(f"    {'':<16} OOS : {_row(t['out_sample'])}")

    log("\n  ABLACIÓN (impacto de cada filtro, full sample):")
    log(f"    base = {r['ablation']['base']['label']}")
    log(f"      {_row(r['ablation']['base']['metrics'])}")
    for s in r["ablation"]["steps"]:
        log(f"    {s['name']:<22} {_row(s['metrics'])}")

    log("\n  POR PAR/TIMEFRAME (config óptima de cada uno en su in-sample):")
    for d in r["per_dataset"]:
        log(f"    {d['symbol']} {d['timeframe']}  [{d['label']}]")
        log(f"        IN : {_row(d['in_sample'])}")
        log(f"        OOS: {_row(d['out_sample'])}")

    log("\n  VEREDICTO:")
    log(f"    {'✅ EDGE ROBUSTO' if r['verdict']['robust'] else '⚠️  EDGE NO ROBUSTO'}")
    for chunk in _wrap(r["verdict"]["text"], 66):
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
