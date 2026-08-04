import json
from pathlib import Path

from research.hypothesis_lab import candle_reversal_shadow as shadow


def test_observador_no_muta_store_y_solo_escribe_shadow(tmp_path):
    setups = tmp_path / "setups.json"
    output = tmp_path / "shadow" / "out.json"
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "hypothesis_id": "HYP-CANDLE-002-SHADOW", "frozen": True, "research_only": True,
        "cohort": {"start_at_ms": 1},
        "decision_protocol": {"minimum_closed_patterns": 30},
    }), encoding="utf-8")
    setup = {"key": "x", "ts_created": 1, "ts_activated": 2, "pair": "BTC_USDT",
             "poi_tf": "1h", "dir": "long", "entry": 100, "sl": 80, "tp": 140,
             "status": "abierta", "result_r": None}
    setups.write_text(json.dumps([setup]), encoding="utf-8")
    before = setups.read_bytes()
    candles = [{"t": i * 3_600_000, "o": 100, "h": 101, "l": 99, "c": 100}
               for i in range(25)]
    payload = shadow.observe(setups, output, spec, now_ms=30 * 3_600_000,
                             fetcher=lambda *_args: candles)
    assert setups.read_bytes() == before
    assert output.exists()
    assert payload["research_only"] is True
    assert payload["execution_enabled"] is False


def test_fuente_no_importa_bot():
    source = Path(shadow.__file__).read_text(encoding="utf-8")
    for forbidden in ("modules.bot", "create_order", "BINANCE_API", "api_post"):
        assert forbidden not in source
