from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from research.hypothesis_lab import cost_telemetry as telemetry


def protocol():
    value, digest = telemetry.load_protocol()
    return copy.deepcopy(value), digest


def source(environment="main"):
    return {
        "source_id": f"{environment}_ledger",
        "environment": environment,
        "eligible_mode": "live",
        "inferential_role": "primary_live_only" if environment == "main" else "diagnostic_only",
    }


def trade(**changes):
    base = {
        "setup_id": "BTC:setup:1",
        "symbol": "BTCUSDT",
        "dir": "long",
        "mode": "live",
        "status": "abierta",
        "opened_at": 2_000,
        "closed_at": None,
        "qty": 2.0,
        "entry_price": 101.0,
        "activation_price": 100.0,
        "setup_entry": 99.0,
        "exit_price": None,
        "partials": [],
        "fees_usd": 0.2,
        "pnl_confirmed": False,
    }
    return {**base, **changes}


def test_slippage_positive_al_empeorar_en_ambas_direcciones():
    assert telemetry._adverse_slippage(101.0, 100.0, "long") == pytest.approx(0.01)
    assert telemetry._adverse_slippage(99.0, 100.0, "short") == pytest.approx(0.01)
    assert telemetry._adverse_slippage(99.0, 100.0, "long") == pytest.approx(-0.01)


def test_comision_solo_es_observada_si_income_fue_confirmado():
    p, _ = protocol()
    waiting = telemetry.build_record(trade(), source(), p, 2_001_000)
    confirmed = telemetry.build_record(
        trade(status="cerrada", closed_at=2_100, exit_price=102.0,
              pnl_confirmed=True, fees_usd=0.4),
        source(), p, 2_101_000,
    )
    assert waiting["commission"]["fees_usd"] is None
    assert waiting["coverage"]["confirmed_commission"] is False
    assert confirmed["commission"]["fees_usd"] == 0.4
    assert confirmed["commission"]["roundtrip_fee_rate_of_entry_notional"] == pytest.approx(0.4 / 202)


def test_turnover_incluye_parcial_y_remanente_final():
    value = telemetry._turnover(trade(
        status="cerrada", exit_price=103.0,
        partials=[{"qty": 0.5, "price": 102.0}],
    ))
    assert value["entry_notional_usd"] == 202.0
    assert value["roundtrip_turnover_usd"] == pytest.approx(202 + 0.5 * 102 + 1.5 * 103)


def test_spread_oportuno_se_congela_y_no_se_vuelve_a_consultar():
    p, digest = protocol()
    p["cohort_start_ms"] = 1_000_000
    row = trade(opened_at=2_000)
    calls = []

    def book(symbol, endpoint):
        calls.append((symbol, endpoint))
        return {
            "bid": 100.0, "ask": 100.02, "mid": 100.01,
            "full_spread_rate": 0.0002, "observed_at_ms": 2_001_000,
            "source": "test",
        }

    first = telemetry.build_snapshot(
        {"main_ledger": [row], "testnet_ledger": []}, p, digest,
        now_ms=2_001_000, book_fetcher=book,
    )
    frozen = first["records"][0]["book_after_fill_detection"]
    assert frozen["timely"] is True
    second = telemetry.build_snapshot(
        {"main_ledger": [row], "testnet_ledger": []}, p, digest,
        now_ms=2_002_000, previous_records=first["records"],
        book_fetcher=lambda *_: (_ for _ in ()).throw(AssertionError("no refetch")),
    )
    assert len(calls) == 1
    assert second["records"][0]["book_after_fill_detection"] == frozen


def test_trade_detectado_tarde_no_fabrica_spread_historico():
    p, digest = protocol()
    p["cohort_start_ms"] = 1_000_000
    snapshot = telemetry.build_snapshot(
        {"main_ledger": [trade(opened_at=2_000)], "testnet_ledger": []}, p, digest,
        now_ms=2_010_000,
        book_fetcher=lambda *_: (_ for _ in ()).throw(AssertionError("late fetch")),
    )
    record = snapshot["records"][0]
    assert record["book_after_fill_detection"] is None
    assert record["coverage"]["timely_spread"] is False


