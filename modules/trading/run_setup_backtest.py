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

# (nombre live, símbolo Binance). TODOS los pares con klines persistidos: así el
# veredicto dice si el edge generaliza o es solo de BTC/ETH.
SYMBOLS = [("BTC_USDT", "BTCUSDT"), ("ETH_USDT", "ETHUSDT"), ("SOL_USDT", "SOLUSDT"),
           ("BNB_USDT", "BNBUSDT"), ("XRP_USDT", "XRPUSDT"), ("ADA_USDT", "ADAUSDT"),
           ("DOGE_USDT", "DOGEUSDT")]
POI_TFS = ["1D", "4h", "1h"]            # TFs de detección de POIs (= smc_live.POI_TFS)
SEL_TFS = ["1h", "4h"]                  # TFs de planeación (= setup_tfs en vivo)
FILE_TF = {"1D": "1d", "4h": "4h", "1h": "1h", "15m": "15m"}
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1D": 86_400_000}

WIN = 400                              # velas que ve el indicador (igual que en vivo)
# Ventana de backtest por TF: usa TODA la historia persistida (~4 años) para que el
# veredicto cubra regímenes distintos (bear 2022, recuperación 2023, bull 2024), no
# solo el último tramo. La detección por barra es local (WIN velas), así que esto
# solo amplía cuántas barras de decisión se evalúan.
BARS = {"1h": 40000, "4h": 12000}
MAX_FWD = {"1h": 240, "4h": 180}       # barras hacia adelante para resolver el trade
IS_FRAC = 0.70                         # 70% in-sample / 30% out-of-sample (por tiempo)

# Variantes de SALIDA ESCALONADA (scale-out) a comparar contra la actual (100% al TP
# lejano). Cada leg = (objetivo, fracción). "far" = la liquidez lejana (el TP único de
# hoy). be_after = cuántos legs deben llenarse antes de mover el SL a break-even.
SCALE_VARIANTS = {
    "actual":        {"legs": [("far", 1.0)], "be_after": 99},
    "tu_idea":       {"legs": [(1.0, 0.5), (2.0, 0.25), ("far", 0.25)], "be_after": 1},
    "runner_agres":  {"legs": [(1.0, 0.5), (3.0, 0.25), ("far", 0.25)], "be_after": 1},
    "be_tardio":     {"legs": [(1.0, 0.5), (2.0, 0.25), ("far", 0.25)], "be_after": 2},
}


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
    """Resuelve un setup con barras POSTERIORES (h/l). Devuelve (estado, R, res_idx, act_idx)."""
    long = setup["dir"] == "long"
    lo, hi, sl, tp, rr = setup["lo"], setup["hi"], setup["sl"], setup["tp"], setup["rr"]
    activated = False
    act_idx = None
    end = min(len(sel), i + 1 + max_fwd)
    for j in range(i + 1, end):
        h, l = sel[j]["h"], sel[j]["l"]
        if not activated:
            # ¿el precio se fue al TP sin llenar la entrada? → anulada (oportunidad perdida).
            if (long and h >= tp) or ((not long) and l <= tp):
                # salvo que la misma barra también haya entrado a la zona:
                if not (l <= hi and h >= lo):
                    return "anulada", None, j, None
            # ¿la barra entra a la zona del POI? → activada.
            if l <= hi and h >= lo:
                activated = True
                act_idx = j
            else:
                continue
        # Activada: resolver TP/SL (si una barra toca ambos, SL primero = conservador).
        if long:
            if l <= sl:
                return "perdida", -1.0, j, act_idx
            if h >= tp:
                return "ganada", float(rr), j, act_idx
        else:
            if h >= sl:
                return "perdida", -1.0, j, act_idx
            if l <= tp:
                return "ganada", float(rr), j, act_idx
    # No se resolvió en la ventana: si llegó a activarse queda "abierto", sino "anulada".
    return ("abierto" if activated else "anulada"), None, end - 1, act_idx


