"""Estudio "abort-si-no-CDC" — research puro, derivado del replay OOS (3202a62).

Hipótesis operable: el pareado del OOS mostró que las zonas tocadas que LUEGO
confirman CDC rinden +0.68 vs -0.16 las que no. Entrar en el CDC pierde (entrada
tardía). La única forma CAUSAL de capturar esa información es: entrar al toque
(igual que el baseline `touch`) y ABORTAR con pérdida reducida si el CDC no
aparece dentro de una ventana de N velas.

Variantes (por cada ventana N en 4/8/12/16/24):
  - `mkt`  : sin CDC en la vela N -> cierre a mercado al close de esa vela.
  - `be`   : sin CDC en la vela N -> si el precio va a favor, stop a break-even
             (y se deja correr al TP); si va en contra, cierre a mercado.
  - `cap03`: sin CDC en la vela N -> stop apretado a -0.3R (si ya está peor que
             -0.3R, cierre a mercado); TP intacto.
En TODAS: si el SL o TP original se toca ANTES de la vela N, manda el original
(mismo criterio conservador del OOS: SL y TP en la misma vela = SL). Si el CDC
aparece dentro de la ventana, el plan original sigue intacto hasta resolverse.

Universo: exactamente los trades del baseline `touch` del estudio OOS (mismos
POIs, entradas, stops y targets), para comparación PAREADA. Costos maker-aware.
Anti-look-ahead: mismas garantías del estudio OOS (piernas causales, swings
confirmados, targets no barridos al momento de la consulta).

Corre:   .venv/bin/python3 research/bta_visual_abort.py
Escribe: research/bta_visual_abort_results.json (el reporte MD se redacta aparte)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import defaultdict

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading.strategies import detect_pois  # noqa: E402
from research import bta_visual_model2 as v2  # noqa: E402
from research import bta_visual_oos as oos  # noqa: E402

OUT_JSON = os.path.join(WT, "research", "bta_visual_abort_results.json")

WINDOWS = (4, 8, 12, 16, 24)
MODES = ("mkt", "be", "cap03")
CAP_R = -0.3
IS_FRAC = 0.70


def sim_trade(candles, i_tap, long, entry, stop, tp, i_cdc, N, mode):
    """Resultado BRUTO en R de un trade con la regla de aborto (N, mode).

    Camina vela a vela desde i_tap+1. Orden de precedencia por vela (conservador):
    SL original -> TP -> (si es la vela N sin CDC previo) aborto según `mode`.
    """
    risk = (entry - stop) if long else (stop - entry)
    if risk <= 0:
        return None
    j_window = i_tap + N
    n = len(candles)
    for j in range(i_tap + 1, min(i_tap + 1 + oos.SIM_MAX, n)):
        c = candles[j]
        if (c["l"] <= stop) if long else (c["h"] >= stop):
            return -1.0
        if (c["h"] >= tp) if long else (c["l"] <= tp):
            return abs(tp - entry) / risk
        cdc_ok = i_cdc is not None and i_cdc <= j
        if j >= j_window and not cdc_ok:
            px = c["c"]
            r_now = ((px - entry) / risk) if long else ((entry - px) / risk)
            if mode == "mkt":
                return r_now
            if mode == "be":
                if r_now <= 0:
                    return r_now              # en contra: fuera ya
                return _resolve_mod(candles, j, long, entry, entry, tp, risk)
            if mode == "cap03":
                if r_now <= CAP_R:
                    return r_now              # ya está peor que el cap: fuera
                cap_px = entry + CAP_R * risk if long else entry - CAP_R * risk
                return _resolve_mod(candles, j, long, entry, cap_px, tp, risk)
    return None                                # no resolvió (excluido, raro)


def _resolve_mod(candles, i0, long, entry, new_sl, tp, risk):
    """Continúa el trade con stop MODIFICADO (BE o cap). Conservador: stop y TP
    en la misma vela cuenta stop. Si no resuelve, sale al último close mirado."""
    n = len(candles)
    last_px = candles[i0]["c"]
    for j in range(i0 + 1, min(i0 + 1 + oos.SIM_MAX, n)):
        c = candles[j]
        last_px = c["c"]
        if (c["l"] <= new_sl) if long else (c["h"] >= new_sl):
            return ((new_sl - entry) / risk) if long else ((entry - new_sl) / risk)
        if (c["h"] >= tp) if long else (c["l"] <= tp):
            return abs(tp - entry) / risk
    return ((last_px - entry) / risk) if long else ((entry - last_px) / risk)


def study_dataset(pair, tf):
    """Universo pareado: por cada trade `touch` del OOS, el baseline y todas las
    variantes de aborto sobre la MISMA entrada/stop/target."""
    path = os.path.join(oos.DATA_DIR, f"klines_{pair}_{tf}.json")
    candles = json.load(open(path))
    n = len(candles)
    legs = v2.build_swing_legs_v2(candles, piv=oos.LEG_PIV)
    pivrows = oos.pivot_rows(candles, oos.LEG_PIV)
    lh2, ll2 = oos.last_confirmed_arrays(candles, oos.POI_PIV)
    t_by_idx = [c["t"] for c in candles]
    import bisect

    rows = []
    for k, poi in enumerate(detect_pois(candles, oos.POI_PIV, oos.POI_DISP)):
        long = poi["dir"] == "long"
        lo, hi = poi["lo"], poi["hi"]
        stop = poi["stop"] * (1 - oos.BUFFER) if long else poi["stop"] * (1 + oos.BUFFER)
        z = v2.zone_from_poi_v2(poi, legs, f"{pair}_{tf}_{k}")
        i_conf = bisect.bisect_left(t_by_idx, poi["t_conf"])

        i_tap = None
        for j in range(i_conf + 1, min(i_conf + 1 + oos.TAP_MAX, n)):
            c = candles[j]
            if (c["c"] < stop) if long else (c["c"] > stop):
                break
            if c["l"] <= hi and c["h"] >= lo:
                i_tap = j
                break
        if i_tap is None:
            continue
        entry = hi if long else lo
        t_tap = candles[i_tap]["t"]
        tp = oos.liquidity_target(pivrows, long, entry, t_tap)
        risk = (entry - stop) if long else (stop - entry)
        if tp is None or risk <= 0:
            continue
        rr = abs(tp - entry) / risk
        if rr < 1.0:
            continue
        r_base, _ = oos.resolve(candles, i_tap, long, entry, stop, tp)
        if r_base is None:
            continue                          # mismo universo que el baseline OOS

        # primer CDC posterior al toque (causal, mismas series confirmadas piv=2)
        i_cdc = None
        for j in range(i_tap + 1, min(i_tap + 1 + max(WINDOWS), n)):
            c = candles[j]
            # si el trade ya murió por SL antes del CDC, el CDC posterior no cuenta
            if (c["l"] <= stop) if long else (c["h"] >= stop):
                break
            ref = lh2[j] if long else ll2[j]
            if ref is not None and ((long and c["c"] > ref) or
                                    (not long and c["c"] < ref)):
                i_cdc = j
                break

        row = dict(pair=pair, tf=tf, dir=poi["dir"], side=z.leg_side_at_birth,
                   rr=round(rr, 1), t=t_tap,
                   cdc_lag=(i_cdc - i_tap) if i_cdc is not None else None,
                   base=round(oos.netR(r_base, entry, stop), 3))
        for N in WINDOWS:
            for mode in MODES:
                r = sim_trade(candles, i_tap, long, entry, stop, tp, i_cdc, N, mode)
                if r is None:
                    r = r_base                # no resolvió el camino modificado: base
                row[f"{mode}_{N}"] = round(oos.netR(r, entry, stop), 3)
        rows.append(row)
    return rows


def agg(vals):
    if not vals:
        return {"n": 0}
    n = len(vals)
    w = sum(1 for v in vals if v > 0)
    tot = sum(vals)
    losers = [v for v in vals if v <= 0]
    # drawdown de la curva acumulada (en R) en el orden temporal dado
    eq = peak = mdd = 0.0
    for v in vals:
        eq += v
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {"n": n, "wr": round(100 * w / n, 1), "avg": round(tot / n, 3),
            "tot": round(tot, 1), "avg_loser": round(sum(losers) / len(losers), 3)
            if losers else 0.0, "dd_R": round(mdd, 1)}


def main():
    rows = []
    for pair, tf in oos.DATASETS:
        if not os.path.isfile(os.path.join(oos.DATA_DIR, f"klines_{pair}_{tf}.json")):
            continue
        r = study_dataset(pair, tf)
        rows.extend(r)
        print(f"  {pair} {tf}: {len(r)} trades pareados")
    rows.sort(key=lambda r: r["t"])
    ts = [r["t"] for r in rows]
    split = ts[int(len(ts) * IS_FRAC)]
    for r in rows:
        r["oos"] = r["t"] > split
        r["year"] = dt.datetime.utcfromtimestamp(r["t"] / 1000).year
        h = dt.datetime.utcfromtimestamp(r["t"] / 1000).hour
        r["ses"] = "Asia" if h < 7 else ("Londres" if h < 12 else
                                         ("NY" if h < 21 else "Fuera"))

    variants = ["base"] + [f"{m}_{N}" for N in WINDOWS for m in MODES]
    res = {"meta": {
        "research_only": True,
        "aviso": "Research only - No senal - No bot - NO usar para activar live",
        "universo": "trades touch del OOS (pareado 1:1)",
        "split_oos": dt.datetime.utcfromtimestamp(split / 1000).isoformat(),
        "cap_R": CAP_R, "ventanas": list(WINDOWS), "modos": list(MODES),
    }, "cortes": {}}
    C = res["cortes"]

    def cortes(sel, rows_sel):
        C[sel] = {}
        for v in variants:
            vals = [r[v] for r in rows_sel]
            C[sel][v] = agg(vals)

    cortes("ALL", rows)
    cortes("IS", [r for r in rows if not r["oos"]])
    cortes("OOS", [r for r in rows if r["oos"]])
    for y in sorted({r["year"] for r in rows}):
        cortes(f"ano_{y}", [r for r in rows if r["year"] == y])
    for tf in ("1h", "15m"):
        cortes(f"tf_{tf}", [r for r in rows if r["tf"] == tf])
        cortes(f"tf_{tf}_OOS", [r for r in rows if r["tf"] == tf and r["oos"]])
    for p in sorted({r["pair"] for r in rows}):
        cortes(f"par_{p}", [r for r in rows if r["pair"] == p])
    for d in ("long", "short"):
        cortes(f"dir_{d}", [r for r in rows if r["dir"] == d])
    for s in ("discount", "premium"):
        cortes(f"lado_{s}", [r for r in rows if r["side"] == s])
    cortes("rr_5p", [r for r in rows if r["rr"] >= 5])
    cortes("rr_5p_OOS", [r for r in rows if r["rr"] >= 5 and r["oos"]])
    cortes("rr_2_5", [r for r in rows if 2 <= r["rr"] < 5])
    for ses in ("Asia", "Londres", "NY", "Fuera"):
        cortes(f"ses_{ses}", [r for r in rows if r["ses"] == ses])

    # adversarial: ¿cuántos winners del baseline destruye cada variante?
    winners = [r for r in rows if r["base"] > 0]
    res["winners_destruidos"] = {
        v: {"n_winners_base": len(winners),
            "destruidos": sum(1 for r in winners if r[v] <= 0),
            "pct": round(100 * sum(1 for r in winners if r[v] <= 0)
                         / max(len(winners), 1), 1)}
        for v in variants if v != "base"}
    # frecuencia de aborto (proxy: cuántos trades cambian de resultado vs base)
    res["trades_afectados"] = {
        v: sum(1 for r in rows if abs(r[v] - r["base"]) > 1e-9) for v in variants
        if v != "base"}

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    print(f"\nresultados: {OUT_JSON}")
    print(f"{'variante':10} {'ALL':>42} {'OOS':>42}")
    for v in variants:
        a, o = C["ALL"][v], C["OOS"][v]
        print(f"{v:10} n={a['n']:5} avg={a['avg']:+.3f} loser={a['avg_loser']:+.3f} "
              f"dd={a['dd_R']:6.1f} | n={o['n']:5} avg={o['avg']:+.3f} "
              f"loser={o['avg_loser']:+.3f} dd={o['dd_R']:6.1f}")


if __name__ == "__main__":
    main()
