#!/usr/bin/env python3
"""Temporal search for BTC target allocation and protective-stop policies."""

from __future__ import annotations

import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.coinsignals_backtest import KlineCache, parse_history  # noqa: E402
from research.coinsignals_btc_swing import (  # noqa: E402
    END_DATE,
    START_DATE,
    has_hold_annotation,
    management_by_signal,
    replay_swing,
    timestamp_ms,
)


HISTORY = ROOT / "data/telegram/coinsignals_history.json"
RESULTS = ROOT / "data/telegram/coinsignals_btc_exit_search.json"
TRAIN_END = "2026-01-01T00:00:00+00:00"
STOP_POLICIES = ("original", "be_tp1", "be_tp2", "step", "lock_tp1_after_tp2")


def allocation_grid() -> list[tuple[float, float, float, float]]:
    allocations = set()
    for first in (0.1, 0.2, 0.25, 0.3, 0.4, 0.5):
        remaining = 1 - first
        allocations.add((first, remaining / 3, remaining / 3, remaining / 3))
        allocations.add((first, remaining * 0.5, remaining * 0.3, remaining * 0.2))
        allocations.add((first, remaining * 0.2, remaining * 0.3, remaining * 0.5))
    allocations.update(
        {
            (1.0, 0.0, 0.0, 0.0),
            (0.5, 0.5, 0.0, 0.0),
            (0.0, 1 / 3, 1 / 3, 1 / 3),
        }
    )
    return sorted(tuple(round(value, 6) for value in row) for row in allocations)


def config_id(weights: tuple[float, ...], stop_policy: str) -> str:
    weight_label = "-".join(str(round(weight * 100, 1)).rstrip("0").rstrip(".") for weight in weights)
    return f"w_{weight_label}__{stop_policy}"


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [row for row in rows if row["status"] == "resolved"]
    values = [row["pnl_r_net"] for row in resolved]
    positives = [value for value in values if value > 0]
    negatives = [value for value in values if value < 0]
    equity = peak = max_drawdown = 0.0
    for row in sorted(resolved, key=lambda item: item["date"]):
        equity += row["pnl_r_net"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "n": len(values),
        "avg_r": round(sum(values) / len(values), 6) if values else None,
        "total_r": round(sum(values), 4),
        "profit_factor": (
            round(sum(positives) / -sum(negatives), 6) if negatives else None
        ),
        "win_rate_pct": round(100 * len(positives) / len(values), 3) if values else None,
        "max_drawdown_r": round(max_drawdown, 4),
    }


def rank_configs(results: list[dict[str, Any]], metric_key: str = "avg_r") -> list[dict[str, Any]]:
    return sorted(
        results,
        key=lambda item: (
            item["train"][metric_key] if item["train"][metric_key] is not None else -math.inf,
            item["train"]["profit_factor"] or -math.inf,
        ),
        reverse=True,
    )


def rank_correlation(results: list[dict[str, Any]]) -> float:
    ordered_train = sorted(results, key=lambda item: item["train"]["avg_r"])
    ordered_oos = sorted(results, key=lambda item: item["oos"]["avg_r"])
    train_rank = {item["id"]: rank for rank, item in enumerate(ordered_train)}
    oos_rank = {item["id"]: rank for rank, item in enumerate(ordered_oos)}
    n = len(results)
    distance = sum((train_rank[item["id"]] - oos_rank[item["id"]]) ** 2 for item in results)
    return round(1 - 6 * distance / (n * (n * n - 1)), 4)


