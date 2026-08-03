"""Forward-only, read-only execution cost telemetry.

The observer reads bot ledgers as immutable inputs, optionally captures a
public Binance Futures bookTicker after detecting a new live fill, and writes a
separate atomic research snapshot. It never imports execution modules.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "research/hypothesis_lab/specs/v1/HYP-COST-003-TELEMETRY.frozen.json"
OUTPUT_PATH = ROOT / "data/hypothesis_lab/telemetry/execution_costs.json"


def _load_json(path: Path) -> Any:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            with path.open(encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.03)
    assert last_error is not None
    raise last_error


def load_protocol(path: Path = SPEC_PATH) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    protocol = json.loads(raw)
    if protocol.get("hypothesis_id") != "HYP-COST-003-TELEMETRY":
        raise ValueError("unexpected telemetry hypothesis")
    if protocol.get("frozen") is not True or protocol.get("research_only") is not True:
        raise ValueError("telemetry protocol must be frozen and research_only")
    governance = protocol.get("governance", {})
    if governance.get("http_methods_allowed") != ["GET"]:
        raise ValueError("only public GET observations are allowed")
    if any(governance.get(key) is not False for key in (
        "execution_enabled", "bot_changes_allowed", "testnet_changes_allowed",
        "live_changes_allowed", "railway_changes_allowed", "vps_changes_allowed",
    )):
        raise ValueError("telemetry governance changed")
    return protocol, hashlib.sha256(raw).hexdigest()


def fetch_book(symbol: str, endpoint: str, timeout: float = 5.0) -> dict[str, Any]:
    query = urllib.parse.urlencode({"symbol": symbol})
    request = urllib.request.Request(
        f"{endpoint}?{query}", headers={"User-Agent": "nexux-cost-telemetry/1"}, method="GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = json.load(response)
    bid, ask = float(raw["bidPrice"]), float(raw["askPrice"])
    mid = (bid + ask) / 2.0
    if bid <= 0 or ask < bid or mid <= 0:
        raise ValueError("invalid public bookTicker")
    return {
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "full_spread_rate": (ask - bid) / mid,
        "observed_at_ms": int(time.time() * 1000),
        "source": "binance_futures_public_bookTicker_after_fill_detection",
    }


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def observation_id(source_id: str, trade: dict[str, Any]) -> str:
    identity = {
        "source_id": source_id,
        "setup_id": trade.get("setup_id"),
        "symbol": trade.get("symbol"),
        "opened_at": trade.get("opened_at"),
    }
    return "cost_" + hashlib.sha256(_canonical(identity)).hexdigest()[:24]


def _adverse_slippage(fill: float | None, reference: float | None, direction: str | None) -> float | None:
    if not fill or not reference or direction not in {"long", "short"}:
        return None
    sign = 1.0 if direction == "long" else -1.0
    return sign * (float(fill) - float(reference)) / float(reference)


def _turnover(trade: dict[str, Any]) -> dict[str, float | None]:
    qty = float(trade.get("qty") or 0.0)
    entry = float(trade.get("entry_price") or 0.0)
    if qty <= 0 or entry <= 0:
        return {"entry_notional_usd": None, "roundtrip_turnover_usd": None}
    entry_notional = qty * entry
    partial_qty = 0.0
    exit_turnover = 0.0
    for partial in trade.get("partials") or []:
        part_qty = max(0.0, float(partial.get("qty") or 0.0))
        part_price = float(partial.get("price") or 0.0)
        partial_qty += part_qty
        exit_turnover += part_qty * part_price
    if trade.get("status") == "cerrada" and trade.get("exit_price") is not None:
        remaining = max(0.0, qty - partial_qty)
        exit_turnover += remaining * float(trade["exit_price"])
        return {
            "entry_notional_usd": entry_notional,
            "roundtrip_turnover_usd": entry_notional + exit_turnover,
        }
    return {"entry_notional_usd": entry_notional, "roundtrip_turnover_usd": None}


def _eligible(trade: dict[str, Any], source: dict[str, Any], protocol: dict[str, Any]) -> bool:
    opened = trade.get("opened_at")
    return bool(
        opened
        and int(opened) * 1000 >= int(protocol["cohort_start_ms"])
        and trade.get("mode") == source["eligible_mode"]
        and trade.get("entry_price")
        and trade.get("symbol")
    )


def build_record(
    trade: dict[str, Any],
    source: dict[str, Any],
    protocol: dict[str, Any],
    now_ms: int,
    *,
    previous: dict[str, Any] | None = None,
    book: dict[str, Any] | None = None,
    book_error: str | None = None,
) -> dict[str, Any]:
    opened_ms = int(trade["opened_at"]) * 1000
    detection = copy.deepcopy(previous.get("book_after_fill_detection")) if previous else None
    detection_error = previous.get("book_detection_error") if previous else None
    if detection is None and book is not None:
        detection = copy.deepcopy(book)
        detection["detection_lag_ms"] = int(book["observed_at_ms"]) - opened_ms
        detection["timely"] = detection["detection_lag_ms"] <= int(
            protocol["observations"]["maximum_timely_spread_detection_lag_ms"]
        )
        detection_error = None
    elif detection is None and book_error:
        detection_error = book_error[:160]

    turnover = _turnover(trade)
    confirmed = bool(trade.get("pnl_confirmed"))
    fees = float(trade.get("fees_usd") or 0.0) if confirmed else None
    entry_notional = turnover["entry_notional_usd"]
    roundtrip_turnover = turnover["roundtrip_turnover_usd"]
    return {
        "research_only": True,
        "hypothesis_id": protocol["hypothesis_id"],
        "observation_id": observation_id(source["source_id"], trade),
        "source_id": source["source_id"],
        "environment": source["environment"],
        "inferential_role": source["inferential_role"],
        "setup_id": trade.get("setup_id"),
        "symbol": trade.get("symbol"),
        "direction": trade.get("dir"),
        "opened_at_ms": opened_ms,
        "closed_at_ms": int(trade["closed_at"]) * 1000 if trade.get("closed_at") else None,
        "ledger_status": trade.get("status"),
        "entry": {
            "fill_price": float(trade["entry_price"]),
            "activation_reference_price": (
                float(trade["activation_price"]) if trade.get("activation_price") else None
            ),
            "setup_reference_price": float(trade["setup_entry"]) if trade.get("setup_entry") else None,
            "adverse_slippage_rate_vs_activation": _adverse_slippage(
                trade.get("entry_price"), trade.get("activation_price"), trade.get("dir")
            ),
            "adverse_slippage_rate_vs_setup": _adverse_slippage(
                trade.get("entry_price"), trade.get("setup_entry"), trade.get("dir")
            ),
        },
        "book_after_fill_detection": detection,
        "book_detection_error": detection_error,
        "commission": {
            "status": "observed_confirmed" if confirmed else "waiting_for_confirmed_income",
            "fees_usd": fees,
            "roundtrip_fee_rate_of_entry_notional": (
                fees / entry_notional if fees is not None and entry_notional else None
            ),
            "fee_rate_of_total_turnover": (
                fees / roundtrip_turnover if fees is not None and roundtrip_turnover else None
            ),
        },
        "turnover": turnover,
        "exit": {
            "fill_price": float(trade["exit_price"]) if trade.get("exit_price") is not None else None,
            "intended_reference_price": None,
            "slippage_rate": None,
            "status": "unavailable_without_intended_exit_reference",
        },
        "coverage": {
            "entry_fill": True,
            "activation_reference": trade.get("activation_price") is not None,
            "timely_spread": bool(detection and detection.get("timely")),
            "confirmed_commission": confirmed,
            "exit_slippage": False,
            "complete_roundtrip_cost": False,
        },
        "last_observed_at_ms": now_ms,
    }


def evaluate(records: list[dict[str, Any]], protocol: dict[str, Any], now_ms: int) -> dict[str, Any]:
    primary = [row for row in records if row["inferential_role"] == "primary_live_only"]
    confirmed = sum(
        row["ledger_status"] == "cerrada" and row["coverage"]["confirmed_commission"]
        for row in primary
    )
    activation = sum(row["coverage"]["activation_reference"] for row in primary)
    timely = sum(row["coverage"]["timely_spread"] for row in primary)
    weeks = max(0.0, (now_ms - int(protocol["cohort_start_ms"])) / (7 * 86_400_000))
    rules = protocol["decision_protocol"]
    ready = all((
        confirmed >= int(rules["minimum_live_closed_with_confirmed_fees"]),
        activation >= int(rules["minimum_live_entries_with_activation_reference"]),
        timely >= int(rules["minimum_live_entries_with_timely_spread"]),
        weeks >= float(rules["minimum_calendar_weeks"]),
    ))
    return {
        "status": "manual_cost_scenario_review_ready" if ready else "collecting_insufficient_coverage",
        "automatic_recalibration": False,
        "automatic_strategy_change": False,
        "minimum_coverage_ready": ready,
        "weeks_elapsed": weeks,
        "primary_live_counts": {
            "records": len(primary),
            "closed_with_confirmed_fees": confirmed,
            "entries_with_activation_reference": activation,
            "entries_with_timely_spread": timely,
        },
    }


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    output = {}
    for environment in sorted({row["environment"] for row in records}):
        rows = [row for row in records if row["environment"] == environment]
        activation_slippage = [
            float(row["entry"]["adverse_slippage_rate_vs_activation"])
            for row in rows if row["entry"]["adverse_slippage_rate_vs_activation"] is not None
        ]
        timely_spreads = [
            float(row["book_after_fill_detection"]["full_spread_rate"])
            for row in rows if row.get("book_after_fill_detection")
            and row["book_after_fill_detection"].get("timely")
        ]
        confirmed_fees = [
            float(row["commission"]["roundtrip_fee_rate_of_entry_notional"])
            for row in rows if row["commission"]["roundtrip_fee_rate_of_entry_notional"] is not None
        ]
        output[environment] = {
            "n": len(rows),
            "mean_adverse_entry_slippage_rate_vs_activation": _mean(activation_slippage),
            "mean_timely_full_spread_rate": _mean(timely_spreads),
            "mean_confirmed_roundtrip_fee_rate_of_entry_notional": _mean(confirmed_fees),
            "coverage": {
                "activation_reference": len(activation_slippage),
                "timely_spread": len(timely_spreads),
                "confirmed_commission": len(confirmed_fees),
            },
        }
    return output


def build_snapshot(
    ledgers: dict[str, list[dict[str, Any]]],
    protocol: dict[str, Any],
    protocol_sha256: str,
    *,
    now_ms: int | None = None,
    previous_records: list[dict[str, Any]] | None = None,
    book_fetcher: Callable[[str, str], dict[str, Any]] = fetch_book,
) -> dict[str, Any]:
    now_ms = now_ms or int(time.time() * 1000)
    previous_by_id = {
        row["observation_id"]: row for row in (previous_records or []) if row.get("observation_id")
    }
    records, errors = [], []
    excluded = {"before_cohort_or_ineligible": 0, "dry": 0}
    endpoint = protocol["inputs"]["public_book_endpoint"]
    max_lag = int(protocol["observations"]["maximum_timely_spread_detection_lag_ms"])
    for source in protocol["inputs"]["ledgers"]:
        for trade in ledgers.get(source["source_id"], []):
            if trade.get("mode") == "dry":
                excluded["dry"] += 1
                continue
            if not _eligible(trade, source, protocol):
                excluded["before_cohort_or_ineligible"] += 1
                continue
            obs_id = observation_id(source["source_id"], trade)
            previous = previous_by_id.get(obs_id)
            book = None
            book_error = None
            opened_ms = int(trade["opened_at"]) * 1000
            needs_book = not previous or not previous.get("book_after_fill_detection")
            if needs_book and now_ms - opened_ms <= max_lag:
                try:
                    book = book_fetcher(str(trade["symbol"]), endpoint)
                except Exception as exc:
                    book_error = f"{type(exc).__name__}: {exc}"
                    errors.append({"observation_id": obs_id, "error": book_error[:160]})
            records.append(build_record(
                trade, source, protocol, now_ms,
                previous=previous, book=book, book_error=book_error,
            ))
    records.sort(key=lambda row: (row["opened_at_ms"], row["observation_id"]))
    return {
        "meta": {
            "research_only": True,
            "notice": protocol["notice"],
            "hypothesis_id": protocol["hypothesis_id"],
            "protocol_sha256": protocol_sha256,
            "cohort_start_ms": protocol["cohort_start_ms"],
            "generated_at_ms": now_ms,
            "n_records": len(records),
            "excluded": excluded,
            "errors": errors,
            "writes_to_source_ledgers": 0,
        },
        "decision_protocol": copy.deepcopy(protocol["decision_protocol"]),
        "decision": evaluate(records, protocol, now_ms),
        "summary_by_environment": summarize(records),
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


def run_once(output_path: Path = OUTPUT_PATH, input_root: Path = ROOT) -> dict[str, Any]:
    protocol, digest = load_protocol()
    ledgers = {}
    load_errors = []
    for source in protocol["inputs"]["ledgers"]:
        path = input_root / source["path"]
        try:
            value = _load_json(path)
            ledgers[source["source_id"]] = value if isinstance(value, list) else []
        except FileNotFoundError:
            ledgers[source["source_id"]] = []
            load_errors.append({"source_id": source["source_id"], "error": "ledger_missing"})
    previous_records = None
    if output_path.exists():
        previous = _load_json(output_path)
        if previous.get("meta", {}).get("protocol_sha256") == digest:
            previous_records = previous.get("records")
    snapshot = build_snapshot(
        ledgers, protocol, digest, previous_records=previous_records,
    )
    snapshot["meta"]["load_errors"] = load_errors
    write_atomic(output_path, snapshot)
    return snapshot


def input_signature(input_root: Path = ROOT) -> tuple[tuple[str, int | None, int | None], ...]:
    """Detect ledger changes without polling the network or rewriting output."""
    protocol, _ = load_protocol()
    values = []
    for source in protocol["inputs"]["ledgers"]:
        path = input_root / source["path"]
        try:
            stat = path.stat()
            values.append((source["source_id"], stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            values.append((source["source_id"], None, None))
    return tuple(values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument(
        "--input-root", type=Path, default=ROOT,
        help="Raiz de solo lectura que contiene las rutas data/ declaradas en el protocolo.",
    )
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    last_signature = None
    last_run_monotonic = 0.0
    while True:
        should_run = True
        if args.watch:
            try:
                signature = input_signature(args.input_root)
                should_run = (
                    signature != last_signature
                    or time.monotonic() - last_run_monotonic >= 60.0
                )
            except Exception:
                signature = None
        if not should_run:
            time.sleep(max(0.5, args.interval))
            continue
        try:
            snapshot = run_once(args.output, args.input_root)
            print(json.dumps(snapshot["meta"], ensure_ascii=False, sort_keys=True), flush=True)
            last_signature = signature if args.watch else None
            last_run_monotonic = time.monotonic()
        except Exception as exc:
            print(json.dumps({
                "research_only": True,
                "status": "observer_error",
                "error_type": type(exc).__name__,
                "error": str(exc)[:200],
            }, ensure_ascii=False), flush=True)
        if not args.watch:
            break
        time.sleep(max(0.5, args.interval))


if __name__ == "__main__":
    main()
