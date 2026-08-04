"""Forward-only observer for HYP-CANDLE-002-SHADOW.

Reads setups and public Binance Futures klines, then writes a separate atomic
research snapshot. It never imports the bot and never mutates the Diario.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from research.hypothesis_lab import candle_reversal_study as pattern


ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "research/hypothesis_lab/specs/v1/HYP-CANDLE-002-SHADOW.frozen.json"
SETUPS_PATH = ROOT / "data/setups.json"
OUTPUT_PATH = ROOT / "data/hypothesis_lab/shadow/candle_reversal_forward.json"
KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
TF_MS = {"1h": 3_600_000, "4h": 14_400_000}


def _load(path: Path) -> Any:
    for attempt in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            if attempt == 2:
                raise
            time.sleep(0.05)


def _atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _get_klines(symbol: str, timeframe: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({
        "symbol": symbol, "interval": timeframe, "startTime": start_ms,
        "endTime": end_ms, "limit": 1000,
    })
    request = urllib.request.Request(f"{KLINES_URL}?{query}", headers={"User-Agent": "nexux-candle-shadow/1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = json.load(response)
    return [{"t": int(row[0]), "o": float(row[1]), "h": float(row[2]),
             "l": float(row[3]), "c": float(row[4])}
            for row in raw if int(row[6]) <= end_ms]


def _symbol(pair: str) -> str:
    return pair.replace("_", "")


def _operation_id(setup: dict[str, Any]) -> str:
    raw = "|".join(str(setup.get(key)) for key in ("key", "ts_created", "ts_activated", "entry", "sl", "tp"))
    return "candle_" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _summary(records: list[dict[str, Any]], protocol: dict[str, Any]) -> dict[str, Any]:
    closed = [row for row in records if isinstance(row.get("result_r_original"), (int, float))]
    with_pattern = [row for row in closed if row.get("pattern_detected") is True]
    without = [row for row in closed if row.get("pattern_status") == "not_detected_window_closed"]
    return {
        "eligible_records": len(records), "closed_records": len(closed),
        "patterns": sum(row.get("pattern_detected") is True for row in records),
        "closed_with_pattern": len(with_pattern), "closed_without_pattern": len(without),
        "avg_r_with_pattern": statistics.fmean(row["result_r_original"] for row in with_pattern) if with_pattern else None,
        "avg_r_without_pattern": statistics.fmean(row["result_r_original"] for row in without) if without else None,
        "decision_status": "collecting_insufficient_evidence",
        "minimum_closed_patterns": protocol["decision_protocol"]["minimum_closed_patterns"],
        "promotion_available": False,
    }


def observe(setups_path: Path = SETUPS_PATH, output_path: Path = OUTPUT_PATH,
            spec_path: Path = SPEC_PATH, now_ms: int | None = None,
            fetcher=_get_klines) -> dict[str, Any]:
    now_ms = now_ms or int(time.time() * 1000)
    protocol = _load(spec_path)
    if not protocol.get("frozen") or not protocol.get("research_only"):
        raise ValueError("shadow protocol must be frozen and research_only")
    before = setups_path.read_bytes()
    setups = json.loads(before)
    records = []
    errors = []
    cohort_start = int(protocol["cohort"]["start_at_ms"])
    for setup in setups:
        activated = setup.get("ts_activated")
        if not isinstance(activated, (int, float)) or int(activated * 1000) < cohort_start:
            continue
        timeframe = setup.get("poi_tf") or setup.get("sel_tf")
        if timeframe not in TF_MS:
            continue
        activation_ms = int(activated * 1000)
        interval = TF_MS[timeframe]
        try:
            candles = fetcher(_symbol(setup["pair"]), timeframe,
                              activation_ms - (pattern.ATR_PERIOD + 4) * interval, now_ms)
            act = next((index for index, row in enumerate(candles)
                        if row["t"] <= activation_ms < row["t"] + interval), None)
            if act is None:
                status, detected = "activation_bar_missing", None
            else:
                adapted = {
                    **setup, "activation_index": act, "original_tp": setup["tp"],
                    "direction": setup.get("dir"),
                }
                atr = pattern._atr(candles)
                detected = pattern.detect_after_touch(adapted, candles, atr)
                if detected:
                    status = "detected"
                elif len(candles) - 1 >= act + pattern.MAX_COMPLETION_BARS_AFTER_TOUCH:
                    status = "not_detected_window_closed"
                else:
                    status = "window_open"
            records.append({
                "research_only": True, "hypothesis_id": protocol["hypothesis_id"],
                "operation_id": _operation_id(setup), "setup_key": setup.get("key"),
                "pair": setup.get("pair"), "timeframe": timeframe, "direction": setup.get("dir"),
                "entry_at_ms": activation_ms, "pattern_status": status,
                "pattern_detected": bool(detected),
                "pattern_completion_at_ms": detected.get("completion_timestamp") if detected else None,
                "bars_after_touch": detected.get("bars_after_touch") if detected else None,
                "status_original": setup.get("status"),
                "result_r_original": setup.get("result_r") if setup.get("status") in ("ganada", "perdida") else None,
                "observed_at_ms": now_ms, "source": "public_binance_futures_closed_klines",
            })
        except Exception as exc:  # individual records must not stop the observer
            errors.append({"key": setup.get("key"), "error": type(exc).__name__})
    if setups_path.read_bytes() != before:
        raise RuntimeError("setup store changed while observing; refusing snapshot")
    payload = {
        "research_only": True, "execution_enabled": False,
        "notice": "Research only - No signal - No bot",
        "meta": {"generated_at_ms": now_ms, "records": len(records), "errors": errors},
        "protocol": protocol, "summary": _summary(records, protocol), "records": records,
    }
    _atomic(output_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setups", type=Path, default=SETUPS_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--spec", type=Path, default=SPEC_PATH)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()
    while True:
        payload = observe(args.setups, args.output, args.spec)
        print(json.dumps({"generated_at_ms": payload["meta"]["generated_at_ms"],
                          **payload["summary"]}, ensure_ascii=False), flush=True)
        if not args.watch:
            break
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    main()
