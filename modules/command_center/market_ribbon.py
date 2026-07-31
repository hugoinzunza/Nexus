"""Agregador read-only para la banda de contexto de mercado."""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable


_ASSET_ORDER = (
    "spx",
    "vix",
    "dxy",
    "total",
    "btcusdt",
    "ethusdt",
    "solusdt",
    "xrpusdt",
)
_YAHOO_ASSETS = (
    ("spx", "SPX", "%5EGSPC", "SPX", "SP:SPX"),
    ("vix", "VIX", "%5EVIX", "VIX", "TVC:VIX"),
    ("dxy", "DXY", "DX-Y.NYB", "DXY", "TVC:DXY"),
)
_FUTURES_ASSETS = (
    ("btcusdt", "BTCUSDT.P", "BTCUSDT", "BINANCE:BTCUSDT.P"),
    ("ethusdt", "ETHUSDT.P", "ETHUSDT", "BINANCE:ETHUSDT.P"),
    ("solusdt", "SOLUSDT.P", "SOLUSDT", "BINANCE:SOLUSDT.P"),
    ("xrpusdt", "XRPUSDT.P", "XRPUSDT", "BINANCE:XRPUSDT.P"),
)
_FRESHNESS_WINDOWS_MS = {
    "index": (15 * 60_000, 2 * 3_600_000, 4 * 86_400_000),
    "aggregate": (10 * 60_000, 30 * 60_000, 2 * 3_600_000),
    "futures": (45_000, 3 * 60_000, 15 * 60_000),
}


