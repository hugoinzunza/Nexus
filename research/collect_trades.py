"""Colector de trades base (SMC POI multi-TF) con FEATURES anti-repaint, para
testear filtros complementarios.

Reproduce EXACTAMENTE el criterio en vivo `smc_live.analyze` (el mismo del backtest
de Hugo: OOS 93 trades, +0.97R, PF 2.14 en BTC+ETH) pero sobre los 7 pares para
tener más muestra, y guarda para cada trade un SNAPSHOT de indicadores y de macro
calculado SOLO con velas/datos YA CERRADOS en la barra de decisión.

Salida: research/trades_features.json  → lista de trades, cada uno con:
  pair, sel_tf, poi_tf, dir, t (ms de la barra de decisión), rr, status, r_gross,
  entry, sl, risk_frac, session, y un bloque `feat` con los indicadores y macro.

Anti-repaint estricto (idéntico al backtest del setup):
  - En la barra i solo se ven velas cerradas (≤ i); las HTF solo si su cierre ≤ cierre de i.
  - El resultado (activación/TP/SL) se resuelve con barras POSTERIORES.
Costos: NO se aplican aquí (se guarda r_gross y risk_frac); el evaluador los modela.
"""
from __future__ import annotations

import bisect
import json
import os
import sys
import time

ROOT = "/Users/hugh/Nexus"          # repo principal (klines en data/, gitignored)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.trading import smc_live, indicators as ind        # noqa: E402
from modules.trading.backtest import session_of                # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macro as macro_mod                                       # noqa: E402

DATA_DIR = os.path.join(ROOT, "data")
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades_features.json")

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
POI_TFS = ["1D", "4h", "1h"]
SEL_TFS = ["1h", "4h"]
FILE_TF = {"1D": "1d", "4h": "4h", "1h": "1h"}
TF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1D": 86_400_000}

WIN = 400
BARS = {"1h": 4000, "4h": 2000}
MAX_FWD = {"1h": 240, "4h": 180}


