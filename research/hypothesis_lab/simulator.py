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


def _variant_legs(setup: dict[str, Any], variant: dict[str, Any]) -> list[dict[str, float]]:
    entry, sl = float(setup["entry"]), float(setup["sl"])
    original_price, original_rr = target_price(setup, {"id": "original", "rr": None})
    long = setup["dir"] == "long"
    legs = []
    for leg in variant["legs"]:
        requested_rr = original_rr if leg.get("target") == "original" else float(leg["rr"])
        rr = min(requested_rr, original_rr)
        price = original_price if rr == original_rr else (
            entry + rr * abs(entry - sl) if long else entry - rr * abs(entry - sl)
        )
        legs.append({"rr": rr, "price": price, "fraction": float(leg["fraction"])})
    if abs(sum(x["fraction"] for x in legs) - 1.0) > 1e-9:
        raise ValueError(f"exit fractions must sum to 1 for {variant['id']}")
    return sorted(legs, key=lambda x: x["rr"])


def simulate_exit_variant(setup: dict[str, Any], candles: list[dict[str, Any]],
                          variant: dict[str, Any], total_cost_rate: float) -> dict[str, Any]:
    """Simulate a frozen exit policy without changing entry, SL or activation.

    Activation-bar TP credit remains forbidden. On later bars the current stop is
    evaluated before every favorable exit. Stop changes become active only on the
    following bar, which is conservative with OHLC data.
    """
    kind = variant.get("kind")
    if kind is None:
        return simulate(setup, candles, variant, total_cost_rate)
    if kind == "single":
        target = ({"id": "original", "rr": None} if variant.get("target") == "original"
                  else {"id": variant["id"], "rr": float(variant["rr"])})
        return {**simulate(setup, candles, target, total_cost_rate), "variant_id": variant["id"]}

    out = {"setup_id": setup["setup_id"], "decision_timestamp": setup["decision_timestamp"],
           "activation_timestamp": setup.get("activation_timestamp"), "variant_id": variant["id"]}
    act = setup.get("activation_index")
    entry, sl = float(setup["entry"]), float(setup["sl"])
    risk = abs(entry - sl)
    if act is None:
        return {**out, "resolution_timestamp": None, "status": "discarded",
                "discarded_reason": "not_activated", "gross_r": None, "cost_r": None, "net_r": None}
    if risk <= 0 or act < 0 or act >= len(candles):
        return {**out, "resolution_timestamp": None, "status": "discarded",
                "discarded_reason": "invalid_risk_or_activation_index", "gross_r": None,
                "cost_r": None, "net_r": None}
    long = setup["dir"] == "long"
    cost_r = float(total_cost_rate) / (risk / entry) if entry else 0.0
    max_end = min(len(candles) - 1, int(setup["decision_index"]) + int(setup["max_forward_bars"]))
    activation_bar = candles[act]
    if (long and activation_bar["l"] <= sl) or ((not long) and activation_bar["h"] >= sl):
        return {**out, "resolution_timestamp": activation_bar["t"], "status": "sl",
                "discarded_reason": None, "gross_r": -1.0, "cost_r": cost_r,
                "net_r": -1.0 - cost_r}

    original_price, original_rr = target_price(setup, {"id": "original", "rr": None})
    remaining, realized, stop = 1.0, 0.0, sl
    legs = _variant_legs(setup, variant) if kind == "scale_out" else []
    taken = [False] * len(legs)
    trigger_rr = min(float(variant.get("trigger_rr", original_rr)), original_rr)
    trigger_price = entry + trigger_rr * risk if long else entry - trigger_rr * risk
    protected_stop_rr = float(variant.get("new_stop_rr", 0.0))

    for j in range(act + 1, max_end + 1):
        bar = candles[j]
        if (long and bar["l"] <= stop) or ((not long) and bar["h"] >= stop):
            stop_r = (stop - entry) / risk if long else (entry - stop) / risk
            gross = realized + remaining * stop_r
            return {**out, "resolution_timestamp": bar["t"], "status": "sl",
                    "discarded_reason": None, "gross_r": gross, "cost_r": cost_r,
                    "net_r": gross - cost_r}
        if kind == "scale_out":
            for idx, leg in enumerate(legs):
                if taken[idx]:
                    continue
                hit = bar["h"] >= leg["price"] if long else bar["l"] <= leg["price"]
                if hit:
                    realized += leg["fraction"] * leg["rr"]
                    remaining -= leg["fraction"]
                    taken[idx] = True
            if remaining <= 1e-9:
                return {**out, "resolution_timestamp": bar["t"], "status": "tp",
                        "discarded_reason": None, "gross_r": realized, "cost_r": cost_r,
                        "net_r": realized - cost_r}
        elif kind == "protect_runner":
            target_hit = bar["h"] >= original_price if long else bar["l"] <= original_price
            if target_hit:
                return {**out, "resolution_timestamp": bar["t"], "status": "tp",
                        "discarded_reason": None, "gross_r": original_rr, "cost_r": cost_r,
                        "net_r": original_rr - cost_r}
            trigger_hit = bar["h"] >= trigger_price if long else bar["l"] <= trigger_price
            if trigger_hit:
                stop = (entry + protected_stop_rr * risk if long
                        else entry - protected_stop_rr * risk)
        else:
            raise ValueError(f"unknown exit variant kind: {kind}")

    close = float(candles[max_end]["c"])
    close_r = (close - entry) / risk if long else (entry - close) / risk
    gross = realized + remaining * close_r
    return {**out, "resolution_timestamp": candles[max_end]["t"], "status": "timeout_closed",
            "discarded_reason": None, "gross_r": gross, "cost_r": cost_r,
            "net_r": gross - cost_r}
