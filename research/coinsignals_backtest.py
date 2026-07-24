#!/usr/bin/env python3
"""Causal parser and market replay for the Vip CoinSignals Telegram export."""

from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY = ROOT / "data/telegram/coinsignals_history.json"
DEFAULT_PARSED = ROOT / "data/telegram/coinsignals_parsed.json"
DEFAULT_RESULTS = ROOT / "data/telegram/coinsignals_backtest.json"
KLINE_DIR = ROOT / "data/telegram/klines"
FUTURES_KLINES = "https://fapi.binance.com/fapi/v1/klines"
INTERVAL = "15m"
STEP_MS = 15 * 60 * 1000
ENTRY_EXPIRY_DAYS = 7
RESOLUTION_DAYS = 30
ROUND_TRIP_COST = 0.0014


NUMBER = r"([0-9][0-9,]*(?:\.[0-9]+)?)"
HEADER_RE = re.compile(r"\b(LONG|SHORT)\s+[#\$]?([A-Z0-9][A-Z0-9/._-]*)", re.I)
ENTRY_RE = re.compile(rf"\bEntry\s*:?[ \t]*{NUMBER}(?:[ \t]*-[ \t]*{NUMBER})?", re.I)
TARGET_RE = re.compile(
    rf"\b(?:Target|Take[ -]?Profit)\s*(\d+)?\s*:[ \t]*{NUMBER}", re.I
)
STOP_RE = re.compile(rf"\bStop\s*loss\s*:[ \t]*{NUMBER}|\bStoploss\s*:[ \t]*{NUMBER}", re.I)
LEVERAGE_RE = re.compile(r"\bLeverage\s*:\s*(\d+(?:\.\d+)?)x", re.I)


@dataclass(frozen=True)
class Signal:
    message_id: int
    date: str
    date_ms: int
    edit_date: str | None
    edit_lag_seconds: float | None
    direction: str
    symbol: str
    asset_class: str
    entry_first: float
    entry_second: float | None
    entry_low: float
    entry_high: float
    stop: float
    targets: tuple[float, ...]
    leverage: float | None
    reply_events: tuple[dict[str, Any], ...]


def _number(value: str) -> float:
    return float(value.replace(",", ""))


