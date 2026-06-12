"""Backtest histórico del MISMO criterio del indicador SMC en vivo.

Reutiliza EXACTAMENTE `smc_live.analyze` (POI multi-TF + zona correcta + TP a la
siguiente liquidez sin barrer + filtro R:R>=2) sobre velas históricas de Binance.

Anti-repaint:
  - En cada barra de decisión solo se usan velas YA CERRADAS (la barra que acaba de
    cerrar y anteriores); las HTF se incluyen solo si su cierre <= cierre de la barra.
  - El resultado (activación, TP/SL) se resuelve únicamente con barras POSTERIORES.

Una entrada solo cuenta como ganada/perdida si el precio realmente entró a la zona
(se activó); si el precio se va al TP sin llenarse, es "anulada" (no cuenta). Si una
misma barra toca SL y TP, se asume SL primero (conservador).

Split temporal in-sample / out-of-sample (70/30) por fecha de registro.

Genera modules/trading/setup_backtest_results.json (servido por la API y mostrado
en el Diario como referencia). Correr:  python3 -m modules.trading.run_setup_backtest
"""
from __future__ import annotations

import bisect
import json
import os
import time

from . import smc_live

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup_backtest_results.json")

# (nombre live, símbolo Binance). Mismos instrumentos que el indicador en vivo.
SYMBOLS = [("BTC_USDT", "BTCUSDT"), ("ETH_USDT", "ETHUSDT")]
POI_TFS = ["1D", "4h", "1h"]            # TFs de detección de POIs (= smc_live.POI_TFS)
SEL_TFS = ["1h", "4h"]                  # TFs de planeación (= setup_tfs en vivo)
FILE_TF = {"1D": "1d", "4h": "4h", "1h": "1h", "15m": "15m"}
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1D": 86_400_000}

WIN = 400                              # velas que ve el indicador (igual que en vivo)
BARS = {"1h": 4000, "4h": 2000}        # ventana de backtest por TF de planeación
MAX_FWD = {"1h": 240, "4h": 180}       # barras hacia adelante para resolver el trade
IS_FRAC = 0.70                         # 70% in-sample / 30% out-of-sample (por tiempo)


