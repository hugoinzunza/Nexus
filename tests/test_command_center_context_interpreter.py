import json
from pathlib import Path

from modules.command_center.context_interpreter import (
    INTERPRETATION_SCHEMA,
    ONE_HOUR_MS,
    MarketContextInterpreter,
)
from modules.command_center.context_recorder import MarketContextRecorder


NOW = 1_800_000_000_000
STEP_MS = 30_000


def _snapshot(timestamp, price, *, source="Binance Futures", freshness="live"):
    return {
        "generated_at_ms": timestamp,
        "assets": [
            {
                "id": "btcusdt",
                "price": price,
                "change_pct": 1.0,
                "observed_at_ms": timestamp,
                "freshness": freshness,
                "source": source,
                "kind": "futures",
            }
        ],
        "provider_errors": [],
    }


def _record(path: Path, points):
    clock = [points[0][0]]
    recorder = MarketContextRecorder(path, clock_ms=lambda: clock[0])
    for timestamp, price, source in points:
        clock[0] = timestamp
        recorder.record(_snapshot(timestamp, price, source=source))


def _hour_points(*, start_price=70_000.0, end_price=70_700.0):
    start = NOW - ONE_HOUR_MS
    points = []
    for index in range(121):
        ratio = index / 120
        price = start_price + ((end_price - start_price) * ratio)
        points.append((start + index * STEP_MS, price, "Binance Futures"))
    return points


def test_interpreter_describe_cambio_solo_con_ventana_completa(tmp_path):
    path = tmp_path / "context.jsonl"
    _record(path, _hour_points())
    interpreter = MarketContextInterpreter(path, clock_ms=lambda: NOW)

    result = interpreter.compare("BTCUSDT")

    assert result["schema"] == INTERPRETATION_SCHEMA
    assert result["status"] == "observed_change"
    assert result["direction"] == "up"
    assert result["delta_pct"] == 1.0
    assert result["basis"] == "stored_snapshots_only"
    assert result["statement"] == (
        "BTCUSDT subio 1% entre observaciones registradas separadas por 60 min."
    )
    evidence = result["evidence"]
    assert evidence["baseline_sequence"] == 1
    assert evidence["current_sequence"] == 121
    assert evidence["sample_count"] == 121
    assert evidence["max_gap_ms"] == STEP_MS
    assert len(evidence["baseline_event_hash"]) == 64
    assert len(evidence["current_event_hash"]) == 64


def test_interpreter_distingue_bajada_y_precio_sin_variacion(tmp_path):
    down_path = tmp_path / "down.jsonl"
    flat_path = tmp_path / "flat.jsonl"
    _record(down_path, _hour_points(start_price=70_000, end_price=69_300))
    _record(flat_path, _hour_points(start_price=70_000, end_price=70_000))

    down = MarketContextInterpreter(down_path, clock_ms=lambda: NOW).compare(
        "btcusdt"
    )
    flat = MarketContextInterpreter(flat_path, clock_ms=lambda: NOW).compare(
        "btcusdt"
    )

    assert down["direction"] == "down"
    assert down["statement"].startswith("BTCUSDT bajo 1%")
    assert flat["direction"] == "flat"
    assert flat["statement"].startswith("BTCUSDT no vario")


def test_interpreter_se_abstiene_sin_historia(tmp_path):
    result = MarketContextInterpreter(
        tmp_path / "missing.jsonl",
        clock_ms=lambda: NOW,
    ).compare("btcusdt")

    assert result["status"] == "insufficient_evidence"
    assert result["reason"] == "no_history"
    assert result["statement"] is None
    assert result["evidence"] is None


def test_interpreter_no_convierte_media_hora_en_una_hora(tmp_path):
    path = tmp_path / "context.jsonl"
    points = _hour_points()[60:]
    _record(path, points)

    result = MarketContextInterpreter(path, clock_ms=lambda: NOW).compare(
        "btcusdt"
    )

    assert result["reason"] == "insufficient_history"
    assert result["statement"] is None


def test_interpreter_rechaza_una_brecha_dentro_de_la_ventana(tmp_path):
    path = tmp_path / "context.jsonl"
    points = _hour_points()
    points = points[:41] + points[45:]
    _record(path, points)

    result = MarketContextInterpreter(path, clock_ms=lambda: NOW).compare(
        "btcusdt"
    )

    assert result["reason"] == "coverage_gap"


def test_interpreter_no_compara_proveedores_distintos(tmp_path):
    path = tmp_path / "context.jsonl"
    points = _hour_points()
    points[60] = (points[60][0], points[60][1], "Other Provider")
    _record(path, points)

    result = MarketContextInterpreter(path, clock_ms=lambda: NOW).compare(
        "btcusdt"
    )

    assert result["reason"] == "source_changed"


def test_interpreter_rechaza_historia_que_ya_no_esta_vigente(tmp_path):
    path = tmp_path / "context.jsonl"
    _record(path, _hour_points())

    result = MarketContextInterpreter(
        path,
        clock_ms=lambda: NOW + 120_001,
    ).compare("btcusdt")

    assert result["reason"] == "stale_history"


def test_interpreter_no_emite_afirmacion_si_la_cadena_fue_alterada(tmp_path):
    path = tmp_path / "context.jsonl"
    _record(path, _hour_points())
    lines = path.read_text().splitlines()
    event = json.loads(lines[-1])
    event["snapshot"]["assets"][0]["price"] = 1
    lines[-1] = json.dumps(event)
    path.write_text("\n".join(lines) + "\n")
    interpreter = MarketContextInterpreter(path, clock_ms=lambda: NOW)

    result = interpreter.compare("btcusdt")

    assert result["reason"] == "integrity_failure"
    assert result["statement"] is None
    assert interpreter.stats()["integrity_failures"] == 1


def test_interpreter_no_autorizado_para_lenguaje_de_continuidad():
    source = (
        Path(__file__).parents[1]
        / "modules"
        / "command_center"
        / "context_interpreter.py"
    ).read_text().lower()

    for phrase in ("continua", "mantiene", "seguira", "deberia", "tendencia"):
        assert phrase not in source