def _timestamp_ms(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def normalize_symbol(raw: str) -> tuple[str, str]:
    symbol = raw.upper().replace("/", "").replace("_", "").replace(".", "")
    if symbol in {"GOLD", "XAUUSD", "XAUUSDT"}:
        return symbol, "gold"
    if symbol.endswith("PERP"):
        symbol = symbol[:-4]
    return symbol, "crypto" if symbol.endswith("USDT") else "other"


def classify_reply(text: str) -> tuple[str, int | None] | None:
    low = text.casefold()
    target = re.search(r"take-profit\s+target\s+(\d+)|\btp\s*(\d+)", low)
    if target:
        return "tp", int(target.group(1) or target.group(2))
    if "stop target hit" in low or "stoploss hit" in low or "closed" in low and "loss" in low:
        return "stop", None
    if "entry" in low and ("average entry" in low or "entries achieved" in low):
        return "entry", None
    if "exit @ entry" in low or "break even" in low or "breakeven" in low:
        return "breakeven", None
    if "closed" in low or "close " in low:
        return "close", None
    return None


def parse_signal(message: dict[str, Any], replies: Iterable[dict[str, Any]] = ()) -> Signal | None:
    text = message.get("text") or ""
    header = HEADER_RE.search(text)
    entry = ENTRY_RE.search(text)
    stop_match = STOP_RE.search(text)
    targets = [_number(match.group(2)) for match in TARGET_RE.finditer(text)]
    if not (header and entry and stop_match and targets):
        return None

    direction = header.group(1).lower()
    symbol, asset_class = normalize_symbol(header.group(2))
    first = _number(entry.group(1))
    second = _number(entry.group(2)) if entry.group(2) else None
    stop_value = next(group for group in stop_match.groups() if group is not None)
    stop = _number(stop_value)
    low, high = sorted((first, second if second is not None else first))
    reference = first
    if reference <= 0 or stop <= 0 or any(target <= 0 for target in targets):
        return None
    if direction == "long" and not (stop < reference and all(t > reference for t in targets)):
        return None
    if direction == "short" and not (stop > reference and all(t < reference for t in targets)):
        return None

    date = message["date"]
    edit_date = message.get("edit_date")
    edit_lag = None
    if edit_date:
        edit_lag = (
            datetime.fromisoformat(edit_date) - datetime.fromisoformat(date)
        ).total_seconds()
    leverage_match = LEVERAGE_RE.search(text)
    events = []
    for reply in sorted(replies, key=lambda row: row["date"]):
        classified = classify_reply(reply.get("text") or "")
        if classified:
            kind, target_number = classified
            events.append(
                {
                    "message_id": reply["id"],
                    "date": reply["date"],
                    "kind": kind,
                    "target_number": target_number,
                }
            )

    return Signal(
        message_id=message["id"],
        date=date,
        date_ms=_timestamp_ms(date),
        edit_date=edit_date,
        edit_lag_seconds=edit_lag,
        direction=direction,
        symbol=symbol,
        asset_class=asset_class,
        entry_first=first,
        entry_second=second,
        entry_low=low,
        entry_high=high,
        stop=stop,
        targets=tuple(targets),
        leverage=float(leverage_match.group(1)) if leverage_match else None,
        reply_events=tuple(events),
    )


def parse_history(payload: dict[str, Any]) -> tuple[list[Signal], dict[str, int]]:
    messages = payload["messages"]
    replies_by_parent: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for message in messages:
        parent = message.get("reply_to_msg_id")
        if parent is not None:
            replies_by_parent[int(parent)].append(message)

    signals = []
    stats = Counter()
    for message in messages:
        text = message.get("text") or ""
        if not HEADER_RE.search(text) or not ENTRY_RE.search(text):
            continue
        stats["candidates"] += 1
        signal = parse_signal(message, replies_by_parent.get(message["id"], ()))
        if signal is None:
            stats["rejected_invalid"] += 1
            continue
        signals.append(signal)
        stats["parsed"] += 1
        stats[f"asset_{signal.asset_class}"] += 1
        if signal.edit_date:
            stats["edited"] += 1
    return signals, dict(stats)


def _ceil_next_bar(timestamp_ms: int) -> int:
    return ((timestamp_ms // STEP_MS) + 1) * STEP_MS


def _touch(candle: dict[str, float], price: float) -> bool:
    return candle["l"] <= price <= candle["h"]


def replay_signal(
    signal: Signal,
    candles: list[dict[str, Any]],
    times: Optional[list[int]] = None,
    entry_price: Optional[float] = None,
) -> dict[str, Any]:
    """Replay entry #1 and targets. Same-bar ambiguity always favors the stop."""
    if not candles:
        return {"status": "no_data"}
    times = times if times is not None else [int(c["t"]) for c in candles]
    entry_price = signal.entry_first if entry_price is None else entry_price
    start_ms = _ceil_next_bar(signal.date_ms)
    start = bisect.bisect_left(times, start_ms)
    expiry = signal.date_ms + ENTRY_EXPIRY_DAYS * 86_400_000
    fill_idx = None
    for idx in range(start, len(candles)):
        candle = candles[idx]
        if candle["t"] > expiry:
            break
        if _touch(candle, entry_price):
            fill_idx = idx
            break
    if fill_idx is None:
        return {"status": "not_filled"}

    long = signal.direction == "long"
    risk = entry_price - signal.stop if long else signal.stop - entry_price
    risk_pct = risk / entry_price
    target_rs = [abs(target - entry_price) / risk for target in signal.targets]
    deadline = candles[fill_idx]["t"] + RESOLUTION_DAYS * 86_400_000
    hit = 0
    stop_idx = None
    resolution_idx = None
    for idx in range(fill_idx, len(candles)):
        candle = candles[idx]
        if candle["t"] > deadline:
            break
        stop_touched = candle["l"] <= signal.stop if long else candle["h"] >= signal.stop
        if stop_touched:
            stop_idx = idx
            resolution_idx = idx
            break
        if idx == fill_idx:
            continue
        while hit < len(signal.targets):
            target = signal.targets[hit]
            target_touched = candle["h"] >= target if long else candle["l"] <= target
            if not target_touched:
                break
            hit += 1
            resolution_idx = idx
        if hit == len(signal.targets):
            break

    unresolved = stop_idx is None and hit < len(signal.targets)
    n_targets = len(signal.targets)
    equal_partial_gross = sum(target_rs[:hit]) / n_targets
    if hit < n_targets:
        equal_partial_gross += (-1.0 if stop_idx is not None else 0.0) * (n_targets - hit) / n_targets
    be_partial_gross = sum(target_rs[:hit]) / n_targets
    if hit == 0 and stop_idx is not None:
        be_partial_gross = -1.0
    cost_r = ROUND_TRIP_COST / risk_pct
    official_tp = max(
        (event["target_number"] or 0 for event in signal.reply_events if event["kind"] == "tp"),
        default=0,
    )
    official_stop = any(event["kind"] == "stop" for event in signal.reply_events)
    return {
        "status": "unresolved" if unresolved else "resolved",
        "entry_price": entry_price,
        "fill_time": datetime.fromtimestamp(candles[fill_idx]["t"] / 1000, timezone.utc).isoformat(),
        "resolution_time": (
            datetime.fromtimestamp(candles[resolution_idx]["t"] / 1000, timezone.utc).isoformat()
            if resolution_idx is not None
            else None
        ),
        "targets_hit": hit,
        "stopped": stop_idx is not None,
        "tp1_win": hit >= 1,
        "risk_pct": round(risk_pct, 6),
        "tp1_r_gross": round(target_rs[0] if hit >= 1 else (-1.0 if stop_idx is not None else 0.0), 4),
        "tp1_r_net": round((target_rs[0] if hit >= 1 else (-1.0 if stop_idx is not None else 0.0)) - cost_r, 4),
        "equal_partial_r_net": round(equal_partial_gross - cost_r, 4),
        "be_after_tp1_r_net": round(be_partial_gross - cost_r, 4),
        "official_max_tp": official_tp,
        "official_stop": official_stop,
    }


class KlineCache:
    def __init__(self, directory: Path = KLINE_DIR):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def path(self, symbol: str) -> Path:
        return self.directory / f"{symbol}_{INTERVAL}.json"

    def load(self, symbol: str) -> list[dict[str, Any]]:
        path = self.path(symbol)
        return json.loads(path.read_text()) if path.exists() else []

    def fetch(self, symbol: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        cached = self.load(symbol)
        by_time = {int(c["t"]): c for c in cached}
        cursor = min(start_ms, min(by_time) if by_time else start_ms)
        if by_time and max(by_time) >= end_ms and min(by_time) <= start_ms:
            return [by_time[t] for t in sorted(by_time)]
        if by_time and min(by_time) <= start_ms:
            cursor = max(by_time) + STEP_MS
        failures = 0
        while cursor <= end_ms:
            query = urllib.parse.urlencode(
                {"symbol": symbol, "interval": INTERVAL, "startTime": cursor, "endTime": end_ms, "limit": 1000}
            )
            request = urllib.request.Request(
                f"{FUTURES_KLINES}?{query}", headers={"User-Agent": "nexux-coinsignals-research"}
            )
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    rows = json.load(response)
            except urllib.error.HTTPError as exc:
                if 400 <= exc.code < 500 and exc.code != 429:
                    break
                failures += 1
                if failures >= 4:
                    break
                time.sleep(failures * 1.5)
                continue
            except (urllib.error.URLError, TimeoutError):
                failures += 1
                if failures >= 4:
                    break
                time.sleep(failures * 1.5)
                continue
            failures = 0
            if not rows:
                break
            for row in rows:
                timestamp = int(row[0])
                by_time[timestamp] = {
                    "t": timestamp,
                    "o": float(row[1]),
                    "h": float(row[2]),
                    "l": float(row[3]),
                    "c": float(row[4]),
                    "v": float(row[5]),
                }
            last = int(rows[-1][0])
            if last < cursor:
                break
            cursor = last + STEP_MS
            if len(rows) < 1000:
                break
            time.sleep(0.08)
        candles = [by_time[t] for t in sorted(by_time)]
        temp = self.path(symbol).with_suffix(".tmp")
        temp.write_text(json.dumps(candles), encoding="utf-8")
        os.chmod(temp, 0o600)
        temp.replace(self.path(symbol))
        return candles


def aggregate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [row[key] for row in rows if row.get("status") == "resolved"]
    wins = [row for row in rows if row.get("status") == "resolved" and row.get("tp1_win")]
    return {
        "n": len(values),
        "wr_tp1_pct": round(100 * len(wins) / len(values), 2) if values else None,
        "avg_r": round(sum(values) / len(values), 4) if values else None,
        "total_r": round(sum(values), 2),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    history = json.loads(args.history.read_text())
    signals, parse_stats = parse_history(history)
    args.parsed.parent.mkdir(parents=True, exist_ok=True)
    args.parsed.write_text(
        json.dumps({"stats": parse_stats, "signals": [asdict(s) for s in signals]}, ensure_ascii=False, indent=2)
    )
    os.chmod(args.parsed, 0o600)

    crypto = [s for s in signals if s.asset_class == "crypto"]
    if args.symbols:
        selected = {symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()}
        crypto = [signal for signal in crypto if signal.symbol in selected]
    by_symbol: dict[str, list[Signal]] = defaultdict(list)
    for signal in crypto:
        by_symbol[signal.symbol].append(signal)
    cache = KlineCache()
    rows = []
    unavailable = []
    now_ms = int(time.time() * 1000)
    for number, (symbol, symbol_signals) in enumerate(sorted(by_symbol.items()), 1):
        start = min(s.date_ms for s in symbol_signals)
        end = min(now_ms, max(s.date_ms for s in symbol_signals) + RESOLUTION_DAYS * 86_400_000)
        candles = cache.load(symbol) if args.offline else cache.fetch(symbol, start, end)
        if not candles:
            unavailable.append(symbol)
            print(f"[{number}/{len(by_symbol)}] {symbol}: no data", flush=True)
            continue
        times = [int(c["t"]) for c in candles]
        for signal in symbol_signals:
            entry_price = (
                (signal.entry_low + signal.entry_high) / 2
                if args.entry_mode == "midpoint"
                else signal.entry_first
            )
            replay = replay_signal(signal, candles, times, entry_price)
            rows.append(
                {
                    "message_id": signal.message_id,
                    "date": signal.date,
                    "year": signal.date[:4],
                    "symbol": signal.symbol,
                    "direction": signal.direction,
                    "edited": signal.edit_date is not None,
                    "edit_lag_seconds": signal.edit_lag_seconds,
                    **replay,
                }
            )
        print(f"[{number}/{len(by_symbol)}] {symbol}: {len(symbol_signals)} signals", flush=True)

    resolved = [row for row in rows if row.get("status") == "resolved"]
    unedited = [row for row in resolved if not row["edited"]]
    output = {
        "research_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "timeframe": INTERVAL,
            "entry": (
                f"entry_{args.entry_mode}, only bars strictly after publication, "
                "expires after 7 days"
            ),
            "intrabar": "stop wins ambiguity; TP is not credited on the fill candle",
            "horizon_days": RESOLUTION_DAYS,
            "round_trip_cost_fraction": ROUND_TRIP_COST,
        },
        "parse_stats": parse_stats,
        "unavailable_symbols": unavailable,
        "counts": Counter(row.get("status") for row in rows),
        "metrics": {
            "tp1_all": aggregate(resolved, "tp1_r_net"),
            "tp1_unedited": aggregate(unedited, "tp1_r_net"),
            "equal_partials_all": aggregate(resolved, "equal_partial_r_net"),
            "equal_partials_unedited": aggregate(unedited, "equal_partial_r_net"),
            "be_after_tp1_all": aggregate(resolved, "be_after_tp1_r_net"),
            "be_after_tp1_unedited": aggregate(unedited, "be_after_tp1_r_net"),
        },
        "rows": rows,
    }
    args.results.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=dict))
    os.chmod(args.results, 0o600)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--parsed", type=Path, default=DEFAULT_PARSED)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--symbols", help="Comma-separated symbols for a scoped replay")
    parser.add_argument("--entry-mode", choices=("first", "midpoint"), default="first")
    parser.add_argument("--offline", action="store_true", help="Use only cached klines; do not access Binance")
    return parser.parse_args()


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps(result["metrics"], indent=2))
