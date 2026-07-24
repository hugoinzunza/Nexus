import pytest

from research.coinglass_hobbyist_study import (
    COST,
    attach_outcomes,
    evaluate_rule,
    rule_signals,
)


def _bar(index, price):
    return {
        "time": index * 4 * 60 * 60 * 1000,
        "month": "2026-01",
        "price": price,
        "price_change": 0.01,
        "oi_change": 0.01,
        "funding": 0.005,
        "crowd_long": 65,
        "taker_buy": 53,
        "book_ratio": 1.5,
        "book_pressure": 0.2,
        "liq_imbalance": 0.5,
        "long_liq": 1,
        "short_liq": 3,
        "partial_radar": 0.2,
    }


def test_outcome_uses_only_future_price_at_requested_horizon():
    bars = [_bar(0, 100), _bar(1, 101), _bar(2, 103), _bar(3, 102)]

    attach_outcomes(bars)

    assert bars[0]["future_returns"]["1"] == pytest.approx(0.01)
    assert bars[0]["future_returns"]["2"] == pytest.approx(0.03)
    assert bars[1]["future_returns"]["2"] == pytest.approx(102 / 101 - 1)
    assert bars[-1]["future_returns"]["1"] is None


def test_fixed_rules_do_not_read_future_outcome():
    bar = _bar(0, 100)
    before = rule_signals(bar)
    bar["future_returns"] = {"1": -0.99}

    assert rule_signals(bar) == before
    assert before["partial_radar"] == 1
    assert before["crowding_contrarian"] == -1


def test_evaluation_deducts_cost_and_skips_overlapping_trade():
    bars = [_bar(index, 100 + index) for index in range(6)]
    attach_outcomes(bars)

    result = evaluate_rule(bars, "buy_hold", horizon=2, start=0, end=len(bars))

    expected = [
        102 / 100 - 1 - COST,
        104 / 102 - 1 - COST,
    ]
    assert result["n"] == 2
    assert result["avg_net_bps"] == round(sum(expected) / 2 * 10_000, 2)
