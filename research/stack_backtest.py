"""Estudio 4 de la misión (2026-06-13): el STACK completo en 1h.

Las capas se validaron POR SEPARADO: régimen (VIX<25 + ADX>25, P=0.97), CDC en
contexto (P=0.81) y el TP de liquidez (estudio 1 de esta misión). ¿Suman al
combinarse o se canibalizan? Variantes sobre el mismo universo (1h, donde se
validaron):

  BASE        primer toque del POI, RR fijo 2 (referencia)
  REG         BASE ∩ régimen favorable al momento de la señal
  CDC         toque → esperar CDC (piv2) en ventana de 16 → entrada (RR 2)
  REG+CDC     ambas capas
  BASE_LIQ    BASE con TP de liquidez (RR efectivo >= 2)
  REGCDC_LIQ  el stack completo con TP de liquidez

Régimen anti-repaint: ADX(14) de 1h con velas cerradas hasta la señal; VIX =
último cierre DIARIO ya conocido (día anterior). Costos, 70/30, bootstrap y
walk-forward de 5 ventanas. Salida: research/stack_results.json
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
from research.regime_filter import adx as adx_calc      # noqa: E402

DATA_DIR = os.path.join(WT, "data")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "stack_results.json")
VIX_PATH = os.path.join(HERE, "data_macro", "vix_1d.json")

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
TF = "1h"
POI_SOURCES = ["1h", "4h", "1d"]

PIV = 2
DISP = 1.0
MAX_AGE_DAYS = 30
CDC_WINDOW = 16
STOP_BUF = 0.0005
RR_FIXED = 2.0
MIN_RR_LIQ = 2.0
VIX_MAX = 25.0
ADX_MIN = 25.0
IS_FRACTION = 0.70
WF_WINDOWS = 5
DAY_MS = 86_400_000

with open(VIX_PATH, "r", encoding="utf-8") as fh:
    _VIX = json.load(fh)
_VIX_T = [v["t"] for v in _VIX]


def vix_known(t_ms):
    """Último cierre diario del VIX YA conocido en t_ms (cierre de día anterior)."""
    i = bisect.bisect_left(_VIX_T, t_ms - DAY_MS + 1) - 1
    return _VIX[i]["c"] if i >= 0 else None


def load(symbol, tf):
    path = os.path.join(DATA_DIR, f"klines_{symbol}_{tf}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.sort(key=lambda c: c["t"])
    return data


def conf_prices(points, n):
    out = [None] * n
    evt = sorted(points, key=lambda p: p["confirm_idx"])
    pi = 0
    cur = None
    for j in range(n):
        while pi < len(evt) and evt[pi]["confirm_idx"] <= j:
            cur = evt[pi]["price"]
            pi += 1
        out[j] = cur
    return out


def liquidity_tp(direction, entry, idx_now, highs, lows, sh, sl):
    if direction == "long":
        cands = sorted((p for p in sh if p["confirm_idx"] <= idx_now and p["price"] > entry),
                       key=lambda p: p["price"])
        for p in cands:
            after = highs[p["idx"] + 1: idx_now + 1]
            if not after or max(after) < p["price"]:
                return p["price"]
    else:
        cands = sorted((p for p in sl if p["confirm_idx"] <= idx_now and p["price"] < entry),
                       key=lambda p: -p["price"])
        for p in cands:
            after = lows[p["idx"] + 1: idx_now + 1]
            if not after or min(after) > p["price"]:
                return p["price"]
    return None


def build(base, pois, use_cdc, use_reg, liq_tp):
    n = len(base)
    opens = [c["o"] for c in base]
    highs = [c["h"] for c in base]
    lows = [c["l"] for c in base]
    closes = [c["c"] for c in base]
    sh, sl = smc.swing_points(base, PIV)
    last_sh, last_sl = conf_prices(sh, n), conf_prices(sl, n)
    adx_arr = adx_calc(base, 14)
    max_age = MAX_AGE_DAYS * DAY_MS

    def reg_ok(j):
        a = adx_arr[j]
        if a is None or a <= ADX_MIN:
            return False
        v = vix_known(base[j]["t"])
        return v is None or v < VIX_MAX   # sin dato de VIX no se veta (igual que el vivo)

    def mk(j, poi):
        if j + 1 >= n:
            return None
        d = poi["dir"]
        stop = poi["stop"] * (1 - STOP_BUF) if d == "long" else poi["stop"] * (1 + STOP_BUF)
        if not liq_tp:
            return (j, d, stop, RR_FIXED)
        entry = opens[j + 1]
        risk = (entry - stop) if d == "long" else (stop - entry)
        if risk <= 0:
            return None
        tp = liquidity_tp(d, entry, j, highs, lows, sh, sl)
        if tp is None:
            return None
        rr = ((tp - entry) if d == "long" else (entry - tp)) / risk
        if rr < MIN_RR_LIQ:
            return None
        return (j, d, stop, round(rr, 3))

    sig = []
    pi = 0
    active = []
    for j in range(n - 1):
        tj = base[j]["t"]
        while pi < len(pois) and pois[pi]["t_conf"] <= tj:
            active.append(dict(pois[pi], used=False, armed=False, arm_bar=-1, dead=False))
            pi += 1
        if not active:
            continue
        kept = []
        for poi in active:
            if tj - poi["t_conf"] > max_age:
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
            if not use_cdc:
                if tapped and not poi["used"]:
                    poi["used"] = True
                    if use_reg and not reg_ok(j):
                        continue
                    s = mk(j, poi)
                    if s:
                        sig.append(s)
                continue
            if tapped and not poi["armed"] and not poi["used"] and not poi["dead"]:
                poi["armed"] = True
                poi["arm_bar"] = j
        if use_cdc:
            for poi in active:
                if not poi["armed"] or poi["used"] or poi["dead"]:
                    continue
                if j - poi["arm_bar"] > CDC_WINDOW:
                    poi["dead"] = True
                    continue
                d = poi["dir"]
                ref = last_sh[j] if d == "long" else last_sl[j]
                if ref is None:
                    continue
                if (d == "long" and closes[j] > ref) or (d == "short" and closes[j] < ref):
                    poi["used"] = True
                    if use_reg and not reg_ok(j):
                        continue
                    s = mk(j, poi)
                    if s:
                        sig.append(s)
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


VARIANTS = [
    ("BASE",       False, False, False),
    ("REG",        False, True,  False),
    ("CDC",        True,  False, False),
    ("REG+CDC",    True,  True,  False),
    ("BASE_LIQ",   False, False, True),
    ("REGCDC_LIQ", True,  True,  True),
]


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
        for vname, use_cdc, use_reg, liq in VARIANTS:
            sig = build(base, pois_all, use_cdc, use_reg, liq)
            per[(vname, sym)] = engine.simulate(base, sig, sym, TF, "stack",
                                                commission=0.0005, slippage=0.0002)
            print(f"{sym} {vname}: {len(sig)} señales", flush=True)

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

    out = {"params": {"TF": TF, "CDC_WINDOW": CDC_WINDOW, "VIX_MAX": VIX_MAX,
                      "ADX_MIN": ADX_MIN, "MIN_RR_LIQ": MIN_RR_LIQ},
           "tables": {}, "bootstrap": {}, "walk_forward": {}}
    for vname, *_ in VARIANTS:
        out["tables"][vname] = {"IS": metrics(collect(vname, "is")),
                                "OOS": metrics(collect(vname, "oos")),
                                "ALL": metrics(collect(vname, "all"))}
        out["bootstrap"][vname] = bootstrap_p(collect(vname, "oos"))
    t0 = min(s[0] for s in spans.values())
    t1 = max(s[1] for s in spans.values())
    edges = [t0 + (t1 - t0) * k / WF_WINDOWS for k in range(WF_WINDOWS + 1)]
    for vname, *_ in VARIANTS:
        allt = collect(vname, "all")
        wins = []
        for k in range(WF_WINDOWS):
            seg = [t for t in allt if edges[k] <= t["entry_time"] < edges[k + 1]]
            m = metrics(seg)
            wins.append({"n": m["trades"], "exp_R": m["expectancy_R"],
                         "PF": m["profit_factor"]})
        out["walk_forward"][vname] = wins

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
