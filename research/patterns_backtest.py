"""Estudio 3 de la misión (2026-06-13): PATRONES del setup base.

Sobre el setup validado (primer toque del POI, RR fijo 2, descuento/premium
local), ¿dónde vive el edge? Desgloses OOS con costos:
  - por SESIÓN (Asia / Londres / NY / solape Londres+NY) — el engine ya tagea,
  - por DÍA de la semana,
  - por TF de ORIGEN del POI (corriendo universos de 1h, 4h y 1d por separado).

ADVERTENCIA metodológica: esto es EXPLORATORIO. Celdas chicas (n<80) no se
leen; cualquier celda "ganadora" es hipótesis para validar aparte, no filtro
para aplicar mañana. Salida: research/patterns_results.json
"""
from __future__ import annotations

import json
import os
import sys
import time

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import engine                       # noqa: E402
from modules.trading.strategies import detect_pois       # noqa: E402
from modules.trading.backtest import metrics             # noqa: E402

DATA_DIR = os.path.join(WT, "data")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patterns_results.json")

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
BASE_TFS = ["1h", "15m"]
POI_SOURCES = ["1h", "4h", "1d"]

PIV = 2
DISP = 1.0
MAX_AGE_DAYS = 30
STOP_BUF = 0.0005
RR_FIXED = 2.0
IS_FRACTION = 0.70
DAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


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


def run_universe(sources, source_keys, tf, sym):
    pois_all = []
    for k in source_keys:
        s = sources.get(k)
        if s:
            pois_all.extend(detect_pois(s, PIV, DISP))
    pois_all.sort(key=lambda x: x["t_conf"])
    base = sources.get(tf) or load(sym, tf)
    if not base or len(base) < 1000:
        return None, None
    sig = build_signals(base, pois_all)
    tr = engine.simulate(base, sig, sym, tf, "pat", commission=0.0005, slippage=0.0002)
    return tr, (base[0]["t"], base[-1]["t"])


def main():
    # Universo completo (para sesión/día) y por TF de origen (para el desglose).
    all_trades = {}     # (universe, tf) -> [trades OOS]
    universes = {"todas": POI_SOURCES, "solo_1h": ["1h"], "solo_4h": ["4h"], "solo_1d": ["1d"]}
    for sym in PAIRS:
        sources = {tfk: load(sym, tfk) for tfk in POI_SOURCES}
        for tf in BASE_TFS:
            for uname, keys in universes.items():
                tr, span = run_universe(sources, keys, tf, sym)
                if tr is None:
                    continue
                t0, t1 = span
                cut = t0 + IS_FRACTION * (t1 - t0)
                oos = [t for t in tr if t["entry_time"] > cut]
                all_trades.setdefault((uname, tf), []).extend(oos)
            print(f"{sym} {tf} ok", flush=True)

    def slice_metrics(trades, keyfn, keys):
        return {k: metrics([t for t in trades if keyfn(t) == k]) for k in keys}

    out = {"nota": "OOS con costos. Celdas con n<80 NO se leen (exploratorio).",
           "por_sesion": {}, "por_dia": {}, "por_tf_origen": {}}
    for tf in BASE_TFS:
        base_tr = all_trades.get(("todas", tf), [])
        sessions = sorted({t.get("session", "?") for t in base_tr})
        out["por_sesion"][tf] = slice_metrics(base_tr, lambda t: t.get("session", "?"), sessions)
        out["por_dia"][tf] = slice_metrics(
            base_tr, lambda t: DAYS[time.gmtime(t["entry_time"] / 1000).tm_wday], DAYS)
        out["por_tf_origen"][tf] = {
            u: metrics(all_trades.get((u, tf), [])) for u in ["solo_1h", "solo_4h", "solo_1d"]}

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
