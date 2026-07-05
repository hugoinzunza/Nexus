"""Replay histórico/OOS del modelo visual BTA v2 — research puro.

Mide, sobre ~4 años de klines locales (data/klines_*.json), si las hipótesis
VISUALES del modelo v2 tienen valor fuera del tramo de capturas (may-jun 2026):

  A  `touch`       — entrar al toque del POI (lo que hoy hace el Diario).
  B  `cdc_post`    — entrar SOLO si hay CDC (cierre que rompe el último swing
                     confirmado piv=2 en la dirección del plan) DESPUÉS del toque
                     y dentro de la ventana. La hipótesis "X Confirmación".
  C  `retest_cont` — zona FALLIDA que se retestea desde el otro lado: entrada de
                     continuación en la dirección invertida.
  D  descriptivo   — tasa de `reclaimed` de los quiebres CDC (escalera) y qué
                     pasa después (¿el quiebre reclamado es un quiebre fallido?).

Anti-look-ahead: piernas causales (build_swing_legs_v2 + active_leg as_of),
POIs de detect_pois (anti-repaint), swings con confirm_idx, targets = pivotes
NO barridos al momento de la consulta, resolución intrabar conservadora
(si SL y TP caen en la misma vela, cuenta SL).

Costos: mismo modelo maker-aware del Diario (`setups_store._cost_fraction`).

Corre:   .venv/bin/python3 research/bta_visual_oos.py
Escribe: research/bta_visual_oos_results.json (el reporte MD se redacta aparte)
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

from modules.trading import smc  # noqa: E402
from modules.trading.setups_store import _cost_fraction  # noqa: E402
from modules.trading.strategies import detect_pois  # noqa: E402
from research import bta_visual_model2 as v2  # noqa: E402

DATA_DIR = os.path.join(WT, "data")
OUT_JSON = os.path.join(WT, "research", "bta_visual_oos_results.json")
OUT_MD = os.path.join(WT, "research", "bta_visual_oos_2026-07-05.md")

DATASETS = ([(p, "1h") for p in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT",
                                 "ADAUSDT", "BNBUSDT", "DOGEUSDT")]
            + [(p, "15m") for p in ("BTCUSDT", "ETHUSDT", "SOLUSDT")])

POI_PIV, POI_DISP = 2, 1.0
LEG_PIV = 10
TAP_MAX = 1500        # velas máx. esperando el toque del POI
SIM_MAX = 2000        # velas máx. para resolver un trade (si no, se excluye)
RETEST_MAX = 500      # velas máx. esperando el retest tras el fallo
CDC_WINDOW = v2.CONFIRM_WINDOW
BUFFER = 0.0015       # mismo SWEEP_BUFFER_PCT del plan
IS_FRAC = 0.70


# ------------------------------ precomputos O(n) ------------------------------

def sweep_times(candles, pivots, side):
    """swept_t de cada pivote con stack monotónico (O(n)); None si no se barre."""
    out = {}
    events = sorted(pivots, key=lambda p: p["idx"])
    ei = 0
    stack = []          # (price, key) pendientes de barrer
    for j, c in enumerate(candles):
        while ei < len(events) and events[ei]["idx"] < j:
            p = events[ei]
            out[(p["idx"], p["price"])] = None
            stack.append((p["price"], (p["idx"], p["price"])))
            ei += 1
        if side == "high":
            keep = []
            for price, key in stack:
                if c["h"] > price and out[key] is None:
                    out[key] = c["t"]
                else:
                    keep.append((price, key))
            stack = keep
        else:
            keep = []
            for price, key in stack:
                if c["l"] < price and out[key] is None:
                    out[key] = c["t"]
                else:
                    keep.append((price, key))
            stack = keep
    return out


def pivot_rows(candles, piv):
    highs, lows = smc.swing_points(candles, piv)
    sw_h = sweep_times(candles, highs, "high")
    sw_l = sweep_times(candles, lows, "low")
    rows = []
    n = len(candles)
    for side, pts, sw in (("high", highs, sw_h), ("low", lows, sw_l)):
        for p in pts:
            ci = min(p["confirm_idx"], n - 1)
            rows.append({"price": p["price"], "side": side,
                         "confirm_t": candles[ci]["t"],
                         "swept_t": sw[(p["idx"], p["price"])]})
    return rows


def last_confirmed_arrays(candles, piv):
    """last_high[j] / last_low[j]: precio del último swing confirmado en cada vela."""
    highs, lows = smc.swing_points(candles, piv)
    n = len(candles)
    lh, ll = [None] * n, [None] * n
    for arr, pts in ((lh, highs), (ll, lows)):
        evt = sorted(pts, key=lambda p: p["confirm_idx"])
        pi, cur = 0, None
        for j in range(n):
            while pi < len(evt) and evt[pi]["confirm_idx"] <= j:
                cur = evt[pi]["price"]
                pi += 1
            arr[j] = cur
    return lh, ll


def liquidity_target(pivrows, long, ref_price, t):
    """Pivote NO barrido más cercano en la dirección del trade, visible en t."""
    if long:
        cands = [r["price"] for r in pivrows
                 if r["side"] == "high" and r["price"] > ref_price
                 and r["confirm_t"] <= t and (r["swept_t"] is None or r["swept_t"] > t)]
        return min(cands) if cands else None
    cands = [r["price"] for r in pivrows
             if r["side"] == "low" and r["price"] < ref_price
             and r["confirm_t"] <= t and (r["swept_t"] is None or r["swept_t"] > t)]
    return max(cands) if cands else None


# ------------------------------ simulación ------------------------------

def resolve(candles, i0, long, entry, sl, tp):
    """Primer toque de SL o TP desde i0+1. Conservador: ambos en la vela => SL.
    Devuelve (r_bruto, i_fin) o (None, None) si no resuelve en SIM_MAX."""
    risk = (entry - sl) if long else (sl - entry)
    if risk <= 0:
        return None, None
    for j in range(i0 + 1, min(i0 + 1 + SIM_MAX, len(candles))):
        c = candles[j]
        hit_sl = c["l"] <= sl if long else c["h"] >= sl
        hit_tp = c["h"] >= tp if long else c["l"] <= tp
        if hit_sl:
            return -1.0, j
        if hit_tp:
            return abs(tp - entry) / risk, j
    return None, None


def netR(r, entry, sl):
    slf = abs(entry - sl) / entry
    if slf <= 0:
        return r
    return r - _cost_fraction(r > 0) / slf


# ------------------------------ estudio por dataset ------------------------------

def study_dataset(pair, tf):
    path = os.path.join(DATA_DIR, f"klines_{pair}_{tf}.json")
    candles = json.load(open(path))
    n = len(candles)
    legs = v2.build_swing_legs_v2(candles, piv=LEG_PIV)
    pivrows = pivot_rows(candles, LEG_PIV)
    lh2, ll2 = last_confirmed_arrays(candles, POI_PIV)
    t_by_idx = [c["t"] for c in candles]

    def idx_of(t):  # índice de la vela con timestamp t (búsqueda binaria simple)
        import bisect
        return bisect.bisect_left(t_by_idx, t)

    pois = detect_pois(candles, POI_PIV, POI_DISP)
    trades = []      # {variant, pair, tf, dir, side_birth, rr, t, won, netR}
    stats = defaultdict(int)

    for k, poi in enumerate(pois):
        long = poi["dir"] == "long"
        lo, hi = poi["lo"], poi["hi"]
        stop = poi["stop"] * (1 - BUFFER) if long else poi["stop"] * (1 + BUFFER)
        z = v2.zone_from_poi_v2(poi, legs, f"{pair}_{tf}_{k}")
        i_conf = idx_of(poi["t_conf"])
        stats["pois"] += 1

        # --- buscar el TOQUE ---
        i_tap = None
        for j in range(i_conf + 1, min(i_conf + 1 + TAP_MAX, n)):
            c = candles[j]
            beyond = c["c"] < stop if long else c["c"] > stop
            if beyond:                     # falló antes de tocar con margen útil
                break
            if c["l"] <= hi and c["h"] >= lo:
                i_tap = j
                break
        if i_tap is None:
            stats["sin_toque"] += 1
        else:
            stats["tocadas"] += 1
            t_tap = candles[i_tap]["t"]
            entry_a = hi if long else lo   # el borde por donde entra el precio
            tp_a = liquidity_target(pivrows, long, entry_a, t_tap)
            if tp_a is not None:
                risk = (entry_a - stop) if long else (stop - entry_a)
                if risk > 0:
                    rr = abs(tp_a - entry_a) / risk
                    if rr >= 1.0:
                        r, _ = resolve(candles, i_tap, long, entry_a, stop, tp_a)
                        if r is not None:
                            trades.append(dict(
                                variant="touch", zid=z.id, pair=pair, tf=tf, dir=poi["dir"],
                                side=z.leg_side_at_birth, rr=round(rr, 1), t=t_tap,
                                won=r > 0, netR=round(netR(r, entry_a, stop), 3)))

            # --- CDC DESPUÉS del toque, dentro de la ventana ---
            i_cdc = None
            for j in range(i_tap + 1, min(i_tap + 1 + CDC_WINDOW, n)):
                c = candles[j]
                beyond = c["c"] < stop if long else c["c"] > stop
                if beyond:
                    break                   # invalidada antes de confirmar
                ref = lh2[j] if long else ll2[j]
                if ref is not None and ((long and c["c"] > ref) or
                                        (not long and c["c"] < ref)):
                    i_cdc = j
                    break
            if i_cdc is not None:
                stats["cdc_confirmadas"] += 1
                c = candles[i_cdc]
                entry_b = c["c"]
                tp_b = liquidity_target(pivrows, long, entry_b, c["t"])
                risk = (entry_b - stop) if long else (stop - entry_b)
                if tp_b is not None and risk > 0:
                    rr = abs(tp_b - entry_b) / risk
                    if rr >= 1.0:
                        r, _ = resolve(candles, i_cdc, long, entry_b, stop, tp_b)
                        if r is not None:
                            trades.append(dict(
                                variant="cdc_post", zid=z.id, pair=pair, tf=tf, dir=poi["dir"],
                                side=z.leg_side_at_birth, rr=round(rr, 1),
                                t=c["t"], won=r > 0,
                                netR=round(netR(r, entry_b, stop), 3)))

        # --- FALLO -> RETEST -> CONTINUACIÓN (dirección invertida) ---
        i_fail = None
        start = i_tap if i_tap is not None else i_conf
        for j in range(start + 1, min(start + 1 + SIM_MAX, n)):
            c = candles[j]
            if (long and c["c"] < lo) or (not long and c["c"] > hi):
                i_fail = j
                break
        if i_fail is not None:
            stats["fallidas"] += 1
            flip_long = not long           # discount fallido -> continuación short, etc.
            for j in range(i_fail + 1, min(i_fail + 1 + RETEST_MAX, n)):
                c = candles[j]
                if c["l"] <= hi and c["h"] >= lo:      # vuelve a tocar la zona
                    # Zona long fallida (rompió hacia abajo): el retest llega desde
                    # abajo -> toca `lo` -> continuación SHORT con stop sobre `hi`.
                    # Zona short fallida: simétrico (retest desde arriba, long).
                    entry_c = hi if flip_long else lo
                    stop_c = (lo * (1 - BUFFER)) if flip_long else (hi * (1 + BUFFER))
                    tp_c = liquidity_target(pivrows, flip_long, entry_c, c["t"])
                    risk = (entry_c - stop_c) if flip_long else (stop_c - entry_c)
                    if tp_c is not None and risk > 0:
                        rr = abs(tp_c - entry_c) / risk
                        if rr >= 1.0:
                            r, _ = resolve(candles, j, flip_long, entry_c, stop_c, tp_c)
                            if r is not None:
                                stats["retesteadas"] += 1
                                trades.append(dict(
                                    variant="retest_cont", zid=z.id, pair=pair, tf=tf,
                                    dir="long" if flip_long else "short",
                                    side=z.leg_side_at_birth, rr=round(rr, 1),
                                    t=c["t"], won=r > 0,
                                    netR=round(netR(r, entry_c, stop_c), 3)))
                    break

    # --- D: reclaimed de quiebres CDC (escalera incremental, solo estados vivos) ---
    rec = {"breaks": 0, "reclaimed": 0, "por_ano": defaultdict(lambda: [0, 0])}
    highs, lows = smc.swing_points(candles, POI_PIV)
    events = sorted([{"side": "high", **p} for p in highs] +
                    [{"side": "low", **p} for p in lows],
                    key=lambda p: p["confirm_idx"])
    ei = 0
    activos = []       # niveles pending/broken (los terminales salen de la lista)
    for j, c in enumerate(candles):
        while ei < len(events) and events[ei]["confirm_idx"] <= j:
            activos.append({"price": events[ei]["price"], "side": events[ei]["side"],
                            "state": "pending", "broken_j": None})
            if len(activos) > 40:
                activos.pop(0)
            ei += 1
        for lvl in activos:
            if lvl["state"] == "pending":
                if (lvl["side"] == "high" and c["c"] > lvl["price"]) or \
                        (lvl["side"] == "low" and c["c"] < lvl["price"]):
                    lvl["state"] = "broken"
                    lvl["broken_j"] = j
                    rec["breaks"] += 1
                    y = dt.datetime.utcfromtimestamp(c["t"] / 1000).year
                    rec["por_ano"][y][0] += 1
            elif lvl["state"] == "broken":
                # Solo cuenta como "quiebre fallido" si se reclama RÁPIDO (<=12
                # velas). Sin ventana, casi todo quiebre micro se "reclama"
                # eventualmente y la estadística no dice nada (94% espurio).
                if j - lvl["broken_j"] > 12:
                    lvl["state"] = "held"          # el quiebre sostuvo
                else:
                    back = (c["c"] < lvl["price"]) if lvl["side"] == "high" \
                        else (c["c"] > lvl["price"])
                    if back:
                        lvl["state"] = "reclaimed"
                        rec["reclaimed"] += 1
                        y = dt.datetime.utcfromtimestamp(c["t"] / 1000).year
                        rec["por_ano"][y][1] += 1
        activos = [l for l in activos if l["state"] in ("pending", "broken")]

    rec["por_ano"] = {y: {"breaks": v[0], "reclaimed": v[1]}
                      for y, v in sorted(rec["por_ano"].items())}
    return trades, dict(stats), rec


# ------------------------------ agregación ------------------------------

def agg(rows):
    if not rows:
        return {"n": 0}
    n = len(rows)
    w = sum(1 for r in rows if r["won"])
    tot = sum(r["netR"] for r in rows)
    return {"n": n, "wr": round(100 * w / n, 1), "avg": round(tot / n, 3),
            "tot": round(tot, 1)}


def main():
    all_trades, all_stats, all_rec = [], {}, {}
    for pair, tf in DATASETS:
        path = os.path.join(DATA_DIR, f"klines_{pair}_{tf}.json")
        if not os.path.isfile(path):
            print(f"  (sin datos {pair} {tf}, salto)")
            continue
        trades, stats, rec = study_dataset(pair, tf)
        all_trades.extend(trades)
        all_stats[f"{pair}_{tf}"] = stats
        all_rec[f"{pair}_{tf}"] = rec
        print(f"  {pair} {tf}: pois={stats.get('pois', 0)} trades={len(trades)}")

    ts = sorted(r["t"] for r in all_trades)
    split = ts[int(len(ts) * IS_FRAC)]
    for r in all_trades:
        r["oos"] = r["t"] > split
        r["year"] = dt.datetime.utcfromtimestamp(r["t"] / 1000).year

    res = {"meta": {
        "research_only": True,
        "aviso": "Research only - No senal - No bot - NO usar para activar live",
        "datasets": [f"{p}_{tf}" for p, tf in DATASETS],
        "split_oos": dt.datetime.utcfromtimestamp(split / 1000).isoformat(),
        "costos": "maker-aware del Diario (_cost_fraction) sobre el % de SL",
        "conservador": "SL y TP en la misma vela cuenta como SL",
    }, "stats": all_stats, "reclaimed": all_rec, "cortes": {}}

    C = res["cortes"]
    for var in ("touch", "cdc_post", "retest_cont"):
        rows = [r for r in all_trades if r["variant"] == var]
        C[var] = {
            "ALL": agg(rows),
            "IS": agg([r for r in rows if not r["oos"]]),
            "OOS": agg([r for r in rows if r["oos"]]),
            "por_ano": {y: agg([r for r in rows if r["year"] == y])
                        for y in sorted({r["year"] for r in rows})},
            "por_par": {p: agg([r for r in rows if r["pair"] == p])
                        for p in sorted({r["pair"] for r in rows})},
            "por_tf": {t: agg([r for r in rows if r["tf"] == t])
                       for t in sorted({r["tf"] for r in rows})},
            "por_dir": {d: agg([r for r in rows if r["dir"] == d])
                        for d in ("long", "short")},
            "por_lado": {s: agg([r for r in rows if r["side"] == s])
                         for s in ("discount", "premium", "equilibrium")},
            "por_rr": {"rr_1_2": agg([r for r in rows if r["rr"] < 2]),
                       "rr_2_5": agg([r for r in rows if 2 <= r["rr"] < 5]),
                       "rr_5p": agg([r for r in rows if r["rr"] >= 5])},
            "OOS_por_par": {p: agg([r for r in rows if r["oos"] and r["pair"] == p])
                            for p in sorted({r["pair"] for r in rows})},
            "OOS_por_lado": {s: agg([r for r in rows if r["oos"] and r["side"] == s])
                             for s in ("discount", "premium", "equilibrium")},
        }

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    print(f"\nresultados: {OUT_JSON}")
    for var in ("touch", "cdc_post", "retest_cont"):
        print(f"  {var:12} ALL {C[var]['ALL']} | OOS {C[var]['OOS']}")
    tot_b = sum(r["breaks"] for r in all_rec.values())
    tot_r = sum(r["reclaimed"] for r in all_rec.values())
    print(f"  reclaimed: {tot_r}/{tot_b} quiebres ({100*tot_r/max(tot_b,1):.0f}%)")


if __name__ == "__main__":
    main()