def test_dry_y_precohorte_quedan_excluidos_sin_mutar_ledger():
    p, digest = protocol()
    p["cohort_start_ms"] = 2_000_000
    rows = [trade(mode="dry", opened_at=3_000), trade(setup_id="old", opened_at=1_000)]
    before = copy.deepcopy(rows)
    snapshot = telemetry.build_snapshot(
        {"main_ledger": rows, "testnet_ledger": []}, p, digest, now_ms=3_001_000,
    )
    assert rows == before
    assert snapshot["records"] == []
    assert snapshot["meta"]["excluded"] == {"before_cohort_or_ineligible": 1, "dry": 1}


def test_testnet_no_puede_habilitar_revision_de_costos_live():
    p, digest = protocol()
    p["cohort_start_ms"] = 1_000_000
    rows = []
    for index in range(40):
        row = trade(
            setup_id=f"testnet-{index}", opened_at=2_000 + index,
            status="cerrada", closed_at=2_100 + index, exit_price=102.0,
            pnl_confirmed=True,
        )
        rows.append(telemetry.build_record(row, source("testnet"), p, 5_000_000,
                                           book={"bid": 100, "ask": 100.01, "mid": 100.005,
                                                 "full_spread_rate": 0.0001,
                                                 "observed_at_ms": (2_000 + index) * 1000,
                                                 "source": "test"}))
    decision = telemetry.evaluate(rows, p, p["cohort_start_ms"] + 8 * 7 * 86_400_000)
    assert decision["minimum_coverage_ready"] is False
    assert decision["primary_live_counts"]["records"] == 0


def test_actualizacion_del_ledger_conserva_book_y_agrega_fee_confirmado():
    p, _ = protocol()
    book = {"bid": 100, "ask": 100.02, "mid": 100.01, "full_spread_rate": 0.0002,
            "observed_at_ms": 2_001_000, "source": "test"}
    opened = telemetry.build_record(trade(), source(), p, 2_001_000, book=book)
    closed = telemetry.build_record(
        trade(status="cerrada", closed_at=2_100, exit_price=102.0,
              pnl_confirmed=True, fees_usd=0.4),
        source(), p, 2_101_000, previous=opened,
    )
    assert closed["book_after_fill_detection"] == opened["book_after_fill_detection"]
    assert closed["coverage"]["confirmed_commission"] is True


def test_atomicidad_y_aislamiento_de_ejecucion(tmp_path):
    output = tmp_path / "costs.json"
    telemetry.write_atomic(output, {"meta": {"research_only": True}})
    assert json.loads(output.read_text())["meta"]["research_only"] is True
    assert not list(tmp_path.glob("*.tmp"))
    source_text = Path(telemetry.__file__).read_text(encoding="utf-8")
    assert "modules.bot" not in source_text
    assert "modules.trading" not in source_text
    assert 'method="GET"' in source_text
    assert 'method="POST"' not in source_text


def test_input_root_separa_codigo_de_ledgers_persistentes(tmp_path):
    input_root = tmp_path / "runtime"
    main_path = input_root / "data" / "bot_trades.json"
    testnet_path = input_root / "data" / "testnet" / "bot_trades.json"
    main_path.parent.mkdir(parents=True)
    testnet_path.parent.mkdir(parents=True)
    main_path.write_text("[]", encoding="utf-8")
    testnet_path.write_text("[]", encoding="utf-8")

    output = tmp_path / "diagnostics" / "costs.json"
    snapshot = telemetry.run_once(output, input_root)

    assert snapshot["meta"]["load_errors"] == []
    assert output.exists()
    signature = telemetry.input_signature(input_root)
    assert {row[0] for row in signature} == {"main_ledger", "testnet_ledger"}


def test_protocolo_congela_minimos_y_prohibe_acciones():
    p, digest = protocol()
    assert p["decision_protocol"]["minimum_live_closed_with_confirmed_fees"] == 30
    assert p["decision_protocol"]["minimum_calendar_weeks"] == 4
    assert p["governance"]["execution_enabled"] is False
    assert digest == "fe632337e675b36256741a65ec5820f4bb1d08f0bce5d9346a712a1629ba2148"
