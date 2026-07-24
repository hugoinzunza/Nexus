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
    ("price", "/api/futures/price/history",
     {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "1h", "limit": 4}),
    ("funding", "/api/futures/funding-rate/oi-weight-history",
     {"symbol": "BTC", "interval": "1h", "limit": 4}),
    ("funding_volume", "/api/futures/funding-rate/vol-weight-history",
     {"symbol": "BTC", "interval": "1h", "limit": 4}),
    ("open_interest", "/api/futures/open-interest/aggregated-history",
     {"symbol": "BTC", "interval": "1h", "limit": 4}),
    ("open_interest_exchanges", "/api/futures/open-interest/exchange-list",
     {"symbol": "BTC"}),
    ("liquidations", "/api/futures/liquidation/aggregated-history",
     {"exchange_list": "Binance,OKX,Bybit", "symbol": "BTC", "interval": "1h", "limit": 4}),
    ("liquidation_exchanges", "/api/futures/liquidation/exchange-list",
     {"symbol": "BTC", "range": "4h"}),
    ("global_accounts", "/api/futures/global-long-short-account-ratio/history",
     {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "1h", "limit": 4}),
    ("top_accounts", "/api/futures/top-long-short-account-ratio/history",
     {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "1h", "limit": 4}),
    ("top_traders", "/api/futures/top-long-short-position-ratio/history",
     {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "1h", "limit": 4}),
    ("taker", "/api/futures/aggregated-taker-buy-sell-volume/history",
     {"exchange_list": "Binance,OKX,Bybit", "symbol": "BTC", "interval": "1h",
      "limit": 4, "unit": "usd"}),
    ("taker_exchanges", "/api/futures/taker-buy-sell-volume/exchange-list",
     {"symbol": "BTC", "range": "4h"}),
    ("orderbook", "/api/futures/orderbook/ask-bids-history",
     {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "1h", "range": "1", "limit": 4}),
    ("orderbook_aggregated", "/api/futures/orderbook/aggregated-ask-bids-history",
     {"exchange_list": "Binance,OKX,Bybit", "symbol": "BTC", "interval": "1h",
      "range": "1", "limit": 4}),
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


def _times(rows: Any) -> list[int]:
    if not isinstance(rows, list):
        return []
    return [int(row["time"]) for row in rows[-4:] if isinstance(row, dict) and row.get("time")]


def _percent_series(rows: Any, keys: tuple[str, ...]) -> list[float]:
    values = _series(rows, keys)
    return [round(value * 100 if abs(value) <= 1 else value, 2) for value in values]


def _usd_millions(value: Any) -> float:
    return round((_number(value) or 0) / 1_000_000, 3)


