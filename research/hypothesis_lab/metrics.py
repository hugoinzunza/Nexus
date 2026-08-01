"""Observed-payoff metrics and dependence-aware inference."""
from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


def _month(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m")


def _year(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y")


def basic_metrics(rows: list[dict[str, Any]], fixed_fraction: float = 0.01) -> dict[str, Any]:
    used = sorted((r for r in rows if r.get("net_r") is not None),
                  key=lambda r: (r.get("activation_timestamp") or 0, r["setup_id"]))
    rs = [float(r["net_r"]) for r in used]
    positives, negatives = [x for x in rs if x > 0], [x for x in rs if x < 0]
    gross_profit, gross_loss = sum(positives), abs(sum(negatives))
    avg_win = statistics.fmean(positives) if positives else None
    avg_loss = abs(statistics.fmean(negatives)) if negatives else None
    be_wr = (avg_loss / (avg_win + avg_loss)) if avg_win is not None and avg_loss is not None else None
    eq_r = peak_r = 0.0
    max_dd_r = 0.0
    loss_streak = max_loss_streak = 0
    equity = peak_equity = 1.0
    max_dd_pct = 0.0
    by_year: dict[str, list[float]] = defaultdict(list)
    for row, r in zip(used, rs):
        eq_r += r
        peak_r = max(peak_r, eq_r)
        max_dd_r = max(max_dd_r, peak_r - eq_r)
        loss_streak = loss_streak + 1 if r < 0 else 0
        max_loss_streak = max(max_loss_streak, loss_streak)
        equity *= max(0.0, 1.0 + fixed_fraction * r)
        peak_equity = max(peak_equity, equity)
        max_dd_pct = max(max_dd_pct, (peak_equity - equity) / peak_equity if peak_equity else 1.0)
        by_year[_year(int(row["activation_timestamp"]))].append(r)
    yearly = {y: {"n": len(v), "avg_net_r": statistics.fmean(v)} for y, v in sorted(by_year.items())}
    return {
        "n_candidates": len(rows), "n_used": len(used),
        "discarded": len(rows) - len(used),
        "avg_net_r": statistics.fmean(rs) if rs else None,
        "profit_factor_net": (gross_profit / gross_loss if gross_loss else None),
        "win_rate_after_costs": (len(positives) / len(rs) if rs else None),
        "break_even_win_rate_after_costs_observed_payoffs": be_wr,
        "payoff_inputs": {"avg_positive_net_r": avg_win, "avg_negative_net_r_abs": avg_loss,
                          "partials_supported": True, "formula": "observed net payoff means"},
        "fixed_nominal_risk": {"max_drawdown_r": max_dd_r, "max_losing_streak": max_loss_streak},
        "fixed_fraction_of_equity": {"risk_fraction": fixed_fraction,
                                      "ending_equity_multiple": equity,
                                      "max_drawdown_pct": 100 * max_dd_pct,
                                      "portfolio_claim": False,
                                      "assumption": "sequential trades; concurrent account heat not modeled"},
        "temporal_stability": {"by_year": yearly,
                               "positive_year_fraction": (sum(v["avg_net_r"] > 0 for v in yearly.values()) / len(yearly)
                                                          if yearly else None)},
    }


def block_bootstrap_mean(rows: list[dict[str, Any]], rng: random.Random, iterations: int) -> dict[str, Any]:
    blocks: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.get("net_r") is not None:
            blocks[_month(int(r["activation_timestamp"]))].append(float(r["net_r"]))
    keys = sorted(blocks)
    if len(keys) < 2:
        return {"status": "blocked_insufficient_temporal_blocks", "months": len(keys), "ci95": None,
                "minimum_detectable_effect_80pct_r": None}
    draws = []
    for _ in range(iterations):
        vals = []
        for _ in keys:
            vals.extend(blocks[keys[rng.randrange(len(keys))]])
        draws.append(statistics.fmean(vals))
    draws.sort()
    lo = draws[int(0.025 * (iterations - 1))]
    hi = draws[int(0.975 * (iterations - 1))]
    block_means = [statistics.fmean(blocks[k]) for k in keys]
    se = statistics.stdev(block_means) / math.sqrt(len(keys)) if len(keys) > 1 else None
    # Normal approximation is reported as sensitivity, not a universal sample-size rule.
    mde = (1.9599639845 + 0.8416212336) * se if se is not None else None
    return {"status": "computed", "months": len(keys), "ci95": [lo, hi],
            "minimum_detectable_effect_80pct_r": mde,
            "sufficiency_interpretation": "use CI width and MDE; no universal trade-count threshold"}


def paired_block_bootstrap(candidate: list[dict[str, Any]], baseline: list[dict[str, Any]],
                           rng: random.Random, iterations: int) -> dict[str, Any]:
    a = {r["setup_id"]: r for r in candidate if r.get("net_r") is not None}
    b = {r["setup_id"]: r for r in baseline if r.get("net_r") is not None}
    if a.keys() != b.keys():
        return {"status": "blocked_pairing_mismatch", "n_candidate": len(a),
                "n_baseline": len(b), "candidate_only": len(a.keys() - b.keys()),
                "baseline_only": len(b.keys() - a.keys()), "n_paired": 0,
                "months": 0, "ci95": None, "p_two_sided": None}
    ids = sorted(a)
    blocks: dict[str, list[float]] = defaultdict(list)
    for setup_id in ids:
        blocks[_month(int(a[setup_id]["activation_timestamp"]))].append(
            float(a[setup_id]["net_r"]) - float(b[setup_id]["net_r"]))
    keys = sorted(blocks)
    if len(keys) < 2:
        return {"status": "blocked_insufficient_temporal_blocks", "n_paired": len(ids),
                "months": len(keys), "ci95": None, "p_two_sided": None}
    draws = []
    for _ in range(iterations):
        vals = []
        for _ in keys:
            vals.extend(blocks[keys[rng.randrange(len(keys))]])
        draws.append(statistics.fmean(vals))
    draws.sort()
    observed = statistics.fmean([v for block in blocks.values() for v in block])
    p_lo = (sum(x <= 0 for x in draws) + 1) / (iterations + 1)
    p_hi = (sum(x >= 0 for x in draws) + 1) / (iterations + 1)
    return {"status": "computed", "n_paired": len(ids), "months": len(keys),
            "mean_difference_net_r": observed,
            "ci95": [draws[int(.025 * (iterations - 1))], draws[int(.975 * (iterations - 1))]],
            "p_two_sided": min(1.0, 2 * min(p_lo, p_hi)),
            "pairing_check": "exact setup_id intersection"}


def holm(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted((dict(x) for x in items if x.get("p") is not None), key=lambda x: x["p"])
    previous, count, result = 0.0, len(ordered), []
    for idx, item in enumerate(ordered):
        adjusted = min(1.0, max(previous, (count - idx) * item["p"]))
        previous = adjusted
        result.append({**item, "p_holm": adjusted, "significant_0_05": adjusted < 0.05})
    return result


EXPLICIT_BLOCKS = {
    "dsr": {"status": "blocked_not_implemented", "reason": "DSR is not simulated in v1."},
    "pbo": {"status": "blocked_not_implemented", "reason": "PBO is not simulated in v1."},
    "block_monte_carlo": {
        "status": "blocked_not_implemented",
        "reason": "Sequence risk (DD 10/20/30%, streaks, ruin) requires a validated regime-preserving block design; IID permutation is forbidden.",
    },
    "dependence_and_account_heat": {
        "status": "blocked_not_modeled",
        "reason": "Overlapping trades, cross-pair correlation and account heat are documented but not converted to portfolio claims in v1.",
    },
}
