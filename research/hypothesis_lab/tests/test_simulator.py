from __future__ import annotations

import pytest

from research.hypothesis_lab.simulator import simulate


def candle(t, high, low, close=100.0):
    return {"t": t, "o": 100.0, "h": high, "l": low, "c": close, "v": 1.0}


def setup(**updates):
    row = {"setup_id": "s1", "decision_timestamp": 0, "activation_timestamp": 1,
           "decision_index": 0, "activation_index": 1, "max_forward_bars": 3,
           "entry": 100.0, "sl": 90.0, "original_tp": 120.0, "dir": "long"}
    row.update(updates)
    return row


def test_activation_bar_never_credits_tp():
    bars = [candle(0, 100, 99), candle(1, 130, 95), candle(2, 101, 89)]
    result = simulate(setup(), bars, {"id": "rr_2", "rr": 2.0}, 0.0)
    assert result["status"] == "sl"
    assert result["gross_r"] == -1.0
    assert result["resolution_timestamp"] == 2


def test_activation_bar_can_stop_and_later_ambiguous_bar_is_sl_first():
    activation_stop = [candle(0, 100, 99), candle(1, 130, 89)]
    assert simulate(setup(max_forward_bars=1), activation_stop,
                    {"id": "rr_2", "rr": 2.0}, 0)["status"] == "sl"
    later_ambiguous = [candle(0, 100, 99), candle(1, 105, 95), candle(2, 125, 85)]
    result = simulate(setup(max_forward_bars=2), later_ambiguous,
                      {"id": "rr_2", "rr": 2.0}, 0)
    assert result["status"] == "sl" and result["resolution_timestamp"] == 2


def test_timeout_is_explicit_and_closed_at_observed_close():
    bars = [candle(0, 100, 99), candle(1, 105, 95), candle(2, 108, 94, 105)]
    result = simulate(setup(max_forward_bars=2), bars, {"id": "rr_2", "rr": 2.0}, 0.001)
    assert result["status"] == "timeout_closed"
    assert result["gross_r"] == pytest.approx(0.5)
    assert result["cost_r"] == pytest.approx(0.01)
    assert result["net_r"] == pytest.approx(0.49)


def test_unactivated_candidate_is_kept_as_discarded():
    result = simulate(setup(activation_index=None, activation_timestamp=None), [candle(0, 1, 1)],
                      {"id": "rr_1", "rr": 1.0}, 0.0)
    assert result["status"] == "discarded"
    assert result["discarded_reason"] == "not_activated"
    assert result["setup_id"] == "s1"

