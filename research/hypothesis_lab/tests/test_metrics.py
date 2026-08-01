from __future__ import annotations

import random

import pytest

from research.hypothesis_lab.metrics import (EXPLICIT_BLOCKS, basic_metrics,
                                               block_bootstrap_mean, holm,
                                               paired_block_bootstrap)


def row(setup_id, ts, net):
    return {"setup_id": setup_id, "activation_timestamp": ts, "net_r": net}


def test_break_even_win_rate_uses_observed_net_payoffs_and_sizing_is_separate():
    rows = [row("a", 1_704_067_200_000, 0.4), row("b", 1_704_153_600_000, -1.2),
            row("c", 1_704_240_000_000, 0.8)]
    out = basic_metrics(rows, fixed_fraction=0.02)
    assert out["break_even_win_rate_after_costs_observed_payoffs"] == pytest.approx(1.2 / 1.8)
    assert out["win_rate_after_costs"] == pytest.approx(2 / 3)
    assert out["payoff_inputs"]["partials_supported"] is True
    assert set(out) >= {"fixed_nominal_risk", "fixed_fraction_of_equity"}
    assert "max_drawdown_r" not in out["fixed_fraction_of_equity"]


def test_block_bootstrap_is_temporal_and_rejects_unpaired_universes():
    jan, feb = 1_704_067_200_000, 1_706_745_600_000
    candidate = [row("a", jan, 1.0), row("b", feb, 2.0), row("candidate-only", feb, 100.0)]
    baseline = [row("a", jan, 0.0), row("b", feb, 0.0), row("base-only", feb, -100.0)]
    mismatch = paired_block_bootstrap(candidate, baseline, random.Random(7), 200)
    assert mismatch["status"] == "blocked_pairing_mismatch"
    paired = paired_block_bootstrap(candidate[:2], baseline[:2], random.Random(7), 200)
    assert paired["status"] == "computed"
    assert paired["n_paired"] == 2
    assert paired["mean_difference_net_r"] == pytest.approx(1.5)
    mean = block_bootstrap_mean(candidate, random.Random(7), 200)
    assert mean["months"] == 2 and mean["minimum_detectable_effect_80pct_r"] is not None


def test_holm_is_monotone_and_unimplemented_methods_are_honest_blocks():
    adjusted = holm([{"id": "a", "p": .01}, {"id": "b", "p": .04}, {"id": "c", "p": .03}])
    assert [x["p_holm"] for x in adjusted] == sorted(x["p_holm"] for x in adjusted)
    assert EXPLICIT_BLOCKS["dsr"]["status"].startswith("blocked")
    assert EXPLICIT_BLOCKS["pbo"]["status"].startswith("blocked")
    assert "IID" in EXPLICIT_BLOCKS["block_monte_carlo"]["reason"]