def _load(symbol, tf):
    path = os.path.join(DATA_DIR, f"klines_{symbol}_{FILE_TF[tf]}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.sort(key=lambda c: c["t"])
    return data


def _htf_slice(series, ts, htf_ms, close_time, n):
    idx = bisect.bisect_right(ts, close_time - htf_ms)
    return series[max(0, idx - n):idx]


def _simulate(setup, sel, i, max_fwd):
    """Igual que run_setup_backtest._simulate: estado final + R bruto (rr o -1)."""
    long = setup["dir"] == "long"
    lo, hi, sl, tp, rr = setup["lo"], setup["hi"], setup["sl"], setup["tp"], setup["rr"]
    activated = False
    end = min(len(sel), i + 1 + max_fwd)
    for j in range(i + 1, end):
        h, l = sel[j]["h"], sel[j]["l"]
        if not activated:
            if (long and h >= tp) or ((not long) and l <= tp):
                if not (l <= hi and h >= lo):
                    return "anulada", None, j
            if l <= hi and h >= lo:
                activated = True
            else:
                continue
        if long:
            if l <= sl:
                return "perdida", -1.0, j
            if h >= tp:
                return "ganada", float(rr), j
        else:
            if h >= sl:
                return "perdida", -1.0, j
            if l <= tp:
                return "ganada", float(rr), j
    return ("abierto" if activated else "anulada"), None, end - 1


# --- ADX (Wilder) -------------------------------------------------------
def adx(candles, period=14):
    n = len(candles)
    out = [None] * n
    if n < 2 * period + 1:
        return out
    tr = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        h, l = candles[i]["h"], candles[i]["l"]
        ph, pl, pc = candles[i - 1]["h"], candles[i - 1]["l"], candles[i - 1]["c"]
        up = h - ph
        dn = pl - l
        plus_dm[i] = up if (up > dn and up > 0) else 0.0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    # Wilder smoothing
    atr = sum(tr[1:period + 1])
    pdm = sum(plus_dm[1:period + 1])
    mdm = sum(minus_dm[1:period + 1])
    dxs = []
    for i in range(period + 1, n):
        atr = atr - atr / period + tr[i]
        pdm = pdm - pdm / period + plus_dm[i]
        mdm = mdm - mdm / period + minus_dm[i]
        if atr <= 0:
            continue
        pdi = 100 * pdm / atr
        mdi = 100 * mdm / atr
        denom = pdi + mdi
        dx = 100 * abs(pdi - mdi) / denom if denom > 0 else 0.0
        dxs.append((i, dx))
        if len(dxs) >= period:
            window = [d for (_, d) in dxs[-period:]]
            out[i] = sum(window) / period
    return out


def _ema_align(ef, es, i, long):
    """+1 si las EMAs apoyan la dirección, -1 si en contra (None si faltan datos)."""
    if i >= len(ef) or i >= len(es) or ef[i] is None or es[i] is None:
        return None
    bullish = ef[i] > es[i]
    return 1 if (bullish == long) else -1


def _precompute(sel):
    """Indicadores de la TF de selección, alineados por índice de vela."""
    closes = [c["c"] for c in sel]
    vols = [c["v"] for c in sel]
    return {
        "ema9": ind.ema(closes, 9), "ema21": ind.ema(closes, 21),
        "ema20": ind.ema(closes, 20), "ema50": ind.ema(closes, 50),
        "ema200": ind.ema(closes, 200), "ema53": ind.ema(closes, 53),
        "rsi": ind.rsi(closes, 14),
        "adx": adx(sel, 14),
        "volsma": ind.sma(vols, 20),
        "closes": closes, "vols": vols,
    }


def _features(arr, i, long, close_time, mac):
    c = arr["closes"][i]
    rsi = arr["rsi"][i]
    adxv = arr["adx"][i]
    vol = arr["vols"][i]
    volsma = arr["volsma"][i]
    e200 = arr["ema200"][i]
    e50 = arr["ema50"][i]
    # Pendiente EMA200 (20 velas), normalizada por precio.
    slope = None
    if i >= 20 and e200 is not None and arr["ema200"][i - 20] is not None and c:
        slope = (e200 - arr["ema200"][i - 20]) / c
    feat = {
        "ema_9_21": _ema_align(arr["ema9"], arr["ema21"], i, long),
        "ema_20_50": _ema_align(arr["ema20"], arr["ema50"], i, long),
        "ema_50_200": _ema_align(arr["ema50"], arr["ema200"], i, long),
        "ema_53_200": _ema_align(arr["ema53"], arr["ema200"], i, long),
        # Precio respecto a EMA200/50 a favor de la dirección.
        "price_vs_ema200": (1 if ((c > e200) == long) else -1) if e200 is not None else None,
        "price_vs_ema50": (1 if ((c > e50) == long) else -1) if e50 is not None else None,
        "ema200_slope_dir": (1 if ((slope > 0) == long) else -1) if slope is not None else None,
        "rsi": round(rsi, 1) if rsi is not None else None,
        "adx": round(adxv, 1) if adxv is not None else None,
        "vol_ratio": round(vol / volsma, 2) if volsma else None,
        # Macro (alineado al cierre de la barra de decisión, anti-repaint).
        "vix": mac.vix_at(close_time),
        "btc_spx_corr30": mac.corr_at(close_time),
        "btc_above_ma200": mac.btc_above_ma200_at(close_time),
    }
    return feat


def run_pass(symbol, sel_tf, series, ts_map, mac):
    sel = series[(symbol, sel_tf)]
    if not sel or len(sel) < WIN + 5:
        return []
    n_bars = min(BARS.get(sel_tf, 3000), len(sel) - WIN - MAX_FWD.get(sel_tf, 200))
    if n_bars <= 0:
        return []
    start = len(sel) - MAX_FWD.get(sel_tf, 200) - n_bars
    sel_ms = TF_MS[sel_tf]
    arr = _precompute(sel)
    out = []
    last_res = {}
    for i in range(start, len(sel) - 1):
        close_time = sel[i]["t"] + sel_ms
        htf_map = {tf: _htf_slice(series[(symbol, tf)], ts_map[(symbol, tf)],
                                  TF_MS[tf], close_time, WIN) for tf in POI_TFS}
        sel_win = sel[max(0, i - WIN + 1):i + 1]
        last = sel[i]["c"]
        try:
            analysis = smc_live.analyze(sel_win, htf_map, last, sel_tf)
        except Exception:  # noqa: BLE001
            continue
        plan = analysis.get("tpsl")
        if not plan:
            continue
        key = f"{plan['tf']}:{plan['dir']}:{round(plan['entry_lo'], 2)}"
        if key in last_res and i <= last_res[key]:
            continue
        long = plan["dir"] == "long"
        entry = (plan["entry_lo"] + plan["entry_hi"]) / 2.0
        sl = plan["sl"]
        risk_frac = abs(entry - sl) / entry if entry else 0.0
        setup = {"dir": plan["dir"], "lo": plan["entry_lo"], "hi": plan["entry_hi"],
                 "sl": sl, "tp": plan["tp"], "rr": plan["rr"]}
        status, r, res_idx = _simulate(setup, sel, i, MAX_FWD.get(sel_tf, 200))
        last_res[key] = res_idx
        feat = _features(arr, i, long, close_time, mac)
        out.append({
            "pair": symbol, "sel_tf": sel_tf, "poi_tf": plan["tf"], "dir": plan["dir"],
            "t": sel[i]["t"], "rr": plan["rr"], "status": status, "r_gross": r,
            "entry": round(entry, 4), "sl": round(sl, 4), "risk_frac": round(risk_frac, 5),
            "session": session_of(sel[i + 1]["t"] if i + 1 < len(sel) else sel[i]["t"]),
            "feat": feat,
        })
    return out


def main():
    t_all = time.time()
    print("Cargando klines (7 pares × 1h/4h/1d)…")
    series, ts_map = {}, {}
    for sym in PAIRS:
        for tf in set(POI_TFS) | set(SEL_TFS):
            s = _load(sym, tf)
            if s is None:
                print(f"  falta {sym} {tf}")
                continue
            series[(sym, tf)] = s
            ts_map[(sym, tf)] = [c["t"] for c in s]
    print("Cargando macro (SPX/VIX/BTC)…")
    mac = macro_mod.Macro()

    all_trades = []
    for sym in PAIRS:
        for sel_tf in SEL_TFS:
            if (sym, sel_tf) not in series:
                continue
            t0 = time.time()
            tr = run_pass(sym, sel_tf, series, ts_map, mac)
            all_trades.extend(tr)
            print(f"  {sym} {sel_tf}: {len(tr)} registros en {time.time()-t0:.1f}s")

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(all_trades, fh, ensure_ascii=False)
    closed = [t for t in all_trades if t["status"] in ("ganada", "perdida")]
    print(f"\nTotal registros: {len(all_trades)} · cerrados: {len(closed)} · "
          f"{time.time()-t_all:.1f}s\n→ {OUT_PATH}")


if __name__ == "__main__":
    main()
