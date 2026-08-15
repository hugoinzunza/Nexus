"""HYP-CANDLE-001: patron causal impulso-absorcion-reclaim tras tocar un POI.

Research only. Compara el resultado original con una entrada posterior a la
confirmacion, sin importar ni modificar ningun modulo de ejecucion.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.hypothesis_lab.metrics import basic_metrics, paired_block_bootstrap  # noqa: E402
from research.hypothesis_lab.simulator import simulate  # noqa: E402
REPORT_PATH = ROOT / "research/hypothesis_lab/reports/HYP-CANDLE-001-20260803.summary.json"
PAIRS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT")
TIMEFRAMES = ("1h", "4h")
TOTAL_COST_RATE = 0.0014
ATR_PERIOD = 14
IMPULSE_RANGE_ATR = 1.25
IMPULSE_BODY_FRACTION = 0.60
BASE_MAX_BODY_VS_IMPULSE = 0.50
BASE_EXTREME_FRACTION = 0.35
RECLAIM_BODY_ATR = 0.50
RECLAIM_FRACTION = 0.50
MAX_COMPLETION_BARS_AFTER_TOUCH = 3
BOOTSTRAP_ITERATIONS = 20_000
BOOTSTRAP_SEED = 20260803


def _canonical_sha(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _atr(candles: list[dict[str, Any]]) -> list[float | None]:
    ranges = []
    output: list[float | None] = []
    for index, candle in enumerate(candles):
        previous = candles[index - 1]["c"] if index else candle["c"]
        ranges.append(max(candle["h"] - candle["l"], abs(candle["h"] - previous),
                          abs(candle["l"] - previous)))
        output.append(statistics.fmean(ranges[-ATR_PERIOD:]) if len(ranges) >= ATR_PERIOD else None)
    return output


def _aligned_pattern(candles: list[dict[str, Any]], atr: list[float | None],
                     start: int, direction: str) -> bool:
    if start < 0 or start + 2 >= len(candles) or atr[start] is None or atr[start + 2] is None:
        return False
    impulse, base, reclaim = candles[start:start + 3]
    span = impulse["h"] - impulse["l"]
    body = abs(impulse["c"] - impulse["o"])
    if span <= 0 or span < IMPULSE_RANGE_ATR * atr[start]:
        return False
    if body / span < IMPULSE_BODY_FRACTION:
        return False
    if abs(base["c"] - base["o"]) > BASE_MAX_BODY_VS_IMPULSE * body:
        return False
    reclaim_body = abs(reclaim["c"] - reclaim["o"])
    if reclaim_body < RECLAIM_BODY_ATR * atr[start + 2]:
        return False
    if direction == "long":
        return (
            impulse["c"] < impulse["o"]
            and base["l"] <= impulse["l"] + BASE_EXTREME_FRACTION * span
            and reclaim["c"] > reclaim["o"]
            and reclaim["c"] >= impulse["c"] + RECLAIM_FRACTION * body
        )
    return (
        impulse["c"] > impulse["o"]
        and base["h"] >= impulse["h"] - BASE_EXTREME_FRACTION * span
        and reclaim["c"] < reclaim["o"]
        and reclaim["c"] <= impulse["c"] - RECLAIM_FRACTION * body
    )


def _still_open(setup: dict[str, Any], candles: list[dict[str, Any]], completion: int) -> bool:
    act = int(setup["activation_index"])
    long = setup["dir"] == "long"
    sl, tp = float(setup["sl"]), float(setup["original_tp"])
    for index in range(act, completion + 1):
        candle = candles[index]
        if (long and candle["l"] <= sl) or ((not long) and candle["h"] >= sl):
            return False
        if index > act and ((long and candle["h"] >= tp) or ((not long) and candle["l"] <= tp)):
            return False
    return True


def detect_after_touch(setup: dict[str, Any], candles: list[dict[str, Any]],
                       atr: list[float | None]) -> dict[str, Any] | None:
    act = setup.get("activation_index")
    if not isinstance(act, int):
        return None
    for start in range(max(0, act - 2), min(len(candles) - 2, act + 2)):
        completion = start + 2
        if completion < act or completion > act + MAX_COMPLETION_BARS_AFTER_TOUCH:
            continue
        if _aligned_pattern(candles, atr, start, setup["dir"]) and _still_open(setup, candles, completion):
            return {
                "start_index": start, "completion_index": completion,
                "start_timestamp": candles[start]["t"],
                "completion_timestamp": candles[completion]["t"],
                "bars_after_touch": completion - act,
            }
    return None


def simulate_confirmation_entry(setup: dict[str, Any], candles: list[dict[str, Any]],
                                completion: int) -> dict[str, Any]:
    entry_index = completion + 1
    out = {"setup_id": setup["setup_id"], "activation_timestamp": setup["activation_timestamp"]}
    if entry_index >= len(candles):
        return {**out, "net_r": None, "discarded_reason": "no_next_bar"}
    entry = float(candles[entry_index]["o"])
    sl, tp = float(setup["sl"]), float(setup["original_tp"])
    long = setup["dir"] == "long"
    risk = entry - sl if long else sl - entry
    reward = tp - entry if long else entry - tp
    if risk <= 0 or reward <= 0:
        return {**out, "net_r": None, "discarded_reason": "confirmation_crossed_plan_boundary"}
    cost_r = TOTAL_COST_RATE / (risk / entry)
    max_end = min(len(candles) - 1, int(setup["decision_index"]) + int(setup["max_forward_bars"]))
    first = candles[entry_index]
    if (long and first["l"] <= sl) or ((not long) and first["h"] >= sl):
        gross, status, end = -1.0, "sl", entry_index
    else:
        gross, status, end = None, "timeout_closed", max(entry_index, max_end)
        for index in range(entry_index + 1, max_end + 1):
            candle = candles[index]
            if (long and candle["l"] <= sl) or ((not long) and candle["h"] >= sl):
                gross, status, end = -1.0, "sl", index
                break
            if (long and candle["h"] >= tp) or ((not long) and candle["l"] <= tp):
                gross, status, end = reward / risk, "tp", index
                break
        if gross is None:
            close = candles[end]["c"]
            gross = (close - entry) / risk if long else (entry - close) / risk
    return {
        **out, "entry_timestamp": candles[entry_index]["t"], "entry_price": entry,
        "status": status, "gross_r": gross, "cost_r": cost_r, "net_r": gross - cost_r,
        "discarded_reason": None, "resolution_timestamp": candles[end]["t"],
    }


def _load(root: Path) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    setups = json.loads((root / "data/setup_backtest_trades.json").read_text(encoding="utf-8"))
    candles = {}
    for pair in PAIRS:
        for timeframe in TIMEFRAMES:
            path = root / f"data/klines_{pair}_{timeframe}.json"
            candles[(pair, timeframe)] = json.loads(path.read_text(encoding="utf-8"))
    return setups, candles


def _month(timestamp: int) -> str:
    return dt.datetime.fromtimestamp(timestamp / 1000, tz=dt.timezone.utc).strftime("%Y-%m")


def _stratum(setup: dict[str, Any]) -> tuple[str, str, str, str]:
    return setup["pair"], setup["sel_tf"], setup["dir"], _month(setup["activation_timestamp"])


def _block_bootstrap(values: list[tuple[str, float]]) -> list[float] | None:
    blocks: dict[str, list[float]] = defaultdict(list)
    for month, value in values:
        blocks[month].append(value)
    keys = sorted(blocks)
    if len(keys) < 2:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    draws = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        sample = [value for _ in keys for value in blocks[rng.choice(keys)]]
        draws.append(statistics.fmean(sample))
    draws.sort()
    return [draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws)) - 1]]


def analyze(root: Path = ROOT) -> dict[str, Any]:
    setups, candle_map = _load(root)
    atr_map = {key: _atr(rows) for key, rows in candle_map.items()}
    eligible = [row for row in setups if row.get("activation_index") is not None
                and (row.get("pair"), row.get("sel_tf")) in candle_map]
    baseline, pattern_baseline, confirmation = [], [], []
    pattern_records = []
    no_pattern_by_stratum: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    pattern_rows = []
    for setup in eligible:
        key = (setup["pair"], setup["sel_tf"])
        candles = candle_map[key]
        original = simulate(setup, candles, {"id": "original", "rr": None}, TOTAL_COST_RATE)
        if original.get("net_r") is None:
            continue
        baseline.append(original)
        pattern = detect_after_touch(setup, candles, atr_map[key])
        if pattern is None:
            no_pattern_by_stratum[_stratum(setup)].append(float(original["net_r"]))
            continue
        pattern_baseline.append(original)
        delayed = simulate_confirmation_entry(setup, candles, pattern["completion_index"])
        if delayed.get("net_r") is not None:
            confirmation.append(delayed)
        pattern_rows.append((setup, original, pattern))
        pattern_records.append({
            "setup_id": setup["setup_id"], "pair": setup["pair"], "timeframe": setup["sel_tf"],
            "direction": setup["dir"], **pattern,
            "original_net_r": original["net_r"], "confirmation_net_r": delayed.get("net_r"),
            "confirmation_discarded_reason": delayed.get("discarded_reason"),
        })

    matched_excess = []
    unmatched = 0
    for setup, original, _pattern in pattern_rows:
        controls = no_pattern_by_stratum.get(_stratum(setup), [])
        if not controls:
            unmatched += 1
            continue
        excess = float(original["net_r"]) - statistics.fmean(controls)
        matched_excess.append((_month(setup["activation_timestamp"]), excess))

    # Pair only rows where the delayed branch is valid.
    valid_ids = {row["setup_id"] for row in confirmation}
    paired_baseline = [row for row in pattern_baseline if row["setup_id"] in valid_ids]
    paired = paired_block_bootstrap(confirmation, paired_baseline, random.Random(BOOTSTRAP_SEED), 2000)
    pattern_metrics = basic_metrics(pattern_baseline)
    no_pattern_baseline = [row for row in baseline if row["setup_id"] not in {x["setup_id"] for x in pattern_baseline}]
    setup_by_id = {row["setup_id"]: row for row in eligible}
    rr5_ids = {row["setup_id"] for row in eligible if float(row.get("rr") or 0) >= 5}
    rr5_pattern = [row for row in pattern_baseline if row["setup_id"] in rr5_ids]
    rr5_confirmation = [row for row in confirmation if row["setup_id"] in rr5_ids]
    rr5_valid_ids = {row["setup_id"] for row in rr5_confirmation}
    rr5_paired_base = [row for row in rr5_pattern if row["setup_id"] in rr5_valid_ids]
    subgroups = {}
    for timeframe in TIMEFRAMES:
        for direction in ("long", "short"):
            ids = {row["setup_id"] for row in eligible
                   if row["sel_tf"] == timeframe and row["dir"] == direction}
            subgroups[f"{timeframe}:{direction}"] = basic_metrics(
                [row for row in pattern_baseline if row["setup_id"] in ids]
            )

    return {
        "hypothesis_id": "HYP-CANDLE-001", "schema_version": 1,
        "research_only": True, "promotion_available": False, "execution_enabled": False,
        "status": "exploratory_post_hoc", "notice": "Research only - No signal - No bot",
        "question": "Does impulse-absorption-reclaim after a POI touch add information or improve entry timing?",
        "parameters": {
            "pattern": "impulse_absorption_reclaim", "atr_period": ATR_PERIOD,
            "impulse_range_atr": IMPULSE_RANGE_ATR,
            "impulse_body_fraction": IMPULSE_BODY_FRACTION,
            "base_max_body_vs_impulse": BASE_MAX_BODY_VS_IMPULSE,
            "base_extreme_fraction": BASE_EXTREME_FRACTION,
            "reclaim_body_atr": RECLAIM_BODY_ATR, "reclaim_fraction": RECLAIM_FRACTION,
            "max_completion_bars_after_touch": MAX_COMPLETION_BARS_AFTER_TOUCH,
            "confirmation_entry": "next_bar_open", "total_cost_rate": TOTAL_COST_RATE,
        },
        "coverage": {
            "eligible_activated_setups": len(eligible), "resolved_baseline": len(baseline),
            "patterns": len(pattern_baseline), "pattern_rate": len(pattern_baseline) / len(baseline) if baseline else None,
            "valid_confirmation_entries": len(confirmation), "matched_information_rows": len(matched_excess),
            "unmatched_information_rows": unmatched,
        },
        "information_value": {
            "pattern_original_entry": pattern_metrics,
            "no_pattern_original_entry": basic_metrics(no_pattern_baseline),
            "matched_strata": "pair + timeframe + direction + calendar month",
            "mean_excess_net_r": statistics.fmean(value for _, value in matched_excess) if matched_excess else None,
            "month_block_bootstrap_ci95": _block_bootstrap(matched_excess),
        },
        "timing_value": {
            "original_entry_on_pattern_setups": basic_metrics(paired_baseline),
            "confirmation_next_open": basic_metrics(confirmation),
            "paired_difference_confirmation_minus_original": paired,
        },
        "posthoc_robustness": {
            "warning": "Sensitivity checks were inspected after the primary result and are not confirmatory.",
            "input_characteristics": {
                "pattern_avg_planned_rr": statistics.fmean(float(setup_by_id[row["setup_id"]]["rr"])
                                                            for row in pattern_baseline),
                "no_pattern_avg_planned_rr": statistics.fmean(float(setup_by_id[row["setup_id"]]["rr"])
                                                               for row in no_pattern_baseline),
                "pattern_avg_sl_fraction": statistics.fmean(float(setup_by_id[row["setup_id"]]["sl_pct"])
                                                             for row in pattern_baseline),
                "no_pattern_avg_sl_fraction": statistics.fmean(float(setup_by_id[row["setup_id"]]["sl_pct"])
                                                                for row in no_pattern_baseline),
            },
            "by_timeframe_direction_original_entry": subgroups,
            "rr_at_least_5": {
                "pattern_original_entry": basic_metrics(rr5_pattern),
                "confirmation_next_open": basic_metrics(rr5_confirmation),
                "paired_difference_confirmation_minus_original": paired_block_bootstrap(
                    rr5_confirmation, rr5_paired_base, random.Random(BOOTSTRAP_SEED), 2000
                ),
            },
        },
        "pattern_records": pattern_records,
        "visual_examples": {
            "count": 2, "effective_events": 1, "role": "vocabulary_only",
            "warning": "Both screenshots appear to show the same selected event and are excluded from inference.",
        },
        "verdict": {
            "classification": "information_candidate_do_not_chase",
            "summary": "El patrón identifica mejores planes originales, pero esperar su cierre destruye la expectativa; candidato solo para observación de mantener/abortar.",
            "production_change": False,
            "next_step": "Registrar el patrón en shadow sobre nuevos setups sin cambiar entrada, stop, target ni gestión.",
        },
        "limitations": [
            "The pattern was defined after reviewing selected screenshots.",
            "The historical setup export is recycled research data, not a fresh confirmation cohort.",
            "OHLC cannot prove intrabar sequence; stop-first rules and next-open confirmation are conservative.",
            "Matched strata reduce but do not eliminate selection and overlapping-trade dependence.",
            "This study does not authorize a candle gate, entry delay, early exit or bot change.",
        ],
        "dataset": {
            "setup_export": "data/setup_backtest_trades.json", "setups_sha256": _canonical_sha(setups),
            "pairs": list(PAIRS), "timeframes": list(TIMEFRAMES),
        },
        "generated_at_ms": int(time.time() * 1000),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = analyze(args.root)
    _atomic_json(args.report, report)
    print(json.dumps({
        "hypothesis_id": report["hypothesis_id"], "patterns": report["coverage"]["patterns"],
        "promotion_available": report["promotion_available"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
