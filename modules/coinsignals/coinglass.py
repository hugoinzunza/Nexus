"""CoinGlass V4 context for the read-only CoinSignals research module."""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
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

HISTORICAL_ENDPOINTS = tuple(
    endpoint for endpoint in ENDPOINTS if endpoint[2].get("interval")
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
    intervals_observed: dict[str, str] = {}
    rate_limited: list[str] = []
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
                    # Lo que se PIDIÓ no es necesariamente lo que llegó. Se mide
                    # el paso real entre marcas de tiempo consecutivas para poder
                    # detectar una degradación de granularidad del lado servidor.
                    observado = _interval_observado(indicators[name])
                    if observado:
                        intervals_observed[name] = observado
                    for header, field in (
                        ("API-KEY-MAX-LIMIT", "max_per_minute"),
                        ("API-KEY-USE-LIMIT", "used_this_minute"),
                    ):
                        value = response.headers.get(header)
                        if value and value.isdigit():
                            quota[field] = int(value)
                break
            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code}: {str(exc)[:140]}"
                if exc.code == 429:
                    # Un 429 NO es "el plan no tiene este intervalo": reintentar
                    # con 4h duplicaba las llamadas justo cuando ya sobrábamos de
                    # cuota. Se anota como rate limit, se pausa y se corta.
                    rate_limited.append(name)
                    time.sleep(_RATE_LIMIT_PAUSE)
                    break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)[:160]
        if name not in indicators:
            errors[name] = last_error
        # Espaciado entre endpoints cuando la cuota leída viene apretada.
        if quota.get("max_per_minute") and quota.get("used_this_minute"):
            if quota["used_this_minute"] > quota["max_per_minute"] * 0.8:
                time.sleep(_RATE_LIMIT_PAUSE)
    if not indicators:
        raise RuntimeError(f"all CoinGlass endpoints failed: {errors}")
    return {
        "research_only": True,
        "source": "coinglass_v4",
        "status": "ok" if not errors else "partial",
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "symbol": "BTC",
        "intervals": intervals,
        # Intervalo MEDIDO en los datos que llegaron, no el que se pidió. Si
        # difiere de `intervals`, la granularidad se degradó del lado servidor.
        "intervals_observed": intervals_observed,
        "interval_mismatch": sorted(
            name for name, pedido in intervals.items()
            if name in intervals_observed and intervals_observed[name] != pedido
        ),
        "rate_limited": rate_limited,
        "indicators": indicators,
        "errors": errors,
        "quota": quota,
    }


def fetch_historical_contexts(
    api_key: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    now: datetime | None = None,
    days: int = 180,
    window_days: int = 90,
    interval: str = "4h",
    pause_seconds: float = 0,
) -> list[dict[str, Any]]:
    """Fetch aligned, causal historical contexts without counting them as forward."""
    if not api_key.strip():
        raise ValueError("CoinGlass API key is required")
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    raw_by_indicator: dict[str, dict[int, dict[str, Any]]] = {}
    intervals: dict[str, str] = {}

    for name, path, base_params in HISTORICAL_ENDPOINTS:
        by_time: dict[int, dict[str, Any]] = {}
        cursor = start
        while cursor < now:
            window_end = min(cursor + timedelta(days=window_days), now)
            params = {
                **base_params,
                "interval": interval,
                "limit": 1000,
                "start_time": int(cursor.timestamp() * 1000),
                "end_time": int(window_end.timestamp() * 1000),
            }
            request = urllib.request.Request(
                f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}",
                headers={"accept": "application/json", "CG-API-KEY": api_key},
            )
            with opener(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if str(payload.get("code")) != "0":
                raise RuntimeError(
                    f"{name}: {payload.get('msg') or payload.get('code')}"
                )
            for row in payload.get("data", []):
                if isinstance(row, dict) and row.get("time"):
                    by_time[int(row["time"])] = row
            cursor = window_end
            if pause_seconds:
                time.sleep(pause_seconds)
        raw_by_indicator[name] = by_time
        intervals[name] = interval

    anchor_times = sorted(raw_by_indicator.get("open_interest", {}))
    summaries: dict[str, dict[int, dict[str, Any]]] = {}
    for name, by_time in raw_by_indicator.items():
        ordered = sorted(by_time.items())
        summaries[name] = {}
        for index, (timestamp, row) in enumerate(ordered):
            prior = ordered[index - 1][1] if index else None
            summaries[name][timestamp] = _summarize(
                name, [prior, row] if prior is not None else [row]
            )

    contexts = []
    for timestamp in anchor_times:
        indicators = {
            name: values[timestamp]
            for name, values in summaries.items()
            if timestamp in values
        }
        if "price" not in indicators or "open_interest" not in indicators:
            continue
        contexts.append({
            "research_only": True,
            "history_origin": "backfill",
            "source": "coinglass_v4",
            "status": "ok",
            "captured_at": datetime.fromtimestamp(
                timestamp / 1000, timezone.utc
            ).isoformat(),
            "symbol": "BTC",
            "intervals": intervals,
            "indicators": indicators,
            "errors": {},
            "quota": {},
        })
    return contexts


def backfill_market_history(
    api_key: str,
    path: Path,
    **fetch_options: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    store = _read_store(path)
    latest = store.get("latest") if isinstance(store.get("latest"), dict) else {}
    existing = store.get("history") if isinstance(store.get("history"), list) else []
    historical = fetch_historical_contexts(api_key, **fetch_options)
    by_bar: dict[int | str, dict[str, Any]] = {}
    # Las filas del backfill van DESPUÉS para ganar el empate: para una barra ya
    # cerrada, el backfill trae la vela completa y la fila forward es una captura
    # a mitad de barra (incompleta). Antes se conservaba la incompleta. La barra
    # en curso no está en el backfill, así que su fila forward sobrevive igual.
    for row in [*existing, *historical]:
        times = row.get("indicators", {}).get("open_interest", {}).get("times", [])
        key = times[-1] if times else row.get("captured_at", "")
        by_bar[key] = row
    history = sorted(
        by_bar.values(),
        key=lambda row: row.get("captured_at", ""),
    )[-HISTORY_LIMIT:]
    _atomic_json(path, {
        "research_only": True,
        "latest": latest,
        "history": history,
    })
    return latest, history


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


_RATE_LIMIT_PAUSE = 2.0     # segundos de espera tras un 429 o cuota apretada
_PASOS_CONOCIDOS = {900_000: "15m", 1_800_000: "30m", 3_600_000: "1h",
                    14_400_000: "4h", 86_400_000: "1d"}


def _interval_observado(indicator: Any) -> str | None:
    """Paso REAL entre marcas de tiempo consecutivas, como etiqueta ('1h','4h').

    Devuelve None si el indicador no trae `times` o no alcanzan para medir. Se
    usa la mediana de los deltas para no dejarse llevar por un hueco puntual.
    """
    if not isinstance(indicator, dict):
        return None
    times = indicator.get("times")
    if not isinstance(times, list) or len(times) < 3:
        return None
    try:
        marcas = sorted(int(t) for t in times)
    except (TypeError, ValueError):
        return None
    deltas = sorted(b - a for a, b in zip(marcas, marcas[1:]) if b > a)
    if not deltas:
        return None
    paso = deltas[len(deltas) // 2]
    etiqueta = _PASOS_CONOCIDOS.get(paso)
    return etiqueta or f"{round(paso / 60_000)}m"


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
