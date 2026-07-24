from research.coinsignals_backtest import parse_signal
from research.coinsignals_btc_swing import (
    entry_tranches,
    equal_notional_average,
    has_hold_annotation,
    parse_global_management,
    parse_management,
    replay_swing,
)


def message(text, *, date="2024-12-31T23:59:00+00:00"):
    return {"id": 1, "date": date, "edit_date": None, "text": text}


def signal_text():
    return """LONG BTCUSDT
Entry: 100 - 90
Target 1: 110
Target 2: 120
Target 3: 130
Target 4: 140
Stoploss: 80
Leverage: 10x"""


def test_management_parser_does_not_treat_close_to_sl_as_close_order():
    assert parse_management("#BTC short close to SL. SL moved to 93666") == {
        "kind": "sl_update",
        "price": 93666,
    }
    assert parse_management("#BTC Wait for the full 4-hour candle to close above SL") == {
        "kind": "stop_confirmation",
        "timeframe": "4h",
    }
    assert parse_management("New BTC Long: if full 4hr candle closes below stoploss") == {
        "kind": "stop_confirmation",
        "timeframe": "4h",
    }


def test_management_parser_recognizes_reliable_closures():
    assert parse_management("Close #BTC at Entry")["kind"] == "close_be"
    assert parse_management("close #BTC in profit.")["kind"] == "close_market"
    assert parse_management("Close #BTC Tiny profit")["kind"] == "close_market"
    assert parse_management("#BTC/USDT Closed due to opposite direction signal")["kind"] == "close_market"
    assert parse_management("#BTC/USDT Closed at stoploss after reaching take profit") is None


def test_management_parser_recognizes_confirmed_entry_prices():
    assert parse_management("#BTC/USDT Entry 1 ✅ Average Entry Price: 65,900") == {
        "kind": "entry_first_confirmed",
        "price": 65900,
    }


def test_global_management_parser_recognizes_portfolio_closures_only():
    assert parse_global_management("BTC & SOL Shorts Hits Tp1, Close Short Positions") == {
        "kind": "close_market",
        "direction": "short",
    }
    assert parse_global_management("Close all Shorts : #BTC @ 66k #ETH @ 1850") == {
        "kind": "close_market",
        "direction": "short",
    }
    assert parse_global_management("#BTC #SOL #BNB Back to entry") == {
        "kind": "close_be",
        "direction": None,
    }
    assert parse_global_management("BTC is close to CME Gap") is None


def test_hold_annotation_is_distinguished_from_other_edits():
    assert has_hold_annotation("Target 4: 90944 / HOLD") is True
    assert has_hold_annotation("Target 4: 90944") is False
    assert parse_management("#BTC/USDT All entries achieved Average Entry Price: 65,500") == {
        "kind": "entry_all_confirmed",
        "price": 65500,
    }


def test_ladder_fills_both_entries_and_holds_through_tp4():
    signal = parse_signal(message(signal_text()))
    candles = [
        {"t": 1735689600000, "o": 100, "h": 101, "l": 89, "c": 95},
        {"t": 1735690500000, "o": 100, "h": 115, "l": 95, "c": 110},
        {"t": 1735691400000, "o": 120, "h": 145, "l": 115, "c": 140},
    ]
    row = replay_swing(signal, candles, entry_mode="ladder")
    assert row["status"] == "resolved"
    assert row["entry_avg"] == 94.7368
    assert row["targets_hit"] == 4
    assert row["exit_reason"] == "all_targets"
    assert row["pnl_r_net"] > 1


def test_equal_cash_entries_use_harmonic_not_arithmetic_average():
    signal = parse_signal(message(signal_text()))
    assert round(equal_notional_average((100, 90)), 4) == 94.7368
    tranches = entry_tranches(signal, "ladder")
    assert tranches[0][1] < tranches[1][1]
    assert round(sum(price * qty for price, qty in tranches), 4) == 94.7368


def test_stop_wins_entry_candle_and_target_is_not_credited():
    signal = parse_signal(message(signal_text()))
    candles = [{"t": 1735689600000, "o": 100, "h": 120, "l": 79, "c": 90}]
    row = replay_swing(signal, candles)
    assert row["exit_reason"] == "stop"
    assert row["targets_hit"] == 0


def test_close_at_entry_exits_remaining_position_after_tp1():
    signal = parse_signal(message(signal_text()))
    candles = [
        {"t": 1735689600000, "o": 100, "h": 101, "l": 99, "c": 100},
        {"t": 1735690500000, "o": 105, "h": 111, "l": 100, "c": 110},
        {"t": 1735691400000, "o": 95, "h": 100, "l": 90, "c": 95},
    ]
    events = [{"kind": "close_be", "effective_ms": 1735691400000, "message_id": 2, "date": "x"}]
    row = replay_swing(signal, candles, events)
    assert row["targets_hit"] == 1
    assert row["exit_reason"] == "close_be"
    assert row["pnl_r_net"] > 0


def test_numeric_sl_update_changes_the_realized_loss():
    signal = parse_signal(message(signal_text()))
    candles = [
        {"t": 1735689600000, "o": 100, "h": 101, "l": 99, "c": 100},
        {"t": 1735690500000, "o": 95, "h": 96, "l": 89, "c": 90},
    ]
    events = [{"kind": "sl_update", "price": 90, "effective_ms": 1735690500000, "message_id": 2, "date": "x"}]
    managed = replay_swing(signal, candles, events)
    assert managed["exit_reason"] == "stop"
    assert managed["current_stop"] == 90
    assert managed["pnl_r_net"] > -1


