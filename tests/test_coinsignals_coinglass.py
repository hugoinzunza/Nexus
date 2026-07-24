import json
from datetime import datetime, timedelta, timezone

from modules.coinsignals.coinglass import fetch_market_context, update_market_context


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
    payloads = {
        "funding-rate": [{"close": "0.007601"}],
        "open-interest": [{"close": "104816.674"}],
        "liquidation": [{
            "aggregated_long_liquidation_usd": 250_000,
            "aggregated_short_liquidation_usd": 1_090_000,
        }],
        "top-long-short": [{"long_position_percentage": 0.6198}],
        "orderbook": [{"bids_usd": 66, "asks_usd": 100}],
    }

    def opener(request, timeout):
        assert timeout == 20
        match = next(key for key in payloads if key in request.full_url)
        return FakeResponse(
            {"code": "0", "msg": "success", "data": payloads[match]},
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
    assert context["quota"] == {"max_per_minute": 30, "used_this_minute": 5}
    assert "private-key" not in json.dumps(context)


def test_fetch_market_context_falls_back_to_4h_and_reports_real_interval():
    def opener(request, timeout):
        if "interval=1h" in request.full_url:
            return FakeResponse({"code": "400", "msg": "interval unavailable"})
        if "liquidation" in request.full_url:
            data = [{
                "aggregated_long_liquidation_usd": 1,
                "aggregated_short_liquidation_usd": 2,
            }]
        elif "top-long-short" in request.full_url:
            data = [{"long_position_percentage": 0.6}]
        elif "orderbook" in request.full_url:
            data = [{"bids_usd": 2, "asks_usd": 1}]
        else:
            data = [{"close": "1"}]
        return FakeResponse({"code": "0", "msg": "success", "data": data})

    context = fetch_market_context("key", opener=opener)

    assert context["status"] == "ok"
    assert set(context["intervals"].values()) == {"4h"}


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
