"""Checks básicos para bta_visual_model.py.

Se ejecuta con:
  python3 research/test_bta_visual_model.py
"""
from __future__ import annotations

import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import bta_visual_model as bta  # noqa: E402


def candle(i, o, h, l, c):
    return {"t": i * 900_000, "o": o, "h": h, "l": l, "c": c, "v": 1.0}


def sample_candles():
    prices = [
        (100, 102, 99, 101),
        (101, 104, 100, 103),
        (103, 106, 102, 105),
        (105, 108, 104, 107),
        (107, 110, 106, 109),
        (109, 109, 103, 104),
        (104, 105, 99, 100),
        (100, 101, 94, 95),
        (95, 97, 90, 92),
        (92, 96, 91, 95),
        (95, 99, 94, 98),
        (98, 103, 97, 102),
        (102, 109, 101, 108),
        (108, 112, 107, 111),
        (111, 113, 108, 109),
        (109, 110, 103, 104),
        (104, 105, 96, 97),
        (97, 99, 92, 93),
        (93, 96, 91, 95),
        (95, 101, 88, 89),
    ]
    return [candle(i, *p) for i, p in enumerate(prices)]


def test_range_map():
    candles = sample_candles()
    rm = bta.build_range_map(candles, window=len(candles))
    assert rm.high == 113
    assert rm.low == 88
    assert rm.eq == 100.5
    assert rm.side_for_price(110) == "premium"
    assert rm.side_for_price(92) == "discount"


def test_cdc_and_legs():
    candles = sample_candles()
    cdcs = bta.detect_character_levels(candles, piv=1)
    assert any(c.direction == "bullish_break" for c in cdcs)
    assert any(c.direction == "bearish_break" for c in cdcs)
    legs = bta.build_swing_legs(candles, piv=1)
    assert legs
    assert all(leg.leg_high >= leg.leg_low for leg in legs)


def test_zone_state_and_candidate():
    candles = sample_candles()
    rm = bta.build_range_map(candles, window=len(candles))
    zone = bta.Zone(
        id="z0",
        kind="discount_poi",
        lo=91,
        hi=96,
        created_t=candles[8]["t"],
        source_tf="15m",
    )
    cdc = bta.CharacterLevel(
        id="cdc0",
        price=99,
        direction="bullish_break",
        created_t=candles[11]["t"],
        state="broken",
        broken_t=candles[11]["t"],
    )
    bta.update_zone_state(zone, candles[8], "long")
    assert zone.state == "tapped"
    bta.update_zone_state(zone, candles[11], "long", cdc)
    assert zone.state == "confirmed"
    assert zone.validation_mark == "check"

    candidate = bta.build_setup_candidate(
        "s0",
        zone,
        rm,
        "long",
        entry=96,
        sl=90,
        cdc=cdc,
        swing_leg=None,
        tp=112,
        tp_kind="range_high",
    )
    assert candidate.rr and candidate.rr >= 2
    assert candidate.score >= 6
    assert candidate.decision == "valid"


def test_failed_to_retest_continuation():
    zone = bta.Zone(
        id="z1",
        kind="premium_poi",
        lo=108,
        hi=112,
        created_t=0,
        source_tf="15m",
    )
    bta.update_zone_state(zone, candle(1, 111, 113, 107, 113), "short")
    assert zone.state == "failed"
    bta.update_zone_state(zone, candle(2, 114, 115, 110, 111), "short")
    assert zone.state == "retest_continuation"


def main():
    test_range_map()
    test_cdc_and_legs()
    test_zone_state_and_candidate()
    test_failed_to_retest_continuation()
    print("bta_visual_model checks OK")


if __name__ == "__main__":
    main()
