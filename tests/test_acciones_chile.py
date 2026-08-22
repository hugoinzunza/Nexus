from decimal import Decimal

import pytest

from modules.acciones_chile.cmf import parse_rows, rows_for_rut
from modules.acciones_chile.fundamentals import analyze_company
from modules.acciones_chile.portfolio import normalize_portfolio
from modules.acciones_chile.auditor import availability
from modules.acciones_chile.youtube import parse_feed


def _payload(period="202603", revenue="1200", profit="120"):
    return (
        f"{period};76543210;EMPRESA CHILENA S.A.;I;CLP;Ingresos de actividades ordinarias;{revenue};TAX CI;ERFG\n"
        f"{period};76543210;EMPRESA CHILENA S.A.;I;CLP;Ganancia (pérdida) de actividades operacionales;{profit};TAX CI;ERFG\n"
        f"{period};76543210;EMPRESA CHILENA S.A.;I;CLP;Ganancia (pérdida);60;TAX CI;ERFG\n"
    )


def test_parse_cmf_and_fundamental_metrics():
    current = rows_for_rut(parse_rows(_payload()), "76.543.210-9")
    previous = parse_rows(_payload("202503", "1000", "80"))
    result = analyze_company(current, previous)
    assert result["revenue"] == "1200"
    assert result["revenue_growth_yoy"] == 0.2
    assert result["operating_margin"] == 0.1
    assert result["net_margin"] == 0.05
    assert result["is_prediction"] is False


def test_parser_fails_closed_on_schema_change():
    with pytest.raises(ValueError, match="9 columnas"):
        parse_rows("202603;solo;dos")


def test_portfolio_is_normalized_and_read_only():
    result = normalize_portfolio({"holdings": [{
        "ticker": " enelchile ", "company_rut": "76.536.353-5",
        "quantity": "10", "average_cost": "52.5",
    }]})
    assert result["holdings"][0] == {
        "ticker": "ENELCHILE", "company_rut": "76536353", "quantity": "10",
        "average_cost": "52.5", "currency": "CLP",
    }
    assert result["read_only"] is True


def test_portfolio_rejects_negative_positions():
    with pytest.raises(ValueError, match="negativos"):
        normalize_portfolio({"holdings": [{
            "ticker": "TEST", "quantity": Decimal("-1"), "average_cost": "1",
        }]})


def test_auditor_is_manual_and_advisory(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    status = availability({"claude_auditor_enabled": True,
                           "claude_auditor_model": "claude-opus-4-8"})
    assert status["run_mode"] == "manual"
    assert status["authority"] == "advisory_only"
    assert status["key_present"] is False


def test_youtube_feed_indexes_chapters_as_secondary_source():
    xml = """<?xml version="1.0"?><feed
      xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/">
      <entry><yt:videoId>abc123</yt:videoId><title>Resultados Q2</title>
      <published>2026-08-22T14:00:00Z</published><media:group>
      <media:description>00:02:18 Cencomalls\n00:10:48 Cencosud</media:description>
      </media:group></entry></feed>"""
    video = parse_feed(xml)[0]
    assert video["video_id"] == "abc123"
    assert video["chapters"][1] == {"timestamp": "00:10:48", "title": "Cencosud"}
    assert video["source_role"] == "secondary_thesis"