def evaluate_walk_forward(
    results: list[dict[str, Any]], rows_by_config: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    folds = (
        ("2026-Q1", "2026-01-01", "2026-04-01"),
        ("2026-Q2", "2026-04-01", "2026-07-01"),
        ("2026-Q3-partial", "2026-07-01", "2026-07-23"),
    )
    output = []
    for label, start, end in folds:
        candidates = []
        for result in results:
            train_rows = [row for row in rows_by_config[result["id"]] if row["date"] < start]
            candidates.append({"id": result["id"], "train": metrics(train_rows)})
        winner = rank_configs(candidates)[0]
        test_rows = [
            row for row in rows_by_config[winner["id"]] if start <= row["date"] < end
        ]
        output.append(
            {
                "fold": label,
                "selected_config": winner["id"],
                "train": winner["train"],
                "test": metrics(test_rows),
            }
        )
    return output


def run() -> dict[str, Any]:
    history = json.loads(HISTORY.read_text())
    messages_by_id = {message["id"]: message for message in history["messages"]}
    signals, _ = parse_history(history)
    start_ms = timestamp_ms(START_DATE)
    end_ms = timestamp_ms(END_DATE)
    btc = [
        signal
        for signal in signals
        if signal.symbol == "BTCUSDT" and start_ms <= signal.date_ms <= end_ms
    ]
    events = management_by_signal(history, btc)
    candles = KlineCache().load("BTCUSDT")
    times = [int(candle["t"]) for candle in candles]
    rows_by_config: dict[str, list[dict[str, Any]]] = {}
    summaries = []

    for weights in allocation_grid():
        for stop_policy in STOP_POLICIES:
            identifier = config_id(weights, stop_policy)
            rows = []
            for signal in btc:
                hold_edit = bool(signal.edit_date) and has_hold_annotation(
                    messages_by_id[signal.message_id].get("text") or ""
                )
                if signal.edit_date and not hold_edit:
                    continue
                replay = replay_swing(
                    signal,
                    candles,
                    events.get(signal.message_id, ()),
                    entry_mode="channel",
                    managed=True,
                    stop_policy=stop_policy,
                    target_weights_override=weights,
                    times=times,
                )
                rows.append(
                    {
                        "message_id": signal.message_id,
                        "date": signal.date,
                        "direction": signal.direction,
                        **replay,
                    }
                )
            rows_by_config[identifier] = rows
            train_rows = [row for row in rows if row["date"] < TRAIN_END]
            oos_rows = [row for row in rows if row["date"] >= TRAIN_END]
            summaries.append(
                {
                    "id": identifier,
                    "weights": weights,
                    "stop_policy": stop_policy,
                    "train": metrics(train_rows),
                    "oos": metrics(oos_rows),
                    "all": metrics(rows),
                    "periods": {
                        "2024_H2": metrics(
                            [row for row in rows if "2024-07-22" <= row["date"] < "2025-01-01"]
                        ),
                        "2025_H1": metrics(
                            [row for row in rows if "2025-01-01" <= row["date"] < "2025-07-01"]
                        ),
                        "2025_H2": metrics(
                            [row for row in rows if "2025-07-01" <= row["date"] < "2026-01-01"]
                        ),
                        "2026_Q1": metrics(
                            [row for row in rows if "2026-01-01" <= row["date"] < "2026-04-01"]
                        ),
                        "2026_Q2": metrics(
                            [row for row in rows if "2026-04-01" <= row["date"] < "2026-07-01"]
                        ),
                        "2026_Q3_partial": metrics(
                            [row for row in rows if "2026-07-01" <= row["date"] < "2026-07-23"]
                        ),
                    },
                }
            )

    ranked = rank_configs(summaries)
    baseline_id = config_id((0.25, 0.25, 0.25, 0.25), "original")
    current_id = config_id((0.25, 0.25, 0.25, 0.25), "be_tp1")
    by_id = {summary["id"]: summary for summary in summaries}
    policy_oos = {}
    for policy in STOP_POLICIES:
        group = [item["oos"]["avg_r"] for item in summaries if item["stop_policy"] == policy]
        policy_oos[policy] = {
            "mean_avg_r": round(sum(group) / len(group), 6),
            "positive_configs": sum(value > 0 for value in group),
            "configs": len(group),
        }

    output = {
        "research_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "search": {
            "config_count": len(summaries),
            "train": f"{START_DATE} to {TRAIN_END}",
            "oos": f"{TRAIN_END} to {END_DATE}",
            "selection_metric": "highest train avg_r; PF tie-break",
            "target_allocations": len(allocation_grid()),
            "stop_policies": STOP_POLICIES,
        },
        "selected_on_train": ranked[0],
        "top_10_train": ranked[:10],
        "best_oos_oracle_not_selectable": max(summaries, key=lambda item: item["oos"]["avg_r"]),
        "baseline": by_id[baseline_id],
        "tp1_25_be": by_id[current_id],
        "rank_correlation_train_oos": rank_correlation(summaries),
        "oos_positive_configs": sum(item["oos"]["avg_r"] > 0 for item in summaries),
        "policy_oos": policy_oos,
        "walk_forward": evaluate_walk_forward(summaries, rows_by_config),
        "all_configs": summaries,
    }
    RESULTS.write_text(json.dumps(output, indent=2), encoding="utf-8")
    os.chmod(RESULTS, 0o600)
    return output


if __name__ == "__main__":
    result = run()
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "selected_on_train",
                    "baseline",
                    "tp1_25_be",
                    "rank_correlation_train_oos",
                    "oos_positive_configs",
                    "policy_oos",
                    "walk_forward",
                )
            },
            indent=2,
        )
    )