def _simulate_scaled(setup, sel, act_idx, end, legs, be_after):
    """R final de un setup YA ACTIVADO con salida escalonada + break-even.

    `act_idx` = barra donde se activó; `end` = límite de la ventana. Camina las barras
    POSTERIORES cerrando fracciones al tocar cada leg; mueve el SL a break-even cuando
    se llenan `be_after` legs. Conservador: dentro de una barra el stop pega antes que
    el TP. Devuelve la R total realizada (ponderada por las fracciones)."""
    long = setup["dir"] == "long"
    entry, sl, tp, rr = setup["entry"], setup["sl"], setup["tp"], setup["rr"]
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    # Construye los objetivos: (precio, R, fracción). Un leg intermedio que caiga más
    # allá del TP lejano se colapsa al TP lejano (no puede estar más lejos que el target).
    targets = []
    for level, frac in legs:
        if level == "far":
            pr, R = tp, float(rr)
        else:
            R = float(level)
            if R >= rr:
                pr = tp; R = float(rr)
            else:
                pr = entry + R * risk if long else entry - R * risk
        targets.append([pr, R, frac, False])      # [precio, R, fracción, tomado]
    targets.sort(key=lambda x: x[1])               # del más cercano al más lejano
    remaining, realized, sl_cur, taken = 1.0, 0.0, sl, 0
    for j in range(act_idx, end):
        h, l = sel[j]["h"], sel[j]["l"]
        # Stop primero (conservador). En break-even el SL = entrada → aporta 0R.
        if (long and l <= sl_cur) or ((not long) and h >= sl_cur):
            stop_r = (sl_cur - entry) / risk if long else (entry - sl_cur) / risk
            realized += remaining * stop_r
            return round(realized, 4)
        for tg in targets:
            if tg[3]:
                continue
            if (long and h >= tg[0]) or ((not long) and l <= tg[0]):
                realized += tg[2] * tg[1]
                remaining -= tg[2]
                tg[3] = True
                taken += 1
                if taken >= be_after and sl_cur != entry:
                    sl_cur = entry          # SL a break-even
                if remaining <= 1e-9:
                    return round(realized, 4)
    # Ventana agotada con remanente abierto: lo cierro a mercado (último cierre).
    last = sel[end - 1]["c"]
    last_r = (last - entry) / risk if long else (entry - last) / risk
    realized += remaining * last_r
    return round(realized, 4)


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
        key = f"{plan['tf']}:{plan['dir']}:{plan['entry_lo']}"
        if key in last_res and i <= last_res[key]:
            continue   # zona aún ocupada por un registro anterior → no duplicar
        entry = plan.get("entry") or (plan["entry_lo"] + plan["entry_hi"]) / 2
        setup = {"dir": plan["dir"], "lo": plan["entry_lo"], "hi": plan["entry_hi"],
                 "sl": plan["sl"], "tp": plan["tp"], "rr": plan["rr"], "entry": entry}
        status, r, res_idx, act_idx = _simulate(setup, sel, i, MAX_FWD.get(sel_tf, 200))
        last_res[key] = res_idx
        sl_pct = abs(entry - plan["sl"]) / entry if entry else None   # distancia al SL
        rec = {"pair": symbol, "sel_tf": sel_tf, "poi_tf": plan["tf"],
               "dir": plan["dir"], "t": sel[i]["t"], "rr": plan["rr"],
               "status": status, "r": r, "sl_pct": sl_pct}
        # Variantes de scale-out SOLO sobre trades que se activaron y resolvieron
        # (mismo universo que el baseline ganada/perdida) → comparación apples-to-apples.
        if status in ("ganada", "perdida") and act_idx is not None:
            end = min(len(sel), i + 1 + MAX_FWD.get(sel_tf, 200))
            rec["scaled"] = {name: _simulate_scaled(setup, sel, act_idx, end,
                                                    v["legs"], v["be_after"])
                             for name, v in SCALE_VARIANTS.items()}
        trades.append(rec)
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


def _cap_sensitivity(closed_sorted):
    """¿El edge vive en los winners grandes? Capa la R de los ganadores y mira qué pasa."""
    rs = [t["r"] for t in closed_sorted]
    out = {}
    for cap in (None, 15, 10, 5, 3):
        tot = sum((min(r, cap) if (cap and r > 0) else r) for r in rs)
        out["sin_tope" if cap is None else f"{cap}R"] = {
            "avg_r": round(tot / len(rs), 2) if rs else 0.0, "total_r": round(tot, 1)}
    return out


