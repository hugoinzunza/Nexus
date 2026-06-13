"""Estudio 1 de la misión (2026-06-13): ¿el TP de LIQUIDEZ supera al RR fijo?

El estudio CDC dejó esta línea abierta: apuntar a la siguiente liquidez opuesta
SIN BARRER (en vez de un RR fijo de 2) dio 1h OOS +0.371R / PF 1.44 (n=383) en
la variante A. Acá se valida formalmente, porque ADEMÁS es el TP que ya usa el
plan en vivo (smc_live._opposite_liquidity) — validarlo alinea backtest y vivo.

Variantes sobre el MISMO universo de toques de POI (A: primer toque, regla
validada con descuento/premium local):
  RR2      TP = RR fijo 2.0 (la referencia validada)
  LIQ15    TP = siguiente liquidez opuesta sin barrer, exigiendo RR efectivo >= 1.5
  LIQ20    TP = ídem con RR >= 2.0 (la del estudio CDC)

Anti-repaint estricto idéntico al repo (t_conf, confirm_idx, cierre → apertura
siguiente). Costos 0.05%/lado + 0.02% slippage. Split 70/30 + walk-forward de 5
ventanas + bootstrap 2000 en OOS. Salida: research/liq_tp_results.json
"""
from __future__ import annotations

import json
import os
import random
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import smc, engine                 # noqa: E402
from modules.trading.strategies import detect_pois      # noqa: E402
from modules.trading.backtest import metrics            # noqa: E402

DATA_DIR = os.path.join(WT, "data")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "liq_tp_results.json")

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
BASE_TFS = ["1h", "15m"]
POI_SOURCES = ["1h", "4h", "1d"]

PIV = 2
DISP = 1.0
MAX_AGE_DAYS = 30
STOP_BUF = 0.0005
IS_FRACTION = 0.70
WF_WINDOWS = 5
VARIANTS = [("RR2", "fixed", 2.0), ("LIQ15", "liquidity", 1.5), ("LIQ20", "liquidity", 2.0)]


