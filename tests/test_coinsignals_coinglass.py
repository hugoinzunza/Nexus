import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import modules.coinsignals.coinglass as coinglass
from modules.coinsignals.coinglass import (
    backfill_market_history,
    fetch_historical_contexts,
    fetch_market_context,
    update_market_context,
)


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_fetch_market_context_normalizes_available_indicators_without_leaking_key():
    def payload_for(url):
        if "price/history" in url:
            return [{"time": 1, "open": 100, "high": 102, "low": 99, "close": 101}]
        if "funding-rate" in url:
            return [{"close": "0.007601"}]
        if "open-interest/exchange-list" in url:
            return [{"exchange": "Binance", "open_interest_usd": 70}]
        if "open-interest" in url:
            return [{"close": "104816.674"}]
        if "liquidation/exchange-list" in url:
            return [{"exchange": "Binance", "longLiquidation_usd": 250_000,
                     "shortLiquidation_usd": 1_090_000}]
        if "liquidation" in url:
            return [{
            "aggregated_long_liquidation_usd": 250_000,
            "aggregated_short_liquidation_usd": 1_090_000,
            }]
        if "global-long-short" in url:
            return [{"global_account_long_percent": 61}]
        if "top-long-short-account" in url:
            return [{"top_account_long_percent": 62}]
        if "top-long-short-position" in url:
            return [{"long_position_percentage": 0.6198}]
        if "taker-buy-sell-volume/exchange-list" in url:
            return {"buy_ratio": 48, "sell_ratio": 52, "exchange_list": []}
        if "taker-buy-sell-volume" in url:
            return [{"aggregated_buy_volume_usd": 48, "aggregated_sell_volume_usd": 52}]
        if "aggregated-ask-bids" in url:
            return [{"aggregated_bids_usd": 80, "aggregated_asks_usd": 100}]
        if "orderbook" in url:
            return [{"bids_usd": 66, "asks_usd": 100}]
        raise AssertionError(url)

    def opener(request, timeout):
        assert timeout == 20
        return FakeResponse(
            {"code": "0", "msg": "success", "data": payload_for(request.full_url)},
            {"API-KEY-MAX-LIMIT": "30", "API-KEY-USE-LIMIT": "5"},
        )

    context = fetch_market_context(
        "private-key",
        opener=opener,
        captured_at="2026-07-24T15:00:00+00:00",
    )

    assert context["research_only"] is True
    assert context["status"] == "ok"
    assert context["indicators"]["funding"]["close_pct"] == [0.007601]
    assert context["indicators"]["open_interest"]["close_usd"] == [104816.674]
    assert context["indicators"]["liquidations"]["bars"] == [{
        "long_musd": 0.25,
        "short_musd": 1.09,
    }]
    assert context["indicators"]["top_traders"]["long_pct"] == [61.98]
    assert context["indicators"]["orderbook"]["bid_ask_ratio"] == [0.66]
    assert context["indicators"]["global_accounts"]["long_pct"] == [61.0]
    assert context["indicators"]["top_accounts"]["long_pct"] == [62.0]
    assert context["indicators"]["orderbook_aggregated"]["bid_ask_ratio"] == [0.8]
    assert context["quota"] == {"max_per_minute": 30, "used_this_minute": 5}
    assert "private-key" not in json.dumps(context)


def test_fetch_market_context_falls_back_to_4h_and_reports_real_interval():
    def opener(request, timeout):
        if "interval=1h" in request.full_url:
            return FakeResponse({"code": "400", "msg": "interval unavailable"})
        if "price/history" in request.full_url:
            data = [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}]
        elif "open-interest/exchange-list" in request.full_url:
            data = []
        elif "liquidation/exchange-list" in request.full_url:
            data = []
        elif "liquidation" in request.full_url:
            data = [{
                "aggregated_long_liquidation_usd": 1,
                "aggregated_short_liquidation_usd": 2,
            }]
        elif "global-long-short" in request.full_url:
            data = [{"global_account_long_percent": 60}]
        elif "top-long-short-account" in request.full_url:
            data = [{"top_account_long_percent": 60}]
        elif "top-long-short-position" in request.full_url:
            data = [{"long_position_percentage": 0.6}]
        elif "taker-buy-sell-volume/exchange-list" in request.full_url:
            data = {"buy_ratio": 50, "sell_ratio": 50, "exchange_list": []}
        elif "taker-buy-sell-volume" in request.full_url:
            data = [{"aggregated_buy_volume_usd": 1, "aggregated_sell_volume_usd": 1}]
        elif "aggregated-ask-bids" in request.full_url:
            data = [{"aggregated_bids_usd": 2, "aggregated_asks_usd": 1}]
        elif "orderbook" in request.full_url:
            data = [{"bids_usd": 2, "asks_usd": 1}]
        else:
            data = [{"close": "1"}]
        return FakeResponse({"code": "0", "msg": "success", "data": data})

    context = fetch_market_context("key", opener=opener)

    assert context["status"] == "ok"
    assert set(context["intervals"].values()) == {"4h", "realtime"}


