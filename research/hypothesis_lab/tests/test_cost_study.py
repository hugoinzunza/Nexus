from __future__ import annotations

import copy

import pytest

from research.hypothesis_lab.cost_study import (
    DEFAULT_SPEC,
    _sha256,
    descriptive_strata,
    friction_components,
    load_frozen_spec,
    simulate_stop,
    stop_price,
)


SCENARIO = {
    "id": "base",
    "entry_maker_fee_rate": 0.0002,
    "exit_maker_fee_rate": 0.0002,
    "exit_taker_fee_rate": 0.0005,
    "roundtrip_spread_rate": 0.0002,
    "entry_slippage_rate": 0.0001,
    "exit_maker_slippage_rate": 0.00005,
    "exit_taker_slippage_rate": 0.0002,
}


def setup(**overrides):
    row = {
        "setup_id": "BTCUSDT:1h:test",
        "pair": "BTCUSDT",
        "sel_tf": "1h",
        "dir": "long",
        "entry": 100.0,
        "sl": 90.0,
        "original_tp": 130.0,
        "decision_index": 1,
        "decision_timestamp": 1_000,
        "activation_index": 2,
        "activation_timestamp": 2_000,
        "max_forward_bars": 4,
    }
    row.update(overrides)
    return row


def candles(*bars):
    return [
        {"t": index * 1_000, "o": values[0], "h": values[1], "l": values[2], "c": values[3]}
        for index, values in enumerate(bars)
    ]


def test_cost_in_r_increases_monotonically_as_stop_tightens():
    rows = candles(
        (95, 96, 94, 95),
        (99, 100, 98, 99),
        (100, 101, 99, 100),
        (101, 105, 99, 104),
        (104, 106, 102, 105),
        (105, 106, 104, 105),
    )
    costs = [simulate_stop(setup(), rows, multiplier, SCENARIO)["cost_r"] for multiplier in (1.0, 0.75, 0.5, 0.35)]
    assert costs == sorted(costs)
    assert costs[0] < costs[-1]


def test_target_price_is_fixed_while_target_r_changes():
    rows = candles(
        (95, 96, 94, 95),
        (99, 100, 98, 99),
        (100, 101, 99, 100),
        (101, 131, 100, 130),
        (130, 131, 129, 130),
        (130, 131, 129, 130),
    )
    baseline = simulate_stop(setup(), rows, 1.0, SCENARIO)
    tighter = simulate_stop(setup(), rows, 0.5, SCENARIO)
    assert baseline["target_price"] == tighter["target_price"] == 130.0
    assert baseline["gross_r"] == pytest.approx(3.0)
    assert tighter["gross_r"] == pytest.approx(6.0)
    assert stop_price(setup(), 0.5) == 95.0


def test_activation_bar_target_is_never_credited():
    rows = candles(
        (95, 96, 94, 95),
        (99, 100, 98, 99),
        (100, 135, 99, 101),
        (101, 102, 89, 90),
        (90, 91, 89, 90),
        (90, 91, 89, 90),
    )
    result = simulate_stop(setup(), rows, 1.0, SCENARIO)
    assert result["status"] == "sl"
    assert result["gross_r"] == -1.0


def test_stop_wins_when_stop_and_target_share_a_bar():
    rows = candles(
        (95, 96, 94, 95),
        (99, 100, 98, 99),
        (100, 101, 99, 100),
        (100, 135, 85, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),
    )
    result = simulate_stop(setup(), rows, 1.0, SCENARIO)
    assert result["status"] == "sl"
    assert result["gross_r"] == -1.0


def test_candles_before_activation_cannot_change_result():
    rows = candles(
        (95, 96, 94, 95),
        (99, 100, 98, 99),
        (100, 101, 99, 100),
        (101, 110, 100, 108),
        (108, 131, 107, 130),
        (130, 131, 129, 130),
    )
    changed = copy.deepcopy(rows)
    changed[0].update({"o": 1, "h": 10_000, "l": 0, "c": 9_000})
    changed[1].update({"o": 9_000, "h": 20_000, "l": 0, "c": 1})
    original = simulate_stop(setup(), rows, 0.75, SCENARIO)
    mutated = simulate_stop(setup(), changed, 0.75, SCENARIO)
    assert original == mutated


def test_observed_friction_overrides_declared_scenario_and_is_labeled():
    row = setup(
        observed_roundtrip_spread_rate=0.00009,
        observed_entry_slippage_rate=0.00003,
        observed_taker_exit_slippage_rate=0.00007,
    )
    value = friction_components(row, SCENARIO, "taker")
    assert value["provenance"] == "observed"
    assert value["roundtrip_spread_rate"] == 0.00009
    assert value["entry_slippage_rate"] == 0.00003
    assert value["exit_slippage_rate"] == 0.00007


def test_partial_observation_falls_back_to_whole_declared_scenario():
    row = setup(observed_roundtrip_spread_rate=0.00009)
    value = friction_components(row, SCENARIO, "maker")
    assert value["provenance"] == "declared_scenario"
    assert value["roundtrip_spread_rate"] == SCENARIO["roundtrip_spread_rate"]
    assert value["entry_slippage_rate"] == SCENARIO["entry_slippage_rate"]


def test_spec_fingerprint_y_gobernanza_quedan_congelados():
    spec = load_frozen_spec()
    assert _sha256(DEFAULT_SPEC) == "3d232764ff367654551a0df9775e5a164df2164ba0b9ef366eed2b25f5f9f608"
    assert spec["governance"]["execution_enabled"] is False
    assert spec["governance"]["automatic_promotion"] is False


def test_estratos_son_descriptivos_y_preservan_emparejamiento():
    baseline = [
        {"setup_id": "a", "pair": "BTCUSDT", "timeframe": "1h", "activation_timestamp": 1,
         "status": "sl", "net_r": -1.0, "cost_r": 0.1,
         "cost_components": {"provenance": "declared_scenario"}},
        {"setup_id": "b", "pair": "ETHUSDT", "timeframe": "4h", "activation_timestamp": 2,
         "status": "tp", "net_r": 2.0, "cost_r": 0.1,
         "cost_components": {"provenance": "declared_scenario"}},
    ]
    candidate = copy.deepcopy(baseline)
    candidate[0]["net_r"] = -0.5
    candidate[1]["net_r"] = 2.25
    strata = descriptive_strata(candidate, baseline)
    assert strata["by_pair"]["BTCUSDT"]["paired_avg_net_r_delta"] == 0.5
    assert strata["by_timeframe"]["4h"]["paired_avg_net_r_delta"] == 0.25
