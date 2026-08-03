"""Forward-only shadow observer for ``protect_3r_runner_original``.

The observer reads the Diario export, obtains public Binance Futures data with
GET requests, and writes a separate atomic research snapshot. It never imports
the bot or trading runtime and never writes to the setup store.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "research/hypothesis_lab/specs/v1/HYP-EXIT-003-SHADOW.frozen.json"
SETUPS_PATH = ROOT / "data/setups.json"
OUTPUT_PATH = ROOT / "data/hypothesis_lab/shadow/protect_3r_runner_original.json"
KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
BOOK_URL = "https://fapi.binance.com/fapi/v1/ticker/bookTicker"
MINUTE_MS = 60_000


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def _load_json(path: Path) -> Any:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            with path.open(encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.05)
    assert last_error is not None
    raise last_error


def load_protocol(path: Path = SPEC_PATH) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    protocol = json.loads(raw)
    if protocol.get("frozen") is not True or protocol.get("research_only") is not True:
        raise ValueError("shadow protocol must be frozen and research_only")
    if protocol.get("governance", {}).get("execution_enabled") is not False:
        raise ValueError("shadow protocol cannot enable execution")
    return protocol, hashlib.sha256(raw).hexdigest()


def operation_id(setup: dict[str, Any]) -> str:
    identity = {
        "key": setup.get("key"),
        "created": setup.get("ts_created"),
        "activated": setup.get("ts_activated"),
        "entry": setup.get("entry"),
        "sl": setup.get("sl"),
        "tp": setup.get("tp"),
    }
    return "op_" + hashlib.sha256(_canonical(identity)).hexdigest()[:24]


def _get_json(url: str, params: dict[str, Any], timeout: float = 20.0) -> Any:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}", headers={"User-Agent": "nexux-research-shadow/1"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def fetch_closed_1m(symbol: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = (start_ms // MINUTE_MS) * MINUTE_MS
    while cursor <= end_ms:
        raw = _get_json(KLINES_URL, {
            "symbol": symbol,
            "interval": "1m",
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        })
        if not raw:
            break
        for item in raw:
            close_ms = int(item[6])
            if close_ms <= end_ms:
                rows.append({
                    "t": int(item[0]), "close_t": close_ms,
                    "o": float(item[1]), "h": float(item[2]),
                    "l": float(item[3]), "c": float(item[4]),
                })
        next_cursor = int(raw[-1][0]) + MINUTE_MS
        if next_cursor <= cursor or len(raw) < 1000:
            break
        cursor = next_cursor
    return rows


def fetch_spread(symbol: str) -> dict[str, Any]:
    raw = _get_json(BOOK_URL, {"symbol": symbol})
    bid, ask = float(raw["bidPrice"]), float(raw["askPrice"])
    mid = (bid + ask) / 2.0
    return {
        "bid": bid,
        "ask": ask,
        "full_spread_rate": ((ask - bid) / mid if mid > 0 else None),
        "observed_at_ms": int(time.time() * 1000),
        "source": "binance_futures_bookTicker_at_detection",
    }


def _hit_stop(bar: dict[str, Any], long: bool, stop: float) -> bool:
    return bar["l"] <= stop if long else bar["h"] >= stop


def _hit_target(bar: dict[str, Any], long: bool, target: float) -> bool:
    return bar["h"] >= target if long else bar["l"] <= target


def _r_at(price: float, entry: float, risk: float, long: bool) -> float:
    return (price - entry) / risk if long else (entry - price) / risk


def _iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def _exit_cost(
    gross_r: float,
    reason: str,
    entry: float,
    risk: float,
    spread: dict[str, Any] | None,
    protocol: dict[str, Any],
) -> tuple[float | None, dict[str, Any]]:
    model = protocol["costs"]
    market = reason in {"stop_original", "stop_protected", "timeout_market"}
    full_spread = spread.get("full_spread_rate") if spread else None
    if market and full_spread is None:
        return None, {
            "status": "missing_spread",
            "commission_rate": None,
            "spread_rate": None,
            "slippage_rate": None,
            "cost_r": None,
        }
    commission = float(model["maker_fee_rate"]) + float(
        model["taker_fee_rate"] if market else model["maker_fee_rate"]
    )
    spread_rate = float(full_spread) / 2.0 if market else 0.0
    slippage = float(model["modeled_market_slippage_rate"]) if market else 0.0
    total_rate = commission + spread_rate + slippage
    cost_r = total_rate / (risk / entry)
    return gross_r - cost_r, {
        "status": "modeled_with_observed_spread",
        "commission_rate": commission,
        "spread_rate": spread_rate,
        "slippage_rate": slippage,
        "total_rate": total_rate,
        "cost_r": cost_r,
        "spread_observation": copy.deepcopy(spread),
    }


def _branch(reason: str, price: float, at_ms: int, gross_r: float) -> dict[str, Any]:
    return {
        "status": "closed",
        "exit_reason": reason,
        "exit_price": price,
        "exit_at_ms": at_ms,
        "exit_at_iso": _iso(at_ms),
        "gross_r": gross_r,
        "net_r": None,
        "costs": None,
    }


def simulate_shadow(
    setup: dict[str, Any],
    candles: list[dict[str, Any]],
    spread: dict[str, Any] | None,
    protocol: dict[str, Any],
    observed_at_ms: int,
) -> dict[str, Any]:
    """Simulate original and protected exits on the same closed 1m bars."""
    entry, sl, target = map(float, (setup["entry"], setup["sl"], setup["tp"]))
    activated_ms = int(setup["ts_activated"]) * 1000
    long = setup["dir"] == "long"
    risk = abs(entry - sl)
    if risk <= 0 or entry <= 0:
        raise ValueError("invalid entry/stop risk")
    trigger_rr = float(protocol["candidate"]["trigger_rr"])
    trigger_price = entry + trigger_rr * risk if long else entry - trigger_rr * risk
    protected_stop = entry
    original_rr = abs(target - entry) / risk
    tf = setup.get("poi_tf") or setup.get("sel_tf") or "unknown"
    record: dict[str, Any] = {
        "research_only": True,
        "hypothesis_id": protocol["hypothesis_id"],
        "operation_id": operation_id(setup),
        "setup_id": f"{setup.get('key')}:{setup.get('ts_created')}",
        "pair": setup.get("pair"),
        "timeframe": tf,
        "direction": setup.get("dir"),
        "entry_at_ms": activated_ms,
        "entry_at_iso": _iso(activated_ms),
        "entry_price": entry,
        "target_original_price": target,
        "target_original_rr": original_rr,
        "trigger_3r_price": trigger_price,
        "trigger_3r_at_ms": None,
        "trigger_3r_at_iso": None,
        "trigger_timestamp_precision_ms": MINUTE_MS,
        "stop_original_price": sl,
        "stop_protected_price": protected_stop,
        "original_branch": {"status": "open", "exit_reason": None, "net_r": None},
        "protected_branch": {"status": "open", "exit_reason": None, "net_r": None},
        "post_3r": {"mae_r": None, "mfe_r": None, "observed_until_ms": None},
        "observed_at_ms": observed_at_ms,
        "source": "public_binance_futures_closed_1m",
    }
    if not candles:
        record["observation_status"] = "waiting_for_closed_candles"
        return record
    activation_index = next(
        (index for index, bar in enumerate(candles)
         if bar["t"] <= activated_ms <= bar["close_t"]),
        None,
    )
    if activation_index is None:
        record["observation_status"] = "activation_bar_missing"
        return record

    original: dict[str, Any] | None = None
    protected: dict[str, Any] | None = None
    trigger_index: int | None = None
    trigger_at: int | None = None

    activation_bar = candles[activation_index]
    if _hit_stop(activation_bar, long, sl):
        original = _branch("stop_original", sl, activation_bar["t"], -1.0)
        protected = copy.deepcopy(original)

    for index in range(activation_index + 1, len(candles)):
        if original is not None and protected is not None:
            break
        bar = candles[index]
        if original is None:
            if _hit_stop(bar, long, sl):
                original = _branch("stop_original", sl, bar["t"], -1.0)
            elif _hit_target(bar, long, target):
                original = _branch("target_original", target, bar["t"], original_rr)

        active_protected_stop = protected_stop if (
            trigger_index is not None and index > trigger_index
        ) else sl
        if protected is None:
            if _hit_stop(bar, long, active_protected_stop):
                reason = "stop_protected" if active_protected_stop == protected_stop else "stop_original"
                protected = _branch(
                    reason, active_protected_stop, bar["t"],
                    _r_at(active_protected_stop, entry, risk, long),
                )
            elif _hit_target(bar, long, target):
                protected = _branch("target_original", target, bar["t"], original_rr)

        if (
            trigger_index is None
            and original_rr > trigger_rr
            and not (original and original["exit_reason"] == "stop_original")
            and _hit_target(bar, long, trigger_price)
        ):
            trigger_index = index
            trigger_at = bar["t"]

    timeout_at_ms = activated_ms + int(
        protocol["cohort"]["maximum_observation_days_per_operation"]
    ) * 86_400_000
    if observed_at_ms >= timeout_at_ms and candles:
        last = candles[-1]
        timeout_r = _r_at(float(last["c"]), entry, risk, long)
        if original is None:
            original = _branch("timeout_market", float(last["c"]), last["t"], timeout_r)
        if protected is None:
            protected = _branch("timeout_market", float(last["c"]), last["t"], timeout_r)

    record["trigger_3r_at_ms"] = trigger_at
    record["trigger_3r_at_iso"] = _iso(trigger_at)
    if trigger_index is not None:
        end_index = len(candles) - 1
        if original is not None:
            end_index = next(
                (i for i, bar in enumerate(candles)
                 if i >= trigger_index and bar["t"] == original["exit_at_ms"]),
                end_index,
            )
        post = candles[trigger_index + 1:end_index + 1]
        if post:
            favorable = [
                _r_at(bar["h"] if long else bar["l"], entry, risk, long)
                for bar in post
            ]
            adverse = [
                _r_at(bar["l"] if long else bar["h"], entry, risk, long)
                for bar in post
            ]
            record["post_3r"] = {
                "mae_r": min(adverse),
                "mfe_r": max(favorable),
                "observed_until_ms": post[-1]["close_t"],
            }

    for key, branch in (("original_branch", original), ("protected_branch", protected)):
        if branch is None:
            continue
        net_r, costs = _exit_cost(
            float(branch["gross_r"]), str(branch["exit_reason"]), entry, risk,
            spread, protocol,
        )
        branch["net_r"] = net_r
        branch["costs"] = costs
        record[key] = branch
    record["observation_status"] = (
        "paired_closed" if original is not None and protected is not None
        else "observing"
    )
    return record


def _eligible(setup: dict[str, Any], protocol: dict[str, Any]) -> bool:
    activated = setup.get("ts_activated")
    if not activated or setup.get("dir") not in {"long", "short"}:
        return False
    if int(activated) * 1000 < int(protocol["cohort_start_ms"]):
        return False
    return all(setup.get(field) is not None for field in ("entry", "sl", "tp"))


def _profit_factor(values: list[float]) -> float | None:
    profit = sum(value for value in values if value > 0)
    loss = abs(sum(value for value in values if value < 0))
    return profit / loss if loss else None


def _max_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def evaluate_decision(
    records: list[dict[str, Any]],
    protocol: dict[str, Any],
    now_ms: int,
) -> dict[str, Any]:
    """Apply the frozen decision protocol without selecting subgroups."""
    closed = sorted((
        row for row in records
        if row.get("observation_status") == "paired_closed"
        and row.get("original_branch", {}).get("net_r") is not None
        and row.get("protected_branch", {}).get("net_r") is not None
    ), key=lambda row: (row["entry_at_ms"], row["operation_id"]))
    original = [float(row["original_branch"]["net_r"]) for row in closed]
    protected = [float(row["protected_branch"]["net_r"]) for row in closed]
    deltas = [candidate - baseline for baseline, candidate in zip(original, protected)]
    weeks_elapsed = max(
        0.0, (now_ms - int(protocol["cohort_start_ms"])) / (7 * 86_400_000)
    )
    triggered = sum(row.get("trigger_3r_at_ms") is not None for row in closed)
    original_pf, protected_pf = _profit_factor(original), _profit_factor(protected)
    original_dd, protected_dd = _max_drawdown(original), _max_drawdown(protected)
    pf_abs = (
        protected_pf - original_pf
        if original_pf is not None and protected_pf is not None else None
    )
    pf_rel = pf_abs / original_pf if pf_abs is not None and original_pf else None
    dd_reduction = (
        (original_dd - protected_dd) / original_dd if original_dd > 0 else None
    )
    avg_delta = statistics.fmean(deltas) if deltas else None

    week_blocks: dict[int, list[float]] = {}
    for row, delta in zip(closed, deltas):
        week = (int(row["entry_at_ms"]) - int(protocol["cohort_start_ms"])) // (7 * 86_400_000)
        week_blocks.setdefault(week, []).append(delta)
    ci95 = None
    if len(week_blocks) >= 2:
        keys = sorted(week_blocks)
        rng = random.Random(20260803)
        draws = []
        iterations = int(protocol["decision_protocol"]["confidence"]["iterations"])
        for _ in range(iterations):
            sample = []
            for _ in keys:
                sample.extend(week_blocks[keys[rng.randrange(len(keys))]])
            draws.append(statistics.fmean(sample))
        draws.sort()
        ci95 = [
            draws[int(0.025 * (iterations - 1))],
            draws[int(0.975 * (iterations - 1))],
        ]

    rules = protocol["decision_protocol"]
    minimum_ready = (
        len(closed) >= int(rules["minimum_paired_closed_operations"])
        and triggered >= int(rules["minimum_operations_reaching_3r"])
        and weeks_elapsed >= float(rules["minimum_calendar_weeks"])
        and ci95 is not None
    )
    promote = False
    discard_reasons: list[str] = []
    if minimum_ready:
        required = rules["promotion_requires_all"]
        promote = all((
            ci95[0] > float(rules["confidence"]["promotion_requires_lower_bound_above_r"]),
            pf_abs is not None and pf_abs >= float(required["absolute_profit_factor_improvement"]),
            pf_rel is not None and pf_rel >= float(required["relative_profit_factor_improvement"]),
            dd_reduction is not None and dd_reduction >= float(required["relative_max_drawdown_reduction"]),
            avg_delta is not None and avg_delta >= float(required["minimum_avg_net_r_delta"]),
        ))
        early = rules["early_discard_after_minimum_sample_if_any"]
        if ci95[1] <= float(early["ci95_upper_bound_at_or_below_r"]):
            discard_reasons.append("ci95_upper_not_positive")
        if pf_rel is not None and pf_rel <= -float(early["relative_profit_factor_deterioration"]):
            discard_reasons.append("profit_factor_deterioration")
        if dd_reduction is not None and dd_reduction <= -float(early["relative_max_drawdown_increase"]):
            discard_reasons.append("drawdown_increase")
        if avg_delta is not None and avg_delta <= float(early["avg_net_r_delta_at_or_below"]):
            discard_reasons.append("avg_r_deterioration")
    terminal = (
        len(closed) >= int(rules["maximum_paired_closed_operations"])
        or weeks_elapsed >= float(rules["maximum_calendar_weeks"])
    )
    if promote:
        status = "promotion_evidence_met_manual_review_required"
    elif discard_reasons or (terminal and not promote):
        status = "discard"
        if terminal and not discard_reasons:
            discard_reasons.append("terminal_cap_without_all_promotion_criteria")
    else:
        status = "collecting_insufficient_evidence"
    return {
        "status": status,
        "automatic_promotion": False,
        "minimum_sample_ready": minimum_ready,
        "n_paired_closed": len(closed),
        "n_reached_3r": triggered,
        "weeks_elapsed": weeks_elapsed,
        "metrics": {
            "original_avg_net_r": statistics.fmean(original) if original else None,
            "protected_avg_net_r": statistics.fmean(protected) if protected else None,
            "paired_avg_net_r_delta": avg_delta,
            "paired_delta_ci95": ci95,
            "original_profit_factor": original_pf,
            "protected_profit_factor": protected_pf,
            "absolute_profit_factor_improvement": pf_abs,
            "relative_profit_factor_improvement": pf_rel,
            "original_max_drawdown_r": original_dd,
            "protected_max_drawdown_r": protected_dd,
            "relative_max_drawdown_reduction": dd_reduction,
        },
        "discard_reasons": discard_reasons,
    }


def build_snapshot(
    setups: list[dict[str, Any]],
    protocol: dict[str, Any],
    protocol_sha256: str,
    *,
    now_ms: int | None = None,
    candle_fetcher: Callable[[str, int, int], list[dict[str, Any]]] = fetch_closed_1m,
    spread_fetcher: Callable[[str], dict[str, Any]] = fetch_spread,
    previous_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now_ms = now_ms or int(time.time() * 1000)
    records, errors = [], []
    previous_by_id = {
        row["operation_id"]: copy.deepcopy(row)
        for row in (previous_records or [])
        if row.get("operation_id")
    }
    eligible = [copy.deepcopy(item) for item in setups if _eligible(item, protocol)]
    for setup in eligible:
        symbol = str(setup["pair"]).replace("_", "")
        op_id = operation_id(setup)
        previous = previous_by_id.get(op_id)
        if previous and previous.get("observation_status") == "paired_closed":
            records.append(previous)
            continue
        start_ms = int(setup["ts_activated"]) * 1000
        max_end = start_ms + int(
            protocol["cohort"]["maximum_observation_days_per_operation"]
        ) * 86_400_000
        end_ms = min(now_ms, max_end)
        try:
            candles = candle_fetcher(symbol, start_ms, end_ms)
            spread = spread_fetcher(symbol)
            records.append(simulate_shadow(
                setup, candles, spread, protocol, now_ms,
            ))
        except Exception as exc:  # observation failure is data, never a trade action
            errors.append({
                "operation_id": operation_id(setup),
                "pair": setup.get("pair"),
                "error_type": type(exc).__name__,
                "error": str(exc)[:160],
            })
    paired = [row for row in records if row["observation_status"] == "paired_closed"]
    triggered = [row for row in records if row["trigger_3r_at_ms"] is not None]
    deltas = [
        row["protected_branch"]["net_r"] - row["original_branch"]["net_r"]
        for row in paired
        if row["protected_branch"].get("net_r") is not None
        and row["original_branch"].get("net_r") is not None
    ]
    decision = evaluate_decision(records, protocol, now_ms)
    return {
        "meta": {
            "research_only": True,
            "notice": protocol["notice"],
            "hypothesis_id": protocol["hypothesis_id"],
            "protocol_sha256": protocol_sha256,
            "generated_at_ms": now_ms,
            "cohort_start_ms": protocol["cohort_start_ms"],
            "n_eligible": len(eligible),
            "n_records": len(records),
            "n_paired_closed": len(paired),
            "n_reached_3r": len(triggered),
            "paired_avg_net_r_delta": statistics.fmean(deltas) if deltas else None,
            "errors": errors,
            "writes_to_bot_or_diario": 0,
        },
        "decision_protocol": copy.deepcopy(protocol["decision_protocol"]),
        "decision": decision,
        "records": records,
    }


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def run_once(setups_path: Path = SETUPS_PATH, output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    protocol, protocol_sha = load_protocol()
    setups = _load_json(setups_path)
    if not isinstance(setups, list):
        raise ValueError("setups input must be a list")
    previous_records = None
    if output_path.exists():
        previous = _load_json(output_path)
        if (
            isinstance(previous, dict)
            and previous.get("meta", {}).get("protocol_sha256") == protocol_sha
        ):
            previous_records = previous.get("records")
    snapshot = build_snapshot(
        setups, protocol, protocol_sha, previous_records=previous_records,
    )
    write_atomic(output_path, snapshot)
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setups", type=Path, default=SETUPS_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=60.0)
    args = parser.parse_args()
    while True:
        try:
            snapshot = run_once(args.setups, args.output)
            print(json.dumps(snapshot["meta"], ensure_ascii=False, sort_keys=True), flush=True)
        except Exception as exc:
            print(json.dumps({
                "research_only": True,
                "status": "observer_error",
                "error_type": type(exc).__name__,
                "error": str(exc)[:200],
            }, ensure_ascii=False), flush=True)
        if not args.watch:
            break
        time.sleep(max(10.0, args.interval))


if __name__ == "__main__":
    main()
