"""Normalize advanced CoinGlass data into a compact, auditable dashboard."""
from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BASE_URL = "https://open-api-v4.coinglass.com"
BINANCE_PRICE_URL = "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT"

ADVANCED_ENDPOINTS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("liquidation_map", "/api/futures/liquidation/map",
     {"exchange": "Binance", "symbol": "BTCUSDT", "range": "7d"}),
    ("liquidation_heatmap", "/api/futures/liquidation/aggregated-heatmap/model2",
     {"symbol": "BTC", "range": "3d"}),
    ("orderbook_heatmap", "/api/futures/orderbook/history",
     {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "1h", "limit": 48}),
    ("large_orders", "/api/futures/orderbook/large-limit-order",
     {"exchange": "Binance", "symbol": "BTCUSDT"}),
)


def _float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _request(
    path: str,
    params: dict[str, Any],
    api_key: str,
    opener: Callable[..., Any],
) -> Any:
    request = urllib.request.Request(
        f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}",
        headers={"accept": "application/json", "CG-API-KEY": api_key},
    )
    with opener(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if str(payload.get("code")) != "0":
        raise RuntimeError(payload.get("msg") or f"CoinGlass code {payload.get('code')}")
    return payload.get("data")


def _liquidation_levels(payload: Any) -> list[dict[str, Any]]:
    source = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(source, dict):
        return []
    levels = []
    for price_key, rows in source.items():
        price = _float(price_key)
        if price is None or not isinstance(rows, list):
            continue
        amount = 0.0
        leverages = set()
        for row in rows:
            if not isinstance(row, (list, tuple)):
                continue
            amount += _float(row[1]) or 0
            leverage = _float(row[2]) if len(row) > 2 else None
            if leverage is not None:
                leverages.add(int(leverage))
        if amount > 0:
            levels.append({
                "price": round(price, 2),
                "amount_usd": round(amount, 2),
                "leverages": sorted(leverages),
            })
    return sorted(levels, key=lambda row: row["amount_usd"], reverse=True)[:120]


def _liquidation_heatmap(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"prices": [], "points": [], "candles": []}
    prices = [_float(value) for value in payload.get("y_axis", [])]
    clean_prices = [round(value, 2) for value in prices if value is not None]
    points = []
    for row in payload.get("liquidation_leverage_data", []):
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        x, y, intensity = int(row[0]), int(row[1]), _float(row[2])
        if intensity is not None and 0 <= y < len(clean_prices):
            points.append([x, y, round(intensity, 2)])
    points = sorted(points, key=lambda row: row[2], reverse=True)[:5000]
    candles = []
    for row in payload.get("price_candlesticks", [])[-500:]:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        values = [_float(value) for value in row[1:5]]
        if all(value is not None for value in values):
            candles.append([int(row[0]), *[round(value, 2) for value in values]])
    return {"prices": clean_prices, "points": points, "candles": candles}


def _book_heatmap(payload: Any) -> list[dict[str, Any]]:
    snapshots = []
    for row in payload[-48:] if isinstance(payload, list) else []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        sides = []
        for raw_side in row[1:3]:
            levels = []
            for level in raw_side if isinstance(raw_side, list) else []:
                if not isinstance(level, (list, tuple)) or len(level) < 2:
                    continue
                price, quantity = _float(level[0]), _float(level[1])
                if price is not None and quantity is not None:
                    levels.append([round(price, 2), round(quantity, 6)])
            sides.append(sorted(levels, key=lambda level: level[1], reverse=True)[:60])
        snapshots.append({"time": int(row[0]), "bids": sides[0], "asks": sides[1]})
    return snapshots


def _large_orders(payload: Any) -> list[dict[str, Any]]:
    orders = []
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, dict):
            continue
        price = _float(row.get("price"))
        usd = _float(row.get("current_usd_value"))
        if price is None or usd is None:
            continue
        orders.append({
            "price": round(price, 2),
            "usd": round(usd, 2),
            "side": "buy" if int(row.get("order_side", 0)) == 2 else "sell",
            "started_at": row.get("start_time"),
            "state": row.get("order_state"),
        })
    return sorted(orders, key=lambda row: row["usd"], reverse=True)[:60]


def _current_price(opener: Callable[..., Any]) -> float | None:
    request = urllib.request.Request(BINANCE_PRICE_URL, headers={"accept": "application/json"})
    try:
        with opener(request, timeout=15) as response:
            return _float(json.loads(response.read().decode("utf-8")).get("price"))
    except Exception:  # noqa: BLE001
        return None


def fetch_advanced(
    api_key: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    preferred_interval: str = "1h",
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    capabilities: dict[str, dict[str, Any]] = {}
    normalizers = {
        "liquidation_map": _liquidation_levels,
        "liquidation_heatmap": _liquidation_heatmap,
        "orderbook_heatmap": _book_heatmap,
        "large_orders": _large_orders,
    }
    for name, path, params in ADVANCED_ENDPOINTS:
        selected = {**params, "interval": preferred_interval} if params.get("interval") else params
        attempts = [selected]
        if preferred_interval == "1h" and params.get("interval") == "1h":
            attempts.append({**params, "interval": "4h"})
        last_error = ""
        for attempt in attempts:
            try:
                data[name] = normalizers[name](_request(path, attempt, api_key, opener))
                capabilities[name] = {
                    "available": True,
                    "interval": attempt.get("interval", "realtime"),
                }
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)[:180]
        if name not in data:
            capabilities[name] = {"available": False, "reason": last_error}
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "price": _current_price(opener),
        "capabilities": capabilities,
        **data,
    }