def _summarize(name: str, rows: Any) -> dict[str, Any]:
    if name == "price":
        candles = []
        for row in rows[-4:] if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            values = [_number(row.get(key)) for key in ("open", "high", "low", "close")]
            if all(value is not None for value in values):
                candles.append({
                    "time": int(row.get("time") or 0),
                    "open": round(values[0], 2),
                    "high": round(values[1], 2),
                    "low": round(values[2], 2),
                    "close": round(values[3], 2),
                    "volume_musd": _usd_millions(row.get("volume_usd")),
                })
        return {"candles": candles}
    if name in {"funding", "funding_volume"}:
        return {"close_pct": _series(rows, ("close", "funding_rate")), "times": _times(rows)}
    if name == "open_interest":
        return {
            "close_usd": _series(rows, ("close", "open_interest", "aggregated_open_interest")),
            "times": _times(rows),
        }
    if name == "open_interest_exchanges":
        normalized = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not row.get("exchange"):
                continue
            normalized.append({
                "exchange": str(row["exchange"]),
                "oi_usd": round(_number(row.get("open_interest_usd")) or 0, 2),
                "stable_margin_usd": round(
                    _number(row.get("open_interest_by_stable_coin_margin")) or 0, 2
                ),
                "coin_margin_usd": round(
                    _number(row.get("open_interest_by_coin_margin")) or 0, 2
                ),
                "change_4h_pct": round(
                    _number(row.get("open_interest_change_percent_4h")) or 0, 3
                ),
                "change_24h_pct": round(
                    _number(row.get("open_interest_change_percent_24h")) or 0, 3
                ),
            })
        total = next((row for row in normalized if row["exchange"].lower() == "all"), None)
        exchanges = sorted(
            (row for row in normalized if row["exchange"].lower() != "all"),
            key=lambda row: row["oi_usd"],
            reverse=True,
        )[:10]
        return {"total": total or {}, "exchanges": exchanges}
    if name == "liquidations":
        bars = []
        for row in rows[-4:] if isinstance(rows, list) else []:
            long_usd = _number(row.get("aggregated_long_liquidation_usd"))
            short_usd = _number(row.get("aggregated_short_liquidation_usd"))
            if long_usd is not None or short_usd is not None:
                bar = {
                    "long_musd": round((long_usd or 0) / 1_000_000, 3),
                    "short_musd": round((short_usd or 0) / 1_000_000, 3),
                }
                if row.get("time"):
                    bar["time"] = int(row["time"])
                bars.append(bar)
        return {"bars": bars}
    if name == "liquidation_exchanges":
        exchanges = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not row.get("exchange"):
                continue
            long_usd = next((_number(row.get(key)) for key in (
                "long_liquidation_usd", "longLiquidation_usd",
            ) if row.get(key) is not None), None)
            short_usd = next((_number(row.get(key)) for key in (
                "short_liquidation_usd", "shortLiquidation_usd",
            ) if row.get(key) is not None), None)
            exchanges.append({
                "exchange": str(row["exchange"]),
                "long_musd": round((long_usd or 0) / 1_000_000, 3),
                "short_musd": round((short_usd or 0) / 1_000_000, 3),
            })
        return {
            "exchanges": sorted(
                (row for row in exchanges if row["exchange"].lower() != "all"),
                key=lambda row: row["long_musd"] + row["short_musd"],
                reverse=True,
            )[:10],
        }
    if name in {"global_accounts", "top_accounts"}:
        keys = (
            ("global_account_long_percent", "long_account_percent", "long_account")
            if name == "global_accounts"
            else ("top_account_long_percent", "long_account_percent", "long_account")
        )
        return {"long_pct": _percent_series(rows, keys), "times": _times(rows)}
    if name == "top_traders":
        values = _percent_series(rows, (
            "top_position_long_percent", "long_position_percentage",
            "long_account", "long_account_ratio", "long_ratio",
        ))
        return {"long_pct": values, "times": _times(rows)}
    if name == "taker":
        bars = []
        for row in rows[-4:] if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            buy = next((_number(row.get(key)) for key in (
                "aggregated_buy_volume_usd", "buy_volume_usd", "buy_vol_usd",
            ) if row.get(key) is not None), None)
            sell = next((_number(row.get(key)) for key in (
                "aggregated_sell_volume_usd", "sell_volume_usd", "sell_vol_usd",
            ) if row.get(key) is not None), None)
            if buy is not None or sell is not None:
                total = (buy or 0) + (sell or 0)
                bars.append({
                    "time": int(row.get("time") or 0),
                    "buy_musd": round((buy or 0) / 1_000_000, 3),
                    "sell_musd": round((sell or 0) / 1_000_000, 3),
                    "buy_ratio": round((buy or 0) / total * 100, 2) if total else None,
                })
        return {"bars": bars}
    if name == "taker_exchanges":
        source = rows if isinstance(rows, dict) else {}
        exchange_rows = source.get("exchange_list", source.get("list", []))
        exchanges = []
        for row in exchange_rows if isinstance(exchange_rows, list) else []:
            if not isinstance(row, dict) or not row.get("exchange"):
                continue
            exchanges.append({
                "exchange": str(row["exchange"]),
                "buy_ratio": round(_number(row.get("buy_ratio")) or 0, 2),
                "sell_ratio": round(_number(row.get("sell_ratio")) or 0, 2),
                "buy_musd": _usd_millions(
                    row.get("buy_vol_usd", row.get("buy_volume_usd"))
                ),
                "sell_musd": _usd_millions(
                    row.get("sell_vol_usd", row.get("sell_volume_usd"))
                ),
            })
        return {
            "buy_ratio": round(_number(source.get("buy_ratio")) or 0, 2),
            "sell_ratio": round(_number(source.get("sell_ratio")) or 0, 2),
            "buy_musd": _usd_millions(
                source.get("buy_vol_usd", source.get("buy_volume_usd"))
            ),
            "sell_musd": _usd_millions(
                source.get("sell_vol_usd", source.get("sell_volume_usd"))
            ),
            "exchanges": exchanges[:10],
        }
    if name in {"orderbook", "orderbook_aggregated"}:
        ratios = []
        for row in rows[-4:] if isinstance(rows, list) else []:
            bid_keys = ("bids_usd",) if name == "orderbook" else ("aggregated_bids_usd", "bids_usd")
            ask_keys = ("asks_usd",) if name == "orderbook" else ("aggregated_asks_usd", "asks_usd")
            bids = next((_number(row.get(key)) for key in bid_keys if row.get(key) is not None), None)
            asks = next((_number(row.get(key)) for key in ask_keys if row.get(key) is not None), None)
            if bids is not None and asks:
                ratios.append(round(bids / asks, 3))
        return {"bid_ask_ratio": ratios, "times": _times(rows)}
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
