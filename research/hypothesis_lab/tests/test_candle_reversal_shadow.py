import json

import pytest
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


def _spec_y_setup(tmp_path):
    setups = tmp_path / "setups.json"
    output = tmp_path / "shadow" / "out.json"
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "hypothesis_id": "HYP-CANDLE-002-SHADOW", "frozen": True, "research_only": True,
        "cohort": {"start_at_ms": 1},
        "decision_protocol": {"minimum_closed_patterns": 30},
    }), encoding="utf-8")
    setups.write_text(json.dumps([]), encoding="utf-8")
    return setups, output, spec


def test_reintenta_cuando_el_store_cambia_durante_la_pasada(tmp_path, monkeypatch):
    """La colisión con el merger canónico es rutina, no anomalía: la pasada debe
    reintentarse desde cero, no convertirse en un exit 1 del servicio."""
    setups, output, spec = _spec_y_setup(tmp_path)
    intentos = []
    observa_real = shadow.observe

    def observa_inestable(*args, **kwargs):
        intentos.append(1)
        if len(intentos) == 1:
            raise RuntimeError("setup store changed while observing; refusing snapshot")
        return observa_real(setups, output, spec, now_ms=30 * 3_600_000,
                            fetcher=lambda *_a: [])

    monkeypatch.setattr(shadow, "observe", observa_inestable)
    esperas = []
    payload = shadow.observe_with_retry(setups, output, spec,
                                        sleeper=esperas.append)
    assert len(intentos) == 2
    assert esperas == [5.0]
    assert payload["research_only"] is True


def test_agotar_reintentos_relanza_el_error_original(tmp_path, monkeypatch):
    setups, output, spec = _spec_y_setup(tmp_path)

    def siempre_cambia(*args, **kwargs):
        raise RuntimeError("setup store changed while observing; refusing snapshot")

    monkeypatch.setattr(shadow, "observe", siempre_cambia)
    with pytest.raises(RuntimeError, match="refusing snapshot"):
        shadow.observe_with_retry(setups, output, spec, retries=2,
                                  sleeper=lambda _s: None)
