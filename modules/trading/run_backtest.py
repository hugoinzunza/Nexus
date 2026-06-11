"""CLI de backtest de la estrategia SMC.

Baja (o lee de caché) el histórico de Binance, corre la estrategia sobre cada
par/timeframe con varias configuraciones (objetivos R y filtro de tendencia),
imprime un reporte honesto y guarda los resultados en
`modules/trading/backtest_results.json` para que la vista web /m/trading/backtest
los muestre (ese JSON SÍ se commitea, así Railway lo sirve sin recalcular).

Uso:
    python3 -m modules.trading.run_backtest          # 3 años, pares por defecto
    python3 -m modules.trading.run_backtest --years 2

Honestidad: no se "tunea" para maximizar. Se fija una config primaria a priori
(2R, sin filtro) y se muestra la sensibilidad a los parámetros, con comisiones
(0.05%/lado) y slippage (0.02%) incluidos.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.trading import binance, backtest
from modules.trading.backtest import Params, metrics, breakdown, equity_curve

PAIRS = ["BTCUSDT", "ETHUSDT"]
TIMEFRAMES = ["1h", "4h"]
RR_VARIANTS = [1.5, 2.0, 3.0]
TREND_VARIANTS = [False, True]

PRIMARY_RR = 2.0
PRIMARY_TREND = False

RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_results.json")


def log(msg):
    print(msg, flush=True)


def _fmt_gmt(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"))
    args = ap.parse_args()

    # 1) Cargar data (de caché si existe).
    series = {}
    coverage = []
    for sym in PAIRS:
        for tf in TIMEFRAMES:
            candles = binance.fetch_klines(sym, tf, years=args.years,
                                           data_dir=args.data_dir, log=log)
            series[(sym, tf)] = candles
            coverage.append({
                "symbol": sym, "timeframe": tf, "bars": len(candles),
                "from": _fmt_gmt(candles[0]["t"]) if candles else None,
                "to": _fmt_gmt(candles[-1]["t"]) if candles else None,
            })

    # 2) Correr todas las variantes (rr x filtro de tendencia).
    #    trades_by[(rr, trend)] = lista combinada de todos los pares/timeframes
    #    trades_pt[(rr, trend, sym, tf)] = lista de ese par/timeframe
    trades_by = {}
    trades_pt = {}
    for trend in TREND_VARIANTS:
        for rr in RR_VARIANTS:
            combined = []
            for sym in PAIRS:
                for tf in TIMEFRAMES:
                    p = Params(rr=rr, use_trend_filter=trend)
                    tr = backtest.run(series[(sym, tf)], sym, tf, p)
                    trades_pt[(rr, trend, sym, tf)] = tr
                    combined.extend(tr)
            trades_by[(rr, trend)] = combined

    primary = trades_by[(PRIMARY_RR, PRIMARY_TREND)]

    # 3) Armar el JSON de resultados.
    sample_params = asdict(Params(rr=PRIMARY_RR, use_trend_filter=PRIMARY_TREND))
    results = {
        "generated_at_ms": int(time.time() * 1000),
        "config": {
            "pairs": PAIRS, "timeframes": TIMEFRAMES,
            "primary_rr": PRIMARY_RR, "primary_trend_filter": PRIMARY_TREND,
            "params": sample_params,
        },
        "costs": {"commission_per_side": sample_params["commission"],
                  "slippage": sample_params["slippage"]},
        "data": coverage,
        "headline": metrics(primary),
        "by_pair_tf": [
            {"symbol": sym, "timeframe": tf,
             **metrics(trades_pt[(PRIMARY_RR, PRIMARY_TREND, sym, tf)])}
            for sym in PAIRS for tf in TIMEFRAMES
        ],
        "by_session": breakdown(primary, "session"),
        "by_direction": breakdown(primary, "direction"),
        "sensitivity": [
            {"rr": rr, "trend_filter": trend, **metrics(trades_by[(rr, trend)])}
            for trend in TREND_VARIANTS for rr in RR_VARIANTS
        ],
        "equity": equity_curve(primary),
    }

    with open(RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False)

    _print_report(results)
    log(f"\n💾 Resultados guardados en {RESULTS_PATH}")
    log("   Vista web: /m/trading/backtest")


def _print_report(r):
    line = "─" * 64
    log("\n" + line)
    log("  BACKTEST · Estrategia SMC (barrido + CHoCH + FVG/OB)")
    log(line)
    log(f"  Config primaria: {r['config']['primary_rr']}R, "
        f"filtro tendencia {'ON' if r['config']['primary_trend_filter'] else 'OFF'}")
    log(f"  Costos: comisión {r['costs']['commission_per_side']*100:.3f}%/lado, "
        f"slippage {r['costs']['slippage']*100:.3f}%")
    log("  Data:")
    for d in r["data"]:
        log(f"    {d['symbol']:<8} {d['timeframe']:<3} {d['bars']:>6} velas  "
            f"{d['from']} → {d['to']}")

    h = r["headline"]
    log("\n  ── RESUMEN (todos los pares/timeframes, config primaria) ──")
    _print_metrics(h)

    log("\n  ── POR PAR / TIMEFRAME ──")
    log(f"    {'par':<9}{'tf':<4}{'trades':>7}{'win%':>7}{'exp.R':>8}"
        f"{'PF':>7}{'maxDD':>8}{'totalR':>8}")
    for row in r["by_pair_tf"]:
        log(f"    {row['symbol']:<9}{row['timeframe']:<4}{row['trades']:>7}"
            f"{row['win_rate']:>7}{row['expectancy_R']:>8}"
            f"{_pf(row['profit_factor']):>7}{row['max_drawdown_R']:>8}{row['total_R']:>8}")

    log("\n  ── POR SESIÓN (config primaria) ──")
    log(f"    {'sesión':<9}{'trades':>7}{'win%':>7}{'exp.R':>8}{'PF':>7}{'totalR':>8}")
    for sess, m in sorted(r["by_session"].items(), key=lambda x: -x[1]["trades"]):
        log(f"    {sess:<9}{m['trades']:>7}{m['win_rate']:>7}{m['expectancy_R']:>8}"
            f"{_pf(m['profit_factor']):>7}{m['total_R']:>8}")

    log("\n  ── POR DIRECCIÓN ──")
    for d, m in r["by_direction"].items():
        log(f"    {d:<7} trades={m['trades']:<5} win={m['win_rate']}%  "
            f"exp={m['expectancy_R']}R  PF={_pf(m['profit_factor'])}  totalR={m['total_R']}")

    log("\n  ── SENSIBILIDAD A PARÁMETROS (resumen agregado) ──")
    log(f"    {'objetivo':<10}{'tend.':<7}{'trades':>7}{'win%':>7}{'exp.R':>8}"
        f"{'PF':>7}{'maxDD':>8}{'totalR':>8}")
    for s in r["sensitivity"]:
        log(f"    {str(s['rr'])+'R':<10}{'ON' if s['trend_filter'] else 'OFF':<7}"
            f"{s['trades']:>7}{s['win_rate']:>7}{s['expectancy_R']:>8}"
            f"{_pf(s['profit_factor']):>7}{s['max_drawdown_R']:>8}{s['total_R']:>8}")
    log("─" * 64)


def _print_metrics(m):
    log(f"    Trades: {m['trades']}   Ganados: {m['wins']}   Perdidos: {m['losses']}"
        f"   Time-stops: {m['timeouts']}")
    log(f"    Win rate: {m['win_rate']}%   Expectativa: {m['expectancy_R']}R/trade")
    log(f"    R prom. ganador: +{m['avg_win_R']}   R prom. perdedor: {m['avg_loss_R']}")
    log(f"    Profit factor: {_pf(m['profit_factor'])}   "
        f"Max drawdown: {m['max_drawdown_R']}R   Racha máx. pérdidas: {m['max_losing_streak']}")
    log(f"    R total acumulado: {m['total_R']}R")


def _pf(v):
    return "∞" if v == float("inf") else v


if __name__ == "__main__":
    main()
