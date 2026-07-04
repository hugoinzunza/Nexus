"""Modelo estructural BTA visual para research.

Traduce lo observado en el TradingView del profe a objetos auditables sin tocar
el bot vivo ni intentar copiar código propietario:

- RangeMap: rango operativo, EQ, premium/discount.
- Zone: POI/referencia/target con estado.
- CharacterLevel: CDC persistente.
- SwingLeg: pivotes conectados como leg activa.
- SetupCandidate: composición explicable de zona + CDC + liquidez.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional

from modules.trading import smc


@dataclass(frozen=True)
class RangeMap:
    id: str
    t_start: int
    t_end: int
    high: float
    high_t: int
    high_kind: str
    low: float
    low_t: int
    low_kind: str
    eq: float
    premium_lo: float
    premium_hi: float
    discount_lo: float
    discount_hi: float
    bias: str = "range"

    def side_for_price(self, price: float) -> str:
        if price >= self.premium_lo:
            return "premium"
        if price <= self.discount_hi:
            return "discount"
        return "equilibrium"


@dataclass
class Zone:
    id: str
    kind: str
    lo: float
    hi: float
    created_t: int
    source_tf: str
    state: str = "pending"
    requires_cdc: bool = True
    cdc_level_id: Optional[str] = None
    validation_mark: str = "none"
    notes: list[str] = field(default_factory=list)

    @property
    def mid(self) -> float:
        return (self.lo + self.hi) / 2.0

    def touches(self, candle: dict) -> bool:
        return candle["l"] <= self.hi and candle["h"] >= self.lo


@dataclass
class CharacterLevel:
    id: str
    price: float
    direction: str
    created_t: int
    state: str = "pending"
    broken_t: Optional[int] = None
    reclaimed_t: Optional[int] = None


@dataclass(frozen=True)
class SwingLeg:
    id: str
    pivot_a: dict
    pivot_b: dict
    direction: str
    leg_high: float
    leg_low: float
    fib0: float
    fib1: float
    eq: float
    state: str = "completed"


@dataclass
class SetupCandidate:
    id: str
    zone_id: str
    range_id: str
    cdc_id: Optional[str]
    swing_leg_id: Optional[str]
    direction: str
    entry: float
    sl: float
    tp: Optional[float]
    tp_kind: Optional[str]
    rr: Optional[float]
    score: int
    decision: str
    reasons: list[str] = field(default_factory=list)


def to_dicts(items: Iterable[object]) -> list[dict]:
    return [asdict(item) for item in items]


def build_range_map(candles: list[dict], end_idx: Optional[int] = None,
                    window: int = 672, range_id: str = "range_0") -> RangeMap:
    """Build a mechanical range map over a recent window.

    `window=672` is 7 days on M15. This is only a proxy for the visual/manual
    range seen on TradingView; the catalog marks where manual validation is
    still required.
    """
    if not candles:
        raise ValueError("candles is empty")
    end = len(candles) - 1 if end_idx is None else min(end_idx, len(candles) - 1)
    start = max(0, end - window + 1)
    subset = candles[start:end + 1]
    high_c = max(subset, key=lambda c: c["h"])
    low_c = min(subset, key=lambda c: c["l"])
    high = high_c["h"]
    low = low_c["l"]
    eq = (high + low) / 2.0
    span = high - low
    bias = "range"
    if high_c["t"] < low_c["t"]:
        bias = "bearish"
    elif low_c["t"] < high_c["t"]:
        bias = "bullish"
    return RangeMap(
        id=range_id,
        t_start=subset[0]["t"],
        t_end=subset[-1]["t"],
        high=high,
        high_t=high_c["t"],
        high_kind="maximo",
        low=low,
        low_t=low_c["t"],
        low_kind="minimo",
        eq=eq,
        premium_lo=eq + span * 0.25,
        premium_hi=high,
        discount_lo=low,
        discount_hi=eq - span * 0.25,
        bias=bias,
    )


def detect_character_levels(candles: list[dict], piv: int = 2) -> list[CharacterLevel]:
    """Detect mechanical CDC candidates from confirmed pivots.

    A close above the last confirmed swing high is a bullish break. A close below
    the last confirmed swing low is bearish. This mirrors the CDC proxy already
    used in research backtests, but persists the level as an object.
    """
    highs, lows = smc.swing_points(candles, piv)
    hi_evt = sorted(highs, key=lambda p: p["confirm_idx"])
    lo_evt = sorted(lows, key=lambda p: p["confirm_idx"])
    levels: list[CharacterLevel] = []
    hi_i = lo_i = 0
    last_high = None
    last_low = None
    seen_breaks: set[tuple[str, int, float]] = set()

    for idx, candle in enumerate(candles):
        while hi_i < len(hi_evt) and hi_evt[hi_i]["confirm_idx"] <= idx:
            last_high = hi_evt[hi_i]
            hi_i += 1
        while lo_i < len(lo_evt) and lo_evt[lo_i]["confirm_idx"] <= idx:
            last_low = lo_evt[lo_i]
            lo_i += 1
        if last_high and candle["c"] > last_high["price"]:
            key = ("bullish_break", last_high["idx"], last_high["price"])
            if key not in seen_breaks:
                seen_breaks.add(key)
                levels.append(CharacterLevel(
                    id=f"cdc_bull_{len(levels)}",
                    price=last_high["price"],
                    direction="bullish_break",
                    created_t=candle["t"],
                    state="broken",
                    broken_t=candle["t"],
                ))
        if last_low and candle["c"] < last_low["price"]:
            key = ("bearish_break", last_low["idx"], last_low["price"])
            if key not in seen_breaks:
                seen_breaks.add(key)
                levels.append(CharacterLevel(
                    id=f"cdc_bear_{len(levels)}",
                    price=last_low["price"],
                    direction="bearish_break",
                    created_t=candle["t"],
                    state="broken",
                    broken_t=candle["t"],
                ))
    return levels


def build_swing_legs(candles: list[dict], piv: int = 10) -> list[SwingLeg]:
    """Connect confirmed pivots into simple swing legs."""
    highs, lows = smc.swing_points(candles, piv)
    pivots = []
    for p in highs:
        pivots.append({"side": "high", **p})
    for p in lows:
        pivots.append({"side": "low", **p})
    pivots.sort(key=lambda p: (p["confirm_idx"], p["idx"]))

    legs: list[SwingLeg] = []
    last = None
    for p in pivots:
        if last is None:
            last = p
            continue
        if p["side"] == last["side"]:
            if (p["side"] == "high" and p["price"] >= last["price"]) or \
                    (p["side"] == "low" and p["price"] <= last["price"]):
                last = p
            continue
        direction = "up" if p["price"] > last["price"] else "down"
        leg_high = max(last["price"], p["price"])
        leg_low = min(last["price"], p["price"])
        legs.append(SwingLeg(
            id=f"leg_{len(legs)}",
            pivot_a=last,
            pivot_b=p,
            direction=direction,
            leg_high=leg_high,
            leg_low=leg_low,
            fib0=last["price"],
            fib1=p["price"],
            eq=(leg_high + leg_low) / 2.0,
        ))
        last = p
    return legs


def zone_from_poi(poi: dict, range_map: RangeMap, zone_id: str) -> Zone:
    """Convert an existing Nexux POI dict into a BTA visual Zone."""
    mid = (poi["lo"] + poi["hi"]) / 2.0
    direction = poi.get("dir")
    side = range_map.side_for_price(mid)
    kind = "counter_poi"
    if direction == "short" and side == "premium":
        kind = "premium_poi"
    elif direction == "long" and side == "discount":
        kind = "discount_poi"
    return Zone(
        id=zone_id,
        kind=kind,
        lo=poi["lo"],
        hi=poi["hi"],
        created_t=poi.get("t_conf", poi.get("t", range_map.t_end)),
        source_tf=poi.get("source_tf", poi.get("tf", "unknown")),
        requires_cdc=True,
        notes=[f"range_side={side}", f"poi_dir={direction}"],
    )


def update_zone_state(zone: Zone, candle: dict, direction: str,
                      cdc: Optional[CharacterLevel] = None) -> None:
    """Update one zone state from a new candle.

    This is intentionally conservative. It only models the states observed in
    the visual audit: tapped, confirmed, failed, retest_continuation.
    """
    prior_state = zone.state
    if zone.state == "pending" and zone.touches(candle):
        zone.state = "tapped"
    if zone.state == "tapped" and cdc and cdc.state in {"broken", "respected"}:
        zone.state = "confirmed"
        zone.cdc_level_id = cdc.id
        zone.validation_mark = "check"

    if direction == "long" and candle["c"] < zone.lo:
        zone.state = "failed" if zone.state != "failed" else zone.state
    elif direction == "short" and candle["c"] > zone.hi:
        zone.state = "failed" if zone.state != "failed" else zone.state

    if prior_state == "failed" and zone.state == "failed" and zone.touches(candle):
        zone.state = "retest_continuation"


def nearest_liquidity_target(direction: str, entry: float, swing_legs: list[SwingLeg]) -> tuple[Optional[float], Optional[str]]:
    """Use leg extremes as a simple visible-liquidity proxy."""
    if direction == "long":
        cands = sorted({leg.leg_high for leg in swing_legs if leg.leg_high > entry})
        return (cands[0], "range_high") if cands else (None, None)
    cands = sorted({leg.leg_low for leg in swing_legs if leg.leg_low < entry}, reverse=True)
    return (cands[0], "range_low") if cands else (None, None)


def score_candidate(zone: Zone, range_map: RangeMap, direction: str,
                    cdc: Optional[CharacterLevel], swing_leg: Optional[SwingLeg],
                    entry: float, sl: float, tp: Optional[float]) -> tuple[int, list[str], Optional[float]]:
    score = 0
    reasons: list[str] = []
    zone_side_ok = (direction == "long" and zone.kind == "discount_poi") or \
        (direction == "short" and zone.kind == "premium_poi")
    if zone_side_ok:
        score += 2
        reasons.append("zona correcta para premium/discount")
    if cdc and cdc.state in {"broken", "respected"}:
        score += 2
        reasons.append("CDC confirmado")
    if zone.validation_mark != "none" or zone.state == "confirmed":
        score += 1
        reasons.append("reaccion visible/estado confirmado")
    if swing_leg and ((direction == "long" and swing_leg.direction == "up") or
                     (direction == "short" and swing_leg.direction == "down")):
        score += 1
        reasons.append("alineado con leg")
    rr = None
    risk = entry - sl if direction == "long" else sl - entry
    if tp is not None and risk > 0:
        rr = (tp - entry) / risk if direction == "long" else (entry - tp) / risk
        if rr >= 2:
            score += 2
            reasons.append("target liquidez RR>=2")
    if range_map.bias in {"bullish", "bearish"}:
        score += 1
        reasons.append(f"rango con sesgo {range_map.bias}")
    return score, reasons, rr


def build_setup_candidate(candidate_id: str, zone: Zone, range_map: RangeMap,
                          direction: str, entry: float, sl: float,
                          cdc: Optional[CharacterLevel] = None,
                          swing_leg: Optional[SwingLeg] = None,
                          tp: Optional[float] = None,
                          tp_kind: Optional[str] = None) -> SetupCandidate:
    score, reasons, rr = score_candidate(zone, range_map, direction, cdc, swing_leg,
                                         entry, sl, tp)
    decision = "valid" if score >= 6 and rr is not None and rr >= 2 else "watch"
    if zone.state in {"failed"}:
        decision = "invalidated"
    elif score < 4:
        decision = "skip"
    return SetupCandidate(
        id=candidate_id,
        zone_id=zone.id,
        range_id=range_map.id,
        cdc_id=cdc.id if cdc else None,
        swing_leg_id=swing_leg.id if swing_leg else None,
        direction=direction,
        entry=entry,
        sl=sl,
        tp=tp,
        tp_kind=tp_kind,
        rr=rr,
        score=score,
        decision=decision,
        reasons=reasons,
    )
