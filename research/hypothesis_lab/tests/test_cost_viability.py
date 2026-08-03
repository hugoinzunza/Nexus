from __future__ import annotations

import copy

import pytest

from research.hypothesis_lab.cost_viability import (
    DEFAULT_SPEC,
    _sha256,
    add_operational_fields,
    load_frozen_spec,
    simulate_portfolio,
    transition_decomposition,
)


SCENARIO = {
    "id": "base",
    "entry_maker_fee_rate": 0.0,
    "exit_maker_fee_rate": 0.0,
    "exit_taker_fee_rate": 0.0,
    "roundtrip_spread_rate": 0.0,
    "entry_slippage_rate": 0.0,
    "exit_maker_slippage_rate": 0.0,
    "exit_taker_slippage_rate": 0.0,
}


PORTFOLIO = {
    "starting_equity_usd": 100_000.0,
    "sizing_modes": ["fixed_dollar", "fixed_fraction_current_equity"],
    "primary_sizing_mode": "fixed_dollar",
    "fixed_stop_loss_budget_usd": 1_000.0,
    "desired_stop_loss_fraction_of_equity": 0.01,
    "cost_inclusive_stop_sizing": True,
    "max_account_heat_fraction": 0.05,
    "max_single_trade_notional_multiple": 1.5,
    "allocation_policy": "all_or_nothing",
    "close_before_open_at_same_timestamp": True,
}


def setup(setup_id="a", rr=3.0):
    return {"setup_id": setup_id, "entry": 100.0, "sl": 90.0, "rr": rr}


def simulated(setup_id="a", *, activation=1_000, resolution=2_000, net_r=2.0,
              status="tp", risk=10.0):
    return {
        "setup_id": setup_id,
        "pair": "BTCUSDT",
        "timeframe": "1h",
        "activation_timestamp": activation,
        "resolution_timestamp": resolution,
        "entry": 100.0,
        "tested_stop": 100.0 - risk,
        "risk_price": risk,
        "status": status,
        "net_r": net_r,
        "gross_r": net_r,
        "total_cost_rate": 0.0,
    }


def operational(row, source=None):
    return add_operational_fields(row, source or setup(row["setup_id"]), SCENARIO)


def test_fixed_notional_return_removes_pure_r_rescaling():
    wide = operational(simulated(net_r=3.0, risk=10.0))
    tight = operational(simulated(net_r=6.0, risk=5.0))
    assert wide["net_return_per_entry_notional"] == pytest.approx(0.30)
    assert tight["net_return_per_entry_notional"] == pytest.approx(0.30)


def test_tighter_stop_requires_more_notional_for_same_fixed_risk():
    wide = operational(simulated(risk=10.0))
    tight = operational(simulated(risk=5.0))
    assert wide["desired_notional_multiple_at_1pct_risk"] == pytest.approx(0.1)
    assert tight["desired_notional_multiple_at_1pct_risk"] == pytest.approx(0.2)


def test_transition_decomposition_attributes_destroyed_winner():
    baseline = [operational(simulated(status="tp", net_r=3.0, risk=10.0))]
    candidate = [operational(simulated(status="sl", net_r=-1.0, risk=5.0))]
    value = transition_decomposition(candidate, baseline)["tp->sl"]
    assert value["n"] == 1
    assert value["mean_delta_r"] == -4.0
    assert value["mean_delta_notional_pct"] == pytest.approx(-35.0)


def test_portfolio_rejects_trade_above_single_notional_cap():
    row = operational(simulated(risk=0.5))
    result = simulate_portfolio([row], PORTFOLIO, gross_cap=5.0, sizing_mode="fixed_dollar")
    assert result["accepted"] == 0
    assert result["skipped"] == {"single_trade_notional_cap": 1}


def test_portfolio_releases_old_trade_before_same_timestamp_open():
    first = operational(simulated("a", activation=1_000, resolution=2_000, risk=1.0))
    second = operational(simulated("b", activation=2_000, resolution=3_000, risk=1.0))
    constrained = {**PORTFOLIO, "max_account_heat_fraction": 0.011}
    result = simulate_portfolio([first, second], constrained, gross_cap=5.0, sizing_mode="fixed_dollar")
    assert result["accepted"] == 2
    assert result["closed"] == 2
    assert result["max_simultaneous_positions"] == 1


def test_activation_bar_resolution_is_closed_not_left_active():
    row = operational(simulated(activation=1_000, resolution=1_000, status="sl", net_r=-1.0))
    result = simulate_portfolio([row], PORTFOLIO, gross_cap=5.0, sizing_mode="fixed_dollar")
    assert result["accepted"] == 1
    assert result["closed"] == 1
    assert result["unresolved_active"] == 0


def test_cost_inclusive_sizing_caps_stop_loss_to_one_percent():
    row = operational(simulated(status="sl", net_r=-1.0))
    row["stop_loss_cost_r"] = 0.25
    row["net_r"] = -1.25
    result = simulate_portfolio([row], PORTFOLIO, gross_cap=5.0, sizing_mode="fixed_dollar")
    assert result["ending_equity_usd"] == pytest.approx(99_000.0)


def test_fractional_sizing_uses_current_equity_after_a_close():
    first = operational(simulated("a", activation=1_000, resolution=2_000, status="tp", net_r=1.0))
    second = operational(simulated("b", activation=2_000, resolution=3_000, status="tp", net_r=1.0))
    result = simulate_portfolio(
        [first, second], PORTFOLIO, gross_cap=5.0, sizing_mode="fixed_fraction_current_equity"
    )
    assert result["ending_equity_usd"] == pytest.approx(102_010.0)


def test_spec_is_frozen_research_only_and_has_no_promotion_path():
    spec = load_frozen_spec()
    assert _sha256(DEFAULT_SPEC) == "c354b84aa3d364d313dc6d79f4a39919bd1057ced62e127377efffa493fd4697"
    assert spec["statistics"]["same_dataset_reuse_makes_all_results_exploratory"] is True
    assert spec["governance"]["automatic_promotion"] is False
    assert spec["governance"]["bot_changes_allowed"] is False


def test_input_rows_are_not_mutated_by_operational_enrichment():
    row = simulated()
    before = copy.deepcopy(row)
    operational(row)
    assert row == before
