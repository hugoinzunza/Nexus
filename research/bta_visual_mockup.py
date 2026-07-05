"""Genera el mockup SVG del indicador visual BTA v2 sobre velas reales.

Research puro: lee `bta_btcusdtp_15m_recent.json`, corre `visual_snapshot` y
dibuja velas + rango + fib de la pierna activa + escalera CDC + targets.
Sin emojis (regla de UI de Hugo); etiquetas en español.

Correr:  .venv/bin/python3 research/bta_visual_mockup.py
Salida:  research/bta_visual_mockup_2026-07-05.svg
"""
from __future__ import annotations

import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import bta_visual_model2 as v2  # noqa: E402

W, H = 1280, 720
PAD_L, PAD_R, PAD_T, PAD_B = 70, 220, 40, 30
DATA = os.path.join(WT, "research", "bta_btcusdtp_15m_recent.json")
OUT = os.path.join(WT, "research", "bta_visual_mockup_2026-07-05.svg")

# paleta sobria (tema oscuro del hub)
C_BG = "#0e1116"
C_GRID = "#1d232c"
C_UP = "#3fb68b"
C_DN = "#e05563"
C_TXT = "#aeb7c2"
C_PREM = "#2a3342"
C_DISC = "#22303f"
C_FIB = "#c9a227"
C_CDC = {"pending": "#8b93a1", "broken": "#e05563", "retest": "#e0a955"}
C_TGT = "#4f9dde"