def _load(symbol: str, tf: str):
    path = os.path.join(DATA_DIR, f"klines_{symbol}_{FILE_TF[tf]}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.sort(key=lambda c: c["t"])
    return data


def _htf_slice(series, ts, htf_ms, close_time, n):
    """Velas HTF YA CERRADAS al `close_time` (anti-repaint): t + intervalo <= close_time."""
    idx = bisect.bisect_right(ts, close_time - htf_ms)
    return series[max(0, idx - n):idx]


def _simulate(setup, sel, i, max_fwd):
    """Resuelve un setup con barras POSTERIORES (h/l). Devuelve estado final y R."""
    long = setup["dir"] == "long"
    lo, hi, sl, tp, rr = setup["lo"], setup["hi"], setup["sl"], setup["tp"], setup["rr"]
    activated = False
    end = min(len(sel), i + 1 + max_fwd)
    for j in range(i + 1, end):
        h, l = sel[j]["h"], sel[j]["l"]
        if not activated:
            # ¿el precio se fue al TP sin llenar la entrada? → anulada (oportunidad perdida).
            if (long and h >= tp) or ((not long) and l <= tp):
                # salvo que la misma barra también haya entrado a la zona:
                if not (l <= hi and h >= lo):
                    return "anulada", None, j
            # ¿la barra entra a la zona del POI? → activada.
            if l <= hi and h >= lo:
                activated = True
            else:
                continue
        # Activada: resolver TP/SL (si una barra toca ambos, SL primero = conservador).
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
    # No se resolvió en la ventana: si llegó a activarse queda "abierto", sino "anulada".
    return ("abierto" if activated else "anulada"), None, end - 1


def _run_pass(symbol, sel_tf, htf_series, htf_ts):
    sel = htf_series[sel_tf]
    if not sel or len(sel) < WIN + 5:
        return []
    n_bars = min(BARS.get(sel_tf, 3000), len(sel) - WIN - MAX_FWD.get(sel_tf, 200))
    if n_bars <= 0:
        return []
    start = len(sel) - MAX_FWD.get(sel_tf, 200) - n_bars
    sel_ms = TF_MS[sel_tf]
    trades = []
    last_res = {}   # clave de zona → índice hasta el que sigue "ocupada" (evita duplicados)
    for i in range(start, len(sel) - 1):
        close_time = sel[i]["t"] + sel_ms
        htf_map = {tf: _htf_slice(htf_series[tf], htf_ts[tf], TF_MS[tf], close_time, WIN)
                   for tf in POI_TFS}
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
            continue   # zona aún ocupada por un registro anterior → no duplicar
        setup = {"dir": plan["dir"], "lo": plan["entry_lo"], "hi": plan["entry_hi"],
                 "sl": plan["sl"], "tp": plan["tp"], "rr": plan["rr"]}
        status, r, res_idx = _simulate(setup, sel, i, MAX_FWD.get(sel_tf, 200))
        last_res[key] = res_idx
        trades.append({"pair": symbol, "sel_tf": sel_tf, "poi_tf": plan["tf"],
                       "dir": plan["dir"], "t": sel[i]["t"], "rr": plan["rr"],
                       "status": status, "r": r})
    return trades


def _stats(trades):
    closed = [t for t in trades if t["status"] in ("ganada", "perdida")]
    wins = [t for t in closed if t["status"] == "ganada"]
    losses = [t for t in closed if t["status"] == "perdida"]
    n = len(closed)
    gw = sum(t["r"] for t in wins)
    gl = abs(sum(t["r"] for t in losses))
    total_r = sum(t["r"] for t in closed)
    return {
        "trades": n,
        "ganadas": len(wins),
        "perdidas": len(losses),
        "anuladas": sum(1 for t in trades if t["status"] == "anulada"),
        "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
        "avg_r": round(total_r / n, 2) if n else 0.0,
        "total_r": round(total_r, 1),
        "pf": (round(gw / gl, 2) if gl > 0 else None),
    }


def main():
    print("Backtest del criterio SMC (mismo que en vivo) · anti-repaint · IS/OOS")
    all_trades = []
    by_pair = {}
    for live_name, symbol in SYMBOLS:
        htf_series = {tf: _load(symbol, tf) for tf in set(POI_TFS) | set(SEL_TFS)}
        if any(htf_series[tf] is None for tf in POI_TFS):
            print(f"  {symbol}: faltan klines, lo salto")
            continue
        htf_ts = {tf: [c["t"] for c in htf_series[tf]] for tf in htf_series}
        pair_trades = []
        for sel_tf in SEL_TFS:
            t0 = time.time()
            tr = _run_pass(symbol, sel_tf, htf_series, htf_ts)
            pair_trades.extend(tr)
            print(f"  {symbol} {sel_tf}: {len(tr)} registros en {time.time()-t0:.1f}s")
        by_pair[live_name] = _stats(pair_trades)
        all_trades.extend(pair_trades)

    if not all_trades:
        print("Sin trades; ¿faltan los klines en data/? Genera con el backtest normal.")
        return

    # Split temporal in-sample / out-of-sample por fecha de registro.
    times = sorted(t["t"] for t in all_trades)
    split = times[0] + IS_FRAC * (times[-1] - times[0])
    is_tr = [t for t in all_trades if t["t"] <= split]
    oos_tr = [t for t in all_trades if t["t"] > split]

    result = {
        "generated_at": int(time.time() * 1000),
        "params": {"win": WIN, "min_rr": smc_live.MIN_RR, "is_frac": IS_FRAC,
                   "sel_tfs": SEL_TFS, "poi_tfs": POI_TFS, "max_fwd": MAX_FWD},
        "bars_per_inst": sum(BARS.get(tf, 0) for tf in SEL_TFS),
        "in_sample": _stats(is_tr),
        "out_sample": _stats(oos_tr),
        "all": _stats(all_trades),
        "by_pair": by_pair,
        "note": ("Mismo criterio que el indicador en vivo. Una entrada cuenta solo si "
                 "el precio entró a la zona (se activó). Pasado no garantiza futuro."),
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"\n→ {OUT_PATH}")
    for k in ("in_sample", "out_sample", "all"):
        s = result[k]
        print(f"  {k:11} trades {s['trades']:4} · win {s['win_rate']:5}% · "
              f"R prom {s['avg_r']:5} · PF {s['pf']} · R acum {s['total_r']}")


if __name__ == "__main__":
    main()
