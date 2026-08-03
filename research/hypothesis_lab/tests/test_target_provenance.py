from __future__ import annotations

import copy

import pytest

from modules.trading import smc_live
from research.hypothesis_lab.contracts import ContractError
from research.hypothesis_lab.datasets import validate_setup_provenance


def candle(t, high, low):
    return {"t": t, "o": 100.0, "h": high, "l": low, "c": 100.0, "v": 1.0}


def setup_row():
    return {
        "decision_index": 1, "decision_timestamp": 2000,
        "activation_index": 2, "activation_timestamp": 3000,
        "original_tp": 120.0,
        "original_tp_source": {
            "kind": "confirmed_swing_level", "type": "high", "price": 120.0,
            "source_t": 1000, "confirm_t": 2000,
        },
    }


def test_range_fallback_records_actual_extreme_timestamps():
    rows = [candle(1000, 110, 95), candle(2000, 130, 98), candle(3000, 115, 90)]
    result = smc_live._range(rows)
    assert result["source_kind"] == "rolling_extreme"
    assert result["strong_high_t"] == 2000
    assert result["weak_low_t"] == 3000


def test_opposite_liquidity_preserves_confirmed_source():
    levels = [{"type": "high", "kind": "weak", "price": 120.0,
               "t": 1000, "confirm_t": 2000}]
    price, label, source = smc_live._opposite_liquidity(levels, True, 100.0, 130.0, 80.0)
    assert (price, label) == (120.0, "Weak High")
    assert source == {"kind": "confirmed_swing_level", "type": "high", "price": 120.0,
                      "source_t": 1000, "confirm_t": 2000}


def test_dataset_rejects_future_or_mismatched_target_provenance():
    rows = [candle(1000, 1, 0), candle(2000, 1, 0), candle(3000, 1, 0)]
    valid = setup_row()
    validate_setup_provenance(valid, rows, 0)

    future = copy.deepcopy(valid)
    future["original_tp_source"]["confirm_t"] = 3000
    with pytest.raises(ContractError, match="not confirmed"):
        validate_setup_provenance(future, rows, 0)

    mismatch = copy.deepcopy(valid)
    mismatch["original_tp_source"]["price"] = 121.0
    with pytest.raises(ContractError, match="price mismatch"):
        validate_setup_provenance(mismatch, rows, 0)