def load(symbol, tf):
    path = os.path.join(DATA_DIR, f"klines_{symbol}_{tf}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.sort(key=lambda c: c["t"])
    return data


def liquidity_tp(direction, entry, idx_now, highs, lows, sh, sl):
    """Siguiente liquidez opuesta SIN BARRER (igual que el estudio CDC y el TP
    del plan vivo): el swing confirmado más cercano más allá de la entrada que
    el precio no haya traspasado desde que se formó."""
    if direction == "long":
        cands = sorted((p for p in sh
                        if p["confirm_idx"] <= idx_now and p["price"] > entry),
                       key=lambda p: p["price"])
        for p in cands:
            after = highs[p["idx"] + 1: idx_now + 1]
            if not after or max(after) < p["price"]:
                return p["price"]
    else:
        cands = sorted((p for p in sl
                        if p["confirm_idx"] <= idx_now and p["price"] < entry),
                       key=lambda p: -p["price"])
        for p in cands:
            after = lows[p["idx"] + 1: idx_now + 1]
            if not after or min(after) > p["price"]:
                return p["price"]
    return None


def build_signals(base, pois, mode, min_rr):
    n = len(base)
    opens = [c["o"] for c in base]
    highs = [c["h"] for c in base]
    lows = [c["l"] for c in base]
    sh, sl = smc.swing_points(base, PIV)
    max_age = MAX_AGE_DAYS * 86_400_000

    sig = []
    pi = 0
    active = []
    for j in range(n - 1):
        tj = base[j]["t"]
        while pi < len(pois) and pois[pi]["t_conf"] <= tj:
            active.append(dict(pois[pi], used=False))
            pi += 1
        if not active:
            continue
        kept = []
        for poi in active:
            if poi["used"] or tj - poi["t_conf"] > max_age:
                continue
            if poi["dir"] == "long" and lows[j] < poi["stop"]:
                continue
            if poi["dir"] == "short" and highs[j] > poi["stop"]:
                continue
            kept.append(poi)
        active = kept[-80:]
        for poi in active:
            d = poi["dir"]
            if not (lows[j] <= poi["hi"] and highs[j] >= poi["lo"]) or poi["used"]:
                continue
            poi["used"] = True
            stop = poi["stop"] * (1 - STOP_BUF) if d == "long" else poi["stop"] * (1 + STOP_BUF)
            if mode == "fixed":
                sig.append((j, d, stop, min_rr))
                continue
            entry = opens[j + 1]
            risk = (entry - stop) if d == "long" else (stop - entry)
            if risk <= 0:
                continue
            tp = liquidity_tp(d, entry, j, highs, lows, sh, sl)
            if tp is None:
                continue
            rr_eff = ((tp - entry) if d == "long" else (entry - tp)) / risk
            if rr_eff < min_rr:
                continue
            sig.append((j, d, stop, round(rr_eff, 3)))
    return sig


def bootstrap_p(trades, n_boot=2000, seed=7):
    rs = [t["R"] for t in trades if t.get("R") is not None]
    if len(rs) < 20:
        return None
    rng = random.Random(seed)
    k = len(rs)
    pos = sum(1 for _ in range(n_boot)
              if sum(rs[rng.randrange(k)] for _ in range(k)) > 0)
    return round(pos / n_boot, 3)


def main():
    per = {}
    spans = {}
    for sym in PAIRS:
        sources = {}
        for tf in POI_SOURCES:
            s = load(sym, tf)
            if s:
                sources[tf] = s
        if not sources:
            continue
        pois_all = []
        for s in sources.values():
            pois_all.extend(detect_pois(s, PIV, DISP))
        pois_all.sort(key=lambda x: x["t_conf"])
        for tf in BASE_TFS:
            base = sources.get(tf) or load(sym, tf)
            if not base or len(base) < 1000:
                continue
            spans[(sym, tf)] = (base[0]["t"], base[-1]["t"])
            for vname, mode, min_rr in VARIANTS:
                sig = build_signals(base, pois_all, mode, min_rr)
                for costs in (True, False):
                    comm, slip = (0.0005, 0.0002) if costs else (0.0, 0.0)
                    per[(vname, sym, tf, costs)] = engine.simulate(
                        base, list(sig), sym, tf, "liq", commission=comm, slippage=slip)
                print(f"{sym} {tf} {vname}: {len(sig)} señales", flush=True)

    def collect(v, tf, costs, period):
        pool = []
        for sym in PAIRS:
            tr = per.get((v, sym, tf, costs), [])
            sp = spans.get((sym, tf))
            if not sp:
                continue
            t0, t1 = sp
            cut = t0 + IS_FRACTION * (t1 - t0)
            if period == "all":
                pool.extend(tr)
            elif period == "is":
                pool.extend(t for t in tr if t["entry_time"] <= cut)
            else:
                pool.extend(t for t in tr if t["entry_time"] > cut)
        return pool

    out = {"params": {"PIV": PIV, "DISP": DISP, "MAX_AGE_DAYS": MAX_AGE_DAYS,
                      "IS_FRACTION": IS_FRACTION, "VARIANTS": [v[0] for v in VARIANTS],
                      "PAIRS": PAIRS, "BASE_TFS": BASE_TFS},
           "tables": {}, "bootstrap": {}, "per_pair": {}, "walk_forward": {}}
    for tf in BASE_TFS:
        td = {}
        for vname, _, _ in VARIANTS:
            vd = {}
            for costs in (True, False):
                ck = "con_costos" if costs else "sin_costos"
                vd[ck] = {"IS": metrics(collect(vname, tf, costs, "is")),
                          "OOS": metrics(collect(vname, tf, costs, "oos")),
                          "ALL": metrics(collect(vname, tf, costs, "all"))}
            td[vname] = vd
        out["tables"][tf] = td
        out["bootstrap"][tf] = {v[0]: bootstrap_p(collect(v[0], tf, True, "oos"))
                                for v in VARIANTS}
        pp = {}
        for sym in PAIRS:
            row = {}
            for vname, _, _ in VARIANTS:
                tr = per.get((vname, sym, tf, True), [])
                sp = spans.get((sym, tf))
                oos = []
                if sp:
                    t0, t1 = sp
                    cut = t0 + IS_FRACTION * (t1 - t0)
                    oos = [t for t in tr if t["entry_time"] > cut]
                row[vname] = {"OOS": metrics(oos)}
            pp[sym] = row
        out["per_pair"][tf] = pp
        # Walk-forward de 5 ventanas (con costos).
        t0 = min((spans[(s, tf)][0] for s in PAIRS if (s, tf) in spans), default=0)
        t1 = max((spans[(s, tf)][1] for s in PAIRS if (s, tf) in spans), default=0)
        wf = {}
        if t1 > t0:
            edges = [t0 + (t1 - t0) * k / WF_WINDOWS for k in range(WF_WINDOWS + 1)]
            for vname, _, _ in VARIANTS:
                allt = collect(vname, tf, True, "all")
                wins = []
                for k in range(WF_WINDOWS):
                    seg = [t for t in allt if edges[k] <= t["entry_time"] < edges[k + 1]]
                    m = metrics(seg)
                    wins.append({"n": m["trades"], "exp_R": m["expectancy_R"],
                                 "PF": m["profit_factor"]})
                wf[vname] = wins
        out["walk_forward"][tf] = wf

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
