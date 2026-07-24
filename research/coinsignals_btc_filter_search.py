#!/usr/bin/env python3
"""Causal signal/regime filter research for reconstructed BTC CoinSignals trades."""

from __future__ import annotations

import bisect
import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.coinsignals_backtest import KlineCache, parse_history  # noqa: E402
from research.coinsignals_btc_exit_search import metrics  # noqa: E402
from research.coinsignals_btc_swing import (  # noqa: E402
    END_DATE,
    START_DATE,
    equal_notional_average,
    has_hold_annotation,
    management_by_signal,
    replay_swing,
    timestamp_ms,
)

HISTORY = ROOT / "data/telegram/coinsignals_history.json"
RESULTS = ROOT / "data/telegram/coinsignals_btc_filter_search.json"
TRAIN_END = "2026-01-01"
ARCHIVE_END = "2024-07-22"
WEIGHTS = (0.25, 0.25, 0.25, 0.25)

PERIODS = (
    ("2024_H2", "2024-07-22", "2025-01-01"),
    ("2025_H1", "2025-01-01", "2025-07-01"),
    ("2025_H2", "2025-07-01", "2026-01-01"),
    ("2026_Q1", "2026-01-01", "2026-04-01"),
    ("2026_Q2", "2026-04-01", "2026-07-01"),
    ("2026_Q3_partial", "2026-07-01", "2026-07-23"),
)


def market_features(
    candles: list[dict[str, Any]], times: list[int], as_of_ms: int
) -> dict[str, float | bool | None]:
    """Features use only candles closed before the entry-confirmation bar."""
    end = bisect.bisect_left(times, as_of_ms)
    if end < 30 * 96 + 1:
        return {}
    closes = [float(candle["c"]) for candle in candles]
    current = closes[end - 1]

    def trailing_return(days: int) -> float:
        return current / closes[end - 1 - days * 96] - 1

    returns_7d = [
        math.log(closes[index] / closes[index - 1])
        for index in range(end - 7 * 96, end)
    ]
    returns_30d = [
        math.log(closes[index] / closes[index - 1])
        for index in range(end - 30 * 96, end)
    ]
    vol_7d = statistics.pstdev(returns_7d)
    vol_30d = statistics.pstdev(returns_30d)
    return {
        "return_1d": trailing_return(1),
        "return_3d": trailing_return(3),
        "return_7d": trailing_return(7),
        "return_14d": trailing_return(14),
        "return_30d": trailing_return(30),
        "vol_7d": vol_7d,
        "vol_30d": vol_30d,
        "vol_expanding": vol_7d > vol_30d,
    }