def _latest(values: Any) -> float | None:
    return _float(values[-1]) if isinstance(values, list) and values else None


def _compact_context(context: dict[str, Any]) -> dict[str, Any]:
    indicators = context.get("indicators", {})
    candles = indicators.get("price", {}).get("candles", [])
    price_now = _float(candles[-1].get("close")) if candles else None
    price_prev = _float(candles[-2].get("close")) if len(candles) > 1 else None
    open_interest = indicators.get("open_interest", {})
    oi = open_interest.get("close_usd") or open_interest.get("close_btc", [])
    oi_now = _latest(oi)
    oi_prev = _float(oi[-2]) if len(oi) > 1 else None
    return {
        "time": context.get("captured_at"),
        "bar_time": (open_interest.get("times") or [None])[-1],
        "price": price_now,
        "price_change_pct": round((price_now / price_prev - 1) * 100, 4)
        if price_now is not None and price_prev else None,
        "funding_pct": _latest(indicators.get("funding", {}).get("close_pct")),
        "funding_volume_pct": _latest(
            indicators.get("funding_volume", {}).get("close_pct")
        ),
        "oi_usd": oi_now,
        "oi_change_pct": round((oi_now / oi_prev - 1) * 100, 4)
        if oi_now is not None and oi_prev else None,
        "top_long_pct": _latest(indicators.get("top_traders", {}).get("long_pct")),
        "global_long_pct": _latest(indicators.get("global_accounts", {}).get("long_pct")),
        "top_account_long_pct": _latest(
            indicators.get("top_accounts", {}).get("long_pct")
        ),
        "taker_buy_pct": _latest([
            row.get("buy_ratio") for row in indicators.get("taker", {}).get("bars", [])
        ]),
        "book_ratio": _latest(indicators.get("orderbook", {}).get("bid_ask_ratio")),
        "aggregated_book_ratio": _latest(
            indicators.get("orderbook_aggregated", {}).get("bid_ask_ratio")
        ),
    }


