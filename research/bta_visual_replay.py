"""Genera el payload REPLAY del modelo visual BTA v2 para la vista web research.

Research puro y datos 100% históricos: lee el archivo estático committeado
`research/bta_btcusdtp_15m_recent.json` (BTCUSDT.P M15, may-jun 2026), corre el
modelo v2 UNA vez de forma causal (todos los objetos llevan timestamps: la
página puede "reproducir" el pasado sin look-ahead) y escribe
`research/bta_visual_replay_2026-07-05.json`, que la vista
`/m/trading/research-bta-v2` sirve tal cual (solo lectura).

NO toca el bot, ni señales live, ni config. `meta.research_only=True` siempre.

Correr:  .venv/bin/python3 research/bta_visual_replay.py
"""
from __future__ import annotations

import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import smc  # noqa: E402
from modules.trading.strategies import detect_pois  # noqa: E402
from research import bta_visual_model2 as v2  # noqa: E402
from research.bta_visual_model import build_swing_legs  # noqa: E402

DATA = os.path.join(WT, "research", "bta_btcusdtp_15m_recent.json")
OUT = os.path.join(WT, "research", "bta_visual_replay_2026-07-05.json")

WINDOW = 3000          # ~31 días M15: liviano para la web y suficiente para replay
LEG_PIV = 10
CDC_PIV = 2
POI_PIV = 2
POI_DISP = 1.0
MAX_ZONES = 60


def _leg_confirm_t(leg, candles) -> int:
    ci = leg.pivot_b.get("confirm_idx")
    ci = min(int(ci), len(candles) - 1) if ci is not None else len(candles) - 1
    return candles[ci]["t"]


def _pivot_rows(candles, piv):
    """Pivotes confirmados con swept_t CAUSAL (primer cruce POSTERIOR al confirm)."""
    highs, lows = smc.swing_points(candles, piv)
    rows = []
    for side, pts in (("high", highs), ("low", lows)):
        for p in pts:
            ci = min(p["confirm_idx"], len(candles) - 1)
            confirm_t = candles[ci]["t"]
            swept_t = None
            for c in candles[ci + 1:]:
                if (side == "high" and c["h"] > p["price"]) or \
                        (side == "low" and c["l"] < p["price"]):
                    swept_t = c["t"]
                    break
            rows.append({"price": p["price"], "side": side, "t": candles[p["idx"]]["t"],
                         "confirm_t": confirm_t, "swept_t": swept_t})
    rows.sort(key=lambda r: r["confirm_t"])
    return rows


def _repisas(pivot_rows, candles):
    """Clusters de >=2 pivotes del mismo lado dentro de la tolerancia del modelo.
    created_t = confirmación del último miembro; swept_t = primer cruce del mid."""
    out = []
    for side in ("high", "low"):
        pts = sorted([r for r in pivot_rows if r["side"] == side], key=lambda r: r["price"])
        used = set()
        for i, a in enumerate(pts):
            if i in used:
                continue
            grupo = [a]
            for j in range(i + 1, len(pts)):
                if abs(pts[j]["price"] - a["price"]) <= a["price"] * v2.REPISA_TOL:
                    grupo.append(pts[j])
                    used.add(j)
            if len(grupo) < 2:
                continue
            mid = sum(r["price"] for r in grupo) / len(grupo)
            created_t = max(r["confirm_t"] for r in grupo)
            swept_t = None
            for c in candles:
                if c["t"] <= created_t:
                    continue
                if c["l"] <= mid <= c["h"]:
                    swept_t = c["t"]
                    break
            out.append({"price": round(mid, 2), "side": side, "n": len(grupo),
                        "created_t": created_t, "swept_t": swept_t})
    return out


def _link_target(zone, pivot_rows):
    """Liquidez objetivo al confirmar: el pivote NO barrido más cercano en la
    dirección del trade (visible a esa hora)."""
    t0 = zone.confirmed_t
    if t0 is None:
        return None
    if zone.direction == "long":
        cands = [r for r in pivot_rows if r["side"] == "high" and r["price"] > zone.hi
                 and r["confirm_t"] <= t0 and (r["swept_t"] is None or r["swept_t"] > t0)]
        cands.sort(key=lambda r: r["price"])
    else:
        cands = [r for r in pivot_rows if r["side"] == "low" and r["price"] < zone.lo
                 and r["confirm_t"] <= t0 and (r["swept_t"] is None or r["swept_t"] > t0)]
        cands.sort(key=lambda r: -r["price"])
    if not cands:
        return None
    r = cands[0]
    tgt = v2.TargetLiquidity(id=f"tgt_{zone.id}", price=r["price"],
                             kind="weak_high" if r["side"] == "high" else "weak_low",
                             created_t=r["confirm_t"])
    if r["swept_t"] is not None:
        tgt.state, tgt.hit_t = "hit", r["swept_t"]
    return tgt