def main() -> None:
    candles = json.load(open(DATA))[-900:]   # ~9 días M15 (ventana tipo captura)
    snap = v2.visual_snapshot(candles)

    los = [c["l"] for c in candles]
    his = [c["h"] for c in candles]
    pmin, pmax = min(los), max(his)
    span = (pmax - pmin) or 1.0
    pmin -= span * 0.03
    pmax += span * 0.03
    span = pmax - pmin

    def X(i: int) -> float:
        return PAD_L + i * (W - PAD_L - PAD_R) / len(candles)

    def Y(p: float) -> float:
        return PAD_T + (pmax - p) * (H - PAD_T - PAD_B) / span

    bw = max(0.6, (W - PAD_L - PAD_R) / len(candles) * 0.7)
    parts: list[str] = []
    parts.append(f'<rect width="{W}" height="{H}" fill="{C_BG}"/>')
    parts.append(f'<text x="{PAD_L}" y="24" fill="{C_TXT}" font-size="15" '
                 f'font-family="system-ui">NexUX - indicador visual BTA v2 (research, '
                 f'solo lectura) - BTCUSDT.P 15m</text>')

    # grid horizontal
    for k in range(6):
        p = pmin + span * k / 5
        y = Y(p)
        parts.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" '
                     f'stroke="{C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{W-PAD_R+6}" y="{y+4:.1f}" fill="{C_TXT}" '
                     f'font-size="11" font-family="system-ui">{p:,.0f}</text>')

    # bandas premium/discount del RANGO (contexto suave, sin veto)
    rng = snap["range"]
    parts.append(f'<rect x="{PAD_L}" y="{Y(rng["premium_hi"]):.1f}" '
                 f'width="{W-PAD_L-PAD_R}" '
                 f'height="{abs(Y(rng["premium_lo"])-Y(rng["premium_hi"])):.1f}" '
                 f'fill="{C_PREM}" opacity="0.35"/>')
    parts.append(f'<rect x="{PAD_L}" y="{Y(rng["discount_hi"]):.1f}" '
                 f'width="{W-PAD_L-PAD_R}" '
                 f'height="{abs(Y(rng["discount_lo"])-Y(rng["discount_hi"])):.1f}" '
                 f'fill="{C_DISC}" opacity="0.35"/>')
    parts.append(f'<text x="{PAD_L+6}" y="{Y(rng["premium_hi"])+14:.1f}" fill="{C_TXT}" '
                 f'font-size="11" font-family="system-ui">premium (contexto global)</text>')
    parts.append(f'<text x="{PAD_L+6}" y="{Y(rng["discount_lo"])-6:.1f}" fill="{C_TXT}" '
                 f'font-size="11" font-family="system-ui">discount (contexto global)</text>')

    # velas
    for i, c in enumerate(candles):
        x = X(i)
        col = C_UP if c["c"] >= c["o"] else C_DN
        parts.append(f'<line x1="{x:.1f}" y1="{Y(c["h"]):.1f}" x2="{x:.1f}" '
                     f'y2="{Y(c["l"]):.1f}" stroke="{col}" stroke-width="0.7"/>')
        yo, yc = Y(c["o"]), Y(c["c"])
        top, hgt = min(yo, yc), max(abs(yc - yo), 0.8)
        parts.append(f'<rect x="{x-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                     f'height="{hgt:.1f}" fill="{col}"/>')

    # pierna activa: fib 0 / 0.5 / 1 LOCAL (la corrección D1)
    leg = snap["active_leg"]
    if leg:
        ia = leg["pivot_a"]["idx"]
        ib = leg["pivot_b"]["idx"]
        pa = leg["pivot_a"]["price"]
        pb = leg["pivot_b"]["price"]
        # limitar al viewport (los pivotes son índices de la ventana completa)
        ia, ib = max(0, min(ia, len(candles) - 1)), max(0, min(ib, len(candles) - 1))
        parts.append(f'<line x1="{X(ia):.1f}" y1="{Y(pa):.1f}" x2="{X(ib):.1f}" '
                     f'y2="{Y(pb):.1f}" stroke="{C_FIB}" stroke-width="1.5" '
                     f'stroke-dasharray="6 3" opacity="0.9"/>')
        for tag, price in (("0", leg["fib0"]), ("0.5 EQ local", leg["fib05"]),
                           ("1", leg["fib1"])):
            y = Y(price)
            if not (PAD_T <= y <= H - PAD_B):
                continue
            x0 = X(min(ia, ib))
            parts.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{W-PAD_R}" '
                         f'y2="{y:.1f}" stroke="{C_FIB}" stroke-width="1.4" '
                         f'stroke-dasharray="2 4" opacity="0.95"/>')
            # etiqueta a la IZQUIERDA del inicio de la pierna (no choca con targets)
            parts.append(f'<text x="{x0-6:.1f}" y="{y-5:.1f}" fill="{C_FIB}" '
                         f'font-size="12" font-family="system-ui" font-weight="600" '
                         f'text-anchor="end">fib {tag} ({price:,.0f})</text>')

    # escalera CDC (peldaños vivos, con estado)
    for lvl in snap["cdc_ladder"]:
        y = Y(lvl["price"])
        col = C_CDC.get(lvl["state"], C_CDC["pending"])
        parts.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" '
                     f'stroke="{col}" stroke-width="1.3" opacity="0.85"/>')
        parts.append(f'<text x="{PAD_L+4}" y="{y-4:.1f}" fill="{col}" font-size="11" '
                     f'font-family="system-ui">CDC {lvl["state"]} '
                     f'({lvl["price"]:,.0f})</text>')

    # targets de liquidez: solo los 3 más cercanos por arriba y por abajo del último
    # precio (el chart del profe muestra POCOS niveles; una escalera de 15 es ruido)
    last_px = candles[-1]["c"]
    pend = [t for t in snap["targets"] if t["state"] == "pending"
            and PAD_T <= Y(t["price"]) <= H - PAD_B]
    arriba = sorted([t for t in pend if t["price"] > last_px], key=lambda t: t["price"])[:3]
    abajo = sorted([t for t in pend if t["price"] <= last_px],
                   key=lambda t: -t["price"])[:3]
    refs = [t for t in pend if t["kind"] in ("alto_referencial", "minimo_ref")]
    vistos: set[str] = set()
    for t in refs + arriba + abajo:
        if t["id"] in vistos:
            continue
        vistos.add(t["id"])
        y = Y(t["price"])
        label = {"weak_high": "weak high", "weak_low": "weak low",
                 "alto_referencial": "Alto Referencial", "minimo_ref": "Minimo ref",
                 "repisa": "repisa liquidez"}.get(t["kind"], t["kind"])
        parts.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" '
                     f'stroke="{C_TGT}" stroke-width="1" stroke-dasharray="8 5" '
                     f'opacity="0.7"/>')
        parts.append(f'<text x="{W-PAD_R-6}" y="{y-4:.1f}" fill="{C_TGT}" '
                     f'font-size="11" font-family="system-ui" text-anchor="end">'
                     f'{label} ({t["price"]:,.0f})</text>')

    # leyenda de estados de zona (caja abajo-izquierda, dentro del lienzo)
    ley = ["Estados de zona: pending / tapped / confirmed (CDC posterior al toque)",
           "failed / retest_continuation (cambia de rol) / target_hit",
           "P-D operativo: LOCAL por pierna (fib 0.5); el rango global es solo contexto"]
    parts.append(f'<rect x="{PAD_L+2}" y="{H-PAD_B-64}" width="470" height="56" '
                 f'fill="{C_BG}" opacity="0.85" rx="4" stroke="{C_GRID}"/>')
    for k, txt in enumerate(ley):
        parts.append(f'<text x="{PAD_L+10}" y="{H-PAD_B-47+k*16}" fill="{C_TXT}" '
                     f'font-size="10.5" font-family="system-ui">{txt}</text>')

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}">' + "".join(parts) + "</svg>")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"mockup: {OUT}")
    print(f"  velas={len(candles)} cdc_vivos={len(snap['cdc_ladder'])} "
          f"targets={len(snap['targets'])} leg={snap['active_leg']['direction'] if snap['active_leg'] else None}")


if __name__ == "__main__":
    main()