def _basic_analysis(basic: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_context(basic)
    indicators = basic.get("indicators", {})
    liquidation_rows = indicators.get("liquidations", {}).get("bars", [])
    liquidation = liquidation_rows[-1] if isinstance(liquidation_rows, list) and liquidation_rows else None
    funding = compact.get("funding_pct")
    oi_change = compact.get("oi_change_pct")
    price_change = compact.get("price_change_pct")
    top_long = compact.get("top_long_pct")
    book = compact.get("book_ratio")
    aggregated_book = compact.get("aggregated_book_ratio")
    taker_buy = compact.get("taker_buy_pct")
    global_long = compact.get("global_long_pct")
    top_account_long = compact.get("top_account_long_pct")
    long_liq = _float(liquidation.get("long_musd")) if isinstance(liquidation, dict) else None
    short_liq = _float(liquidation.get("short_musd")) if isinstance(liquidation, dict) else None
    if price_change is not None and oi_change is not None:
        if price_change > 0.15 and oi_change > 0.15:
            leverage = "precio sube + OI sube · nuevos longs"
        elif price_change < -0.15 and oi_change > 0.15:
            leverage = "precio baja + OI sube · nuevos shorts"
        elif price_change > 0.15 and oi_change < -0.15:
            leverage = "precio sube + OI baja · cierre de shorts"
        elif price_change < -0.15 and oi_change < -0.15:
            leverage = "precio baja + OI baja · salida de longs"
        else:
            leverage = "precio/OI sin divergencia clara"
    else:
        leverage = (
        "sin datos" if oi_change is None
        else "apalancamiento entrando" if oi_change > 0.25
        else "desapalancamiento" if oi_change < -0.25
        else "OI estable"
        )
    funding_state = (
        "sin datos" if funding is None
        else "longs pagan elevado" if funding > 0.01
        else "longs pagan moderado" if funding > 0
        else "shorts pagan"
    )
    liquidation_state = (
        "sin datos" if long_liq is None or short_liq is None
        else "flush de longs" if long_liq > short_liq * 2
        else "flush de shorts" if short_liq > long_liq * 2
        else "liquidación equilibrada"
    )
    positioning = (
        "sin datos" if top_long is None
        else "top traders cargados long" if top_long >= 60
        else "top traders cargados short" if top_long <= 40
        else "posicionamiento equilibrado"
    )
    book_state = (
        "sin datos" if book is None and aggregated_book is None
        else "bids dominan Binance y agregado"
        if book is not None and aggregated_book is not None and book >= 1.2 and aggregated_book >= 1.2
        else "asks dominan Binance y agregado"
        if book is not None and aggregated_book is not None and book <= 0.83 and aggregated_book <= 0.83
        else "libros divergen entre exchanges"
        if book is not None and aggregated_book is not None
        and (book - 1) * (aggregated_book - 1) < 0
        else "más bids en ±1%" if (aggregated_book or book or 0) >= 1.2
        else "más asks en ±1%" if (aggregated_book or book or 0) <= 0.83
        else "profundidad equilibrada"
    )
    taker_state = (
        "sin datos" if taker_buy is None
        else "compradores agresivos dominan" if taker_buy >= 52
        else "vendedores agresivos dominan" if taker_buy <= 48
        else "flujo taker equilibrado"
    )
    crowd_values = [
        value for value in (global_long, top_account_long, top_long) if value is not None
    ]
    crowd_state = (
        "sin datos" if not crowd_values
        else "consenso long elevado" if min(crowd_values) >= 60
        else "consenso short elevado" if max(crowd_values) <= 40
        else "segmentos de traders divergen"
        if max(crowd_values) - min(crowd_values) >= 8
        else "posicionamiento mixto"
    )
    return {
        "research_only": True,
        "interval": basic.get("intervals", {}).get("open_interest", "4h"),
        "leverage": leverage,
        "funding": funding_state,
        "liquidations": liquidation_state,
        "positioning": positioning,
        "crowding": crowd_state,
        "taker": taker_state,
        "orderbook": book_state,
    }


def _pressure(basic: dict[str, Any], advanced: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_context(basic)
    price = _float(advanced.get("price"))
    levels = advanced.get("liquidation_map", [])
    above = sum(row["amount_usd"] for row in levels if price and row["price"] > price)
    below = sum(row["amount_usd"] for row in levels if price and row["price"] < price)
    liquidity = (above - below) / (above + below) if above + below else None
    ratio = compact.get("book_ratio")
    book = (ratio - 1) / (ratio + 1) if ratio is not None and ratio > 0 else 0
    funding = compact.get("funding_pct") or 0
    top_long = compact.get("top_long_pct")
    crowd = -((top_long - 50) / 50) if top_long is not None else 0
    funding_contrarian = -math.tanh(funding / 0.03)
    score = (
        100 * (0.45 * liquidity + 0.35 * book + 0.10 * crowd + 0.10 * funding_contrarian)
        if liquidity is not None else None
    )
    return {
        "research_only": True,
        "validated": False,
        "score": round(max(-100, min(100, score)), 1) if score is not None else None,
        "components": {
            "liquidation_attraction": round(liquidity, 4) if liquidity is not None else None,
            "orderbook_imbalance": round(book, 4),
            "positioning_contrarian": round(crowd, 4),
            "funding_contrarian": round(funding_contrarian, 4),
        },
        "liquidation_usd": {"above": round(above, 2), "below": round(below, 2)},
        "label": (
            "modelo incompleto" if score is None
            else "presión alcista" if score >= 15
            else "presión bajista" if score <= -15
            else "neutral"
        ),
    }


def build_dashboard(
    basic: dict[str, Any],
    basic_history: list[dict[str, Any]],
    advanced: dict[str, Any],
) -> dict[str, Any]:
    by_bar = {}
    for row in basic_history:
        compact = _compact_context(row)
        key = compact.get("bar_time") or compact.get("time")
        by_bar[key] = compact
    history = list(by_bar.values())[-540:]
    return {
        "research_only": True,
        "execution_enabled": False,
        "mode": "research",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": "BTCUSDT",
        "basic": basic,
        "basic_analysis": _basic_analysis(basic),
        "history": history,
        "advanced": advanced,
        "experimental_pressure": {
            **_pressure(basic, advanced),
            "observations": len(history),
            "minimum_for_calibration": 100,
            "status": "collecting" if len(history) < 100 else "ready_for_backtest",
        },
    }


def update_dashboard(
    api_key: str,
    path: Path,
    basic: dict[str, Any],
    basic_history: list[dict[str, Any]],
    *,
    max_age_seconds: int = 300,
    now: datetime | None = None,
    advanced_fetcher: Callable[[str], dict[str, Any]] = fetch_advanced,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cached: dict[str, Any] = {}
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        captured = datetime.fromisoformat(
            cached["advanced"]["captured_at"].replace("Z", "+00:00")
        )
        if (now - captured).total_seconds() < max_age_seconds:
            return build_dashboard(basic, basic_history, cached["advanced"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass
    try:
        advanced = advanced_fetcher(api_key)
    except Exception as exc:  # noqa: BLE001
        if cached.get("advanced"):
            advanced = dict(cached["advanced"])
            advanced["stale"] = True
            advanced["last_error"] = str(exc)[:180]
        else:
            advanced = {
                "captured_at": now.isoformat(),
                "price": None,
                "capabilities": {},
                "stale": True,
                "last_error": str(exc)[:180],
            }
    dashboard = build_dashboard(basic, basic_history, advanced)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(dashboard, ensure_ascii=False), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)
    return dashboard
