"""Modelo visual BTA v2 — research puro, NO toca el bot ni el dry-run.

Corrige los tres defectos que la auditoría visual (research/bta_visual_audit2_
2026-07-05.md) encontró en el prototipo v1 (`bta_visual_model.py`):

  D1. v1 clasificaba zonas contra el EQ del rango GLOBAL (`zone_from_poi` usaba
      `range_map.side_for_price`) — el mismo error conceptual del veto `disc_ok`
      que se sacó del bot. v2 clasifica contra el EQ LOCAL de la pierna activa
      (fib 0/0.5/1 por SwingLeg, como mide el profe en el zigzag).
  D2. v1 creaba los CDC ya nacidos "broken", sin ciclo de vida. v2 modela el CDC
      como ESCALERA: varios niveles simultáneos, cada uno con estados
      pending → broken → reclaimed / retest (lo visible en las capturas
      2026-05-15 y 2026-06-11, donde hay múltiples líneas CDC a la vez).
  D3. v1 confirmaba una zona con cualquier CDC "broken", aunque el quiebre fuera
      ANTERIOR al toque — exactamente la "entrada tardía" que el Diario penalizó
      (cdc confirmado al nacer: +0.095R vs zona fresca +0.707R). v2 exige
      quiebre POSTERIOR al toque y dentro de una ventana.

Además agrega los objetos que faltaban del mapa del profe:
  - TargetLiquidity (weak high/low sin barrer, con estado pending/hit),
  - ReferenceLevel: `alto_referencial` (techo no barrido), `minimo_ref`,
    y `repisa` (cluster de pivotes casi iguales = liquidez intermedia),
  - Zone v2 con máquina de estados completa (incluye target_hit y
    retest_continuation con cambio de rol), con historial auditable.

Todo es capa de LECTURA/VISUALIZACIÓN. Nada de esto decide trades.
"""
from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Optional

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import smc  # noqa: E402
from research.bta_visual_model import RangeMap, SwingLeg, build_range_map, build_swing_legs  # noqa: E402

# Tolerancia para "tocar" un nivel / agrupar pivotes en repisa (fracción del precio).
TOUCH_TOL = 0.0008
REPISA_TOL = 0.0012
CDC_KEEP = 6            # peldaños máximos vivos en la escalera (como el chart: pocos)
CONFIRM_WINDOW = 16     # velas tras el toque para aceptar el CDC (misma ventana research)


# ---------------------------------------------------------------------------
# D1 — premium/discount LOCAL por pierna (fib 0/0.5/1 del SwingLeg)
# ---------------------------------------------------------------------------

def active_leg(legs: list[SwingLeg], t: Optional[int] = None) -> Optional[SwingLeg]:
    """La pierna vigente: la última cuyo pivote B ya confirmó (a `t`, o la final)."""
    if not legs:
        return None
    if t is None:
        return legs[-1]
    vivas = [l for l in legs if l.pivot_b["confirm_idx"] is not None]
    vivas = [l for l in legs if l.pivot_b.get("t", 0) <= t] or legs[:1]
    return vivas[-1]


def leg_fibs(leg: SwingLeg) -> dict:
    """fib 0/0.5/1 de la pierna, orientados según su dirección (0 = origen)."""
    return {"fib0": leg.fib0, "fib05": (leg.fib0 + leg.fib1) / 2.0, "fib1": leg.fib1,
            "direction": leg.direction}


def leg_side(leg: SwingLeg, price: float) -> str:
    """Lado LOCAL del precio respecto al EQ de la pierna (no del rango global).

    Pierna alcista: bajo el 0.5 = discount (long de continuación barato).
    Pierna bajista: sobre el 0.5 = premium (short de continuación caro).
    """
    eq = (leg.leg_high + leg.leg_low) / 2.0
    if price < eq:
        return "discount"
    if price > eq:
        return "premium"
    return "equilibrium"


# ---------------------------------------------------------------------------
# D2 — CDC como escalera con ciclo de vida
# ---------------------------------------------------------------------------

