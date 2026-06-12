"""Backtest de validación: ¿la CONFIRMACIÓN CDC del plan debe usar el swing
MICRO (PIV=2, lo validado) o el swing ESTRUCTURAL (PIV=10, lo que dibuja el
gráfico tras calibrar contra el indicador de referencia)?

Misma metodología del estudio CDC (variante B: armar al toque del POI, esperar
el CDC dentro de una ventana de 16 velas, entrar en la apertura siguiente):
solo cambia el pivote de los swings de referencia que el cierre debe romper.

  B2   CDC con swings PIV=2  (la regla validada: OOS 1h +0.066R, P=0.81)
  B10  CDC con swings PIV=10 (estructural, como los CDC dibujados)

Anti-repaint estricto idéntico (t_conf, confirm_idx, cierre → apertura
siguiente), costos 0.05%/lado + 0.02% slippage, RR fijo 2, split 70/30,
bootstrap 2000 en OOS. Salida: research/cdc_struct_results.json
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
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cdc_struct_results.json")

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
BASE_TFS = ["1h", "15m"]
POI_SOURCES = ["1h", "4h", "1d"]

PIV = 2            # pivote de detección de POIs (no cambia)
DISP = 1.0
MAX_AGE_DAYS = 30
CDC_WINDOW = 16
STOP_BUF = 0.0005
RR_FIXED = 2.0
IS_FRACTION = 0.70
CDC_PIVS = [2, 10]   # micro (validado) vs estructural (dibujado)


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


def build_signals(base, pois, cdc_piv):
    """Variante B del estudio CDC: arma al toque, espera el CDC (cierre rompe el
    último swing de referencia con pivote `cdc_piv`) dentro de la ventana."""
    n = len(base)
    highs = [c["h"] for c in base]
    lows = [c["l"] for c in base]
    closes = [c["c"] for c in base]
    sh, sl = smc.swing_points(base, cdc_piv)
    last_sh = conf_prices(sh, n)
    last_sl = conf_prices(sl, n)
    max_age = MAX_AGE_DAYS * 86_400_000

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
            if not poi["armed"] and not poi["used"] and not poi["dead"] \
                    and lows[j] <= poi["hi"] and highs[j] >= poi["lo"]:
                poi["armed"] = True
                poi["arm_bar"] = j
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
                stop = poi["stop"] * (1 - STOP_BUF) if d == "long" else poi["stop"] * (1 + STOP_BUF)
                sig.append((j, d, stop, RR_FIXED))
                poi["used"] = True
    return sig


def bootstrap_p(trades, n_boot=2000, seed=7):
    rs = [t["R"] for t in trades if t.get("R") is not None]
    if len(rs) < 20:
        return None
    rng = random.Random(seed)
    k = len(rs)
    pos = 0
    for _ in range(n_boot):
        if sum(rs[rng.randrange(k)] for _ in range(k)) > 0:
            pos += 1
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
            for cdc_piv in CDC_PIVS:
                sig = build_signals(base, pois_all, cdc_piv)
                for costs in (True, False):
                    comm, slip = (0.0005, 0.0002) if costs else (0.0, 0.0)
                    per[(cdc_piv, sym, tf, costs)] = engine.simulate(
                        base, list(sig), sym, tf, "cdc_s", commission=comm, slippage=slip)
                print(f"{sym} {tf} piv{cdc_piv}: {len(sig)} señales", flush=True)

    def collect(cdc_piv, tf, costs, period):
        pool = []
        for sym in PAIRS:
            tr = per.get((cdc_piv, sym, tf, costs), [])
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

    out = {"params": {"PIV": PIV, "DISP": DISP, "CDC_WINDOW": CDC_WINDOW,
                      "RR_FIXED": RR_FIXED, "CDC_PIVS": CDC_PIVS,
                      "IS_FRACTION": IS_FRACTION, "PAIRS": PAIRS,
                      "BASE_TFS": BASE_TFS},
           "tables": {}, "bootstrap": {}}
    for tf in BASE_TFS:
        td = {}
        for cdc_piv in CDC_PIVS:
            vd = {}
            for costs in (True, False):
                ck = "con_costos" if costs else "sin_costos"
                vd[ck] = {"IS": metrics(collect(cdc_piv, tf, costs, "is")),
                          "OOS": metrics(collect(cdc_piv, tf, costs, "oos")),
                          "ALL": metrics(collect(cdc_piv, tf, costs, "all"))}
            td[f"piv{cdc_piv}"] = vd
        out["tables"][tf] = td
        out["bootstrap"][tf] = {f"piv{p}": bootstrap_p(collect(p, tf, True, "oos"))
                                for p in CDC_PIVS}

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
