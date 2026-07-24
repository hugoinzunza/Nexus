"""CoinGlass V4 context for the read-only CoinSignals research module."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BASE_URL = "https://open-api-v4.coinglass.com"
HISTORY_LIMIT = 90 * 24 * 12

ENDPOINTS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("funding", "/api/futures/funding-rate/oi-weight-history",
     {"symbol": "BTC", "interval": "1h", "limit": 4}),
    ("open_interest", "/api/futures/open-interest/aggregated-history",
     {"symbol": "BTC", "interval": "1h", "limit": 4}),
    ("liquidations", "/api/futures/liquidation/aggregated-history",
     {"exchange_list": "Binance,OKX,Bybit", "symbol": "BTC", "interval": "1h", "limit": 4}),
    ("top_traders", "/api/futures/top-long-short-position-ratio/history",
     {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "1h", "limit": 4}),
    ("orderbook", "/api/futures/orderbook/ask-bids-history",
     {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "1h", "range": "1", "limit": 4}),
)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _series(rows: Any, keys: tuple[str, ...]) -> list[float]:
    if not isinstance(rows, list):
        return []
    values = []
    for row in rows[-4:]:
        if not isinstance(row, dict):
            continue
        value = next((_number(row.get(key)) for key in keys if row.get(key) is not None), None)
        if value is not None:
            values.append(round(value, 6))
    return values


def _summarize(name: str, rows: Any) -> dict[str, Any]:
    if name == "funding":
        return {"close_pct": _series(rows, ("close", "funding_rate"))}
    if name == "open_interest":
        return {"close_usd": _series(rows, ("close", "open_interest", "aggregated_open_interest"))}
    if name == "liquidations":
        bars = []
        for row in rows[-4:] if isinstance(rows, list) else []:
            long_usd = _number(row.get("aggregated_long_liquidation_usd"))
            short_usd = _number(row.get("aggregated_short_liquidation_usd"))
            if long_usd is not None or short_usd is not None:
                bars.append({
                    "long_musd": round((long_usd or 0) / 1_000_000, 3),
                    "short_musd": round((short_usd or 0) / 1_000_000, 3),
                })
        return {"bars": bars}
    if name == "top_traders":
        values = _series(rows, (
            "top_position_long_percent", "long_position_percentage",
            "long_account", "long_account_ratio", "long_ratio",
        ))
        return {"long_pct": [round(value * 100 if value <= 1 else value, 2) for value in values]}
    if name == "orderbook":
        ratios = []
        for row in rows[-4:] if isinstance(rows, list) else []:
            bids = _number(row.get("bids_usd"))
            asks = _number(row.get("asks_usd"))
            if bids is not None and asks:
                ratios.append(round(bids / asks, 3))
        return {"bid_ask_ratio": ratios}
    return {}


def fetch_market_context(
    api_key: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    captured_at: str | None = None,
    preferred_interval: str = "1h",
) -> dict[str, Any]:
    if not api_key.strip():
        raise ValueError("CoinGlass API key is required")
    indicators: dict[str, Any] = {}
    errors: dict[str, str] = {}
    intervals: dict[str, str] = {}
    quota: dict[str, int] = {}
    for name, path, params in ENDPOINTS:
        selected = {**params, "interval": preferred_interval} if params.get("interval") else params
        attempts = [selected]
        if preferred_interval == "1h" and params.get("interval") == "1h":
            attempts.append({**params, "interval": "4h"})
        last_error = ""
        for attempt in attempts:
            request = urllib.request.Request(
                f"{BASE_URL}{path}?{urllib.parse.urlencode(attempt)}",
                headers={"accept": "application/json", "CG-API-KEY": api_key},
            )
            try:
                with opener(request, timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    if str(payload.get("code")) != "0":
                        raise RuntimeError(
                            payload.get("msg") or f"CoinGlass code {payload.get('code')}"
                        )
                    indicators[name] = _summarize(name, payload.get("data"))
                    intervals[name] = attempt.get("interval", "realtime")
                    for header, field in (
                        ("API-KEY-MAX-LIMIT", "max_per_minute"),
                        ("API-KEY-USE-LIMIT", "used_this_minute"),
                    ):
                        value = response.headers.get(header)
                        if value and value.isdigit():
                            quota[field] = int(value)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)[:160]
        if name not in indicators:
            errors[name] = last_error
    if not indicators:
        raise RuntimeError(f"all CoinGlass endpoints failed: {errors}")
    return {
        "research_only": True,
        "source": "coinglass_v4",
        "status": "ok" if not errors else "partial",
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "symbol": "BTC",
        "intervals": intervals,
        "indicators": indicators,
        "errors": errors,
        "quota": quota,
    }


def _read_store(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)


def update_market_context(
    api_key: str,
    path: Path,
    *,
    max_age_seconds: int = 300,
    now: datetime | None = None,
    fetcher: Callable[[str], dict[str, Any]] = fetch_market_context,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    now = now or datetime.now(timezone.utc)
    store = _read_store(path)
    latest = store.get("latest")
    history = store.get("history") if isinstance(store.get("history"), list) else []
    if isinstance(latest, dict):
        try:
            captured = datetime.fromisoformat(latest["captured_at"].replace("Z", "+00:00"))
            if (now - captured).total_seconds() < max_age_seconds:
                return latest, history
        except (KeyError, TypeError, ValueError):
            pass
    try:
        latest = fetcher(api_key)
        history.append(latest)
        history = history[-HISTORY_LIMIT:]
        _atomic_json(path, {"research_only": True, "latest": latest, "history": history})
        return latest, history
    except Exception as exc:  # noqa: BLE001
        if isinstance(latest, dict):
            stale = dict(latest)
            stale["status"] = "stale"
            stale["last_error"] = str(exc)[:160]
            return stale, history
        return {
            "research_only": True,
            "source": "coinglass_v4",
            "status": "unavailable",
            "captured_at": now.isoformat(),
            "indicators": {},
            "last_error": str(exc)[:160],
        }, history
