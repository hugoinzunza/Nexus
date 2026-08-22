import json
from decimal import Decimal

import pytest

from modules.acciones_chile.cmf import parse_rows, rows_for_rut
from modules.acciones_chile.fundamentals import analyze_company
from modules.acciones_chile.portfolio import normalize_portfolio
from modules.acciones_chile.auditor import availability
from modules.acciones_chile.youtube import parse_feed
from modules.acciones_chile.dataset import (
    build_audit_snapshot, build_dataset, build_multi_period_dataset, select_comparison_periods,
    select_refresh_periods,
)
from modules.acciones_chile.telegram_events import parse_event
from modules.acciones_chile.predictor import event_features, normalize_company, readiness


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


def test_comparison_period_is_same_quarter_previous_year():
    assert select_comparison_periods(["202606", "202603", "202506"]) == ("202606", "202506")
    assert select_comparison_periods(["202606", "202603"]) == ("202606", None)
    assert select_refresh_periods(["202606", "202603", "202506", "202503"]) == [
        "202606", "202506", "202603", "202503",
    ]


def test_compact_dataset_preserves_provenance_and_secondary_videos():
    feed = """<?xml version="1.0"?><feed
      xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"><entry>
      <yt:videoId>v1</yt:videoId><title>Resultados</title>
      <published>2026-08-22T00:00:00Z</published><media:group>
      <media:description>00:01 Empresa</media:description></media:group>
      </entry></feed>"""
    data = build_dataset(_payload().encode(), _payload("202503", "1000", "80").encode(), feed)
    assert data["cmf"]["periods"] == ["202603", "202503"]
    assert data["cmf"]["sources"][0]["rows"] == 3
    assert len(data["cmf"]["sources"][0]["sha256"]) == 64
    assert data["cmf"]["issuers"][0]["analysis"]["revenue_growth_yoy"] == 0.2
    assert data["youtube"]["entries"][0]["source_role"] == "secondary_thesis"


def test_partial_latest_period_keeps_catalog_from_previous_quarter():
    latest = _payload("202606", "1400", "140").replace("76543210", "11111111")
    prior_quarter = _payload("202603", "1200", "120")
    prior_year = _payload("202503", "1000", "80")
    data = build_multi_period_dataset({
        "202606": latest.encode(), "202603": prior_quarter.encode(),
        "202503": prior_year.encode(),
    })
    by_rut = {item["rut"]: item for item in data["cmf"]["issuers"]}
    assert set(by_rut) == {"11111111", "76543210"}
    assert by_rut["76543210"]["latest_available_period"] == "202603"
    assert by_rut["76543210"]["analysis"]["revenue_growth_yoy"] == 0.2
    snapshot = build_audit_snapshot(data)
    assert snapshot["cmf"]["issuer_count"] == 2
    assert snapshot["boundaries"]["orders"] == "prohibited"
    assert "holdings" not in json.dumps(snapshot)


def test_telegram_parser_keeps_causal_message_time_and_ignores_chat():
    text = """📢 NUEVO ESTADO FINANCIERO 📢 🏢 Empresa : ENEL CHILE S.A.
      🗓 Periodo : 2T 2026 📅 Fecha Emisión : 17/08/2026 18:41
      📂 Tipo Balance : Consolidado 📄 Estado Financiero : EEFF PDF"""
    event = parse_event(2762, "2026-08-17T22:44:03+00:00", text)
    assert event["event_type"] == "financial_statement"
    assert event["company"] == "ENEL CHILE S.A."
    assert event["period"] == "2T 2026"
    assert event["available_at"] == "2026-08-17T22:44:03+00:00"
    assert event["reported_emission_local"] == "17/08/2026 18:41"
    assert parse_event(1, "2026-08-18T11:08:53+00:00", "Saben los eeff de Schwager?") is None


def test_predictor_features_exclude_future_events():
    events = [
        {"event_type": "financial_statement", "company": "ENEL CHILE S.A.",
         "available_at": "2026-08-17T22:44:03+00:00", "period": "2T 2026"},
        {"event_type": "essential_notice", "company": "Enel Chile SA",
         "available_at": "2026-08-25T10:00:00+00:00"},
    ]
    features = event_features(events, "Enel Chile", "2026-08-20T00:00:00+00:00")
    assert normalize_company("ENEL CHILE S.A.") == "ENEL CHILE"
    assert features["last_statement_period"] == "2T 2026"
    assert features["essential_notices_30d"] == 0
    assert features["future_events_excluded"] is True


def test_predictor_readiness_fails_closed_without_history_and_prices():
    state = readiness({"events": [{
        "event_type": "financial_statement", "company": "ENEL CHILE S.A.",
        "available_at": "2026-08-17T22:44:03+00:00", "period": "2T 2026",
    }]})
    assert state["can_train"] is False
    assert state["can_generate_signal"] is False
    assert state["youtube_feature_allowed"] is False
    assert len(state["blockers"]) == 2