def test_channel_entry_confirmation_can_fill_inside_discarded_publication_bar():
    signal = parse_signal(message(signal_text()))
    candles = [
        {"t": 1735689600000, "o": 105, "h": 106, "l": 101, "c": 104},
    ]
    events = [
        {
            "kind": "entry_first_confirmed",
            "price": 100,
            "effective_ms": 1735689600000,
            "message_id": 2,
            "date": "x",
        }
    ]
    market = replay_swing(signal, candles, entry_mode="first")
    confirmed = replay_swing(signal, candles, events, entry_mode="channel")
    assert market["status"] == "not_filled"
    assert confirmed["status"] == "open"


def test_runner_profile_keeps_more_size_for_tp4():
    signal = parse_signal(message(signal_text()))
    candles = [
        {"t": 1735689600000, "o": 100, "h": 101, "l": 99, "c": 100},
        {"t": 1735690500000, "o": 105, "h": 111, "l": 100, "c": 110},
        {"t": 1735691400000, "o": 125, "h": 145, "l": 115, "c": 140},
    ]
    equal = replay_swing(signal, candles, entry_mode="first")
    runner = replay_swing(signal, candles, entry_mode="first", target_profile="runner")
    assert runner["targets_hit"] == 4
    assert runner["pnl_r_net"] > equal["pnl_r_net"]


def test_4h_stop_confirmation_ignores_wick_and_exits_on_close():
    signal = parse_signal(message(signal_text()))
    candles = []
    for index in range(16):
        candles.append(
            {
                "t": 1735689600000 + index * 900000,
                "o": 100,
                "h": 101,
                "l": 79 if index == 1 else 85,
                "c": 79 if index == 15 else 90,
            }
        )
    events = [
        {
            "kind": "stop_confirmation",
            "timeframe": "4h",
            "effective_ms": 1735689600000,
            "message_id": 2,
            "date": "x",
        }
    ]
    direct = replay_swing(signal, candles, entry_mode="first")
    confirmed = replay_swing(signal, candles, events, entry_mode="first")
    assert direct["exit_reason"] == "stop"
    assert confirmed["exit_reason"] == "stop_on_close"
    assert confirmed["resolution_time"] > direct["resolution_time"]


def test_tp1_closes_25_percent_and_moves_the_rest_to_break_even():
    signal = parse_signal(message(signal_text()))
    candles = [
        {"t": 1735689600000, "o": 100, "h": 101, "l": 99, "c": 100},
        {"t": 1735690500000, "o": 105, "h": 111, "l": 100, "c": 110},
        {"t": 1735691400000, "o": 100, "h": 105, "l": 99, "c": 100},
    ]
    baseline = replay_swing(signal, candles, entry_mode="first")
    protected = replay_swing(signal, candles, entry_mode="first", be_after_tp1=True)
    assert baseline["status"] == "open"
    assert protected["status"] == "resolved"
    assert protected["targets_hit"] == 1
    assert protected["exit_reason"] == "break_even"
    assert protected["pnl_r_net"] > 0


def test_tp1_break_even_does_not_prevent_continuation_to_tp4():
    signal = parse_signal(message(signal_text()))
    candles = [
        {"t": 1735689600000, "o": 100, "h": 101, "l": 99, "c": 100},
        {"t": 1735690500000, "o": 105, "h": 111, "l": 101, "c": 110},
        {"t": 1735691400000, "o": 120, "h": 145, "l": 105, "c": 140},
    ]
    row = replay_swing(signal, candles, entry_mode="first", be_after_tp1=True)
    assert row["exit_reason"] == "all_targets"
    assert row["targets_hit"] == 4


def test_conservative_same_bar_policy_stops_after_tp1_before_later_targets():
    signal = parse_signal(message(signal_text()))
    candles = [
        {"t": 1735689600000, "o": 100, "h": 101, "l": 99, "c": 100},
        {"t": 1735690500000, "o": 110, "h": 145, "l": 99, "c": 120},
    ]
    row = replay_swing(
        signal,
        candles,
        entry_mode="first",
        be_after_tp1=True,
        be_same_bar_conservative=True,
    )
    assert row["exit_reason"] == "break_even_same_bar"
    assert row["targets_hit"] == 1


def test_step_policy_locks_tp1_after_tp2():
    signal = parse_signal(message(signal_text()))
    candles = [
        {"t": 1735689600000, "o": 100, "h": 101, "l": 99, "c": 100},
        {"t": 1735690500000, "o": 110, "h": 121, "l": 101, "c": 120},
        {"t": 1735691400000, "o": 115, "h": 116, "l": 109, "c": 110},
    ]
    row = replay_swing(signal, candles, entry_mode="first", stop_policy="step")
    assert row["targets_hit"] == 2
    assert row["exit_reason"] == "locked_profit"
    assert row["pnl_r_net"] > 0


def test_custom_target_weights_change_runner_payoff():
    signal = parse_signal(message(signal_text()))
    candles = [
        {"t": 1735689600000, "o": 100, "h": 101, "l": 99, "c": 100},
        {"t": 1735690500000, "o": 110, "h": 145, "l": 101, "c": 140},
    ]
    front = replay_swing(
        signal,
        candles,
        entry_mode="first",
        target_weights_override=(0.4, 0.3, 0.2, 0.1),
    )
    runner = replay_swing(
        signal,
        candles,
        entry_mode="first",
        target_weights_override=(0.1, 0.2, 0.3, 0.4),
    )
    assert runner["pnl_r_net"] > front["pnl_r_net"]
