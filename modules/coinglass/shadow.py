"""Forward-only virtual evaluator for CoinGlass visual context."""
from __future__ import annotations

from datetime import datetime
from typing import Any

ENTRY_THRESHOLD = 25
MAX_HOLD_SECONDS = 4 * 60 * 60
ROUND_TRIP_COST_PCT = 0.08


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def shadow_plan(indicator: dict[str, Any]) -> dict[str, Any]:
    score = indicator.get("score")
    levels = indicator.get("levels") or {}
    base = {
        "research_only": True,
        "execution_enabled": False,
        "strategy": "visual_context_v0",
        "entry_threshold": ENTRY_THRESHOLD,
    }
    if score is None:
        return {**base, "action": "observe", "reason": "sin indice visual"}
    if score >= ENTRY_THRESHOLD:
        direction = "long"
        target = levels.get("nearest_above")
        stop = levels.get("nearest_below")
    elif score <= -ENTRY_THRESHOLD:
        direction = "short"
        target = levels.get("nearest_below")
        stop = levels.get("nearest_above")
    else:
        return {**base, "action": "observe", "reason": "indice bajo umbral"}
    if not target or not stop:
        return {**base, "action": "observe", "reason": "faltan niveles opuestos"}

    entry = float(indicator["price"])
    target_price = float(target["price"])
    stop_price = float(stop["price"])
    reward = abs(target_price - entry)
    risk = abs(entry - stop_price)
    rr = reward / risk if risk > 0 else 0
    if reward / entry * 100 < 0.15 or risk / entry * 100 > 3 or rr < 0.5:
        return {
            **base,
            "action": "observe",
            "reason": "geometria de niveles no operable",
            "candidate_direction": direction,
            "rr": round(rr, 3),
        }
    return {
        **base,
        "action": "virtual_entry",
        "direction": direction,
        "entry": entry,
        "target": target_price,
        "stop": stop_price,
        "rr": round(rr, 3),
        "score": score,
        "captured_at": indicator["captured_at"],
        "max_hold_seconds": MAX_HOLD_SECONDS,
    }


def _return_pct(direction: str, entry: float, exit_price: float) -> float:
    gross = (exit_price / entry - 1) * 100
    return gross if direction == "long" else -gross


def replay_shadow(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Replay snapshots at their observed prices; never interpolates intrabar."""
    ordered = sorted(
        [row for row in records if row.get("indicator")],
        key=lambda row: row["captured_at"],
    )
    open_trade = None
    trades = []
    decisions = 0
    for row in ordered:
        indicator = row["indicator"]
        if indicator.get("price") is None or not indicator.get("captured_at"):
            continue
        now = _time(row["captured_at"])
        price = float(indicator["price"])
        if open_trade:
            direction = open_trade["direction"]
            target_hit = (
                price >= open_trade["target"] if direction == "long"
                else price <= open_trade["target"]
            )
            stop_hit = (
                price <= open_trade["stop"] if direction == "long"
                else price >= open_trade["stop"]
            )
            expired = (now - _time(open_trade["opened_at"])).total_seconds() >= MAX_HOLD_SECONDS
            opposite = (
                indicator.get("score") is not None
                and (
                    direction == "long" and indicator["score"] <= -ENTRY_THRESHOLD
                    or direction == "short" and indicator["score"] >= ENTRY_THRESHOLD
                )
            )
            reason = (
                "stop" if stop_hit else "target" if target_hit
                else "opposite" if opposite else "time" if expired else None
            )
            if reason:
                net = _return_pct(direction, open_trade["entry"], price) - ROUND_TRIP_COST_PCT
                trades.append({
                    **open_trade,
                    "closed_at": row["captured_at"],
                    "exit": price,
                    "exit_reason": reason,
                    "net_pct": round(net, 4),
                })
                open_trade = None
        if open_trade is None:
            plan = shadow_plan(indicator)
            decisions += 1
            if plan["action"] == "virtual_entry":
                open_trade = {
                    "research_only": True,
                    "direction": plan["direction"],
                    "entry": plan["entry"],
                    "target": plan["target"],
                    "stop": plan["stop"],
                    "rr": plan["rr"],
                    "score": plan["score"],
                    "opened_at": row["captured_at"],
                }

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in trades:
        equity += trade["net_pct"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    winners = sum(trade["net_pct"] > 0 for trade in trades)
    return {
        "research_only": True,
        "execution_enabled": False,
        "strategy": "visual_context_v0",
        "sampling": "snapshot_only",
        "decisions": decisions,
        "closed_trades": len(trades),
        "open_trade": open_trade,
        "metrics": {
            "win_rate_pct": round(winners / len(trades) * 100, 1) if trades else None,
            "avg_net_pct": round(
                sum(trade["net_pct"] for trade in trades) / len(trades), 4
            ) if trades else None,
            "total_net_pct": round(equity, 4),
            "max_drawdown_pct": round(max_drawdown, 4),
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        },
        "recent_trades": trades[-20:],
        "warning": (
            "Simulacion forward por snapshots; no observa el recorrido intrabar "
            "y no puede enviar ordenes."
        ),
    }
