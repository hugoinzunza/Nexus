from pathlib import Path

from research.hypothesis_lab import trendline_study as study


def _rows(closes):
    start = 1_700_000_000_000
    return [{
        "date": f"2024-01-{index + 1:02d}", "open_time_ms": start + index * 86_400_000,
        "close_time_ms": start + (index + 1) * 86_400_000 - 1,
        "open": close, "high": close + 1, "low": close - 1, "close": close,
    } for index, close in enumerate(closes)]


def test_pivote_solo_existe_despues_de_confirmacion():
    rows = _rows([10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10, 9])
    pivots = study.confirmed_pivots(rows)
    high = next(item for item in pivots if item["kind"] == "high")
    assert high["index"] == 5
    assert high["confirm_index"] == 10


def test_linea_exige_dos_pivotes_y_direccion_estructural():
    rows = _rows([10.0] * 40)
    pivots = [
        {"kind": "high", "index": 5, "confirm_index": 10, "price": 20.0},
        {"kind": "high", "index": 15, "confirm_index": 20, "price": 18.0},
        {"kind": "low", "index": 7, "confirm_index": 12, "price": 5.0},
        {"kind": "low", "index": 17, "confirm_index": 22, "price": 4.0},
    ]
    lines = study._lines(rows, pivots)
    assert [line["direction"] for line in lines] == ["bullish"]


def test_reporte_no_habilita_promocion_y_es_causal():
    path = Path(study.REPORT_PATH)
    if not path.exists():
        return
    import json
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["promotion_available"] is False
    assert report["execution_enabled"] is False
    assert report["causality"]["all_anchors_known_before_break"] is True
    assert report["visual_examples"]["role"] == "vocabulary_only"


def test_estudio_no_importa_ejecucion():
    source = Path(study.__file__).read_text(encoding="utf-8")
    for forbidden in ("modules.bot", "create_order", "BINANCE_API", "api_post"):
        assert forbidden not in source