def _fetch_json(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 NexUX/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.load(response)


def _change_percent(price: float, previous: float) -> float:
    if previous <= 0:
        raise ValueError("previous close must be positive")
    return round((price / previous - 1.0) * 100.0, 3)


def _freshness(kind: str, observed_at_ms: int | None, now_ms: int) -> str:
    if not observed_at_ms:
        return "unknown"
    age = max(0, now_ms - observed_at_ms)
    live_ms, current_ms, usable_ms = _FRESHNESS_WINDOWS_MS[kind]
    if age <= live_ms:
        return "live"
    if age <= current_ms:
        return "current"
    if kind == "index" and age <= usable_ms:
        return "close"
    return "stale"


class MarketRibbonService:
    """Combina proveedores sin ocultar su timestamp ni su degradación."""

    def __init__(
        self,
        *,
        fetch_json: Callable[[str], object] = _fetch_json,
        clock_ms: Callable[[], int] | None = None,
        ttl_ms: int = 15_000,
    ):
        self._fetch_json = fetch_json
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._ttl_ms = ttl_ms
        self._lock = threading.Lock()
        self._last_response: dict | None = None
        self._last_refresh_ms = 0
        self._provider_cache: dict[str, list[dict]] = {}
        self._history_cache: dict[str, dict] = {}

    def snapshot(self) -> dict:
        now_ms = self._clock_ms()
        with self._lock:
            if (
                self._last_response
                and now_ms - self._last_refresh_ms < self._ttl_ms
            ):
                return self._decorate(self._last_response, now_ms)

            providers = (
                ("yahoo", self._load_yahoo),
                ("coingecko", self._load_total),
                ("binance-futures", self._load_futures),
            )
            with ThreadPoolExecutor(
                max_workers=len(providers),
                thread_name_prefix="market-ribbon",
            ) as executor:
                futures = {
                    provider: executor.submit(loader)
                    for provider, loader in providers
                }

            errors = []
            assets = []
            for provider, _loader in providers:
                try:
                    rows = futures[provider].result()
                    if not rows:
                        raise ValueError("provider returned no assets")
                    self._provider_cache[provider] = rows
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "provider": provider,
                            "code": type(exc).__name__,
                        }
                    )
                    rows = self._provider_cache.get(provider, [])
                assets.extend(rows)

            by_id = {asset["id"]: asset for asset in assets}
            normalized = [
                by_id.get(asset_id, self._unknown_asset(asset_id))
                for asset_id in _ASSET_ORDER
            ]
            self._last_response = {
                "assets": normalized,
                "provider_errors": errors,
            }
            self._last_refresh_ms = now_ms
            return self._decorate(self._last_response, now_ms)

    def _decorate(self, response: dict, now_ms: int) -> dict:
        assets = []
        for source in response["assets"]:
            asset = dict(source)
            asset["freshness"] = _freshness(
                asset["kind"],
                asset.get("observed_at_ms"),
                now_ms,
            )
            assets.append(asset)
        return {
            "generated_at_ms": now_ms,
            "assets": assets,
            "provider_errors": list(response["provider_errors"]),
        }

    def _load_yahoo(self) -> list[dict]:
        with ThreadPoolExecutor(
            max_workers=len(_YAHOO_ASSETS),
            thread_name_prefix="market-ribbon-yahoo",
        ) as executor:
            loaded = list(executor.map(self._load_yahoo_asset, _YAHOO_ASSETS))
        rows = []
        for row, history in loaded:
            self._history_cache[row["id"]] = history
            rows.append(row)
        return rows

    def _load_yahoo_asset(self, definition) -> dict:
        asset_id, symbol, provider_symbol, chart_symbol, tv_symbol = definition
        payload = None
        last_error = None
        for host in ("query2", "query1"):
            url = (
                f"https://{host}.finance.yahoo.com/v8/finance/chart/"
                f"{provider_symbol}?range=1mo&interval=1h"
            )
            try:
                payload = self._fetch_json(url)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if payload is None:
            raise last_error or RuntimeError("yahoo unavailable")
        result = payload["chart"]["result"][0]
        meta = result["meta"]
        price = float(meta["regularMarketPrice"])
        previous = float(
            meta.get("chartPreviousClose")
            or meta["regularMarketPreviousClose"]
        )
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        candles = []
        for index, timestamp in enumerate(timestamps):
            values = {
                key: (quote.get(key) or [])[index]
                if index < len(quote.get(key) or [])
                else None
                for key in ("open", "high", "low", "close")
            }
            if any(values[key] is None for key in values):
                continue
            candles.append(
                {
                    "time": int(timestamp),
                    "open": float(values["open"]),
                    "high": float(values["high"]),
                    "low": float(values["low"]),
                    "close": float(values["close"]),
                }
            )
        if not candles:
            observed = int(meta["regularMarketTime"])
            candles = [
                {
                    "time": observed,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                }
            ]
        latest = candles[-1]
        latest["close"] = price
        latest["high"] = max(latest["high"], price)
        latest["low"] = min(latest["low"], price)
        row = {
            "id": asset_id,
            "symbol": symbol,
            "chart_symbol": chart_symbol,
            "tv_symbol": tv_symbol,
            "chart_proxy": False,
            "chart_mode": "same_source",
            "price": price,
            "price_decimals": max(0, min(8, int(meta.get("priceHint", 2)))),
            "change_pct": _change_percent(price, previous),
            "observed_at_ms": int(meta["regularMarketTime"]) * 1000,
            "source": "Yahoo Finance",
            "kind": "index",
        }
        history = {
            "id": asset_id,
            "symbol": symbol,
            "interval": "1h",
            "source": "Yahoo Finance",
            "observed_at_ms": row["observed_at_ms"],
            "price": price,
            "candles": candles,
        }
        return row, history

    def _load_total(self) -> list[dict]:
        payload = self._fetch_json("https://api.coingecko.com/api/v3/global")
        data = payload["data"]
        price = float(data["total_market_cap"]["usd"])
        change = round(
            float(data["market_cap_change_percentage_24h_usd"]),
            3,
        )
        observed_at_ms = int(data["updated_at"]) * 1000
        existing = self._history_cache.get("total", {}).get("points", [])
        points = list(existing)
        point = {"time": observed_at_ms // 1000, "value": price}
        if points and points[-1]["time"] == point["time"]:
            points[-1] = point
        else:
            points.append(point)
        self._history_cache["total"] = {
            "id": "total",
            "symbol": "TOTAL",
            "interval": "observed",
            "source": "CoinGecko",
            "observed_at_ms": observed_at_ms,
            "price": price,
            "points": points[-720:],
        }
        return [
            {
                "id": "total",
                "symbol": "TOTAL",
                "chart_symbol": "TOTAL",
                "tv_symbol": "CRYPTOCAP:TOTAL",
                "chart_proxy": False,
                "chart_mode": "current_only",
                "price": price,
                "price_decimals": 2,
                "change_pct": change,
                "observed_at_ms": observed_at_ms,
                "source": "CoinGecko",
                "kind": "aggregate",
            }
        ]

    def _load_futures(self) -> list[dict]:
        symbols = [item[2] for item in _FUTURES_ASSETS]
        query = urllib.parse.urlencode(
            {"symbols": json.dumps(symbols, separators=(",", ":"))}
        )
        payload = self._fetch_json(
            f"https://fapi.binance.com/fapi/v1/ticker/24hr?{query}"
        )
        by_symbol = {row["symbol"]: row for row in payload}
        with ThreadPoolExecutor(
            max_workers=len(_FUTURES_ASSETS),
            thread_name_prefix="market-ribbon-binance",
        ) as executor:
            histories = list(
                executor.map(
                    lambda definition: self._load_binance_history(
                        definition,
                        by_symbol[definition[2]],
                    ),
                    _FUTURES_ASSETS,
                )
            )
        rows = []
        for row, history in histories:
            self._history_cache[row["id"]] = history
            rows.append(row)
        return rows

    def _load_binance_history(self, definition, ticker: dict) -> tuple[dict, dict]:
        asset_id, symbol, provider_symbol, tv_symbol = definition
        payload = self._fetch_json(
            "https://fapi.binance.com/fapi/v1/klines?"
            + urllib.parse.urlencode(
                {
                    "symbol": provider_symbol,
                    "interval": "1h",
                    "limit": 240,
                }
            )
        )
        raw_price = str(ticker["lastPrice"])
        price = float(raw_price)
        decimals = (
            len(raw_price.rstrip("0").split(".", 1)[1])
            if "." in raw_price and raw_price.rstrip("0").split(".", 1)[1]
            else 0
        )
        candles = [
            {
                "time": int(item[0]) // 1000,
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
            }
            for item in payload
        ]
        if not candles:
            observed = int(ticker["closeTime"]) // 1000
            candles = [
                {
                    "time": observed,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                }
            ]
        candles[-1]["close"] = price
        candles[-1]["high"] = max(candles[-1]["high"], price)
        candles[-1]["low"] = min(candles[-1]["low"], price)
        row = {
            "id": asset_id,
            "symbol": symbol,
            "chart_symbol": provider_symbol,
            "tv_symbol": tv_symbol,
            "chart_proxy": False,
            "chart_mode": "same_source",
            "price": price,
            "price_decimals": max(0, min(8, decimals)),
            "change_pct": round(float(ticker["priceChangePercent"]), 3),
            "observed_at_ms": int(ticker["closeTime"]),
            "source": "Binance Futures",
            "kind": "futures",
        }
        history = {
            "id": asset_id,
            "symbol": symbol,
            "interval": "1h",
            "source": "Binance Futures",
            "observed_at_ms": row["observed_at_ms"],
            "price": price,
            "candles": candles,
        }
        return row, history

    def history(self, asset_id: str) -> dict:
        if asset_id not in set(_ASSET_ORDER):
            raise KeyError(asset_id)
        self.snapshot()
        with self._lock:
            history = self._history_cache.get(asset_id)
            if history is None:
                raise RuntimeError("market history unavailable")
            return json.loads(json.dumps(history))

    @staticmethod
    def _unknown_asset(asset_id: str) -> dict:
        definitions = {
            item[0]: (item[1], item[3], item[4], "index", False)
            for item in _YAHOO_ASSETS
        }
        definitions["total"] = (
            "TOTAL",
            "TOTAL",
            "CRYPTOCAP:TOTAL",
            "aggregate",
            False,
        )
        definitions.update(
            {
                item[0]: (item[1], item[2], item[3], "futures", False)
                for item in _FUTURES_ASSETS
            }
        )
        symbol, chart_symbol, tv_symbol, kind, chart_proxy = definitions[
            asset_id
        ]
        return {
            "id": asset_id,
            "symbol": symbol,
            "chart_symbol": chart_symbol,
            "tv_symbol": tv_symbol,
            "chart_proxy": chart_proxy,
            "chart_mode": "current_only"
            if kind == "aggregate"
            else "same_source",
            "price": None,
            "price_decimals": 2,
            "change_pct": None,
            "observed_at_ms": None,
            "source": None,
            "kind": kind,
        }
