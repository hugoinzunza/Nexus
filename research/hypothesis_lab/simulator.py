"""Shared causal OHLC exit simulator for paired TP/RR experiments."""
from __future__ import annotations

from typing import Any


def target_price(setup: dict[str, Any], target: dict[str, Any]) -> tuple[float, float]:
    entry, sl = float(setup["entry"]), float(setup["sl"])
    risk = abs(entry - sl)
    if target["id"] == "original":
        price = float(setup["original_tp"])
        rr = abs(price - entry) / risk if risk else 0.0
    else:
        rr = float(target["rr"])
        price = entry + rr * risk if setup["dir"] == "long" else entry - rr * risk
    return price, rr


def simulate(setup: dict[str, Any], candles: list[dict[str, Any]], target: dict[str, Any],
             total_cost_rate: float) -> dict[str, Any]:
    """Resolve one target on the exact exported entry/SL and activation.

    The activation bar may stop the trade but never credits TP. From the next bar,
    SL is checked before TP. An unresolved trade is explicitly closed at the final
    timeout-bar close so every activated setup has an observed paired payoff.
    """
    out = {"setup_id": setup["setup_id"], "decision_timestamp": setup["decision_timestamp"],
           "activation_timestamp": setup.get("activation_timestamp")}
    act = setup.get("activation_index")
    if act is None:
        return {**out, "resolution_timestamp": None, "status": "discarded",
                "discarded_reason": "not_activated", "gross_r": None, "cost_r": None, "net_r": None}
    entry, sl = float(setup["entry"]), float(setup["sl"])
    risk = abs(entry - sl)
    if risk <= 0 or act < 0 or act >= len(candles):
        return {**out, "resolution_timestamp": None, "status": "discarded",
                "discarded_reason": "invalid_risk_or_activation_index", "gross_r": None,
                "cost_r": None, "net_r": None}
    tp, rr = target_price(setup, target)
    long = setup["dir"] == "long"
    cost_r = float(total_cost_rate) / (risk / entry) if entry else 0.0
    max_end = min(len(candles) - 1, int(setup["decision_index"]) + int(setup["max_forward_bars"]))

    # Fill intrabar: adverse excursion can hit SL, but the already-observed high/low
    # cannot pay TP because OHLC does not reveal whether it happened after the fill.
    c = candles[act]
    if (long and c["l"] <= sl) or ((not long) and c["h"] >= sl):
        gross, status, end = -1.0, "sl", act
    else:
        gross = None
        status, end = "timeout_closed", max(act, max_end)
        for j in range(act + 1, max_end + 1):
            c = candles[j]
            if (long and c["l"] <= sl) or ((not long) and c["h"] >= sl):
                gross, status, end = -1.0, "sl", j
                break
            if (long and c["h"] >= tp) or ((not long) and c["l"] <= tp):
                gross, status, end = rr, "tp", j
                break
        if gross is None:
            close = float(candles[end]["c"])
            gross = (close - entry) / risk if long else (entry - close) / risk
    return {**out, "resolution_timestamp": candles[end]["t"], "status": status,
            "discarded_reason": None, "gross_r": gross, "cost_r": cost_r,
            "net_r": gross - cost_r, "target_price": tp, "target_rr": rr}