def _risk_r(closed_sorted):
    """Drawdown y racha perdedora más larga en R (curva de R sin compounding)."""
    eq = peak = mdd = streak = max_streak = 0
    for t in closed_sorted:
        eq += t["r"]; peak = max(peak, eq); mdd = min(mdd, eq - peak)
        streak = streak + 1 if t["r"] < 0 else 0
        max_streak = max(max_streak, streak)
    return {"max_drawdown_r": round(mdd, 1), "max_losing_streak": max_streak}


def _equity_sim(closed_sorted, capital=38000.0, risk_pct=0.02, cost_rate=0.0014,
                cap=None, compounding=True, curve_points=120):
    """Traduce los trades (en orden temporal) a PLATA real con sizing de riesgo fijo.

    - risk_pct: cuánto del capital se arriesga por trade (la distancia entrada→SL).
    - cost_rate: comisión sobre el NOCIONAL (igual que la cuenta paper, 0,14%).
    - compounding: True = riesgo sobre el capital vivo; False = riesgo sobre el inicial.
    Devuelve capital final, retorno %, peor drawdown % y una curva submuestreada.
    """
    eq = capital
    peak = eq
    max_dd = 0.0
    blown = False
    curve = [eq]
    n = len(closed_sorted)
    step = max(1, n // curve_points)
    for idx, t in enumerate(closed_sorted):
        r = t["r"]
        if cap and r > 0:
            r = min(r, cap)
        base = eq if compounding else capital
        risk_amt = base * risk_pct
        sl_pct = t.get("sl_pct") or 0.02
        notional = risk_amt / sl_pct if sl_pct else 0.0
        cost = notional * cost_rate
        eq += risk_amt * r - cost
        if eq <= 0:
            eq = 0.0; blown = True
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
        if idx % step == 0 or idx == n - 1:
            curve.append(round(eq, 2))
        if blown:
            break
    return {
        "capital_inicial": capital,
        "risk_pct": risk_pct,
        "compounding": compounding,
        "cap": cap,
        "capital_final": round(eq, 2),
        "retorno_pct": round((eq / capital - 1) * 100, 1) if capital else 0.0,
        "max_drawdown_pct": round(max_dd * 100, 1),
        "quebro": blown,
        "curve": curve,
    }


def _scale_comparison(closed_with_scaled, capital=38000.0, risk_pct=0.02):
    """Compara cada variante de scale-out sobre el MISMO conjunto de trades.
    Métricas en R + traducción a $ con 2% de riesgo fijo (lo realista)."""
    out = {}
    for name in SCALE_VARIANTS:
        rows = []
        for t in closed_with_scaled:
            r = t["scaled"].get(name)
            if r is None:
                continue
            rows.append({"r": r, "sl_pct": t.get("sl_pct"), "t": t["t"]})
        rows.sort(key=lambda x: x["t"])
        rs = [x["r"] for x in rows]
        n = len(rs)
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r < 0]
        gw, gl = sum(wins), abs(sum(losses))
        eq = _equity_sim(rows, capital, risk_pct, compounding=False)
        out[name] = {
            "trades": n,
            "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
            "avg_r": round(sum(rs) / n, 2) if n else 0.0,
            "total_r": round(sum(rs), 1),
            "pf": round(gw / gl, 2) if gl > 0 else None,
            "risk": _risk_r(rows),
            "capital_final": eq["capital_final"],
            "retorno_pct": eq["retorno_pct"],
            "max_drawdown_pct": eq["max_drawdown_pct"],
            "curve": eq["curve"],
        }
    return out


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
        pair_closed = sorted((t for t in pair_trades if t["status"] in ("ganada", "perdida")),
                             key=lambda t: t["t"])
        st = _stats(pair_trades)
        st["risk"] = _risk_r(pair_closed)
        st["cap_sensitivity"] = _cap_sensitivity(pair_closed)
        by_pair[live_name] = st
        all_trades.extend(pair_trades)

    if not all_trades:
        print("Sin trades; ¿faltan los klines en data/? Genera con el backtest normal.")
        return

    # Split temporal in-sample / out-of-sample por fecha de registro.
    times = sorted(t["t"] for t in all_trades)
    split = times[0] + IS_FRAC * (times[-1] - times[0])
    is_tr = [t for t in all_trades if t["t"] <= split]
    oos_tr = [t for t in all_trades if t["t"] > split]

    # Desglose por AÑO (¿el edge aguanta distintos regímenes o es de uno solo?).
    closed_sorted = sorted((t for t in all_trades if t["status"] in ("ganada", "perdida")),
                           key=lambda t: t["t"])
    by_year = {}
    for t in closed_sorted:
        by_year.setdefault(time.strftime("%Y", time.gmtime(t["t"] / 1000)), []).append(t)
    by_year = {y: _stats(ts) for y, ts in by_year.items()}

    # Sensibilidad al CAP de R y dureza en R (drawdown, racha) sobre TODO el conjunto.
    cap_sensitivity = _cap_sensitivity(closed_sorted)
    risk_r = _risk_r(closed_sorted)

    # Comparación de SALIDA ESCALONADA (scale-out) vs la actual, mismos trades.
    closed_with_scaled = [t for t in closed_sorted if "scaled" in t]
    scale_out = _scale_comparison(closed_with_scaled)

    # Traducción a PLATA: ¿qué le pasa a $38k con sizing de riesgo fijo? Compara
    # 1%/2%/3% por trade, compounding vs fijo, y "dejar correr" vs capar en 3R.
    CAP38 = 38000.0
    equity = {
        "fijo_2pct": _equity_sim(closed_sorted, CAP38, 0.02, compounding=False),
        "comp_1pct": _equity_sim(closed_sorted, CAP38, 0.01, compounding=True),
        "comp_2pct": _equity_sim(closed_sorted, CAP38, 0.02, compounding=True),
        "comp_3pct": _equity_sim(closed_sorted, CAP38, 0.03, compounding=True),
        "comp_2pct_cap3R": _equity_sim(closed_sorted, CAP38, 0.02, compounding=True, cap=3),
    }

    result = {
        "generated_at": int(time.time() * 1000),
        "params": {"win": WIN, "min_rr": smc_live.MIN_RR, "is_frac": IS_FRAC,
                   "sel_tfs": SEL_TFS, "poi_tfs": POI_TFS, "max_fwd": MAX_FWD,
                   "symbols": [s[0] for s in SYMBOLS]},
        "bars_per_inst": sum(BARS.get(tf, 0) for tf in SEL_TFS),
        "span": {"from": closed_sorted[0]["t"], "to": closed_sorted[-1]["t"]} if closed_sorted else None,
        "in_sample": _stats(is_tr),
        "out_sample": _stats(oos_tr),
        "all": _stats(all_trades),
        "by_pair": by_pair,
        "by_year": by_year,
        "cap_sensitivity": cap_sensitivity,
        "risk": risk_r,
        "equity": equity,
        "scale_out": scale_out,
        "note": ("Mismo criterio que el indicador en vivo, sobre 7 pares y ~4 años. "
                 "Una entrada cuenta solo si el precio entró a la zona (se activó). "
                 "El edge depende de dejar correr los winners a la liquidez lejana "
                 "(ver cap_sensitivity): capar en 3R lo vuelve negativo. La sección "
                 "equity traduce a $ con sizing de riesgo fijo. Pasado no garantiza futuro."),
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"\n→ {OUT_PATH}")
    for k in ("in_sample", "out_sample", "all"):
        s = result[k]
        print(f"  {k:11} trades {s['trades']:4} · win {s['win_rate']:5}% · "
              f"R prom {s['avg_r']:5} · PF {s['pf']} · R acum {s['total_r']}")
    for k, e in equity.items():
        print(f"  ${k:16} → ${e['capital_final']:>12,.0f} ({e['retorno_pct']:+.0f}%) "
              f"DD máx {e['max_drawdown_pct']}%{' QUEBRÓ' if e['quebro'] else ''}")
    print("  scale-out (mismos trades, 2% fijo):")
    for k, s in scale_out.items():
        print(f"    {k:14} n={s['trades']:4} win={s['win_rate']:5}% avgR={s['avg_r']:5} "
              f"totR={s['total_r']:7} PF={s['pf']} → ${s['capital_final']:>11,.0f} "
              f"({s['retorno_pct']:+.0f}%) DD {s['max_drawdown_pct']}% racha {s['risk']['max_losing_streak']}")


if __name__ == "__main__":
    main()
