"""Estudio 2 de la misión (2026-06-13): FRACTALES — sensibilidad del pivote.

La detección de POIs usa swings fractales con piv=2 (2 velas por lado) para el
barrido y la estructura local (detect_pois). ¿Es robusto ese 2, o el edge es
frágil a la escala fractal? Se corre el MISMO setup (primer toque del POI,
RR fijo 2) variando SOLO el pivote de detección: piv ∈ {2, 3, 5}.

OJO: no es para tunear (elegir el mejor OOS sería overfitting); es para mapear
la CURVA de sensibilidad. Si piv=2 es un pico aislado → frágil; si la zona es
plana → robusto. Anti-repaint y costos idénticos al resto de los estudios.
Salida: research/fractal_piv_results.json
"""
from __future__ import annotations

import json
import os
import random
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import engine                       # noqa: E402
from modules.trading.strategies import detect_pois       # noqa: E402
from modules.trading.backtest import metrics             # noqa: E402

DATA_DIR = os.path.join(WT, "data")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fractal_piv_results.json")

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
BASE_TFS = ["1h", "15m"]
POI_SOURCES = ["1h", "4h", "1d"]

PIVS = [2, 3, 5]
DISP = 1.0
MAX_AGE_DAYS = 30
STOP_BUF = 0.0005
RR_FIXED = 2.0
IS_FRACTION = 0.70


def load(symbol, tf):
    path = os.path.join(DATA_DIR, f"klines_{symbol}_{tf}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.sort(key=lambda c: c["t"])
    return data


def build_signals(base, pois):
    n = len(base)
    highs = [c["h"] for c in base]
    lows = [c["l"] for c in base]
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
            if poi["used"] or not (lows[j] <= poi["hi"] and highs[j] >= poi["lo"]):
                continue
            poi["used"] = True
            stop = poi["stop"] * (1 - STOP_BUF) if d == "long" else poi["stop"] * (1 + STOP_BUF)
            sig.append((j, d, stop, RR_FIXED))
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
        for piv in PIVS:
            pois_all = []
            for s in sources.values():
                pois_all.extend(detect_pois(s, piv, DISP))
            pois_all.sort(key=lambda x: x["t_conf"])
            for tf in BASE_TFS:
                base = sources.get(tf) or load(sym, tf)
                if not base or len(base) < 1000:
                    continue
                spans[(sym, tf)] = (base[0]["t"], base[-1]["t"])
                sig = build_signals(base, pois_all)
                for costs in (True, False):
                    comm, slip = (0.0005, 0.0002) if costs else (0.0, 0.0)
                    per[(piv, sym, tf, costs)] = engine.simulate(
                        base, list(sig), sym, tf, "fr", commission=comm, slippage=slip)
                print(f"{sym} {tf} piv{piv}: {len(sig)} señales", flush=True)

    def collect(piv, tf, costs, period):
        pool = []
        for sym in PAIRS:
            tr = per.get((piv, sym, tf, costs), [])
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

    out = {"params": {"PIVS": PIVS, "DISP": DISP, "RR_FIXED": RR_FIXED,
                      "PAIRS": PAIRS, "BASE_TFS": BASE_TFS},
           "tables": {}, "bootstrap": {}}
    for tf in BASE_TFS:
        td = {}
        for piv in PIVS:
            vd = {}
            for costs in (True, False):
                ck = "con_costos" if costs else "sin_costos"
                vd[ck] = {"IS": metrics(collect(piv, tf, costs, "is")),
                          "OOS": metrics(collect(piv, tf, costs, "oos"))}
            td[f"piv{piv}"] = vd
        out["tables"][tf] = td
        out["bootstrap"][tf] = {f"piv{p}": bootstrap_p(collect(p, tf, True, "oos"))
                                for p in PIVS}

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
