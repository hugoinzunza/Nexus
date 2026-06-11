"""Experimento de mejoras por capas sobre la estrategia "SMC POI multi-TF".

La estrategia POI quedó break-even (#1 del laboratorio). Acá probamos, por capas,
qué mueve la expectativa OOS de ~0 a positiva, primero AISLANDO cada capa
(ablación) y luego combinando las prometedoras:

  1) Filtro de tendencia HTF (4h, 1D o ambos): largos solo en descuento con
     estructura alcista; cortos solo en premium con estructura bajista.
  2) Confirmación en la entrada: CHoCH, vela de rechazo o engulfing.
  3) Confluencia multi-TF estricta: solo POIs que solapan con otra TF.
  4) Filtro de sesión: excluir Londres / solo NY / solo Asia.
  5) Gestión de salida: parcial en 1R + breakeven, o trailing por ATR, vs TP fijo.

ANTI-REPINTADO estricto: condiciones al CIERRE de la vela, entrada en la apertura
siguiente, TF superiores solo con velas ya cerradas. Costos: 0.05%/lado + 0.02%
slippage. Validación IS/OOS + walk-forward; muestra OOS <30 = no confiable.

Eficiencia: los DISPAROS base (taps de precio en POIs) se calculan una sola vez
por (par, TF base); cada variante es un filtro + simulación de salida barata.

Guarda poi_layers_results.json (commiteado) y lo imprime.
Uso:  python3 -m modules.trading.run_poi_lab
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.trading import binance, smc, strategies
from modules.trading.backtest import metrics, session_of

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
BASE_TFS = ["15m", "1h"]                      # scalp y swing
POI_SOURCES = {"15m": ["1h", "4h", "1d"], "1h": ["1h", "4h", "1d"]}
TREND_TFS = ["4h", "1d"]
YEARS = 4.0
IS_FRACTION = 0.70
PIV, DISP = 2, 1.0
MAX_AGE_MS = 30 * 86_400_000
STOP_BUF = 0.0005
MIN_STOP_FRAC = 0.0015
COMM, SLIP = 0.0005, 0.0002
MIN_OOS_TRADES = 30
MIN_OOS_PF = 1.1
DATA_DIR = os.path.join(ROOT, "data")
RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poi_layers_results.json")


def log(m):
    print(m, flush=True)


def gmt(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


# --- Disparos base (una vez por par/TF) ---------------------------------
def base_triggers(base_candles, sources):
    """Detecta POIs en las TF fuente y devuelve los TAPS (precio entra a un POI
    sin mitigar). Cada disparo: {j, dir, tf, lo, hi, stop, confluence}."""
    pois = []
    for tf, hc in sources.items():
        for p in strategies.detect_pois(hc, PIV, DISP):
            pois.append({**p, "tf": tf})
    # Confluencia: ¿el POI solapa con otro de DISTINTA TF y misma dirección?
    for a in pois:
        a["confluence"] = any(
            b is not a and b["tf"] != a["tf"] and b["dir"] == a["dir"]
            and a["lo"] <= b["hi"] and a["hi"] >= b["lo"]
            for b in pois)
    pois.sort(key=lambda x: x["t_conf"])

    n = len(base_candles)
    lows = [c["l"] for c in base_candles]
    highs = [c["h"] for c in base_candles]
    trig = []
    pi = 0
    active = []
    for j in range(n - 1):
        tj = base_candles[j]["t"]
        while pi < len(pois) and pois[pi]["t_conf"] <= tj:
            active.append(dict(pois[pi], used=False))
            pi += 1
        if not active:
            continue
        kept = []
        for poi in active:
            if poi["used"] or tj - poi["t_conf"] > MAX_AGE_MS:
                continue
            if poi["dir"] == "long" and lows[j] < poi["stop"]:
                continue
            if poi["dir"] == "short" and highs[j] > poi["stop"]:
                continue
            kept.append(poi)
        active = kept[-40:]
        for poi in active:
            if poi["dir"] == "long" and lows[j] <= poi["hi"] and highs[j] >= poi["lo"]:
                trig.append({"j": j, "dir": "long", "tf": poi["tf"], "lo": poi["lo"],
                             "hi": poi["hi"], "stop": poi["stop"], "confluence": poi["confluence"]})
                poi["used"] = True
            elif poi["dir"] == "short" and highs[j] >= poi["lo"] and lows[j] <= poi["hi"]:
                trig.append({"j": j, "dir": "short", "tf": poi["tf"], "lo": poi["lo"],
                             "hi": poi["hi"], "stop": poi["stop"], "confluence": poi["confluence"]})
                poi["used"] = True
    return trig


def context_arrays(base_candles, htf_for_trend):
    """Arrays precomputados para aplicar las capas barato: estructura HTF mapeada,
    swings de la TF base (para CHoCH/rechazo) y ATR."""
    n = len(base_candles)
    dirs = {}
    for tf, hc in htf_for_trend.items():
        hd = smc.structure_direction(hc, lookback=2)
        dirs[tf] = smc.map_htf_direction(base_candles, hc, hd, binance.INTERVAL_MS[tf])
    sh, sl = smc.swing_points(base_candles, 3)
    return {
        "dir": dirs,
        "last_sh": strategies._recent_prices(sh, n),
        "last_sl": strategies._recent_prices(sl, n),
        "atr": smc.atr(base_candles, 14),
    }


# --- Simulación de salida (varios modos) --------------------------------
def _legs_R(legs, risk, short):
    pnl = comm = 0.0
    for frac, ef, xf in legs:
        pnl += frac * ((ef - xf) if short else (xf - ef))
        comm += frac * COMM * (ef + xf)
    return (pnl - comm) / risk


def simulate(candles, j, direction, stop, mode, rr, atr, max_hold=96):
    n = len(candles)
    if j + 1 >= n:
        return None
    e = j + 1
    entry = candles[e]["o"]
    short = direction == "short"
    risk = (stop - entry) if short else (entry - stop)
    if risk <= 0 or risk / entry < MIN_STOP_FRAC:
        return None
    ef = entry * (1 - SLIP) if short else entry * (1 + SLIP)   # fill de entrada
    end = min(n - 1, e + max_hold)

    def stop_fill(px):
        return px * (1 + SLIP) if short else px * (1 - SLIP)

    if mode == "fixed":
        tp = entry - rr * risk if short else entry + rr * risk
        for m in range(e + 1, end + 1):
            c = candles[m]
            if (short and c["h"] >= stop) or (not short and c["l"] <= stop):
                return {"R": _legs_R([(1.0, ef, stop_fill(stop))], risk, short), "exit_idx": m}
            if (short and c["l"] <= tp) or (not short and c["h"] >= tp):
                return {"R": _legs_R([(1.0, ef, tp)], risk, short), "exit_idx": m}
        return {"R": _legs_R([(1.0, ef, stop_fill(candles[end]["c"]))], risk, short), "exit_idx": end}

    if mode == "partial_be":
        t1 = entry - risk if short else entry + risk           # 1R
        tp2 = entry - rr * risk if short else entry + rr * risk
        reached = False
        for m in range(e + 1, end + 1):
            c = candles[m]
            if not reached:
                if (short and c["h"] >= stop) or (not short and c["l"] <= stop):
                    return {"R": _legs_R([(1.0, ef, stop_fill(stop))], risk, short), "exit_idx": m}
                if (short and c["l"] <= t1) or (not short and c["h"] >= t1):
                    reached = True   # mitad sale en 1R; resto con stop en breakeven
                    continue
            else:
                if (short and c["h"] >= entry) or (not short and c["l"] <= entry):
                    return {"R": _legs_R([(0.5, ef, t1), (0.5, ef, stop_fill(entry))], risk, short), "exit_idx": m}
                if (short and c["l"] <= tp2) or (not short and c["h"] >= tp2):
                    return {"R": _legs_R([(0.5, ef, t1), (0.5, ef, tp2)], risk, short), "exit_idx": m}
        last = candles[end]["c"]
        if reached:
            return {"R": _legs_R([(0.5, ef, t1), (0.5, ef, stop_fill(last))], risk, short), "exit_idx": end}
        return {"R": _legs_R([(1.0, ef, stop_fill(last))], risk, short), "exit_idx": end}

    if mode == "trailing":
        mult = 2.0
        trail = stop
        for m in range(e + 1, end + 1):
            c = candles[m]
            if (short and c["h"] >= trail) or (not short and c["l"] <= trail):
                return {"R": _legs_R([(1.0, ef, stop_fill(trail))], risk, short), "exit_idx": m}
            a = atr[m] or 0.0
            if not short:
                trail = max(trail, c["c"] - mult * a)
            else:
                trail = min(trail, c["c"] + mult * a)
        return {"R": _legs_R([(1.0, ef, stop_fill(candles[end]["c"]))], risk, short), "exit_idx": end}
    return None


# --- Aplicar una variante (capas) a los disparos base -------------------
def _confirm_ok(candles, j, direction, arrays, kind):
    if kind == "none":
        return True
    c = candles[j]
    if kind == "choch":
        ref = arrays["last_sh"][j] if direction == "long" else arrays["last_sl"][j]
        if ref is None:
            return False
        return c["c"] > ref if direction == "long" else c["c"] < ref
    if kind == "rejection":
        rng = c["h"] - c["l"]
        if rng <= 0:
            return False
        if direction == "long":
            return c["c"] > c["o"] and (c["c"] - c["l"]) > 0.5 * rng
        return c["c"] < c["o"] and (c["h"] - c["c"]) > 0.5 * rng
    if kind == "engulfing":
        if j < 1:
            return False
        p = candles[j - 1]
        if direction == "long":
            return c["c"] > c["o"] and c["c"] > p["h"]
        return c["c"] < c["o"] and c["c"] < p["l"]
    return True


def apply_variant(triggers, arrays, candles, v, symbol, tf):
    trades = []
    occupied = -1
    for t in sorted(triggers, key=lambda x: x["j"]):
        j = t["j"]
        if j <= occupied:
            continue
        direction = t["dir"]
        # Capa tendencia HTF.
        ok = True
        for ttf in v.get("trend", []):
            d = arrays["dir"].get(ttf, [0] * len(candles))[j]
            if (direction == "long" and d != 1) or (direction == "short" and d != -1):
                ok = False
                break
        if not ok:
            continue
        # Capa confluencia.
        if v.get("confluence") and not t["confluence"]:
            continue
        # Capa confirmación.
        if not _confirm_ok(candles, j, direction, arrays, v.get("confirm", "none")):
            continue
        # Capa sesión (por la vela de entrada j+1).
        et = candles[min(j + 1, len(candles) - 1)]["t"]
        sess = session_of(et)
        if v.get("sessions_only") and sess not in v["sessions_only"]:
            continue
        if v.get("sessions_exclude") and sess in v["sessions_exclude"]:
            continue
        # Simular salida.
        sim = simulate(candles, j, direction, t["stop"] * (1 - STOP_BUF if direction == "long" else 1 + STOP_BUF),
                       v.get("exit", "fixed"), v.get("rr", 3.0), arrays["atr"])
        if not sim:
            continue
        trades.append({"symbol": symbol, "timeframe": tf, "direction": direction,
                       "entry_time": et, "R": round(sim["R"], 4), "session": sess,
                       "outcome": "win" if sim["R"] > 0 else "loss"})
        occupied = sim["exit_idx"]
    return trades


# --- Variantes -----------------------------------------------------------
def variants():
    base = {"trend": [], "confirm": "none", "confluence": False,
            "sessions_only": None, "sessions_exclude": None, "exit": "fixed", "rr": 3.0}

    def V(name, layer, **over):
        return {"name": name, "layer": layer, **{**base, **over}}

    vs = [
        V("Base (3R fijo)", "base"),
        V("TP fijo 2R", "base", rr=2.0),
        # 1) Tendencia
        V("+ Tendencia 4h", "tendencia", trend=["4h"]),
        V("+ Tendencia 1D", "tendencia", trend=["1d"]),
        V("+ Tendencia 4h+1D", "tendencia", trend=["4h", "1d"]),
        # 2) Confirmación
        V("+ Confirmación CHoCH", "confirmación", confirm="choch"),
        V("+ Confirmación rechazo", "confirmación", confirm="rejection"),
        V("+ Confirmación engulfing", "confirmación", confirm="engulfing"),
        # 3) Confluencia
        V("+ Confluencia 2+ TF", "confluencia", confluence=True),
        # 4) Sesión
        V("+ Excluir Londres", "sesión", sessions_exclude=["Londres"]),
        V("+ Solo NY", "sesión", sessions_only=["NY"]),
        V("+ Solo Asia", "sesión", sessions_only=["Asia"]),
        # 5) Salidas
        V("+ Salida parcial 1R+BE", "salida", exit="partial_be"),
        V("+ Salida trailing ATR", "salida", exit="trailing"),
        # Combinaciones prometedoras
        V("Tendencia 4h+1D + CHoCH", "combo", trend=["4h", "1d"], confirm="choch"),
        V("Tendencia 4h+1D + Excluir Londres", "combo", trend=["4h", "1d"], sessions_exclude=["Londres"]),
        V("Tendencia 4h+1D + CHoCH + Excl. Londres", "combo", trend=["4h", "1d"],
          confirm="choch", sessions_exclude=["Londres"]),
        V("Confluencia + Tendencia 4h+1D", "combo", trend=["4h", "1d"], confluence=True),
        V("Tendencia 4h+1D + Salida parcial", "combo", trend=["4h", "1d"], exit="partial_be"),
        V("Todo (tend+CHoCH+exclLon+parcial)", "combo", trend=["4h", "1d"], confirm="choch",
          sessions_exclude=["Londres"], exit="partial_be"),
    ]
    return vs


def window(trades, lo, hi):
    return [t for t in trades if lo <= t["entry_time"] < hi]


def main():
    log("Cargando data (1d/4h/1h/15m)…")
    S = {}
    for sym in PAIRS:
        for tf in ["15m", "1h", "4h", "1d"]:
            S[(sym, tf)] = binance.fetch_klines(sym, tf, years=YEARS, data_dir=DATA_DIR, log=log)

    t0 = min(S[(s, t)][0]["t"] for s in PAIRS for t in BASE_TFS)
    t1 = max(S[(s, t)][-1]["t"] for s in PAIRS for t in BASE_TFS)
    split = t0 + int(IS_FRACTION * (t1 - t0))
    qs = [t0 + int((t1 - t0) * f) for f in (0.25, 0.5, 0.75)] + [t1 + 1]

    # Disparos base + contexto, una vez por (par, TF base).
    log("Calculando disparos base por par/timeframe…")
    base = {}
    arrays = {}
    for sym in PAIRS:
        for tf in BASE_TFS:
            sources = {s: S[(sym, s)] for s in POI_SOURCES[tf]}
            base[(sym, tf)] = base_triggers(S[(sym, tf)], sources)
            arrays[(sym, tf)] = context_arrays(S[(sym, tf)], {t: S[(sym, t)] for t in TREND_TFS})
        log(f"  {sym} listo")

    vs = variants()
    log(f"Evaluando {len(vs)} variantes…")
    rows = []
    for v in vs:
        combined = []
        per_mode = {"15m": [], "1h": []}
        per_sess = {}
        for sym in PAIRS:
            for tf in BASE_TFS:
                tr = apply_variant(base[(sym, tf)], arrays[(sym, tf)], S[(sym, tf)], v, sym, tf)
                combined.extend(tr)
                per_mode[tf].extend(tr)
        is_m = metrics(window(combined, t0, split))
        oos_m = metrics(window(combined, split, t1 + 1))
        full_m = metrics(combined)
        wfo = []
        for i in range(3):
            wfo.extend(window(combined, qs[i], qs[i + 1]))  # misma config en cada ventana
        wfo_m = metrics(wfo)
        # Desglose por sesión (OOS) para ver el efecto Londres.
        for s in ("Asia", "Londres", "NY", "Fuera"):
            per_sess[s] = metrics([t for t in window(combined, split, t1 + 1) if t["session"] == s])
        robust = (is_m["expectancy_R"] > 0 and oos_m["expectancy_R"] > 0
                  and oos_m["profit_factor"] >= MIN_OOS_PF and oos_m["trades"] >= MIN_OOS_TRADES
                  and wfo_m["expectancy_R"] > 0)
        rows.append({
            "name": v["name"], "layer": v["layer"],
            "in_sample": is_m, "out_sample": oos_m, "full": full_m, "wfo": wfo_m,
            "by_mode": {"15m": metrics(window(per_mode["15m"], split, t1 + 1)),
                        "1h": metrics(window(per_mode["1h"], split, t1 + 1))},
            "by_session_oos": per_sess,
            "confident": oos_m["trades"] >= MIN_OOS_TRADES,
            "robust": robust,
        })

    rows.sort(key=lambda r: (r["out_sample"]["expectancy_R"], r["out_sample"]["profit_factor"]), reverse=True)
    winners = [r for r in rows if r["robust"]]
    base_row = next(r for r in rows if r["name"] == "Base (3R fijo)")

    results = {
        "generated_at_ms": int(time.time() * 1000),
        "title": "Mejoras por capas · SMC POI multi-TF",
        "costs": {"commission_per_side": COMM, "slippage": SLIP},
        "pairs": PAIRS, "base_tfs": BASE_TFS,
        "split": {"is_until": gmt(split)},
        "robustness_rule": "expectativa>0 in-sample Y out-of-sample, PF OOS≥1.1, ≥30 trades OOS y walk-forward>0",
        "base": base_row,
        "variants": rows,
        "verdict": {
            "any_robust": bool(winners),
            "winners": [w["name"] for w in winners],
            "text": _verdict(rows, winners, base_row),
        },
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(_safe(results), fh, ensure_ascii=False, allow_nan=False)
    _print(results)
    log(f"\n💾 Guardado en {RESULTS_PATH}\n   Vista: /m/trading/backtest (sección capas)")


def _safe(o):
    import math
    if isinstance(o, float):
        return None if (math.isinf(o) or math.isnan(o)) else o
    if isinstance(o, dict):
        return {k: _safe(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_safe(v) for v in o]
    return o


def _verdict(rows, winners, base_row):
    top = rows[0]
    b = base_row["out_sample"]["expectancy_R"]
    helped = [r["name"] for r in rows
              if r["layer"] in ("tendencia", "confirmación", "confluencia", "sesión", "salida")
              and r["out_sample"]["expectancy_R"] > b + 0.005]
    helped_txt = (" Capas que mejoran sobre la base: " + ", ".join(helped) + ".") if helped else \
        " Ninguna capa por sí sola mejora de forma clara la expectativa OOS."
    if winners:
        return (f"{len(winners)} variante(s) superan el umbral de robustez: {', '.join(winners)}. "
                f"La mejor es {top['name']}: OOS {top['out_sample']['expectancy_R']}R, "
                f"PF {top['out_sample']['profit_factor']}, {top['out_sample']['trades']} trades; "
                f"walk-forward {top['wfo']['expectancy_R']}R." + helped_txt)
    return (f"NINGUNA variante supera el umbral de robustez. La mejor por OOS es {top['name']} "
            f"({top['out_sample']['expectancy_R']}R, PF {top['out_sample']['profit_factor']}, "
            f"{top['out_sample']['trades']} trades), vs la base {b}R. El edge sigue sin ser "
            "robusto fuera de muestra." + helped_txt)


def _pf(v):
    return "∞" if v == float("inf") else v


def _print(r):
    line = "─" * 78
    log("\n" + line)
    log("  MEJORAS POR CAPAS · SMC POI multi-TF")
    log(line)
    log(f"  {len(r['pairs'])} pares × {len(r['base_tfs'])} TF base (15m scalp, 1h swing) · "
        f"costos 0.05%/lado + 0.02% · corte IS hasta {r['split']['is_until']}")
    log(f"  Umbral: {r['robustness_rule']}")
    log(f"\n  RANKING POR EXPECTATIVA OOS:")
    log(f"    {'variante':<42}{'IS':>7}{'OOS':>8}{'PF':>7}{'n':>7}{'WFO':>8}  rob")
    for v in r["variants"]:
        flag = "✅" if v["robust"] else ("·" if v["confident"] else "⚠")
        log(f"    {v['name'][:41]:<42}{v['in_sample']['expectancy_R']:>7}"
            f"{v['out_sample']['expectancy_R']:>8}{_pf(v['out_sample']['profit_factor']):>7}"
            f"{v['out_sample']['trades']:>7}{v['wfo']['expectancy_R']:>8}  {flag}")
    log("\n  VEREDICTO:")
    log(f"    {'✅ EDGE ROBUSTO' if r['verdict']['any_robust'] else '⚠️  SIN EDGE ROBUSTO'}")
    for chunk in _wrap(r["verdict"]["text"], 74):
        log(f"    {chunk}")
    log(line)


def _wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


if __name__ == "__main__":
    main()