def build_replay(candles: list[dict]) -> dict:
    window = candles[-WINDOW:]
    n = len(window)

    legs = build_swing_legs(window, piv=LEG_PIV)
    leg_rows = []
    for leg in legs:
        leg_rows.append({
            "id": leg.id, "direction": leg.direction,
            "a_t": window[min(leg.pivot_a["idx"], n - 1)]["t"],
            "a_price": leg.pivot_a["price"],
            "b_t": window[min(leg.pivot_b["idx"], n - 1)]["t"],
            "b_price": leg.pivot_b["price"],
            "confirm_t": _leg_confirm_t(leg, window),
            **v2.leg_fibs(leg),
        })

    ladder = v2.cdc_ladder(window, piv=CDC_PIV)
    cdc_rows = [{
        "id": l.id, "price": l.price, "side": l.side, "created_t": l.created_t,
        "broken_t": l.broken_t, "broken_dir": l.broken_dir,
        "reclaimed_t": l.reclaimed_t, "retest_t": l.retest_t,
        "history": l.history,
    } for l in ladder]

    pivots = _pivot_rows(window, LEG_PIV)
    repisas = _repisas(pivots, window)

    # Zonas desde los POIs validados de Nexux (detect_pois, anti-repaint), pasadas
    # por la máquina de estados v2. Anti-look-ahead: al clasificar la zona solo se
    # le muestran las piernas CONFIRMADAS antes de su creación (evita el bug de
    # active_leg() que tomaría la pierna final).
    pois = detect_pois(window, POI_PIV, POI_DISP)[-MAX_ZONES:]
    zone_rows = []
    for k, poi in enumerate(pois):
        legs_visibles = [leg for i, leg in enumerate(legs)
                         if leg_rows[i]["confirm_t"] <= poi["t_conf"]]
        z = v2.zone_from_poi_v2(poi, legs_visibles, f"zone_{k}")
        target = None
        for c in window:
            if c["t"] <= z.created_t:
                continue
            if z.state == "confirmed" and target is None:
                target = _link_target(z, pivots)
            z.step(c, ladder, target=target)
        zone_rows.append({
            "id": z.id, "kind": z.kind, "dir_original": poi.get("dir"),
            "dir_final": z.direction, "lo": z.lo, "hi": z.hi,
            "created_t": z.created_t, "tap_t": z.tap_t, "confirmed_t": z.confirmed_t,
            "failed_t": z.failed_t, "retest_t": z.retest_t,
            "leg_side_at_birth": z.leg_side_at_birth,
            "target": ({"price": target.price, "kind": target.kind,
                        "hit_t": target.hit_t} if target else None),
            "state_final": z.state, "history": z.history,
        })

    return {
        "meta": {
            "research_only": True,
            "titulo": "BTA visual v2 - replay historico",
            "aviso": "Research only - No senal - No bot",
            "dataset": "BTCUSDT.P 15m historico (archivo estatico, sin conexion live)",
            "modelo": "research/bta_visual_model2.py",
            "doc": "research/bta_visual_model2_2026-07-05.md",
            "generado_por": "research/bta_visual_replay.py",
            "window": n,
        },
        "candles": [{"t": c["t"], "o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"]}
                    for c in window],
        "legs": leg_rows,
        "cdc": cdc_rows,
        "pivots": pivots,
        "repisas": repisas,
        "zones": zone_rows,
    }


def main() -> None:
    candles = json.load(open(DATA))
    payload = build_replay(candles)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    kb = os.path.getsize(OUT) // 1024
    z = payload["zones"]
    print(f"replay: {OUT} ({kb} KB)")
    print(f"  velas={len(payload['candles'])} legs={len(payload['legs'])} "
          f"cdc={len(payload['cdc'])} pivots={len(payload['pivots'])} "
          f"repisas={len(payload['repisas'])} zonas={len(z)}")
    from collections import Counter
    print(f"  estados finales de zona: {dict(Counter(x['state_final'] for x in z))}")


if __name__ == "__main__":
    main()
