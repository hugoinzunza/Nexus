#!/usr/bin/env python3
"""Detailed causal BTC swing replay for the Vip CoinSignals export."""

from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.coinsignals_backtest import (  # noqa: E402
    KlineCache,
    ROUND_TRIP_COST,
    STEP_MS,
    Signal,
    parse_history,
)


DEFAULT_HISTORY = ROOT / "data/telegram/coinsignals_history.json"
DEFAULT_PARSED = ROOT / "data/telegram/coinsignals_parsed.json"
DEFAULT_RESULTS = ROOT / "data/telegram/coinsignals_btc_swing_2y.json"
START_DATE = "2024-07-22T00:00:00+00:00"
END_DATE = "2026-07-22T23:59:59+00:00"
GLOBAL_EVENT_LOOKBACK_DAYS = 120

PRICE_RE = re.compile(r"\$?([0-9][0-9,.]*(?:\.\d+)?\s*[kK]?)")
SL_UPDATE_RE = re.compile(
    r"(?:temp(?:orarily)?\s+sl\s+update|sl\s+(?:temporarily\s+)?(?:change|moved|update))"
    r"\s*(?::|to)?\s*\$?([0-9][0-9,.]*(?:\.\d+)?\s*[kK]?)",
    re.I,
)


def timestamp_ms(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def next_bar(timestamp: int) -> int:
    return ((timestamp // STEP_MS) + 1) * STEP_MS


def parse_price(value: str) -> float:
    cleaned = value.replace(",", "").replace(" ", "")
    multiplier = 1000 if cleaned.lower().endswith("k") else 1
    if multiplier != 1:
        cleaned = cleaned[:-1]
    return float(cleaned) * multiplier


def has_hold_annotation(text: str) -> bool:
    return bool(re.search(r"/\s*hold\b", text, re.I))


def parse_management(text: str) -> Optional[dict[str, Any]]:
    """Return only actionable management; narrative status text is ignored."""
    compact = " ".join(text.split())
    low = compact.casefold()
    average_match = re.search(r"average entry price\s*:\s*\$?([0-9][0-9,.]*)", compact, re.I)
    if average_match and ("all entry" in low or "all entries" in low):
        return {"kind": "entry_all_confirmed", "price": parse_price(average_match.group(1))}
    if average_match and "entry 1" in low:
        return {"kind": "entry_first_confirmed", "price": parse_price(average_match.group(1))}
    sl_match = SL_UPDATE_RE.search(compact)
    if sl_match:
        return {"kind": "sl_update", "price": parse_price(sl_match.group(1))}
    if "stop" in low or " sl" in low:
        if "daily candle" in low and ("close" in low or "closes" in low):
            return {"kind": "stop_confirmation", "timeframe": "1d"}
        if ("full 4-hour candle" in low or "full 4hr candle" in low) and (
            "close" in low or "closes" in low
        ):
            return {"kind": "stop_confirmation", "timeframe": "4h"}
    if "stop target hit" in low or "closed at stoploss" in low:
        return None
    if (
        "back to entry" in low
        or "close #btc at entry" in low
        or "closed at entry" in low
        or "close at entry" in low
        or "closed near entry" in low
    ):
        return {"kind": "close_be"}
    if "closed due to opposite direction" in low:
        return {"kind": "close_market"}
    if re.search(r"\bclose\s+#?btc\b.*\b(?:in|tiny|small)\s+profit\b", low):
        return {"kind": "close_market"}
    if re.search(r"\b(?:manually\s+)?cancel(?:led)?\b", low):
        return {"kind": "cancel"}
    return None


def parse_global_management(text: str) -> Optional[dict[str, Any]]:
    """Parse strict BTC portfolio instructions that are not replies to a signal."""
    compact = " ".join(text.split())
    low = compact.casefold()
    if "btc" not in low and "shorts closed" not in low and "longs closed" not in low:
        return None
    if ("stop" in low or " sl" in low) and ("close" in low or "closes" in low):
        if "daily candle" in low and ("swing long" in low or "below" in low):
            return {"kind": "stop_confirmation", "timeframe": "1d", "direction": "long"}
        if "full 4hr candle" in low or "full 4-hour candle" in low:
            direction = "short" if "above" in low and "below" not in low else "long"
            return {"kind": "stop_confirmation", "timeframe": "4h", "direction": direction}
    if (
        "close near entry" in low
        or "back to entry" in low
        or "closed near entry" in low
        or re.search(r"closed\s+btc\s+long\s+@\s*entry", low)
    ):
        # La dirección se conserva si el propio texto la nombra. Antes esta rama
        # se evaluaba antes que las direccionales y devolvía siempre None, así que
        # "Shorts closed near entry point" cerraba también los LONG a break-even
        # (21 vínculos con dirección contraria al texto en el export real).
        if "short" in low and "long" not in low:
            return {"kind": "close_be", "direction": "short"}
        if "long" in low and "short" not in low:
            return {"kind": "close_be", "direction": "long"}
        return {"kind": "close_be", "direction": None}
    if "close all shorts" in low or "closed all short positions" in low or "shorts closed" in low:
        return {"kind": "close_market", "direction": "short"}
    if "longs closed" in low:
        return {"kind": "close_market", "direction": "long"}
    if re.search(r"close\s+(?:#?btc|#?btc\s*&)", low) and "profit" in low:
        return {"kind": "close_market", "direction": None}
    if "btc" in low and "closed in profit" in low:
        return {"kind": "close_market", "direction": None}
    if "btc" in low and "closed in buy zone" in low:
        return {"kind": "close_market", "direction": "long"}
    if "btc" in low and "close short positions" in low:
        return {"kind": "close_market", "direction": "short"}
    return None


def management_by_signal(
    history: dict[str, Any], signals: Iterable[Signal], *, include_global: bool = True
) -> dict[int, list[dict[str, Any]]]:
    """Eventos de gestión por señal.

    `include_global=False` deja SOLO los que responden explícitamente a la señal
    (`reply_to_msg_id`). El camino global adjunta un mensaje a todas las señales
    de los últimos 120 días: en el export real son 24 mensajes generando 363
    vínculos, con sesgo sistemático al alza. Para métricas forward, la atribución
    heurística no debe contar (auditoría 2026-07-24).
    """
    signal_ids = {signal.message_id for signal in signals}
    events: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for message in history["messages"]:
        parent = message.get("reply_to_msg_id")
        if parent not in signal_ids:
            continue
        parsed = parse_management(message.get("text") or "")
        if parsed is None:
            continue
        events[parent].append(
            {
                "message_id": message["id"],
                "date": message["date"],
                "effective_ms": next_bar(timestamp_ms(message["date"])),
                # Atribución causal: este evento responde explícitamente a ESTA
                # señal. Ver `global` más abajo para el caso heurístico.
                "attribution": "reply",
                "edited": message.get("edit_date") is not None,
                **parsed,
            }
        )
    max_age_ms = GLOBAL_EVENT_LOOKBACK_DAYS * 86_400_000
    for message in history["messages"] if include_global else []:
        if message.get("reply_to_msg_id") is not None or message["id"] in signal_ids:
            continue
        parsed = parse_global_management(message.get("text") or "")
        if parsed is None:
            continue
        event_ms = timestamp_ms(message["date"])
        direction = parsed.pop("direction")
        for signal in signals:
            age = event_ms - signal.date_ms
            if age <= 0 or age > max_age_ms:
                continue
            if direction is not None and signal.direction != direction:
                continue
            events[signal.message_id].append(
                {
                    "message_id": message["id"],
                    "date": message["date"],
                    "effective_ms": next_bar(event_ms),
                    "source": "global",
                    # Atribución HEURÍSTICA: el mensaje no responde a esta señal;
                    # se le adjunta por proximidad temporal. En el export real,
                    # 24 mensajes generan 363 vínculos (uno llega a 43 señales) y
                    # el sesgo va siempre al alza porque close_be rescata a BE
                    # posiciones perdedoras. No debe alimentar la métrica primaria.
                    "attribution": "global",
                    "edited": message.get("edit_date") is not None,
                    **parsed,
                }
            )
    for signal_events in events.values():
        signal_events.sort(key=lambda event: event["effective_ms"])
    return events


def equal_notional_average(prices: Iterable[float]) -> float:
    """Average entry when the same quote amount is allocated at every price."""
    values = tuple(float(price) for price in prices)
    if not values or any(price <= 0 for price in values):
        raise ValueError("entry prices must be positive")
    return len(values) / sum(1 / price for price in values)


def entry_tranches(signal: Signal, mode: str) -> list[tuple[float, float]]:
    if mode == "first":
        return [(signal.entry_first, 1.0)]
    if mode == "midpoint":
        return [((signal.entry_low + signal.entry_high) / 2, 1.0)]
    if signal.entry_low == signal.entry_high:
        return [(signal.entry_first, 1.0)]
    prices = (signal.entry_first, signal.entry_second)
    quantities = tuple(1 / price for price in prices)
    total_quantity = sum(quantities)
    return [
        (price, quantity / total_quantity)
        for price, quantity in zip(prices, quantities)
    ]


def touched(candle: dict[str, Any], price: float) -> bool:
    return candle["l"] <= price <= candle["h"]


def replay_swing(
    signal: Signal,
    candles: list[dict[str, Any]],
    events: Iterable[dict[str, Any]] = (),
    *,
    entry_mode: str = "ladder",
    managed: bool = True,
    exit_mode: str = "partials",
    target_profile: str = "equal",
    be_after_tp1: bool = False,
    be_same_bar_conservative: bool = False,
    stop_policy: Optional[str] = None,
    target_weights_override: Optional[tuple[float, ...]] = None,
    times: Optional[list[int]] = None,
) -> dict[str, Any]:
    """Replay until all targets, current SL, an explicit close, or the data end."""
    times = times if times is not None else [int(candle["t"]) for candle in candles]
    start = bisect.bisect_left(times, next_bar(signal.date_ms))
    tranches = [
        {"price": price, "weight": weight, "filled": False}
        for price, weight in entry_tranches(signal, entry_mode)
    ]
    planned_risk = sum(
        tranche["weight"] * abs(tranche["price"] - signal.stop) for tranche in tranches
    )
    if planned_risk <= 0:
        return {"status": "invalid"}

    actionable = list(events) if managed or entry_mode == "channel" else []
    event_idx = 0
    current_stop = signal.stop
    filled_qty = 0.0
    entry_value = 0.0
    remaining_qty = 0.0
    base_qty: Optional[float] = None
    targets_hit = 0
    realized_quote = 0.0
    fill_time = None
    resolution_time = None
    exit_reason = None
    pending_cancelled = False
    management_used: list[dict[str, Any]] = []
    ambiguous_events = 0
    ambiguous_intrabar_exit = False
    stop_confirmation_ms: Optional[int] = None
    auto_be_active = False
    locked_profit_active = False
    direction = 1 if signal.direction == "long" else -1
    if target_weights_override is not None:
        if len(target_weights_override) != len(signal.targets):
            raise ValueError("target_weights_override must match target count")
        if any(weight < 0 for weight in target_weights_override):
            raise ValueError("target weights cannot be negative")
        total_weight = sum(target_weights_override)
        if total_weight <= 0:
            raise ValueError("target weights must have positive total")
        target_weights = tuple(weight / total_weight for weight in target_weights_override)
    elif target_profile == "frontloaded" and len(signal.targets) == 4:
        target_weights = (0.4, 0.3, 0.2, 0.1)
    elif target_profile == "runner" and len(signal.targets) == 4:
        target_weights = (0.1, 0.2, 0.3, 0.4)
    else:
        target_weights = tuple(1 / len(signal.targets) for _ in signal.targets)
    effective_stop_policy = stop_policy or ("be_tp1" if be_after_tp1 else "original")
    if effective_stop_policy not in {
        "original",
        "be_tp1",
        "be_tp2",
        "step",
        "lock_tp1_after_tp2",
    }:
        raise ValueError(f"unknown stop policy: {effective_stop_policy}")

    def average_entry() -> float:
        return entry_value / filled_qty

    def close_quantity(quantity: float, price: float) -> None:
        nonlocal realized_quote, remaining_qty
        realized_quote += quantity * direction * (price - average_entry())
        remaining_qty -= quantity

    for candle in candles[start:]:
        filled_this_bar = False
        while event_idx < len(actionable) and actionable[event_idx]["effective_ms"] <= candle["t"]:
            event = actionable[event_idx]
            event_idx += 1
            if event["kind"] in {"entry_first_confirmed", "entry_all_confirmed"}:
                if entry_mode != "channel" or pending_cancelled or targets_hit > 0:
                    continue
                if event["kind"] == "entry_first_confirmed" and filled_qty == 0:
                    quantity = tranches[0]["weight"]
                    filled_qty = quantity
                    remaining_qty = quantity
                    entry_value = event["price"] * quantity
                    fill_time = candle["t"]
                    filled_this_bar = True
                elif event["kind"] == "entry_all_confirmed":
                    filled_qty = 1.0
                    remaining_qty = 1.0
                    entry_value = event["price"]
                    fill_time = fill_time or candle["t"]
                    filled_this_bar = True
                continue
            if event["kind"] == "ambiguous_4h_stop":
                ambiguous_events += 1
                continue
            if event["kind"] == "stop_confirmation":
                stop_confirmation_ms = 4 * 60 * 60 * 1000 if event["timeframe"] == "4h" else 86_400_000
                management_used.append(event)
                continue
            if event["kind"] == "sl_update":
                current_stop = event["price"]
                auto_be_active = False
                locked_profit_active = False
                management_used.append(event)
                continue
            if event["kind"] == "cancel" and filled_qty == 0:
                exit_reason = "cancelled_before_fill"
                resolution_time = candle["t"]
                management_used.append(event)
                break
            if event["kind"] in {"close_be", "close_market"}:
                management_used.append(event)
                pending_cancelled = True
                if remaining_qty > 0:
                    price = average_entry() if event["kind"] == "close_be" else candle["o"]
                    close_quantity(remaining_qty, price)
                    exit_reason = event["kind"]
                    resolution_time = candle["t"]
                else:
                    exit_reason = "cancelled_before_fill"
                    resolution_time = candle["t"]
                break
        if exit_reason is not None:
            break

        if entry_mode != "channel" and not pending_cancelled and targets_hit == 0:
            for tranche in tranches:
                if not tranche["filled"] and touched(candle, tranche["price"]):
                    tranche["filled"] = True
                    filled_qty += tranche["weight"]
                    remaining_qty += tranche["weight"]
                    entry_value += tranche["price"] * tranche["weight"]
                    fill_time = fill_time or candle["t"]
                    filled_this_bar = True

        if remaining_qty <= 0:
            continue

        if stop_confirmation_ms is None:
            stop_touched = (
                candle["l"] <= current_stop
                if signal.direction == "long"
                else candle["h"] >= current_stop
            )
            stop_exit_price = current_stop
        else:
            confirmation_bar = (candle["t"] + STEP_MS) % stop_confirmation_ms == 0
            stop_touched = confirmation_bar and (
                candle["c"] <= current_stop
                if signal.direction == "long"
                else candle["c"] >= current_stop
            )
            stop_exit_price = candle["c"]
        if stop_touched:
            if targets_hit < len(signal.targets):
                next_target = signal.targets[targets_hit]
                ambiguous_intrabar_exit = (
                    candle["h"] >= next_target
                    if signal.direction == "long"
                    else candle["l"] <= next_target
                )
            close_quantity(remaining_qty, stop_exit_price)
            if auto_be_active:
                exit_reason = "break_even"
            elif locked_profit_active:
                exit_reason = "locked_profit"
            else:
                exit_reason = "stop" if stop_confirmation_ms is None else "stop_on_close"
            resolution_time = candle["t"]
            break
        if filled_this_bar:
            continue

        while targets_hit < len(signal.targets):
            target = signal.targets[targets_hit]
            target_touched = (
                candle["h"] >= target
                if signal.direction == "long"
                else candle["l"] <= target
            )
            if not target_touched:
                break
            if base_qty is None:
                base_qty = filled_qty
                pending_cancelled = True
            targets_hit += 1
            quantity = remaining_qty if exit_mode == "tp1_full" else min(
                remaining_qty, base_qty * target_weights[targets_hit - 1]
            )
            close_quantity(quantity, target)
            resolution_time = candle["t"]
            protective_stop = None
            if effective_stop_policy == "be_tp1" and targets_hit == 1:
                protective_stop = average_entry()
            elif effective_stop_policy == "be_tp2" and targets_hit == 2:
                protective_stop = average_entry()
            elif effective_stop_policy == "step":
                if targets_hit == 1:
                    protective_stop = average_entry()
                elif targets_hit >= 2:
                    protective_stop = signal.targets[targets_hit - 2]
            elif effective_stop_policy == "lock_tp1_after_tp2" and targets_hit == 2:
                protective_stop = signal.targets[0]
            if protective_stop is not None and remaining_qty > 1e-12:
                current_stop = protective_stop
                stop_confirmation_ms = None
                auto_be_active = abs(current_stop - average_entry()) < 1e-9
                locked_profit_active = not auto_be_active
                returned_to_entry = (
                    candle["l"] <= current_stop
                    if signal.direction == "long"
                    else candle["h"] >= current_stop
                )
                if be_same_bar_conservative and returned_to_entry:
                    close_quantity(remaining_qty, current_stop)
                    exit_reason = (
                        "break_even_same_bar" if auto_be_active else "locked_profit_same_bar"
                    )
                    break
            if exit_mode == "tp1_full":
                exit_reason = "tp1"
                break
        if exit_reason is not None:
            break
        if remaining_qty <= 1e-12:
            remaining_qty = 0.0
            exit_reason = "all_targets"
            break

    if filled_qty == 0:
        status = "cancelled" if exit_reason == "cancelled_before_fill" else "not_filled"
        return {
            "status": status,
            "exit_reason": exit_reason,
            "targets_hit": 0,
            "management_used": management_used,
            "ambiguous_events": ambiguous_events,
        }
    if exit_reason is None:
        return {
            "status": "open",
            "entry_avg": round(average_entry(), 4),
            "filled_fraction": filled_qty,
            "remaining_fraction": remaining_qty,
            "targets_hit": targets_hit,
            "current_stop": current_stop,
            "fill_time": datetime.fromtimestamp(fill_time / 1000, timezone.utc).isoformat(),
            "management_used": management_used,
            "ambiguous_events": ambiguous_events,
        }

    cost_quote = ROUND_TRIP_COST * average_entry() * filled_qty
    pnl_r_gross = realized_quote / planned_risk
    pnl_r_net = (realized_quote - cost_quote) / planned_risk
    return {
        "status": "resolved",
        "exit_reason": exit_reason,
        "entry_avg": round(average_entry(), 4),
        "filled_fraction": filled_qty,
        "targets_hit": targets_hit,
        "current_stop": current_stop,
        "pnl_r_gross": round(pnl_r_gross, 4),
        "pnl_r_net": round(pnl_r_net, 4),
        "fill_time": datetime.fromtimestamp(fill_time / 1000, timezone.utc).isoformat(),
        "resolution_time": datetime.fromtimestamp(
            resolution_time / 1000, timezone.utc
        ).isoformat(),
        "duration_days": round((resolution_time - fill_time) / 86_400_000, 2),
        "management_used": management_used,
        "ambiguous_events": ambiguous_events,
        "ambiguous_intrabar_exit": ambiguous_intrabar_exit,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [row for row in rows if row["status"] == "resolved"]
    values = [row["pnl_r_net"] for row in resolved]
    positives = [value for value in values if value > 0]
    negatives = [value for value in values if value < 0]
    return {
        "signals": len(rows),
        "statuses": dict(Counter(row["status"] for row in rows)),
        "resolved": len(resolved),
        "win_rate_pct": round(100 * len(positives) / len(values), 2) if values else None,
        "avg_r_net": round(sum(values) / len(values), 4) if values else None,
        "total_r_net": round(sum(values), 2),
        "profit_factor": round(sum(positives) / -sum(negatives), 3) if negatives else None,
        "tp_distribution": dict(Counter(row["targets_hit"] for row in resolved)),
        "exit_reasons": dict(Counter(row["exit_reason"] for row in resolved)),
        "ambiguous_intrabar_exits": sum(
            bool(row.get("ambiguous_intrabar_exit")) for row in resolved
        ),
        "median_duration_days": (
            round(sorted(row["duration_days"] for row in resolved)[len(resolved) // 2], 2)
            if resolved
            else None
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    history = json.loads(args.history.read_text())
    messages_by_id = {message["id"]: message for message in history["messages"]}
    signals, parse_stats = parse_history(history)
    start_ms = timestamp_ms(args.start)
    end_ms = timestamp_ms(args.end)
    btc = [
        signal
        for signal in signals
        if signal.symbol == "BTCUSDT" and start_ms <= signal.date_ms <= end_ms
    ]
    events = management_by_signal(history, btc)
    candles = KlineCache().load("BTCUSDT")
    candle_times = [int(candle["t"]) for candle in candles]
    variants = {}
    configurations = (
        ("ladder_original", "ladder", False, "partials", "equal", False, False),
        ("ladder_managed", "ladder", True, "partials", "equal", False, False),
        ("first_managed", "first", True, "partials", "equal", False, False),
        ("midpoint_managed", "midpoint", True, "partials", "equal", False, False),
        ("channel_entries_managed", "channel", True, "partials", "equal", False, False),
        ("channel_entries_tp1_25_be", "channel", True, "partials", "equal", True, False),
        ("channel_entries_tp1_25_be_samebar", "channel", True, "partials", "equal", True, True),
        ("channel_entries_frontloaded", "channel", True, "partials", "frontloaded", False, False),
        ("channel_entries_runner", "channel", True, "partials", "runner", False, False),
        ("tp1_full_managed", "ladder", True, "tp1_full", "equal", False, False),
    )
    for (
        name,
        entry_mode,
        managed,
        exit_mode,
        target_profile,
        be_after_tp1,
        be_same_bar_conservative,
    ) in configurations:
        rows = []
        for signal in btc:
            hold_annotation_edit = bool(signal.edit_date) and has_hold_annotation(
                messages_by_id[signal.message_id].get("text") or ""
            )
            replay = replay_swing(
                signal,
                candles,
                events.get(signal.message_id, ()),
                entry_mode=entry_mode,
                managed=managed,
                exit_mode=exit_mode,
                target_profile=target_profile,
                be_after_tp1=be_after_tp1,
                be_same_bar_conservative=be_same_bar_conservative,
                times=candle_times,
            )
            rows.append(
                {
                    "message_id": signal.message_id,
                    "date": signal.date,
                    "direction": signal.direction,
                    "edited": signal.edit_date is not None,
                    "hold_annotation_edit": hold_annotation_edit,
                    "edit_lag_seconds": signal.edit_lag_seconds,
                    "leverage": signal.leverage,
                    **replay,
                }
            )
        variants[name] = {
            "all": summarize(rows),
            "unedited": summarize([row for row in rows if not row["edited"]]),
            "reconstructible": summarize(
                [
                    row
                    for row in rows
                    if not row["edited"] or row["hold_annotation_edit"]
                ]
            ),
            "rows": rows,
        }
    output = {
        "research_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": args.start, "end": args.end},
        "method": {
            "timeframe": "15m",
            "entry": "no expiry; ladder is equal 50/50 at both published endpoints",
            "targets": "equal fractions; hold until all targets, active SL, explicit close, or data end",
            "management": "explicit close-at-entry, close-in-profit/opposite, and numeric SL updates",
            "intrabar": "stop first; no target credit on an entry candle",
            "round_trip_cost_fraction": ROUND_TRIP_COST,
        },
        "parse_stats": parse_stats,
        "signal_count": len(btc),
        "management_event_counts": dict(
            Counter(event["kind"] for signal_events in events.values() for event in signal_events)
        ),
        "variants": variants,
    }
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(args.results, 0o600)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--start", default=START_DATE)
    parser.add_argument("--end", default=END_DATE)
    return parser.parse_args()


if __name__ == "__main__":
    result = run(parse_args())
    print(
        json.dumps(
            {
                name: {
                    "all": variant["all"],
                    "unedited": variant["unedited"],
                    "reconstructible": variant["reconstructible"],
                }
                for name, variant in result["variants"].items()
            },
            indent=2,
        )
    )
