"""Build three read-only CoinSignals books from Telegram and public BTC candles."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from research.coinsignals_backtest import KlineCache, parse_history
from research.coinsignals_btc_swing import (
    equal_notional_average,
    has_hold_annotation,
    management_by_signal,
    replay_swing,
)

ROOT = Path(__file__).resolve().parents[2]
HISTORY_PATH = ROOT / "data/telegram/coinsignals_history.json"
INITIAL_EQUITY = 1000.0
RISK_PCT = 0.005
ROUND_TRIP_COST_PCT = 0.14

BOOKS: tuple[tuple[str, str, Callable[[dict[str, Any]], bool]], ...] = (
    ("baseline", "Todas", lambda row: True),
    ("long_only", "Solo long", lambda row: row["direction"] == "long"),
    ("tp1_r_14", "TP1 >= 1.4R", lambda row: row["tp1_r_plan"] >= 1.4),
)


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = sorted(
        (row for row in rows if row["status"] == "resolved"),
        key=lambda row: row.get("resolution_time") or row["date"],
    )
    values = [row["pnl_r_net"] for row in resolved]
    positives = [value for value in values if value > 0]
    negatives = [value for value in values if value < 0]
    equity = INITIAL_EQUITY
    peak = equity
    max_dd = 0.0
    curve = []
    for row in resolved:
        equity += row["pnl_r_net"] * INITIAL_EQUITY * RISK_PCT
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        curve.append({"t": row["resolution_time"], "equity": round(equity, 2)})
    return {
        "signals": len(rows),
        "resolved": len(resolved),
        "open": sum(row["status"] == "open" for row in rows),
        "waiting": sum(row["status"] in {"not_filled", "cancelled"} for row in rows),
        "win_rate_pct": round(100 * len(positives) / len(values), 1) if values else None,
        "avg_r": round(sum(values) / len(values), 4) if values else None,
        "total_r": round(sum(values), 2),
        "profit_factor": round(sum(positives) / -sum(negatives), 3) if negatives else None,
        "equity_usdt": round(equity, 2),
        "pnl_usdt": round(equity - INITIAL_EQUITY, 2),
        "max_drawdown_usdt": round(max_dd, 2),
        "equity_curve": curve,
    }


def build_snapshot(
    history_path: Path = HISTORY_PATH,
    *,
    forward_start: str,
    candles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    history = json.loads(history_path.read_text(encoding="utf-8"))
    messages = {message["id"]: message for message in history["messages"]}
    signals, parse_stats = parse_history(history)
    signals = [
        signal
        for signal in signals
        if signal.symbol == "BTCUSDT"
        and len(signal.targets) == 4
        and (
            not signal.edit_date
            or has_hold_annotation(messages[signal.message_id].get("text") or "")
        )
    ]
    events = management_by_signal(history, signals)
    candles = candles if candles is not None else KlineCache().load("BTCUSDT")
    times = [int(candle["t"]) for candle in candles]
    rows = []
    for signal in signals:
        replay = replay_swing(
            signal,
            candles,
            events.get(signal.message_id, ()),
            entry_mode="channel",
            managed=True,
            stop_policy="be_tp1",
            target_weights_override=(0.25, 0.25, 0.25, 0.25),
            times=times,
        )
        planned_entry = equal_notional_average(
            price for price in (signal.entry_first, signal.entry_second) if price is not None
        )
        risk = abs(planned_entry - signal.stop)
        rows.append(
            {
                "signal_id": signal.message_id,
                "date": signal.date,
                "direction": signal.direction,
                "entry_low": signal.entry_low,
                "entry_high": signal.entry_high,
                "entry_plan_equal_cash": round(planned_entry, 4),
                "entry_confirmed": replay.get("entry_avg"),
                "stop": signal.stop,
                "targets": signal.targets,
                "leverage_published": signal.leverage,
                "tp1_r_plan": round(abs(signal.targets[0] - planned_entry) / risk, 3),
                **replay,
            }
        )

    reference_rows = [row for row in rows if "2024-07-22" <= row["date"] < forward_start]
    forward_rows = [row for row in rows if row["date"] >= forward_start]
    books = []
    for identifier, label, predicate in BOOKS:
        selected = [row for row in forward_rows if predicate(row)]
        books.append(
            {
                "id": identifier,
                "label": label,
                "metrics": _metrics(selected),
                "trades": sorted(selected, key=lambda row: row["date"], reverse=True),
            }
        )
    return {
        "research_only": True,
        "execution_enabled": False,
        "mode": "shadow",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_exported_at": history.get("exported_at"),
        "forward_start": forward_start,
        "account": {"initial_equity_usdt": INITIAL_EQUITY, "risk_pct": RISK_PCT},
        "entry_policy": {
            "confirmed": "average price explicitly published by CoinSignals",
            "planned": "equal USDT per entry; harmonic average",
            "partials": [0.25, 0.25, 0.25, 0.25],
            "after_tp1": "move remaining stop to confirmed average entry",
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        },
        "parse_stats": parse_stats,
        "reference": _metrics(reference_rows),
        "books": books,
    }
