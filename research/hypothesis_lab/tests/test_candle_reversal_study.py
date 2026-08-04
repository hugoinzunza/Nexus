from pathlib import Path

from research.hypothesis_lab import candle_reversal_study as study


def _bar(o, h, l, c, t):
    return {"o": o, "h": h, "l": l, "c": c, "t": t}


def test_detecta_impulso_absorcion_reclaim_alcista():
    candles = [_bar(100, 101, 99, 100, i) for i in range(20)]
    candles[14] = _bar(100, 101, 89, 90, 14)
    candles[15] = _bar(90, 92, 88, 91, 15)
    candles[16] = _bar(91, 99, 90, 98, 16)
    atr = [5.0] * len(candles)
    assert study._aligned_pattern(candles, atr, 14, "long") is True
    assert study._aligned_pattern(candles, atr, 14, "short") is False


def test_no_confunde_reclaim_pequeno_con_reversion():
    candles = [_bar(100, 101, 99, 100, i) for i in range(20)]
    candles[14] = _bar(100, 101, 89, 90, 14)
    candles[15] = _bar(90, 92, 88, 91, 15)
    candles[16] = _bar(91, 93, 90, 92, 16)
    assert study._aligned_pattern(candles, [5.0] * 20, 14, "long") is False


def test_reporte_publicado_no_autoriza_ejecucion():
    if not study.REPORT_PATH.exists():
        return
    import json
    report = json.loads(study.REPORT_PATH.read_text(encoding="utf-8"))
    assert report["research_only"] is True
    assert report["promotion_available"] is False
    assert report["execution_enabled"] is False
    assert report["visual_examples"]["effective_events"] == 1


def test_estudio_no_importa_ejecucion():
    source = Path(study.__file__).read_text(encoding="utf-8")
    for forbidden in ("modules.bot", "create_order", "BINANCE_API", "api_post"):
        assert forbidden not in source
