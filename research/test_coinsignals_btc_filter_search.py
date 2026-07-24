from copy import deepcopy

from research.coinsignals_btc_filter_search import (
    add_shadow_features,
    market_features,
    select_on_train,
)


def _candles(count=3000):
    return [
        {"t": index * 900_000, "c": 100 + index * 0.01, "o": 0, "h": 0, "l": 0}
        for index in range(count)
    ]


def test_market_features_ignore_future_candles():
    candles = _candles()
    times = [row["t"] for row in candles]
    as_of = times[-20]
    expected = market_features(candles, times, as_of)
    changed = deepcopy(candles)
    for row in changed[-20:]:
        row["c"] = 1_000_000
    assert market_features(changed, times, as_of) == expected


def test_market_features_do_not_use_current_bar_close():
    candles = _candles()
    times = [row["t"] for row in candles]
    as_of = times[-1]
    expected = market_features(candles, times, as_of)
    candles[-1]["c"] = 1_000_000
    assert market_features(candles, times, as_of) == expected


def test_selection_does_not_read_oos_metrics():
    periods = {
        "2024_H2": {"n": 10},
        "2025_H1": {"n": 10},
        "2025_H2": {"n": 10},
    }
    candidates = [
        {
            "id": "a",
            "train": {"n": 30, "avg_r": 0.2, "profit_factor": 1.4},
            "oos": {"avg_r": -99},
            "positive_train_periods": 2,
            "periods": periods,
        },
        {
            "id": "b",
            "train": {"n": 30, "avg_r": 0.1, "profit_factor": 1.2},
            "oos": {"avg_r": 99},
            "positive_train_periods": 2,
            "periods": periods,
        },
    ]
    assert select_on_train(candidates)["id"] == "a"


def test_selection_requires_temporal_breadth_and_sample():
    broad = {
        "2024_H2": {"n": 5},
        "2025_H1": {"n": 5},
        "2025_H2": {"n": 10},
    }
    candidates = [
        {
            "id": "small",
            "train": {"n": 19, "avg_r": 9, "profit_factor": 99},
            "positive_train_periods": 3,
            "periods": broad,
        },
        {
            "id": "one_period",
            "train": {"n": 50, "avg_r": 8, "profit_factor": 20},
            "positive_train_periods": 1,
            "periods": broad,
        },
        {
            "id": "thin_period",
            "train": {"n": 30, "avg_r": 7, "profit_factor": 10},
            "positive_train_periods": 3,
            "periods": {
                "2024_H2": {"n": 20},
                "2025_H1": {"n": 4},
                "2025_H2": {"n": 6},
            },
        },
        {
            "id": "eligible",
            "train": {"n": 20, "avg_r": 0.1, "profit_factor": 1.2},
            "positive_train_periods": 2,
            "periods": broad,
        },
    ]
    assert select_on_train(candidates)["id"] == "eligible"


def test_shadow_health_uses_only_trades_resolved_before_fill():
    rows = []
    for index in range(6):
        rows.append(
            {
                "fill_time": f"2025-01-{index + 2:02d}T00:00:00+00:00",
                "resolution_time": f"2025-01-{index + 1:02d}T12:00:00+00:00",
                "pnl_r_be_tp1": 1.0,
            }
        )
    future = {
        "fill_time": "2025-02-01T00:00:00+00:00",
        "resolution_time": "2025-02-02T00:00:00+00:00",
        "pnl_r_be_tp1": -100.0,
    }
    enriched = add_shadow_features(rows + [future])
    assert enriched[5]["shadow_avg_5"] == 1.0


def test_unresolved_overlapping_trade_is_not_in_shadow_health():
    rows = [
        {
            "fill_time": "2025-01-01T00:00:00+00:00",
            "resolution_time": "2025-02-01T00:00:00+00:00",
            "pnl_r_be_tp1": 10.0,
        },
        {
            "fill_time": "2025-01-02T00:00:00+00:00",
            "resolution_time": "2025-01-03T00:00:00+00:00",
            "pnl_r_be_tp1": 0.0,
        },
    ]
    assert add_shadow_features(rows)[1]["shadow_resolved_n"] == 0
