from __future__ import annotations

import copy
import json
from pathlib import Path

from research.hypothesis_lab import shadow_exit as shadow


def _protocol():
    protocol, digest = shadow.load_protocol()
    return protocol, digest


def _setup(**changes):
    base = {
        "key": "BTC_USDT:1h:long:100",
        "pair": "BTC_USDT",
        "dir": "long",
        "poi_tf": "1h",
        "entry": 100.0,
        "sl": 90.0,
        "tp": 150.0,
        "ts_created": 1785593249,
        "ts_activated": 1785593250,
    }
    return {**base, **changes}


def _bar(t, o, h, low, c):
    return {"t": t, "close_t": t + 59_999, "o": o, "h": h, "l": low, "c": c}


def _spread():
    return {
        "bid": 99.99, "ask": 100.01, "full_spread_rate": 0.0002,
        "observed_at_ms": 1785593500000,
        "source": "test",
    }


def test_shadow_protege_en_barra_siguiente_y_conserva_runner_original():
    protocol, _ = _protocol()
    start = 1785593220000
    candles = [
        _bar(start, 101, 104, 95, 100),
        _bar(start + 60_000, 100, 131, 99, 130),
        _bar(start + 120_000, 125, 126, 99, 101),
        _bar(start + 180_000, 102, 151, 98, 149),
    ]
    result = shadow.simulate_shadow(
        _setup(ts_activated=(start + 20_000) // 1000), candles, _spread(),
        protocol, start + 240_000,
    )
    assert result["trigger_3r_at_ms"] == start + 60_000
    assert result["protected_branch"]["exit_reason"] == "stop_protected"
    assert result["protected_branch"]["gross_r"] == 0.0
    assert result["original_branch"]["exit_reason"] == "target_original"
    assert result["original_branch"]["gross_r"] == 5.0
    assert result["post_3r"]["mae_r"] == -0.2
    assert result["post_3r"]["mfe_r"] == 5.1
    assert result["protected_branch"]["net_r"] < 0.0


def test_activation_bar_no_acredita_target_y_si_acredita_stop():
    protocol, _ = _protocol()
    start = 1785593220000
    candles = [_bar(start, 100, 160, 89, 120)]
    result = shadow.simulate_shadow(
        _setup(ts_activated=(start + 20_000) // 1000), candles, _spread(),
        protocol, start + 60_000,
    )
    assert result["original_branch"]["exit_reason"] == "stop_original"
    assert result["protected_branch"]["exit_reason"] == "stop_original"
    assert result["trigger_3r_at_ms"] is None


def test_build_snapshot_es_forward_pareado_idempotente_y_no_muta_input():
    protocol, digest = _protocol()
    start = protocol["cohort_start_ms"]
    setups = [
        _setup(ts_activated=start // 1000 - 1),
        _setup(key="ETH_USDT:1h:long:100", pair="ETH_USDT",
               ts_activated=start // 1000 + 1),
    ]
    before = copy.deepcopy(setups)
    candles = [
        _bar(start, 100, 104, 95, 100),
        _bar(start + 60_000, 100, 151, 95, 150),
    ]
    kwargs = {
        "now_ms": start + 120_000,
        "candle_fetcher": lambda *_: candles,
        "spread_fetcher": lambda *_: _spread(),
    }
    one = shadow.build_snapshot(setups, protocol, digest, **kwargs)
    two = shadow.build_snapshot(setups, protocol, digest, **kwargs)
    assert setups == before
    assert one == two
    assert one["meta"]["n_eligible"] == 1
    assert one["meta"]["writes_to_bot_or_diario"] == 0
    assert one["records"][0]["operation_id"] == two["records"][0]["operation_id"]


def test_cierre_pareado_congela_costos_y_no_se_reestima_con_spread_futuro():
    protocol, digest = _protocol()
    start = protocol["cohort_start_ms"]
    setup = _setup(ts_activated=start // 1000 + 1)
    candles = [
        _bar(start, 100, 104, 95, 100),
        _bar(start + 60_000, 100, 151, 95, 150),
    ]
    first = shadow.build_snapshot(
        [setup], protocol, digest, now_ms=start + 120_000,
        candle_fetcher=lambda *_: candles,
        spread_fetcher=lambda *_: _spread(),
    )
    frozen = first["records"][0]
    assert frozen["observation_status"] == "paired_closed"
    second = shadow.build_snapshot(
        [setup], protocol, digest, now_ms=start + 180_000,
        candle_fetcher=lambda *_: (_ for _ in ()).throw(AssertionError("no refetch")),
        spread_fetcher=lambda *_: (_ for _ in ()).throw(AssertionError("no respread")),
        previous_records=first["records"],
    )
    assert second["records"][0] == frozen


def test_atomic_output_y_aislamiento_estan_fijados(tmp_path):
    payload = {"meta": {"research_only": True}, "records": []}
    output = tmp_path / "shadow.json"
    shadow.write_atomic(output, payload)
    assert json.loads(output.read_text()) == payload
    assert not list(tmp_path.glob("*.tmp"))
    source = Path(shadow.__file__).read_text(encoding="utf-8")
    assert "modules.bot" not in source
    assert "modules.trading" not in source
    assert "urlopen" in source
    assert 'method="POST"' not in source


def test_protocolo_predefine_promocion_y_descarte_sin_editarse():
    protocol, digest = _protocol()
    decision = protocol["decision_protocol"]
    assert decision["minimum_paired_closed_operations"] == 100
    assert decision["minimum_operations_reaching_3r"] == 25
    assert decision["confidence"]["level"] == 0.95
    assert decision["promotion_requires_all"]["relative_max_drawdown_reduction"] == 0.1
    assert decision["rule_changes_after_start"] == "forbidden"
    assert protocol["governance"]["execution_enabled"] is False
    assert digest == "138c49a8e5f82fb1ab65d2d246d8ce53642dbe4cd324850983b20c13ec6bcbc6"


def test_decision_no_promueve_antes_de_la_muestra_minima():
    protocol, _ = _protocol()
    decision = shadow.evaluate_decision([], protocol, protocol["cohort_start_ms"])
    assert decision["status"] == "collecting_insufficient_evidence"
    assert decision["automatic_promotion"] is False


def test_decision_exige_todos_los_criterios_predefinidos():
    protocol, _ = _protocol()
    start = protocol["cohort_start_ms"]
    records = []
    for index in range(100):
        baseline = 2.0 if index % 2 == 0 else -1.0
        candidate = 2.2 if index % 2 == 0 else -0.5
        records.append({
            "operation_id": f"op_{index}",
            "entry_at_ms": start + (index % 12) * 7 * 86_400_000,
            "observation_status": "paired_closed",
            "trigger_3r_at_ms": start if index < 25 else None,
            "original_branch": {"net_r": baseline},
            "protected_branch": {"net_r": candidate},
        })
    decision = shadow.evaluate_decision(
        records, protocol, start + 12 * 7 * 86_400_000,
    )
    assert decision["minimum_sample_ready"] is True
    assert decision["status"] == "promotion_evidence_met_manual_review_required"
    assert decision["metrics"]["paired_delta_ci95"][0] > 0
