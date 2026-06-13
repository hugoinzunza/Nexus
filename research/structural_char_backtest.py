"""Estudio 2b de la misión (2026-06-13): el CARÁCTER ESTRUCTURAL como filtro.

Petición explícita de Hugo: estudiar los fractales ESTRUCTURALES (los del
cambio de carácter mayor), no los pivotes chicos. Se computa por vela el
carácter del mercado con la MISMA lógica calibrada del gráfico (CDC mayor:
swings calificados — con reversión posterior — pegajosos hasta que un cierre
los rompe) y se mide el setup POI según su alineación:

  BASE      primer toque del POI, RR fijo 2 (referencia)
  ALINEADO  largos solo con carácter alcista, cortos solo con bajista
  CONTRA    lo opuesto (largos en carácter bajista, etc.)
  REVERSION entradas dentro de las 48 velas posteriores a un CDC mayor a favor
            (el timing "el carácter acaba de cambiar")

Pivote estructural: 10 (el calibrado) y 20 (sensibilidad). TF 1h. Anti-repaint
estricto. Costos, 70/30, bootstrap. Salida: research/structural_char_results.json
"""
from __future__ import annotations

import bisect
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
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "structural_char_results.json")

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
TF = "1h"
POI_SOURCES = ["1h", "4h", "1d"]

PIV = 2                 # detección de POIs (no cambia)
DISP = 1.0
MAX_AGE_DAYS = 30
STOP_BUF = 0.0005
RR_FIXED = 2.0
IS_FRACTION = 0.70
STRUCT_PIVS = [10, 20]  # escala estructural del carácter
RANGE_WINDOW = 400
REVERSION_BARS = 48     # ventana "CDC mayor reciente"
DAY_MS = 86_400_000


def load(symbol, tf):
    path = os.path.join(DATA_DIR, f"klines_{symbol}_{tf}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.sort(key=lambda c: c["t"])
    return data


def structural_character(base, struct_piv):
    """Por vela: carácter (+1 alcista / -1 bajista / 0 indefinido) y la vela del
    último CDC mayor. Misma lógica calibrada del gráfico: swings calificados
    (con pivote opuesto posterior confirmado), nivel pegajoso por lado, quiebre
    por CIERRE; el carácter es la dirección del último quiebre mayor."""
    n = len(base)
    sh, sl = smc.swing_points(base, struct_piv)
    closes = [c["c"] for c in base]
    INF = 10 ** 9

    def breaks(own, opp, is_high):
        opp_sorted = sorted(opp, key=lambda p: p["idx"])
        opp_idx = [p["idx"] for p in opp_sorted]
        suf = [INF] * (len(opp_sorted) + 1)
        for i in range(len(opp_sorted) - 1, -1, -1):
            suf[i] = min(opp_sorted[i]["confirm_idx"], suf[i + 1])
        avail = []
        for p in own:
            k = bisect.bisect_right(opp_idx, p["idx"])
            a = max(p["confirm_idx"], suf[k])
            if a < INF:
                avail.append((a, p))
        avail.sort(key=lambda t: t[0])
        out = []
        floor = -1
        cur = None
        pool = []
        pi = 0
        for j in range(n):
            added = False
            while pi < len(avail) and avail[pi][0] <= j:
                pool.append(avail[pi][1])
                pi += 1
                added = True
            if cur is not None and (cur["idx"] <= floor or j - cur["idx"] > 2 * RANGE_WINDOW):
                cur = None
            if cur is None or added:
                cands = [p for p in pool if p["idx"] > floor and p["idx"] >= j - RANGE_WINDOW]
                if cur is not None:
                    cands = [p for p in cands
                             if (p["price"] > cur["price"]) == is_high
                             and p["price"] != cur["price"]] + [cur]
                if cands:
                    cur = max(cands, key=lambda p: p["price"]) if is_high \
                        else min(cands, key=lambda p: p["price"])
            if cur is None:
                continue
            if (closes[j] > cur["price"]) if is_high else (closes[j] < cur["price"]):
                out.append(j)
                floor = j
                cur = None
        return out

    ups = breaks(sh, sl, True)
    downs = breaks(sl, sh, False)
    char = [0] * n
    last_cdc = [-1] * n
    events = sorted([(j, 1) for j in ups] + [(j, -1) for j in downs])
    ei = 0
    cur_char, cur_bar = 0, -1
    for j in range(n):
        while ei < len(events) and events[ei][0] <= j:
            cur_bar, cur_char = events[ei][0], events[ei][1]
            ei += 1
        char[j] = cur_char
        last_cdc[j] = cur_bar
    return char, last_cdc


def build_taps(base, pois):
    """Toques de POI (primer toque, regla validada) sin filtrar: (j, poi)."""
    n = len(base)
    highs = [c["h"] for c in base]
    lows = [c["l"] for c in base]
    max_age = MAX_AGE_DAYS * DAY_MS
    taps = []
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
            if poi["used"] or not (lows[j] <= poi["hi"] and highs[j] >= poi["lo"]):
                continue
            poi["used"] = True
            taps.append((j, dict(poi)))
    return taps


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
        for tfk in POI_SOURCES:
            s = load(sym, tfk)
            if s:
                sources[tfk] = s
        pois_all = []
        for s in sources.values():
            pois_all.extend(detect_pois(s, PIV, DISP))
        pois_all.sort(key=lambda x: x["t_conf"])
        base = sources.get(TF) or load(sym, TF)
        if not base or len(base) < 1000:
            continue
        spans[sym] = (base[0]["t"], base[-1]["t"])
        taps = build_taps(base, pois_all)
        for spv in STRUCT_PIVS:
            char, last_cdc = structural_character(base, spv)
            variants = {
                "BASE": lambda j, d: True,
                "ALINEADO": lambda j, d: char[j] == (1 if d == "long" else -1),
                "CONTRA": lambda j, d: char[j] == (-1 if d == "long" else 1),
                "REVERSION": lambda j, d: (char[j] == (1 if d == "long" else -1)
                                           and last_cdc[j] >= 0
                                           and j - last_cdc[j] <= REVERSION_BARS),
            }
            for vname, gate in variants.items():
                if vname == "BASE" and spv != STRUCT_PIVS[0]:
                    continue   # BASE no depende del pivote estructural
                sig = []
                for (j, poi) in taps:
                    d = poi["dir"]
                    if not gate(j, d):
                        continue
                    stop = poi["stop"] * (1 - STOP_BUF) if d == "long" \
                        else poi["stop"] * (1 + STOP_BUF)
                    sig.append((j, d, stop, RR_FIXED))
                key = vname if vname == "BASE" else f"{vname}_p{spv}"
                per[(key, sym)] = engine.simulate(base, sig, sym, TF, "sc",
                                                  commission=0.0005, slippage=0.0002)
        print(f"{sym} ok", flush=True)

    keys = ["BASE"] + [f"{v}_p{p}" for p in STRUCT_PIVS
                       for v in ["ALINEADO", "CONTRA", "REVERSION"]]

    def collect(v, period):
        pool = []
        for sym in PAIRS:
            tr = per.get((v, sym), [])
            sp = spans.get(sym)
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

    out = {"params": {"TF": TF, "STRUCT_PIVS": STRUCT_PIVS,
                      "REVERSION_BARS": REVERSION_BARS},
           "tables": {}, "bootstrap": {}}
    for k in keys:
        out["tables"][k] = {"IS": metrics(collect(k, "is")),
                            "OOS": metrics(collect(k, "oos"))}
        out["bootstrap"][k] = bootstrap_p(collect(k, "oos"))

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
