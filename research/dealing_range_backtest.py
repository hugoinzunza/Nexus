"""Backtest de investigación: ¿aporta el filtro de EQ GLOBAL (ventana 400) sobre
los POIs, además del descuento/premium LOCAL que ya valida detect_pois?

Contexto (pregunta de Hugo, 2026-06-12): el POI ya nace clasificado por el
equilibrio (fib 0.5) de SU dealing range local — el último swing high/low
confirmado al momento de formarse (detect_pois). Pero la capa de PLAN en vivo
(smc_live._tpsl) exige ADEMÁS que el POI quede del lado correcto del EQ de un
dealing range GLOBAL: el swing alto más alto y el swing bajo más bajo de las
últimas 400 velas de la TF de planeación (RANGE_PIV=10). Ese segundo filtro NO
estaba en el backtest validado. ¿Suma o solo recorta?

Variantes sobre el MISMO universo de señales (toque de POI, 1:1):
  A   POI solo (regla validada: descuento/premium LOCAL al formarse).
  B   A ∩ EQ global: el POI además está del lado correcto del EQ de la ventana
      de 400 velas en el momento del toque (lo que hace la capa de plan hoy).
  C   A \\ B: los toques que el filtro global HABRÍA descartado.

Anti-repaint idéntico al repo: POIs HTF solo con vela cerrada (t_conf); swings
con confirm_idx; el EQ global en la vela j usa solo swings confirmados <= j
dentro de las últimas RANGE_WINDOW velas; señal al cierre → entrada en la
apertura siguiente (engine.simulate). Costos 0.05%/lado + 0.02% slippage.
Split temporal 70/30 por par/TF + bootstrap (2000 remuestreos) en OOS.
Salida: research/dealing_range_results.json
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
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dealing_range_results.json")

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
BASE_TFS = ["15m", "1h"]
POI_SOURCES = ["1h", "4h", "1d"]

# Mismos parámetros del research previo (fijados a priori, sin tuneo).
PIV = 2
DISP = 1.0
MAX_AGE_DAYS = 30
STOP_BUF = 0.0005
RR_FIXED = 2.0
IS_FRACTION = 0.70
# Réplica de la capa de plan en vivo (smc_live).
RANGE_PIV = 10
RANGE_WINDOW = 400


def load(symbol, tf):
    path = os.path.join(DATA_DIR, f"klines_{symbol}_{tf}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.sort(key=lambda c: c["t"])
    return data


def global_eq_fn(base):
    """Devuelve eq(j): equilibrio del dealing range GLOBAL en la vela j, como lo
    calcula smc_live._range — swing alto MÁS ALTO y swing bajo MÁS BAJO de las
    últimas RANGE_WINDOW velas, usando solo pivotes confirmados (<= j)."""
    sh, sl = smc.swing_points(base, RANGE_PIV)
    sh = sorted(sh, key=lambda p: p["idx"])
    sl = sorted(sl, key=lambda p: p["idx"])

    def eq(j):
        lo_idx = j - RANGE_WINDOW
        his = [p["price"] for p in sh if lo_idx <= p["idx"] and p["confirm_idx"] <= j]
        los = [p["price"] for p in sl if lo_idx <= p["idx"] and p["confirm_idx"] <= j]
        if not his or not los:
            return None
        return (max(his) + min(los)) / 2

    return eq


def build_signals(base, pois):
    """Señales al PRIMER toque de cada POI (variante A del estudio CDC), con la
    marca de si el toque pasa el filtro de EQ global (variante B)."""
    n = len(base)
    highs = [c["h"] for c in base]
    lows = [c["l"] for c in base]
    eq = global_eq_fn(base)
    max_age = MAX_AGE_DAYS * 86_400_000

    sigA, sigB, sigC = [], [], []
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
            tapped = lows[j] <= poi["hi"] and highs[j] >= poi["lo"]
            if not tapped or poi["used"]:
                continue
            poi["used"] = True
            stop = poi["stop"] * (1 - STOP_BUF) if d == "long" else poi["stop"] * (1 + STOP_BUF)
            s = (j, d, stop, RR_FIXED)
            sigA.append(s)
            e = eq(j)
            mid = (poi["lo"] + poi["hi"]) / 2
            ok_global = e is not None and ((d == "long" and mid < e) or
                                           (d == "short" and mid > e))
            (sigB if ok_global else sigC).append(s)
    return sigA, sigB, sigC


def bootstrap_p(trades, n_boot=2000, seed=7):
    """P(expectativa > 0) por bootstrap sobre los R de los trades."""
    rs = [t["R"] for t in trades if t.get("R") is not None]
    if len(rs) < 20:
        return None
    rng = random.Random(seed)
    k = len(rs)
    pos = 0
    for _ in range(n_boot):
        s = sum(rs[rng.randrange(k)] for _ in range(k))
        if s > 0:
            pos += 1
    return round(pos / n_boot, 3)


def main():
    per = {}    # (variant, pair, tf, costs) -> trades
    spans = {}
    counts = {}
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
            sigA, sigB, sigC = build_signals(base, pois_all)
            counts[(sym, tf)] = (len(sigA), len(sigB), len(sigC))
            for vname, sig in [("A", sigA), ("B", sigB), ("C", sigC)]:
                for costs in (True, False):
                    comm, slip = (0.0005, 0.0002) if costs else (0.0, 0.0)
                    per[(vname, sym, tf, costs)] = engine.simulate(
                        base, list(sig), sym, tf, "dr", commission=comm, slippage=slip)
            print(f"{sym} {tf}: A={len(sigA)} B={len(sigB)} C={len(sigC)}", flush=True)

    def collect(variant, tf, costs, period):
        pool = []
        for sym in PAIRS:
            tr = per.get((variant, sym, tf, costs), [])
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
                      "RR_FIXED": RR_FIXED, "RANGE_PIV": RANGE_PIV,
                      "RANGE_WINDOW": RANGE_WINDOW, "IS_FRACTION": IS_FRACTION,
                      "PAIRS": PAIRS, "BASE_TFS": BASE_TFS,
                      "POI_SOURCES": POI_SOURCES},
           "counts": {f"{s}_{t}": c for (s, t), c in counts.items()},
           "tables": {}, "per_pair": {}, "bootstrap": {}}

    for tf in BASE_TFS:
        tdict = {}
        for variant in ["A", "B", "C"]:
            vd = {}
            for costs in (True, False):
                ck = "con_costos" if costs else "sin_costos"
                vd[ck] = {"IS": metrics(collect(variant, tf, costs, "is")),
                          "OOS": metrics(collect(variant, tf, costs, "oos")),
                          "ALL": metrics(collect(variant, tf, costs, "all"))}
            tdict[variant] = vd
        out["tables"][tf] = tdict
        out["bootstrap"][tf] = {
            v: bootstrap_p(collect(v, tf, True, "oos")) for v in ["A", "B", "C"]}
        pp = {}
        for sym in PAIRS:
            row = {}
            for variant in ["A", "B", "C"]:
                tr = per.get((variant, sym, tf, True), [])
                sp = spans.get((sym, tf))
                oos = []
                if sp:
                    t0, t1 = sp
                    cut = t0 + IS_FRACTION * (t1 - t0)
                    oos = [t for t in tr if t["entry_time"] > cut]
                row[variant] = {"OOS": metrics(oos)}
            pp[sym] = row
        out["per_pair"][tf] = pp

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
