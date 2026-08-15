from pathlib import Path

from research.hypothesis_lab import seasonality_study as study


ROOT = Path(__file__).resolve().parents[3]


def _rows():
    rows = []
    price = 100.0
    returns = {
        (2020, 5): -5.0, (2020, 6): -4.0, (2020, 7): 10.0,
        (2021, 5): 4.0, (2021, 6): -2.0, (2021, 7): -3.0,
    }
    for year in (2020, 2021):
        for month in range(1, 9):
            value = returns.get((year, month), 1.0)
            close = price * (1 + value / 100)
            rows.append({"year": year, "month": month, "open": price,
                         "close": close, "return_pct": value})
            price = close
    return rows


def test_separa_tasa_base_de_condicion_mayo_junio():
    report = study.analyze(_rows())
    assert report["july_baseline"]["n"] == 2
    assert report["may_june_negative_then_july"]["n"] == 1
    assert report["may_june_negative_then_july"]["years"] == [2020]
    assert report["other_julys"]["n"] == 1
    assert report["promotion_available"] is False


def test_agregar_futuro_no_cambia_un_julio_cerrado():
    base = _rows()
    before = study.analyze(base)
    future = {"year": 2022, "month": 1, "open": 100.0, "close": 150.0,
              "return_pct": 50.0}
    after = study.analyze(base + [future])
    assert before["cases"] == after["cases"]


def test_reporte_publicado_es_exploratorio_y_julio_no_es_933():
    path = ROOT / "research/hypothesis_lab/reports/HYP-SEASON-001-20260803.summary.json"
    if not path.exists():
        return
    import json
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["status"] == "exploratory_post_hoc"
    assert report["promotion_available"] is False
    assert 7.2 < report["july_2026"]["july_return_pct"] < 7.4


def test_estudio_no_importa_ejecucion():
    source = Path(study.__file__).read_text(encoding="utf-8")
    for forbidden in ("modules.bot", "create_order", "BINANCE_API", "api_post"):
        assert forbidden not in source
