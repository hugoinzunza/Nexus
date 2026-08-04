"""HYP-SEASON-001: estacionalidad de julio y reversion tras mayo-junio rojos.

Estudio exploratorio y post-hoc. Usa exclusivamente velas mensuales cerradas de
BTCUSDT spot en Binance y no importa ningun modulo de ejecucion.
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
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_URL = (
    "https://api.binance.com/api/v3/klines"
    "?symbol=BTCUSDT&interval=1M&startTime=1501545600000&limit=1000"
)
DATASET_PATH = ROOT / "research/hypothesis_lab/data/BINANCE_BTCUSDT_MONTHLY_2017_2026.json"
REPORT_PATH = ROOT / "research/hypothesis_lab/reports/HYP-SEASON-001-20260803.summary.json"
BOOTSTRAP_SEED = 20260803
BOOTSTRAP_ITERATIONS = 20_000


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


def fetch_closed_months(now_ms: int | None = None) -> list[dict[str, Any]]:
    now_ms = now_ms or int(time.time() * 1000)
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "NexUX-research/1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = json.load(response)
    rows = []
    for item in raw:
        if int(item[6]) >= now_ms:
            continue
        opened = dt.datetime.fromtimestamp(int(item[0]) / 1000, tz=dt.timezone.utc)
        open_price, close_price = float(item[1]), float(item[4])
        rows.append({
            "year": opened.year,
            "month": opened.month,
            "open_time_ms": int(item[0]),
            "close_time_ms": int(item[6]),
            "open": open_price,
            "high": float(item[2]),
            "low": float(item[3]),
            "close": close_price,
            "return_pct": (close_price / open_price - 1) * 100,
        })
    return rows


def _wilson(successes: int, n: int, z: float = 1.959963984540054) -> list[float] | None:
    if n <= 0:
        return None
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [max(0.0, centre - margin), min(1.0, centre + margin)]


def _summary(values: list[float]) -> dict[str, Any]:
    positives = sum(value > 0 for value in values)
    return {
        "n": len(values),
        "positive": positives,
        "positive_rate": positives / len(values) if values else None,
        "positive_rate_wilson_ci95": _wilson(positives, len(values)),
        "avg_return_pct": statistics.mean(values) if values else None,
        "median_return_pct": statistics.median(values) if values else None,
    }


def _slope_pct(closes: list[float]) -> float:
    logs = [math.log(value) for value in closes]
    x_mean = (len(logs) - 1) / 2
    y_mean = statistics.mean(logs)
    denominator = sum((index - x_mean) ** 2 for index in range(len(logs)))
    slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(logs)) / denominator
    return (math.exp(slope) - 1) * 100


def _bootstrap_delta(conditioned: list[float], control: list[float]) -> dict[str, Any]:
    if not conditioned or not control:
        return {"mean_delta_pct_points": None, "ci95": None}
    rng = random.Random(BOOTSTRAP_SEED)
    draws = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        left = statistics.mean(rng.choice(conditioned) for _ in conditioned)
        right = statistics.mean(rng.choice(control) for _ in control)
        draws.append(left - right)
    draws.sort()
    lo = draws[int(0.025 * len(draws))]
    hi = draws[int(0.975 * len(draws)) - 1]
    return {
        "mean_delta_pct_points": statistics.mean(conditioned) - statistics.mean(control),
        "ci95": [lo, hi],
        "method": "independent_year_bootstrap",
        "iterations": BOOTSTRAP_ITERATIONS,
        "seed": BOOTSTRAP_SEED,
    }


def _fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    row_1, row_2, success = a + b, c + d, a + c
    total = row_1 + row_2
    denominator = math.comb(total, row_1)
    minimum = max(0, row_1 - (total - success))
    maximum = min(row_1, success)

    def probability(value: int) -> float:
        return math.comb(success, value) * math.comb(total - success, row_1 - value) / denominator

    observed = probability(a)
    return min(1.0, sum(probability(value) for value in range(minimum, maximum + 1)
                        if probability(value) <= observed + 1e-15))


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["year"], row["month"]))
    by_month = {(row["year"], row["month"]): row for row in ordered}
    julys = []
    for year in sorted({row["year"] for row in ordered}):
        may, june, july = (by_month.get((year, month)) for month in (5, 6, 7))
        january_to_june = [by_month.get((year, month)) for month in range(1, 7)]
        if not may or not june or not july or any(item is None for item in january_to_june):
            continue
        closes = [item["close"] for item in january_to_june]
        slope = _slope_pct(closes)
        julys.append({
            "year": year,
            "may_return_pct": may["return_pct"],
            "june_return_pct": june["return_pct"],
            "july_return_pct": july["return_pct"],
            "may_june_both_negative": may["return_pct"] < 0 and june["return_pct"] < 0,
            "six_month_log_slope_pct_per_month": slope,
            "june_below_six_month_sma": june["close"] < statistics.mean(closes),
        })

    conditioned = [row for row in julys if row["may_june_both_negative"]]
    other_julys = [row for row in julys if not row["may_june_both_negative"]]
    rolling_two_red = []
    two_red_falling = []
    two_red_not_falling = []
    after_falling_six_months = []
    for index in range(6, len(ordered)):
        current = ordered[index]
        prior_six = ordered[index - 6:index]
        slope = _slope_pct([row["close"] for row in prior_six])
        if slope < 0:
            after_falling_six_months.append(current["return_pct"])
        if ordered[index - 2]["return_pct"] < 0 and ordered[index - 1]["return_pct"] < 0:
            rolling_two_red.append(current["return_pct"])
            target = two_red_falling if slope < 0 else two_red_not_falling
            target.append(current["return_pct"])

    conditional_values = [row["july_return_pct"] for row in conditioned]
    control_values = [row["july_return_pct"] for row in other_julys]
    a = sum(value > 0 for value in conditional_values)
    b = len(conditional_values) - a
    c = sum(value > 0 for value in control_values)
    d = len(control_values) - c
    july_2026 = next((row for row in julys if row["year"] == 2026), None)
    trend_overlap = sum(row["six_month_log_slope_pct_per_month"] < 0 for row in conditioned)

    return {
        "hypothesis_id": "HYP-SEASON-001",
        "schema_version": 1,
        "research_only": True,
        "promotion_available": False,
        "status": "exploratory_post_hoc",
        "notice": "Research only - No signal - No bot",
        "question": "Does a negative May and June increase BTC's July return beyond July's base rate?",
        "july_2026": july_2026,
        "july_baseline": _summary([row["july_return_pct"] for row in julys]),
        "may_june_negative_then_july": {
            **_summary(conditional_values),
            "years": [row["year"] for row in conditioned],
        },
        "other_julys": _summary(control_values),
        "conditioned_vs_other_julys": {
            **_bootstrap_delta(conditional_values, control_values),
            "fisher_exact_two_sided_p": _fisher_two_sided(a, b, c, d),
        },
        "controls": {
            "any_month_after_two_negative_months": _summary(rolling_two_red),
            "any_month_after_falling_six_month_trend": _summary(after_falling_six_months),
            "two_negative_and_falling_trend": _summary(two_red_falling),
            "two_negative_without_falling_trend": _summary(two_red_not_falling),
        },
        "trend_interaction": {
            "definition": "OLS slope of log monthly closes from January through June, known at June close",
            "conditioned_cases_with_negative_slope": trend_overlap,
            "conditioned_cases": len(conditioned),
            "independent_confirmation": False,
            "reason": "Every conditioned July also has a negative six-month slope in this sample, so the trend feature is redundant with the drawdown condition.",
        },
        "cases": julys,
        "verdict": {
            "classification": "interesting_but_insufficient",
            "summary": "El patrón 4/4 existe en Binance, pero julio ya tiene una tasa base positiva alta y la incertidumbre sigue siendo amplia.",
            "production_change": False,
            "next_step": "Mantener como contexto de research y contrastar con historia independiente y julios futuros sin cambiar entradas.",
        },
        "limitations": [
            "The hypothesis was selected after viewing the CoinGlass heatmap and July 2026, so this is discovery, not confirmation.",
            "Binance BTCUSDT monthly history begins after July 2017; the screenshot's 2013-2016 values are not used inferentially.",
            "Only four conditioned Julys exist in the Binance sample.",
            "The trend definition is deterministic and causal, but it is not independent of the two-month drawdown in the conditioned July sample.",
            "No trading costs are applied because this study measures monthly context, not an executable strategy.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Snapshot JSON existente; evita red.")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    if args.input:
        snapshot = json.loads(args.input.read_text(encoding="utf-8"))
        rows = snapshot["rows"]
    else:
        rows = fetch_closed_months()
        snapshot = {
            "schema_version": 1,
            "source": "Binance Spot public klines",
            "source_url": SOURCE_URL,
            "timezone": "UTC",
            "fetched_at_ms": int(time.time() * 1000),
            "closed_months_only": True,
            "rows": rows,
        }
        snapshot["rows_sha256"] = _canonical_sha(rows)
        _atomic_json(args.dataset, snapshot)

    report = analyze(rows)
    report["dataset"] = {
        "path": str(args.dataset.relative_to(ROOT)) if args.dataset.is_relative_to(ROOT) else str(args.dataset),
        "rows": len(rows),
        "rows_sha256": _canonical_sha(rows),
        "source": snapshot.get("source"),
        "timezone": snapshot.get("timezone"),
    }
    report["generated_at_ms"] = int(time.time() * 1000)
    _atomic_json(args.report, report)
    print(json.dumps({
        "hypothesis_id": report["hypothesis_id"],
        "status": report["status"],
        "july_2026_return_pct": report["july_2026"]["july_return_pct"],
        "conditioned_n": report["may_june_negative_then_july"]["n"],
        "promotion_available": report["promotion_available"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