def test_update_market_context_uses_cache_and_writes_private_file(tmp_path):
    path = tmp_path / "context.json"
    calls = []

    def fetcher(_key):
        calls.append(True)
        return {
            "research_only": True,
            "captured_at": "2026-07-24T15:00:00+00:00",
            "status": "ok",
            "indicators": {"funding": {"close_pct": [0.01]}},
        }

    first, history = update_market_context(
        "key",
        path,
        now=datetime(2026, 7, 24, 15, 0, tzinfo=timezone.utc),
        fetcher=fetcher,
    )
    second, second_history = update_market_context(
        "key",
        path,
        now=datetime(2026, 7, 24, 15, 4, tzinfo=timezone.utc),
        fetcher=lambda _key: (_ for _ in ()).throw(AssertionError("cache miss")),
    )

    assert first == second
    assert len(calls) == 1
    assert history == second_history
    assert path.stat().st_mode & 0o777 == 0o600
    assert "key" not in path.read_text()


def test_update_market_context_keeps_last_valid_data_on_api_failure(tmp_path):
    path = tmp_path / "context.json"
    previous = {
        "research_only": True,
        "captured_at": "2026-07-24T14:00:00+00:00",
        "status": "ok",
        "indicators": {"open_interest": {"close_usd": [100]}},
    }
    path.write_text(json.dumps({
        "research_only": True,
        "latest": previous,
        "history": [previous],
    }))

    latest, history = update_market_context(
        "key",
        path,
        now=datetime(2026, 7, 24, 15, 0, tzinfo=timezone.utc),
        fetcher=lambda _key: (_ for _ in ()).throw(RuntimeError("HTTP 429")),
    )

    assert latest["status"] == "stale"
    assert latest["indicators"] == previous["indicators"]
    assert "429" in latest["last_error"]
    assert history == [previous]


def test_update_market_context_refreshes_after_five_minutes(tmp_path):
    path = tmp_path / "context.json"
    now = datetime(2026, 7, 24, 15, 0, tzinfo=timezone.utc)
    stale = {
        "research_only": True,
        "captured_at": (now - timedelta(minutes=6)).isoformat(),
        "status": "ok",
        "indicators": {},
    }
    path.write_text(json.dumps({"latest": stale, "history": [stale]}))

    fresh = dict(stale, captured_at=now.isoformat())
    latest, history = update_market_context(
        "key",
        path,
        now=now,
        fetcher=lambda _key: fresh,
    )

    assert latest == fresh
    assert history == [stale, fresh]


def test_fetch_historical_contexts_aligns_windows_and_marks_backfill(monkeypatch):
    monkeypatch.setattr(coinglass, "HISTORICAL_ENDPOINTS", (
        ("price", "/price", {"symbol": "BTCUSDT", "interval": "1h"}),
        ("open_interest", "/oi", {"symbol": "BTC", "interval": "1h"}),
    ))

    def opener(request, timeout):
        assert timeout == 30
        query = parse_qs(urlparse(request.full_url).query)
        timestamp = int(query["start_time"][0]) + 4 * 60 * 60 * 1000
        if "/price" in request.full_url:
            row = {
                "time": timestamp, "open": 100, "high": 102,
                "low": 99, "close": 101, "volume_usd": 1_000_000,
            }
        else:
            row = {"time": timestamp, "close": 1_000_000}
        return FakeResponse({"code": "0", "data": [row]})

    rows = fetch_historical_contexts(
        "key",
        opener=opener,
        now=datetime(2026, 7, 24, tzinfo=timezone.utc),
        days=2,
        window_days=1,
    )

    assert len(rows) == 2
    assert all(row["history_origin"] == "backfill" for row in rows)
    assert all(row["intervals"] == {"price": "4h", "open_interest": "4h"} for row in rows)
    assert rows[1]["indicators"]["price"]["candles"][-1]["close"] == 101
    assert rows[1]["indicators"]["open_interest"]["close_usd"] == [
        1_000_000.0, 1_000_000.0,
    ]


def test_backfill_market_history_preserves_forward_bar(monkeypatch, tmp_path):
    path = tmp_path / "context.json"
    forward = {
        "captured_at": "2026-07-24T16:00:00+00:00",
        "indicators": {"open_interest": {"times": [2]}},
    }
    historical = {
        "history_origin": "backfill",
        "captured_at": "2026-07-23T16:00:00+00:00",
        "indicators": {"open_interest": {"times": [1]}},
    }
    path.write_text(json.dumps({"latest": forward, "history": [forward]}))
    monkeypatch.setattr(
        coinglass,
        "fetch_historical_contexts",
        lambda *_args, **_kwargs: [historical],
    )

    latest, history = backfill_market_history("key", path)

    assert latest == forward
    assert history == [historical, forward]
    assert json.loads(path.read_text())["history"] == history
