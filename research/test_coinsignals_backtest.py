from types import SimpleNamespace

from research.coinsignals_backtest import parse_signal, replay_signal


def message(text, *, mid=10, date="2024-01-01T00:01:00+00:00", edit_date=None):
    return {"id": mid, "date": date, "edit_date": edit_date, "text": text}


def signal_text(direction="LONG", symbol="BTCUSDT"):
    return f"""➡️ {direction} {symbol}
Entry: 100 - 98
Target 1: 110
Target 2: 120
Target 3: 130
Target 4: 140
Stoploss: 90
Leverage: 10x"""


def test_parse_signal_and_linked_reply_events():
    reply = message("#BTC Take-Profit target 1 ✅", mid=11, date="2024-01-01T01:00:00+00:00")
    parsed = parse_signal(message(signal_text()), [reply])
    assert parsed is not None
    assert parsed.symbol == "BTCUSDT"
    assert parsed.entry_first == 100
    assert parsed.entry_low == 98
    assert parsed.targets == (110, 120, 130, 140)
    assert parsed.reply_events[0]["kind"] == "tp"


def test_parse_rejects_levels_on_wrong_side():
    assert parse_signal(message(signal_text().replace("Stoploss: 90", "Stoploss: 105"))) is None


def test_replay_never_uses_publication_candle_for_fill():
    parsed = parse_signal(message(signal_text()))
    candles = [
        {"t": 1704067200000, "o": 100, "h": 101, "l": 99, "c": 100},
        {"t": 1704068100000, "o": 105, "h": 106, "l": 101, "c": 104},
    ]
    assert replay_signal(parsed, candles)["status"] == "not_filled"


def test_fill_candle_stop_wins_and_tp_is_not_credited():
    parsed = parse_signal(message(signal_text()))
    candles = [
        {"t": 1704068100000, "o": 100, "h": 115, "l": 89, "c": 105},
    ]
    row = replay_signal(parsed, candles)
    assert row["status"] == "resolved"
    assert row["stopped"] is True
    assert row["targets_hit"] == 0


def test_targets_are_sequential_and_stop_wins_later_ambiguity():
    parsed = parse_signal(message(signal_text()))
    candles = [
        {"t": 1704068100000, "o": 101, "h": 105, "l": 99, "c": 102},
        {"t": 1704069000000, "o": 105, "h": 125, "l": 100, "c": 120},
        {"t": 1704069900000, "o": 120, "h": 135, "l": 89, "c": 95},
    ]
    row = replay_signal(parsed, candles)
    assert row["targets_hit"] == 2
    assert row["stopped"] is True
    assert row["equal_partial_r_net"] < row["be_after_tp1_r_net"]


def test_replay_accepts_precomputed_timestamps_without_changing_result():
    parsed = parse_signal(message(signal_text()))
    candles = [
        {"t": 1704068100000, "o": 101, "h": 105, "l": 99, "c": 102},
        {"t": 1704069000000, "o": 105, "h": 115, "l": 100, "c": 110},
    ]
    expected = replay_signal(parsed, candles)
    assert replay_signal(parsed, candles, [candle["t"] for candle in candles]) == expected


def test_replay_can_use_range_midpoint_as_entry():
    parsed = parse_signal(message(signal_text()))
    candles = [
        {"t": 1704068100000, "o": 99, "h": 100, "l": 98.5, "c": 99},
        {"t": 1704069000000, "o": 105, "h": 111, "l": 99, "c": 110},
    ]
    first = replay_signal(parsed, candles)
    midpoint = replay_signal(parsed, candles, entry_price=99)
    assert first["entry_price"] == 100
    assert midpoint["entry_price"] == 99
    assert midpoint["tp1_r_net"] > first["tp1_r_net"]
