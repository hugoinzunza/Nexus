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
    ("spx", "SPX", "%5EGSPC", "SP:SPX"),
    ("vix", "VIX", "%5EVIX", "TVC:VIX"),
    ("dxy", "DXY", "DX-Y.NYB", "TVC:DXY"),
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
        snapshot_observer: Callable[[dict], object] | None = None,
    ):
        self._fetch_json = fetch_json
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._ttl_ms = ttl_ms
        self._snapshot_observer = snapshot_observer
        self._lock = threading.Lock()
        self._last_response: dict | None = None
        self._last_refresh_ms = 0
        self._provider_cache: dict[str, list[dict]] = {}
        self._refresh_count = 0
        self._cache_hit_count = 0
        self._last_refresh_duration_ms: float | None = None
        self._provider_successes: dict[str, int] = {}
        self._provider_failures: dict[str, int] = {}
        self._observer_failures = 0

    def snapshot(self) -> dict:
        now_ms = self._clock_ms()
        with self._lock:
            if (
                self._last_response
                and now_ms - self._last_refresh_ms < self._ttl_ms
            ):
                self._cache_hit_count += 1
                return self._decorate(self._last_response, now_ms)

            refresh_started = time.perf_counter()
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
                    self._provider_successes[provider] = (
                        self._provider_successes.get(provider, 0) + 1
                    )
                except Exception as exc:  # noqa: BLE001
                    self._provider_failures[provider] = (
                        self._provider_failures.get(provider, 0) + 1
                    )
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
            self._refresh_count += 1
            self._last_refresh_duration_ms = round(
                (time.perf_counter() - refresh_started) * 1000,
                3,
            )
            decorated = self._decorate(self._last_response, now_ms)
            if self._snapshot_observer is not None:
                try:
                    self._snapshot_observer(decorated)
                except Exception:  # noqa: BLE001
                    self._observer_failures += 1
            return decorated

    def stats(self) -> dict:
        """Expone telemetría operacional sin incluir datos de mercado."""
        with self._lock:
            errors = (
                self._last_response.get("provider_errors", [])
                if self._last_response
                else []
            )
            if not self._last_response:
                status = "idle"
            elif errors:
                status = "degraded"
            else:
                status = "ready"
            return {
                "status": status,
                "refresh_count": self._refresh_count,
                "cache_hit_count": self._cache_hit_count,
                "last_refresh_ms": self._last_refresh_ms or None,
                "last_refresh_duration_ms": self._last_refresh_duration_ms,
                "cached_providers": sorted(self._provider_cache),
                "current_error_providers": sorted(
                    error["provider"] for error in errors
                ),
                "provider_successes": dict(
                    sorted(self._provider_successes.items())
                ),
                "provider_failures": dict(
                    sorted(self._provider_failures.items())
                ),
                "observer_failures": self._observer_failures,
            }

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
            return list(executor.map(self._load_yahoo_asset, _YAHOO_ASSETS))

    def _load_yahoo_asset(self, definition) -> dict:
        asset_id, symbol, provider_symbol, tv_symbol = definition
        payload = None
        last_error = None
        for host in ("query2", "query1"):
            url = (
                f"https://{host}.finance.yahoo.com/v8/finance/chart/"
                f"{provider_symbol}?range=5d&interval=5m"
            )
            try:
                payload = self._fetch_json(url)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if payload is None:
            raise last_error or RuntimeError("yahoo unavailable")
        meta = payload["chart"]["result"][0]["meta"]
        price = float(meta["regularMarketPrice"])
        previous = float(
            meta.get("chartPreviousClose")
            or meta["regularMarketPreviousClose"]
        )
        return {
            "id": asset_id,
            "symbol": symbol,
            "chart_symbol": symbol,
            "tv_symbol": tv_symbol,
            "chart_mode": "external_only",
            "price": price,
            "price_decimals": max(0, min(8, int(meta.get("priceHint", 2)))),
            "change_pct": _change_percent(price, previous),
            "observed_at_ms": int(meta["regularMarketTime"]) * 1000,
            "source": "Yahoo Finance",
            "kind": "index",
        }

    def _load_total(self) -> list[dict]:
        payload = self._fetch_json("https://api.coingecko.com/api/v3/global")
        data = payload["data"]
        return [
            {
                "id": "total",
                "symbol": "TOTAL",
                "chart_symbol": "TOTAL",
                "tv_symbol": "CRYPTOCAP:TOTAL",
                "chart_mode": "external_only",
                "price": float(data["total_market_cap"]["usd"]),
                "price_decimals": 2,
                "change_pct": round(
                    float(data["market_cap_change_percentage_24h_usd"]),
                    3,
                ),
                "observed_at_ms": int(data["updated_at"]) * 1000,
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
        rows = []
        for asset_id, symbol, provider_symbol, tv_symbol in _FUTURES_ASSETS:
            row = by_symbol[provider_symbol]
            raw_price = str(row["lastPrice"])
            decimals = (
                len(raw_price.rstrip("0").split(".", 1)[1])
                if "." in raw_price
                and raw_price.rstrip("0").split(".", 1)[1]
                else 0
            )
            rows.append(
                {
                    "id": asset_id,
                    "symbol": symbol,
                    "chart_symbol": provider_symbol,
                    "tv_symbol": tv_symbol,
                    "chart_mode": "tradingview",
                    "price": float(row["lastPrice"]),
                    "price_decimals": max(0, min(8, decimals)),
                    "change_pct": round(float(row["priceChangePercent"]), 3),
                    "observed_at_ms": int(row["closeTime"]),
                    "source": "Binance Futures",
                    "kind": "futures",
                }
            )
        return rows

    @staticmethod
    def _unknown_asset(asset_id: str) -> dict:
        definitions = {
            item[0]: (item[1], item[1], item[3], "index")
            for item in _YAHOO_ASSETS
        }
        definitions["total"] = (
            "TOTAL",
            "TOTAL",
            "CRYPTOCAP:TOTAL",
            "aggregate",
        )
        definitions.update(
            {
                item[0]: (item[1], item[2], item[3], "futures")
                for item in _FUTURES_ASSETS
            }
        )
        symbol, chart_symbol, tv_symbol, kind = definitions[asset_id]
        return {
            "id": asset_id,
            "symbol": symbol,
            "chart_symbol": chart_symbol,
            "tv_symbol": tv_symbol,
            "chart_mode": "external_only"
            if kind in {"index", "aggregate"}
            else "tradingview",
            "price": None,
            "price_decimals": 2,
            "change_pct": None,
            "observed_at_ms": None,
            "source": None,
            "kind": kind,
        }