def add_shadow_features(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach provider-health metrics from trades resolved before each new fill."""
    output = []
    for row in rows:
        prior = sorted(
            (
                candidate
                for candidate in rows
                if candidate["resolution_time"] < row["fill_time"]
            ),
            key=lambda candidate: candidate["resolution_time"],
        )
        enriched = dict(row)
        enriched["shadow_resolved_n"] = len(prior)
        for window in (5, 10, 20):
            sample = prior[-window:]
            enriched[f"shadow_avg_{window}"] = (
                sum(item["pnl_r_be_tp1"] for item in sample) / window
                if len(sample) == window
                else None
            )
        output.append(enriched)
    return output


def build_candidates() -> list[tuple[str, Callable[[dict[str, Any]], bool]]]:
    candidates: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        ("all", lambda row: True),
        ("long", lambda row: row["direction"] == "long"),
        ("short", lambda row: row["direction"] == "short"),
        ("vol_expanding", lambda row: row["vol_expanding"]),
        ("vol_contracting", lambda row: not row["vol_expanding"]),
        ("leverage_lte_10", lambda row: row["leverage"] <= 10),
        ("leverage_gt_10", lambda row: row["leverage"] > 10),
    ]
    for window in (5, 10, 20):
        candidates.append(
            (
                f"shadow_avg_{window}_positive",
                lambda row, size=window: row[f"shadow_avg_{size}"] is not None
                and row[f"shadow_avg_{size}"] > 0,
            )
        )
    for threshold in (1.0, 1.2, 1.3, 1.4):
        candidates.append(
            (f"tp1_r_gte_{threshold}", lambda row, value=threshold: row["tp1_r"] >= value)
        )
    for threshold in (3.0, 3.5, 3.75, 4.0, 4.25, 4.5):
        candidates.append(
            (f"tp4_r_gte_{threshold}", lambda row, value=threshold: row["tp4_r"] >= value)
        )
    for threshold in (0.015, 0.02, 0.03):
        candidates.extend(
            [
                (
                    f"risk_pct_lte_{threshold}",
                    lambda row, value=threshold: row["risk_pct"] <= value,
                ),
                (
                    f"risk_pct_gte_{threshold}",
                    lambda row, value=threshold: row["risk_pct"] >= value,
                ),
            ]
        )
    for days in (1, 3, 7, 14, 30):
        key = f"return_{days}d"
        candidates.extend(
            [
                (
                    f"trend_{days}d_aligned",
                    lambda row, feature=key: (row[feature] >= 0)
                    == (row["direction"] == "long"),
                ),
                (
                    f"trend_{days}d_counter",
                    lambda row, feature=key: (row[feature] >= 0)
                    != (row["direction"] == "long"),
                ),
            ]
        )
    candidates.extend(
        [
            (
                "long_and_tp1_r_gte_1.3",
                lambda row: row["direction"] == "long" and row["tp1_r"] >= 1.3,
            ),
            (
                "long_and_trend_7d_aligned",
                lambda row: row["direction"] == "long" and row["return_7d"] >= 0,
            ),
            (
                "tp1_r_gte_1.3_and_trend_7d_aligned",
                lambda row: row["tp1_r"] >= 1.3
                and (row["return_7d"] >= 0) == (row["direction"] == "long"),
            ),
            (
                "tp1_r_gte_1.4_and_trend_7d_aligned",
                lambda row: row["tp1_r"] >= 1.4
                and (row["return_7d"] >= 0) == (row["direction"] == "long"),
            ),
        ]
    )
    return candidates


def candidate_summary(
    identifier: str,
    predicate: Callable[[dict[str, Any]], bool],
    rows: list[dict[str, Any]],
    outcome: str = "pnl_r_be_tp1",
) -> dict[str, Any]:
    selected = [
        {**row, "status": "resolved", "pnl_r_net": row[outcome]}
        for row in rows
        if predicate(row)
    ]
    train = [row for row in selected if row["date"] < TRAIN_END]
    oos = [row for row in selected if row["date"] >= TRAIN_END]
    periods = {
        label: metrics([row for row in selected if start <= row["date"] < end])
        for label, start, end in PERIODS
    }
    positive_train_periods = sum(
        periods[label]["avg_r"] is not None and periods[label]["avg_r"] > 0
        for label, _, _ in PERIODS[:3]
    )
    return {
        "id": identifier,
        "train": metrics(train),
        "oos": metrics(oos),
        "all": metrics(selected),
        "periods": periods,
        "positive_train_periods": positive_train_periods,
    }


def select_on_train(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Selection cannot see OOS fields and requires temporal breadth."""
    eligible = [
        item
        for item in summaries
        if item["train"]["n"] >= 20
        and item["positive_train_periods"] >= 2
        and all(item["periods"][label]["n"] >= 5 for label, _, _ in PERIODS[:3])
    ]
    return max(
        eligible,
        key=lambda item: (
            item["positive_train_periods"],
            item["train"]["avg_r"],
            item["train"]["profit_factor"] or 0,
        ),
    )


def walk_forward(
    rows: list[dict[str, Any]], candidates: list[tuple[str, Callable[[dict[str, Any]], bool]]]
) -> list[dict[str, Any]]:
    folds = PERIODS[2:]
    output = []
    for label, start, end in folds:
        prior = [row for row in rows if row["date"] < start]
        candidates_train = []
        for identifier, predicate in candidates:
            picked = [
                {**row, "status": "resolved", "pnl_r_net": row["pnl_r_be_tp1"]}
                for row in prior
                if predicate(row)
            ]
            if len(picked) >= 15 and len(picked) / len(prior) >= 0.25:
                candidates_train.append((identifier, predicate, metrics(picked)))
        winner_id, winner_predicate, train_metrics = max(
            candidates_train,
            key=lambda item: (item[2]["avg_r"], item[2]["profit_factor"] or 0),
        )
        test = [
            {**row, "status": "resolved", "pnl_r_net": row["pnl_r_be_tp1"]}
            for row in rows
            if start <= row["date"] < end and winner_predicate(row)
        ]
        output.append(
            {
                "fold": label,
                "selected_filter": winner_id,
                "train": train_metrics,
                "test": metrics(test),
            }
        )
    return output


def build_rows() -> list[dict[str, Any]]:
    history = json.loads(HISTORY.read_text())
    messages = {message["id"]: message for message in history["messages"]}
    signals, _ = parse_history(history)
    signals = [
        signal
        for signal in signals
        if signal.symbol == "BTCUSDT"
        and signal.date_ms <= timestamp_ms(END_DATE)
        and len(signal.targets) == 4
        and (
            not signal.edit_date
            or has_hold_annotation(messages[signal.message_id].get("text") or "")
        )
    ]
    events = management_by_signal(history, signals)
    candles = KlineCache().load("BTCUSDT")
    times = [int(candle["t"]) for candle in candles]
    rows = []
    for signal in signals:
        outcomes = {}
        replay_metadata = None
        for policy in ("original", "be_tp1"):
            replay = replay_swing(
                signal,
                candles,
                events.get(signal.message_id, ()),
                entry_mode="channel",
                managed=True,
                stop_policy=policy,
                target_weights_override=WEIGHTS,
                times=times,
            )
            if replay.get("status") != "resolved":
                break
            outcomes[policy] = replay["pnl_r_net"]
            replay_metadata = replay
        if len(outcomes) != 2 or replay_metadata is None:
            continue
        context = market_features(candles, times, timestamp_ms(replay_metadata["fill_time"]))
        if not context:
            continue
        planned_entry = equal_notional_average(
            price
            for price in (signal.entry_first, signal.entry_second)
            if price is not None
        )
        risk = abs(planned_entry - signal.stop)
        rows.append(
            {
                "message_id": signal.message_id,
                "date": signal.date,
                "fill_time": replay_metadata["fill_time"],
                "resolution_time": replay_metadata["resolution_time"],
                "direction": signal.direction,
                "leverage": signal.leverage or 0,
                "risk_pct": risk / planned_entry,
                "entry_width_r": (signal.entry_high - signal.entry_low) / risk,
                "tp1_r": abs(signal.targets[0] - planned_entry) / risk,
                "tp4_r": abs(signal.targets[-1] - planned_entry) / risk,
                "pnl_r_original": outcomes["original"],
                "pnl_r_be_tp1": outcomes["be_tp1"],
                **context,
            }
        )
    return add_shadow_features(rows)


def run() -> dict[str, Any]:
    all_rows = build_rows()
    rows = [row for row in all_rows if row["date"] >= ARCHIVE_END]
    archive_rows = [row for row in all_rows if row["date"] < ARCHIVE_END]
    candidates = build_candidates()
    summaries = [candidate_summary(identifier, predicate, rows) for identifier, predicate in candidates]
    selected = select_on_train(summaries)
    by_id = {item["id"]: item for item in summaries}
    selected_original = candidate_summary(
        selected["id"],
        dict(candidates)[selected["id"]],
        rows,
        outcome="pnl_r_original",
    )
    archive_validation = {}
    for identifier in (selected["id"], "all", "long", "tp1_r_gte_1.3", "tp1_r_gte_1.4"):
        predicate = dict(candidates)[identifier]
        picked = [
            {**row, "status": "resolved", "pnl_r_net": row["pnl_r_be_tp1"]}
            for row in archive_rows
            if predicate(row)
        ]
        archive_validation[identifier] = {
            "all": metrics(picked),
            "by_year": {
                year: metrics([row for row in picked if row["date"].startswith(year)])
                for year in ("2021", "2022", "2023", "2024")
            },
        }
    archive_candidates = []
    for identifier, predicate in candidates:
        picked = [
            {**row, "status": "resolved", "pnl_r_net": row["pnl_r_be_tp1"]}
            for row in archive_rows
            if predicate(row)
        ]
        archive_candidates.append({"id": identifier, "archive": metrics(picked)})
    archive_by_id = {item["id"]: item["archive"] for item in archive_candidates}
    robust_candidates = [
        {
            "id": item["id"],
            "archive": archive_by_id[item["id"]],
            "train": item["train"],
            "oos": item["oos"],
        }
        for item in summaries
        if archive_by_id[item["id"]]["n"] >= 15
        and item["train"]["n"] >= 20
        and item["oos"]["n"] >= 10
        and archive_by_id[item["id"]]["avg_r"] > 0
        and item["train"]["avg_r"] > 0
        and item["oos"]["avg_r"] > 0
    ]
    output = {
        "research_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "dataset_rows": len(rows),
            "archive_rows": len(archive_rows),
            "train": f"{START_DATE} to {TRAIN_END}",
            "oos": f"{TRAIN_END} to {END_DATE}",
            "candidate_count": len(candidates),
            "selection": "train only; n>=20; >=5 in each train period; positive in >=2/3",
            "execution": "channel-confirmed entries; 25% each TP; BE after TP1",
            "market_features": "only candles closed before entry confirmation",
        },
        "selected_on_train": selected,
        "selected_with_original_stop": selected_original,
        "baseline": by_id["all"],
        "long": by_id["long"],
        "tp1_r_gte_1.3": by_id["tp1_r_gte_1.3"],
        "tp1_r_gte_1.4": by_id["tp1_r_gte_1.4"],
        "top_train": sorted(
            summaries,
            key=lambda item: item["train"]["avg_r"] or -math.inf,
            reverse=True,
        )[:10],
        "walk_forward": walk_forward(rows, candidates),
        "archive_validation_2021_to_2024": archive_validation,
        "archive_all_candidates": archive_candidates,
        "positive_archive_train_oos_candidates": robust_candidates,
        "all_candidates": summaries,
        "rows": rows,
    }
    RESULTS.write_text(json.dumps(output, indent=2), encoding="utf-8")
    os.chmod(RESULTS, 0o600)
    return output


if __name__ == "__main__":
    result = run()
    print(
        json.dumps(
            {
                "method": result["method"],
                "selected_on_train": result["selected_on_train"],
                "selected_with_original_stop": result["selected_with_original_stop"],
                "baseline": result["baseline"],
                "long": result["long"],
                "tp1_r_gte_1.3": result["tp1_r_gte_1.3"],
                "tp1_r_gte_1.4": result["tp1_r_gte_1.4"],
                "walk_forward": result["walk_forward"],
            },
            indent=2,
        )
    )
