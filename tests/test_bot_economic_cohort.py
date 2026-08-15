import copy
import json
from pathlib import Path

import pytest

from modules.bot.bot_store import BotStore
from modules.bot.economic_cohort import (
    EconomicCohortError,
    load_and_validate,
    operational_status,
    policy_projection,
    sha256_value,
    trade_metadata,
)


ROOT = Path(__file__).resolve().parents[1]


def _config():
    return json.loads((ROOT / "config" / "nexus.json").read_text())["modules"]["bot"]


def test_frozen_protocol_matches_complete_bot_policy():
    cfg = _config()
    protocol, protocol_sha = load_and_validate(cfg)

    assert protocol["cohort_id"] == "ECON-COHORT-001"
    assert protocol_sha == cfg["economic_cohort"]["protocol_sha256"]
    assert sha256_value(policy_projection(cfg)) == protocol["frozen_bot_policy_sha256"]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("risk_usd_fixed",), 10.0),
        (("entry_profiles",), [{"min_rr": 4}]),
        (("pairs",), ["BTCUSDT"]),
        (("watchdog", "tolerancia_r"), 0.5),
    ],
)
def test_any_policy_change_fails_closed(path, value):
    cfg = copy.deepcopy(_config())
    target = cfg
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(EconomicCohortError, match="politica completa"):
        load_and_validate(cfg)


def test_live_mode_cannot_join_dry_cohort():
    cfg = copy.deepcopy(_config())
    cfg["live"] = True
    with pytest.raises(EconomicCohortError, match="exclusivamente dry"):
        load_and_validate(cfg)


def test_trade_keeps_cohort_and_hashes(tmp_path):
    cfg = _config()
    metadata = trade_metadata(cfg, now_ms=1786768200000)
    store = BotStore(path=str(tmp_path / "book.json"))
    rec = {
        "setup_id": "BTC_USDT:1",
        "symbol": "BTCUSDT",
        "pair": "BTC_USDT",
        "dir": "long",
        "mode": "dry",
        "qty": 0.001,
        "entry_price": 100.0,
        **metadata,
    }
    saved = store.open_trade(rec)

    assert saved["economic_cohort_id"] == "ECON-COHORT-001"
    assert saved["economic_protocol_sha256"] == cfg["economic_cohort"]["protocol_sha256"]
    assert saved["economic_policy_sha256"]


def test_operational_status_hides_outcomes_until_exact_stop():
    cfg = _config()
    metadata = trade_metadata(cfg, now_ms=1786768200000)
    trades = [
        {
            "setup_id": f"s:{i}",
            "status": "cerrada",
            "closed_at": i,
            "opened_at": 1786768200 + i,
            "pnl_usd": 999999.0,
            **metadata,
        }
        for i in range(49)
    ]
    status = operational_status(trades, cfg, now_ms=1786768200001)

    assert status["status"] == "collecting"
    assert status["closed"] == 49
    assert status["outcome_metrics_hidden_until_close"] is True
    assert "pnl_usd" not in status
    assert status["automatic_live"] is False


def test_exact_n_or_deadline_are_the_only_stops():
    cfg = _config()
    metadata = trade_metadata(cfg, now_ms=1786768200000)
    trades = [
        {"setup_id": f"s:{i}", "status": "cerrada", "closed_at": i,
         "opened_at": 1786768200 + i, **metadata}
        for i in range(50)
    ]

    by_n = operational_status(trades, cfg, now_ms=1786768200001)
    by_date = operational_status([], cfg, now_ms=1791606600000)

    assert by_n["status"] == "ready_for_single_evaluation"
    assert by_n["stop_reason"] == "n_exact"
    assert by_date["status"] == "ready_for_single_evaluation"
    assert by_date["stop_reason"] == "deadline"


def test_bot_module_adds_cohort_to_state_without_outcome_metrics():
    from modules.bot.module import BotModule

    data = {"trades": []}
    BotModule._add_economic_cohort(data, cfg=_config())

    assert data["economic_cohort"]["status"] == "collecting"
    assert data["economic_cohort"]["automatic_live"] is False
    assert "avg_net_r" not in data["economic_cohort"]