@dataclass
class CDCLevel:
    """Un peldaño de la escalera CDC (línea roja del profe), con vida propia."""
    id: str
    price: float
    side: str                    # "high" (romperlo = bullish) | "low" (= bearish)
    created_t: int
    state: str = "pending"       # pending -> broken -> reclaimed | retest
    broken_t: Optional[int] = None
    broken_dir: Optional[str] = None   # bullish_break | bearish_break
    reclaimed_t: Optional[int] = None
    retest_t: Optional[int] = None
    history: list = field(default_factory=list)

    def _set(self, state: str, t: int) -> None:
        self.state = state
        self.history.append((state, t))


def cdc_ladder(candles: list[dict], piv: int = 2, keep: int = CDC_KEEP) -> list[CDCLevel]:
    """Escalera de CDC: cada swing confirmado crea un peldaño; cada peldaño vive.

    pending  — nivel creado (swing confirmado), sin quiebre por cierre.
    broken   — cierre más allá del nivel (bullish si era high, bearish si era low).
    reclaimed— cierre de vuelta al otro lado tras el quiebre (quiebre fallido).
    retest   — tras el quiebre, el precio VUELVE a tocar el nivel sin cerrarlo de
               vuelta: el nivel cambió de rol (soporte<->resistencia), señal visual
               de continuación en el chart del profe.
    Anti-repaint: solo pivotes con confirm_idx y solo cierres de vela.
    """
    highs, lows = smc.swing_points(candles, piv)
    events = sorted(
        [{"side": "high", **p} for p in highs] + [{"side": "low", **p} for p in lows],
        key=lambda p: p["confirm_idx"])
    ladder: list[CDCLevel] = []
    ev_i = 0
    n_created = 0
    for idx, c in enumerate(candles):
        # nacen peldaños cuando su pivote confirma
        while ev_i < len(events) and events[ev_i]["confirm_idx"] <= idx:
            p = events[ev_i]
            ev_i += 1
            lvl = CDCLevel(id=f"cdc_{n_created}", price=p["price"], side=p["side"],
                           created_t=candles[min(p["confirm_idx"], len(candles) - 1)]["t"])
            lvl.history.append(("pending", lvl.created_t))
            n_created += 1
            ladder.append(lvl)
            if len([l for l in ladder if l.state in ("pending", "broken", "retest")]) > keep:
                # se poda el peldaño MÁS ANTIGUO aún vivo (el chart mantiene pocos)
                vivos = [l for l in ladder if l.state in ("pending", "broken", "retest")]
                vivos[0]._set("pruned", c["t"])
        tol = c["c"] * TOUCH_TOL
        for lvl in ladder:
            if lvl.state == "pending":
                if lvl.side == "high" and c["c"] > lvl.price:
                    lvl.broken_t, lvl.broken_dir = c["t"], "bullish_break"
                    lvl._set("broken", c["t"])
                elif lvl.side == "low" and c["c"] < lvl.price:
                    lvl.broken_t, lvl.broken_dir = c["t"], "bearish_break"
                    lvl._set("broken", c["t"])
            elif lvl.state == "broken":
                back = (c["c"] < lvl.price) if lvl.broken_dir == "bullish_break" \
                    else (c["c"] > lvl.price)
                if back:
                    lvl.reclaimed_t = c["t"]
                    lvl._set("reclaimed", c["t"])
                elif c["t"] > (lvl.broken_t or 0) and c["l"] - tol <= lvl.price <= c["h"] + tol:
                    lvl.retest_t = c["t"]
                    lvl._set("retest", c["t"])
    return ladder


# ---------------------------------------------------------------------------
# Targets de liquidez y niveles de referencia (Alto Referencial / repisas)
# ---------------------------------------------------------------------------

@dataclass
class TargetLiquidity:
    id: str
    price: float
    kind: str                  # weak_high | weak_low | alto_referencial | minimo_ref | repisa
    created_t: int
    state: str = "pending"     # pending -> hit
    hit_t: Optional[int] = None


