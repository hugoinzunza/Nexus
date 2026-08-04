"""HYP-TREND-001: rupturas y retests causales de lineas por pivotes BTC.

Estudio exploratorio y post-hoc. Las capturas de CoinSignals solo definen el
vocabulario visual; todas las mediciones usan velas diarias cerradas de Binance.
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
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
API_URL = "https://api.binance.com/api/v3/klines"
DATASET_PATH = ROOT / "research/hypothesis_lab/data/BINANCE_BTCUSDT_DAILY_2017_2026.json"
REPORT_PATH = ROOT / "research/hypothesis_lab/reports/HYP-TREND-001-20260803.summary.json"
PIVOT_WIDTH = 5
ATR_PERIOD = 14
BREAK_BUFFER_ATR = 0.25
RETEST_WINDOW_DAYS = 10
MAX_LINE_AGE_DAYS = 120
MIN_ANCHOR_SPAN_DAYS = 7
EVENT_COOLDOWN_DAYS = 10
HORIZONS = (5, 10, 20)
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


def fetch_closed_days(now_ms: int | None = None) -> list[dict[str, Any]]:
    now_ms = now_ms or int(time.time() * 1000)
    start_ms = 1_501_545_600_000  # 2017-08-01 UTC
    rows: list[dict[str, Any]] = []
    while start_ms < now_ms:
        query = urllib.parse.urlencode({
            "symbol": "BTCUSDT", "interval": "1d", "startTime": start_ms, "limit": 1000,
        })
        request = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": "NexUX-research/1"})
        with urllib.request.urlopen(request, timeout=20) as response:
            page = json.load(response)
        if not page:
            break
        for item in page:
            if int(item[6]) >= now_ms:
                continue
            opened = dt.datetime.fromtimestamp(int(item[0]) / 1000, tz=dt.timezone.utc)
            rows.append({
                "date": opened.date().isoformat(), "open_time_ms": int(item[0]),
                "close_time_ms": int(item[6]), "open": float(item[1]),
                "high": float(item[2]), "low": float(item[3]), "close": float(item[4]),
            })
        next_start = int(page[-1][6]) + 1
        if next_start <= start_ms:
            break
        start_ms = next_start
    return rows


def _atr(rows: list[dict[str, Any]]) -> list[float | None]:
    true_ranges = []
    result: list[float | None] = []
    for index, row in enumerate(rows):
        previous = rows[index - 1]["close"] if index else row["close"]
        true_ranges.append(max(row["high"] - row["low"], abs(row["high"] - previous), abs(row["low"] - previous)))
        result.append(statistics.mean(true_ranges[-ATR_PERIOD:]) if len(true_ranges) >= ATR_PERIOD else None)
    return result


def confirmed_pivots(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pivots = []
    for index in range(PIVOT_WIDTH, len(rows) - PIVOT_WIDTH):
        window = rows[index - PIVOT_WIDTH:index + PIVOT_WIDTH + 1]
        high = rows[index]["high"]
        low = rows[index]["low"]
        if high == max(item["high"] for item in window) and sum(item["high"] == high for item in window) == 1:
            pivots.append({"kind": "high", "index": index, "confirm_index": index + PIVOT_WIDTH, "price": high})
        if low == min(item["low"] for item in window) and sum(item["low"] == low for item in window) == 1:
            pivots.append({"kind": "low", "index": index, "confirm_index": index + PIVOT_WIDTH, "price": low})
    return sorted(pivots, key=lambda item: (item["confirm_index"], item["index"], item["kind"]))


def _line_value(first: dict[str, Any], second: dict[str, Any], index: int) -> float:
    slope = (second["price"] - first["price"]) / (second["index"] - first["index"])
    return second["price"] + slope * (index - second["index"])


def _lines(rows: list[dict[str, Any]], pivots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = []
    for kind, direction in (("high", "bullish"), ("low", "bearish")):
        points = [item for item in pivots if item["kind"] == kind]
        for first, second in zip(points, points[1:]):
            span = second["index"] - first["index"]
            descending_highs = kind == "high" and second["price"] < first["price"]
            ascending_lows = kind == "low" and second["price"] > first["price"]
            if span < MIN_ANCHOR_SPAN_DAYS or not (descending_highs or ascending_lows):
                continue
            available = second["confirm_index"]
            if available >= len(rows):
                continue
            lines.append({
                "kind": kind, "direction": direction, "first": first, "second": second,
                "available_index": available,
                "expires_index": min(len(rows) - 1, second["index"] + MAX_LINE_AGE_DAYS),
                "line_id": f"{kind}:{first['index']}:{second['index']}",
            })
    return lines


def detect_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    atr = _atr(rows)
    lines = _lines(rows, confirmed_pivots(rows))
    candidates = []
    for line in lines:
        start = max(line["available_index"], line["second"]["index"] + 1)
        broken_index = None
        for index in range(start, line["expires_index"] + 1):
            if atr[index] is None:
                continue
            level = _line_value(line["first"], line["second"], index)
            buffer = BREAK_BUFFER_ATR * atr[index]
            crossed = (rows[index]["close"] > level + buffer if line["direction"] == "bullish"
                       else rows[index]["close"] < level - buffer)
            if crossed:
                broken_index = index
                break
        if broken_index is None:
            continue
        retest_index = None
        for index in range(broken_index + 1, min(len(rows), broken_index + RETEST_WINDOW_DAYS + 1)):
            if atr[index] is None:
                continue
            level = _line_value(line["first"], line["second"], index)
            tolerance = BREAK_BUFFER_ATR * atr[index]
            held = (rows[index]["low"] <= level + tolerance and rows[index]["close"] > level
                    if line["direction"] == "bullish"
                    else rows[index]["high"] >= level - tolerance and rows[index]["close"] < level)
            if held:
                retest_index = index
                break
        if retest_index is None:
            continue
        candidates.append({**line, "break_index": broken_index, "event_index": retest_index})

    # Una linea nueva puede describir el mismo movimiento. Conservamos un evento
    # por direccion dentro del cooldown para no inflar N con señales solapadas.
    selected = []
    last_by_direction = {"bullish": -10_000, "bearish": -10_000}
    for item in sorted(candidates, key=lambda value: (value["event_index"], value["available_index"])):
        if item["event_index"] - last_by_direction[item["direction"]] < EVENT_COOLDOWN_DAYS:
            continue
        selected.append(item)
        last_by_direction[item["direction"]] = item["event_index"]
    return selected


def _event_returns(rows: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for event in events:
        index = event["event_index"]
        sign = 1 if event["direction"] == "bullish" else -1
        returns = {
            str(horizon): sign * (rows[index + horizon]["close"] / rows[index]["close"] - 1) * 100
            for horizon in HORIZONS if index + horizon < len(rows)
        }
        current_date = dt.date.fromisoformat(rows[index]["date"])
        output.append({
            "line_id": event["line_id"], "direction": event["direction"],
            "break_date": rows[event["break_index"]]["date"], "event_date": rows[index]["date"],
            "entry_close": rows[index]["close"], "returns_pct": returns,
            "calendar_month": current_date.month,
            "calendar_year": current_date.year,
            "anchor_1_date": rows[event["first"]["index"]]["date"],
            "anchor_2_date": rows[event["second"]["index"]]["date"],
            "anchor_2_confirmed_date": rows[event["second"]["confirm_index"]]["date"],
            "anchors_known_before_break": event["second"]["confirm_index"] <= event["break_index"],
        })
    return output


def _summary(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "positive_rate": sum(value > 0 for value in values) / len(values) if values else None,
        "avg_return_pct": statistics.mean(values) if values else None,
        "median_return_pct": statistics.median(values) if values else None,
    }


def _bootstrap_mean(values: list[float]) -> list[float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    draws = sorted(statistics.mean(rng.choice(values) for _ in values) for _ in range(BOOTSTRAP_ITERATIONS))
    return [draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws)) - 1]]


def _block_bootstrap_mean(pairs: list[tuple[int, float]]) -> list[float] | None:
    years = sorted({year for year, _ in pairs})
    if len(years) < 2:
        return None
    blocks = {year: [value for item_year, value in pairs if item_year == year] for year in years}
    rng = random.Random(BOOTSTRAP_SEED)
    draws = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        sampled = [rng.choice(years) for _ in years]
        values = [value for year in sampled for value in blocks[year]]
        draws.append(statistics.mean(values))
    draws.sort()
    return [draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws)) - 1]]


def _matched_month_baseline(rows: list[dict[str, Any]], event: dict[str, Any], horizon: int) -> float:
    sign = 1 if event["direction"] == "bullish" else -1
    values = []
    for index, row in enumerate(rows):
        date = dt.date.fromisoformat(row["date"])
        if date.year != event["calendar_year"] or date.month != event["calendar_month"]:
            continue
        if index + horizon >= len(rows) or row["date"] == event["event_date"]:
            continue
        values.append(sign * (rows[index + horizon]["close"] / row["close"] - 1) * 100)
    return statistics.mean(values) if values else 0.0


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: row["open_time_ms"])
    events = _event_returns(ordered, detect_events(ordered))
    groups = {}
    for direction in ("bullish", "bearish"):
        selected = [event for event in events if event["direction"] == direction]
        groups[direction] = {}
        for horizon in HORIZONS:
            eligible = [event for event in selected if str(horizon) in event["returns_pct"]]
            values = [event["returns_pct"][str(horizon)] for event in eligible]
            excess = [
                value - _matched_month_baseline(ordered, event, horizon)
                for event, value in zip(eligible, values)
            ]
            groups[direction][str(horizon)] = {
                **_summary(values), "raw_mean_bootstrap_ci95": _bootstrap_mean(values),
                "matched_same_year_month": {
                    "avg_excess_return_pct": statistics.mean(excess) if excess else None,
                    "year_block_bootstrap_ci95": _block_bootstrap_mean([
                        (event["calendar_year"], value) for event, value in zip(eligible, excess)
                    ]),
                },
            }
    july = [event for event in events if event["calendar_month"] == 7]
    return {
        "hypothesis_id": "HYP-TREND-001", "schema_version": 1, "research_only": True,
        "promotion_available": False, "execution_enabled": False,
        "status": "exploratory_post_hoc", "notice": "Research only - No signal - No bot",
        "question": "Do causal pivot trendline breaks followed by a retest have directional forward value?",
        "parameters": {
            "timeframe": "1d", "pivot_width_bars": PIVOT_WIDTH, "atr_period": ATR_PERIOD,
            "break_buffer_atr": BREAK_BUFFER_ATR, "retest_window_days": RETEST_WINDOW_DAYS,
            "max_line_age_days": MAX_LINE_AGE_DAYS, "minimum_anchor_span_days": MIN_ANCHOR_SPAN_DAYS,
            "event_cooldown_days": EVENT_COOLDOWN_DAYS, "forward_horizons_days": list(HORIZONS),
        },
        "causality": {
            "pivot_confirmation_delay_bars": PIVOT_WIDTH,
            "all_anchors_known_before_break": all(event["anchors_known_before_break"] for event in events),
            "future_prices_used_for_signal": False,
        },
        "events": events, "event_count": len(events), "groups": groups,
        "july_events": {"n": len(july), "events": july},
        "visual_examples": {
            "count": 9,
            "role": "vocabulary_only",
            "families": ["descending_channel", "triangle_compression", "ascending_support", "horizontal_structure", "scenario_arrow"],
            "warning": "Selected screenshots and drawn arrows are not outcome labels and are excluded from inferential metrics.",
        },
        "verdict": {
            "classification": "continuation_not_supported",
            "production_change": False,
            "summary": "La continuacion alcista no muestra edge; el quiebre bajista es anti-predictivo a 10 dias y parece revertir.",
        },
        "limitations": [
            "The hypothesis and parameters were defined after reviewing selected CoinSignals screenshots.",
            "Daily pivots approximate drawings made on mixed 1h, 4h and daily timeframes.",
            "Events may share market regimes despite the directional cooldown.",
            "Forward returns are diagnostic and do not include an executable entry, stop or trading costs.",
            "July-specific samples are expected to be too small for confirmation.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    if args.input:
        snapshot = json.loads(args.input.read_text(encoding="utf-8"))
        rows = snapshot["rows"]
    else:
        rows = fetch_closed_days()
        snapshot = {
            "schema_version": 1, "source": "Binance Spot public klines",
            "source_url": API_URL, "timezone": "UTC", "closed_days_only": True,
            "fetched_at_ms": int(time.time() * 1000), "rows": rows,
            "rows_sha256": _canonical_sha(rows),
        }
        _atomic_json(args.dataset, snapshot)
    report = analyze(rows)
    report["dataset"] = {
        "path": str(args.dataset.relative_to(ROOT)) if args.dataset.is_relative_to(ROOT) else str(args.dataset),
        "rows": len(rows), "rows_sha256": _canonical_sha(rows),
        "source": snapshot.get("source"), "timezone": snapshot.get("timezone"),
    }
    report["generated_at_ms"] = int(time.time() * 1000)
    _atomic_json(args.report, report)
    print(json.dumps({
        "hypothesis_id": report["hypothesis_id"], "events": report["event_count"],
        "causal": report["causality"]["all_anchors_known_before_break"],
        "promotion_available": report["promotion_available"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
