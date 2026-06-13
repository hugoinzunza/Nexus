"""Simulación P&L 2026 YTD del criterio SMC en vivo, $1000 a 20x por trade.

Responde: "¿cuánto sería hoy si en 2026, con esta estrategia, en todos los trades
hubiéramos ido con 1000 USD a 20x?". Reusa run_setup_backtest (mismo plan + anti-
repaint) pero calcula P&L en USD REAL (notional × % movimiento entrada→salida), con
costos del backtest riguroso (comisión 0.05%/lado + slippage 0.02%/fill = 0.14%
round-trip) y chequeo de LIQUIDACIÓN a 20x (adverso ~4.6% = 1/20 − 0.4% manten.).

Dos lecturas del sizing (ambas reportadas):
  FIJO       — $1000 de margen cada trade (no compone). Es position sizing, NO
               "una cuenta de $1000": requiere bankroll que aguante el drawdown.
  COMPOUND   — cuenta arranca en $1000 y va all-in a 20x cada trade (reinvierte
               todo). Aquí el sobre-apalancamiento mata el edge.

Correr: python3 research/sim_2026_20x.py
"""
from __future__ import annotations

import calendar
import os
import sys
import time

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import run_setup_backtest as B  # noqa: E402
from modules.trading import smc_live  # noqa: E402

YEAR_START = calendar.timegm((2026, 1, 1, 0, 0, 0)) * 1000
LEV = 20
MARGIN = 1000.0
NOTIONAL = LEV * MARGIN
COST = 0.0014        # 0.05%*2 comisión + 0.02%*2 slippage (= backtest riguroso)
LIQ = 0.046          # adverso de liquidación a 20x (1/20 − 0.4% mantenimiento)


def _sim(setup, sel, i, mf):
    long = setup["dir"] == "long"
    lo, hi, sl, tp, e = setup["lo"], setup["hi"], setup["sl"], setup["tp"], setup["entry"]
    act = False
    mae = 0.0
    end = min(len(sel), i + 1 + mf)
    for j in range(i + 1, end):
        h, l = sel[j]["h"], sel[j]["l"]
        if not act:
            if (long and h >= tp) or ((not long) and l <= tp):
                if not (l <= hi and h >= lo):
                    return "anulada", None, 0.0, j
            if l <= hi and h >= lo:
                act = True
            else:
                continue
        mae = max(mae, (e - l) / e if long else (h - e) / e)
        if long:
            if l <= sl:
                return "perdida", sl, mae, j
            if h >= tp:
                return "ganada", tp, mae, j
        else:
            if h >= sl:
                return "perdida", sl, mae, j
            if l <= tp:
                return "ganada", tp, mae, j
    return "abierto", None, mae, end - 1


def collect(symbols):
    trades = []
    for _live, sym in symbols:
        htf = {tf: B._load(sym, tf) for tf in set(B.POI_TFS) | set(B.SEL_TFS)}
        if any(htf[tf] is None for tf in B.POI_TFS):
            continue
        ts = {tf: [c["t"] for c in htf[tf]] for tf in htf}
        for stf in B.SEL_TFS:
            sel, sm, lr = htf[stf], B.TF_MS[stf], {}
            start = max(B.WIN, len(sel) - B.BARS.get(stf, 3000) - B.MAX_FWD.get(stf, 200))
            for i in range(start, len(sel) - 1):
                if sel[i]["t"] < YEAR_START:
                    continue
                ct = sel[i]["t"] + sm
                hm = {tf: B._htf_slice(htf[tf], ts[tf], B.TF_MS[tf], ct, B.WIN) for tf in B.POI_TFS}
                try:
                    a = smc_live.analyze(sel[max(0, i - B.WIN + 1):i + 1], hm, sel[i]["c"], stf)
                except Exception:  # noqa: BLE001
                    continue
                p = a.get("tpsl")
                if not p:
                    continue
                k = f"{p['tf']}:{p['dir']}:{round(p['entry_lo'], 2)}"
                if k in lr and i <= lr[k]:
                    continue
                setup = {"dir": p["dir"], "lo": p["entry_lo"], "hi": p["entry_hi"],
                         "sl": p["sl"], "tp": p["tp"], "entry": p["entry"]}
                st, ex, mae, res = _sim(setup, sel, i, B.MAX_FWD.get(stf, 200))
                lr[k] = res
                if st in ("ganada", "perdida"):
                    long = p["dir"] == "long"
                    e = p["entry"]
                    pct = (ex - e) / e if long else (e - ex) / e
                    trades.append({"sym": sym, "t": sel[i]["t"], "st": st, "pct": pct,
                                   "mae": mae, "liq": st == "perdida" and mae >= LIQ})
    trades.sort(key=lambda t: t["t"])
    return trades


def report(trades, label):
    print(f"\n===== {label} — {len(trades)} trades =====")
    if not trades:
        return
    wins = sum(1 for t in trades if t["st"] == "ganada")
    liqs = [t for t in trades if t["liq"]]
    print(f"win {wins}/{len(trades)} = {wins/len(trades)*100:.1f}% | liquidaciones (MAE>={LIQ*100:.1f}%): {len(liqs)}")
    for mode in ("normal", "liq"):
        eq = MARGIN
        peak = MARGIN
        mdd = best = worst = 0
        best, worst = -9e9, 9e9
        for t in trades:
            pnl = -MARGIN if (mode == "liq" and t["liq"]) else NOTIONAL * t["pct"] - NOTIONAL * COST
            best, worst = max(best, pnl), min(worst, pnl)
            eq += pnl
            peak = max(peak, eq)
            mdd = min(mdd, eq - peak)
        tag = "liq=-margen" if mode == "liq" else "SL normal "
        print(f"  FIJO $1000/tr [{tag}]: neto {eq-MARGIN:+.0f} | final {eq:.0f} | "
              f"mejor {best:+.0f} | peor {worst:+.0f} | maxDD {mdd:.0f}")
    for mode in ("normal", "liq"):
        eq = MARGIN
        ruin = None
        for k, t in enumerate(trades):
            no = LEV * eq
            pnl = -eq if (mode == "liq" and t["liq"]) else no * t["pct"] - no * COST
            eq += pnl
            if eq <= 0:
                ruin = k + 1
                eq = 0
                break
        tag = "liq=-margen" if mode == "liq" else "SL normal "
        print(f"  COMPOUND all-in [{tag}]: " + (f"RUINA en trade #{ruin}" if ruin else f"final {eq:,.0f}"))


if __name__ == "__main__":
    print("P&L 2026 YTD · $1000 a 20x · costos 0.14% round-trip · liq ~4.6%")
    report(collect([("BTC_USDT", "BTCUSDT")]), "BTC 2026")
    report(collect(B.SYMBOLS), "BTC+ETH 2026 (agregado)")