def find_targets(candles: list[dict], piv: int = 10) -> list[TargetLiquidity]:
    """Liquidez visible: weak highs/lows no barridos + techo/piso de referencia +
    repisas (clusters de >=2 pivotes casi iguales, la 'liquidez de repisa' celeste)."""
    highs, lows = smc.swing_points(candles, piv)
    n = len(candles)
    targets: list[TargetLiquidity] = []
    tid = 0

    def _mk(price, kind, t):
        nonlocal tid
        targets.append(TargetLiquidity(id=f"tgt_{tid}", price=price, kind=kind, created_t=t))
        tid += 1

    unswept_h = [p for p in highs if p["confirm_idx"] < n and
                 not any(c["h"] > p["price"] for c in candles[p["idx"] + 1:])]
    unswept_l = [p for p in lows if p["confirm_idx"] < n and
                 not any(c["l"] < p["price"] for c in candles[p["idx"] + 1:])]
    for p in unswept_h[-3:]:
        _mk(p["price"], "weak_high", candles[p["idx"]]["t"])
    for p in unswept_l[-3:]:
        _mk(p["price"], "weak_low", candles[p["idx"]]["t"])
    if unswept_h:
        top = max(unswept_h, key=lambda p: p["price"])
        _mk(top["price"], "alto_referencial", candles[top["idx"]]["t"])
    if unswept_l:
        bot = min(unswept_l, key=lambda p: p["price"])
        _mk(bot["price"], "minimo_ref", candles[bot["idx"]]["t"])

    # repisas: >=2 pivotes del mismo lado agrupados dentro de REPISA_TOL
    for pts, _kind in ((highs, "high"), (lows, "low")):
        used: set[int] = set()
        srt = sorted(pts, key=lambda p: p["price"])
        for i, a in enumerate(srt):
            if i in used:
                continue
            grupo = [a]
            for j in range(i + 1, len(srt)):
                if abs(srt[j]["price"] - a["price"]) <= a["price"] * REPISA_TOL:
                    grupo.append(srt[j])
                    used.add(j)
            if len(grupo) >= 2:
                mid = sum(p["price"] for p in grupo) / len(grupo)
                _mk(mid, "repisa", candles[max(p["idx"] for p in grupo)]["t"])
    return targets


def update_targets(targets: list[TargetLiquidity], candle: dict) -> None:
    for t in targets:
        if t.state == "pending" and candle["l"] <= t.price <= candle["h"]:
            t.state, t.hit_t = "hit", candle["t"]


# ---------------------------------------------------------------------------
# D3 — Zone v2: máquina de estados con CDC POSTERIOR al toque
# ---------------------------------------------------------------------------

@dataclass
class ZoneV2:
    """Zona del mapa (POI premium/discount, referencia, target) con estados del
    chart del profe: pending, tapped, confirmed, failed, retest_continuation,
    target_hit. Con historial auditable y regla anti-entrada-tardía."""
    id: str
    kind: str                   # premium_poi | discount_poi | counter_poi
    direction: str              # long | short (rol ORIGINAL de la zona)
    lo: float
    hi: float
    created_t: int
    source_tf: str = "15m"
    leg_side_at_birth: Optional[str] = None   # lado LOCAL (pierna) al nacer
    state: str = "pending"
    tap_t: Optional[int] = None
    confirmed_t: Optional[int] = None
    failed_t: Optional[int] = None
    retest_t: Optional[int] = None
    target_id: Optional[str] = None
    cdc_id: Optional[str] = None
    history: list = field(default_factory=list)

    def _set(self, state: str, t: int) -> None:
        self.state = state
        self.history.append((state, t))

    def touches(self, c: dict) -> bool:
        return c["l"] <= self.hi and c["h"] >= self.lo

    def step(self, c: dict, ladder: list[CDCLevel],
             target: Optional[TargetLiquidity] = None,
             bar_ms: int = 900_000) -> None:
        """Avanza la máquina de estados con UNA vela cerrada."""
        if self.state == "pending" and self.touches(c):
            self.tap_t = c["t"]
            self._set("tapped", c["t"])
            return  # la confirmación exige velas POSTERIORES al toque
        if self.state == "tapped":
            # CDC válido: quiebre en la dirección de la zona, POSTERIOR al toque
            # y dentro de la ventana (regla E4: sin esto es entrada tardía o toque pelado).
            want = "bullish_break" if self.direction == "long" else "bearish_break"
            limit = (self.tap_t or 0) + CONFIRM_WINDOW * bar_ms
            for lvl in ladder:
                if (lvl.broken_dir == want and lvl.broken_t is not None
                        and (self.tap_t or 0) < lvl.broken_t <= min(c["t"], limit)):
                    self.confirmed_t, self.cdc_id = lvl.broken_t, lvl.id
                    self._set("confirmed", lvl.broken_t)
                    break
        if self.state in ("tapped", "confirmed"):
            beyond = (c["c"] < self.lo) if self.direction == "long" else (c["c"] > self.hi)
            if beyond:
                self.failed_t = c["t"]
                self._set("failed", c["t"])
                return
        if self.state == "confirmed" and target and target.state == "hit" \
                and (target.hit_t or 0) >= (self.confirmed_t or 0):
            self.target_id = target.id
            self._set("target_hit", target.hit_t or c["t"])
            return
        if self.state == "failed" and self.failed_t is not None \
                and c["t"] > self.failed_t and self.touches(c):
            # la zona perdida se retestea desde el otro lado: cambia de ROL
            # (discount fallido pasa a resistencia de continuación short, y viceversa).
            self.retest_t = c["t"]
            self.direction = "short" if self.direction == "long" else "long"
            self._set("retest_continuation", c["t"])


def zone_from_poi_v2(poi: dict, legs: list[SwingLeg], zone_id: str) -> ZoneV2:
    """Zona desde un POI de Nexux, clasificada por la pierna LOCAL (no rango global)."""
    mid = (poi["lo"] + poi["hi"]) / 2.0
    direction = poi.get("dir", "long")
    leg = active_leg(legs, poi.get("t_conf") or poi.get("t"))
    side = leg_side(leg, mid) if leg else "equilibrium"
    kind = "counter_poi"
    if direction == "long" and side == "discount":
        kind = "discount_poi"
    elif direction == "short" and side == "premium":
        kind = "premium_poi"
    z = ZoneV2(id=zone_id, kind=kind, direction=direction, lo=poi["lo"], hi=poi["hi"],
               created_t=poi.get("t_conf") or poi.get("t") or 0,
               source_tf=poi.get("tf", "15m"), leg_side_at_birth=side)
    z.history.append(("pending", z.created_t))
    return z


# ---------------------------------------------------------------------------
# Snapshot para la UI (payload de solo lectura)
# ---------------------------------------------------------------------------

def visual_snapshot(candles: list[dict], pois: Optional[list[dict]] = None,
                    piv_leg: int = 10, piv_cdc: int = 2) -> dict:
    """Payload completo del indicador visual v2. SOLO contexto de lectura:
    `research_only=True` — nada de esto alimenta al bot ni a las señales."""
    rng: RangeMap = build_range_map(candles)
    legs = build_swing_legs(candles, piv=piv_leg)
    leg = active_leg(legs)
    ladder = cdc_ladder(candles, piv=piv_cdc)
    targets = find_targets(candles, piv=piv_leg)
    zones: list[ZoneV2] = []
    if pois:
        for i, poi in enumerate(pois):
            zones.append(zone_from_poi_v2(poi, legs, f"zone_{i}"))
    return {
        "research_only": True,
        "range": asdict(rng),                       # contexto global (NO veto)
        "active_leg": (asdict(leg) | leg_fibs(leg)) if leg else None,
        "cdc_ladder": [asdict(l) for l in ladder
                       if l.state in ("pending", "broken", "retest")][-CDC_KEEP:],
        "targets": [asdict(t) for t in targets],
        "zones": [asdict(z) for z in zones],
        "nota": ("premium/discount se lee LOCAL por pierna (fib 0/0.5/1); el rango "
                 "global es solo contexto visual. Ver bta_visual_audit2_2026-07-05."),
    }
