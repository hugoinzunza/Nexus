import json
import ast
import urllib.error
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.acciones_chile.cmf import CMFDownload, _validated_url, parse_rows, rows_for_rut
from modules.acciones_chile.banks import (
    BankDownload, _validated_url as validated_bank_url, availability as bank_availability,
    build_bank_dataset, parse_results,
)
from modules.acciones_chile.fundamentals import analyze_company
from modules.acciones_chile.fx import (
    FxDownload, _validated_url as validated_fx_url, availability as fx_availability,
    build_fx_dataset, build_public_fx_dataset, download_observed_dollar,
    download_public_observed_dollar, eps_unit_availability, parse_observed_dollar,
    parse_public_observed_dollar,
    rate_as_of, read_fx_dataset, validate_eps_unit_dataset,
)
from modules.acciones_chile.portfolio import normalize_portfolio
from modules.acciones_chile.auditor import availability
from modules.acciones_chile.youtube import parse_feed
from modules.acciones_chile.dataset import (
    _download_with_integrity, _persist_raw_artifact, build_audit_snapshot, build_dataset,
    build_multi_period_dataset, select_comparison_periods, select_refresh_periods,
)
from modules.acciones_chile.telegram_events import parse_event
from modules.acciones_chile.predictor import (
    build_feature_records, event_features, feature_join_report, normalize_company, readiness,
    portfolio_event_monitor, telegram_period_to_cmf,
)
from modules.acciones_chile.market_data import parse_market_csv
from modules.acciones_chile.universe import (
    UniverseIncompleteError, load_universe, resolve_ticker, snapshot_as_of, universe_status,
    validate_universe,
)
from modules.acciones_chile.strategy import (
    build_radar, evaluate_decision_evidence, evaluate_observation, evaluate_valuation,
    portfolio_concentration,
)
from modules.acciones_chile import module as acciones_module


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


def test_fundamentals_include_balance_and_free_cash_flow():
    extended = _payload() + (
        "202603;76543210;EMPRESA CHILENA S.A.;I;CLP;Total de activos;5000;TAX CI;ESF\n"
        "202603;76543210;EMPRESA CHILENA S.A.;I;CLP;Total de pasivos;2500;TAX CI;ESF\n"
        "202603;76543210;EMPRESA CHILENA S.A.;I;CLP;Activos corrientes totales;1500;TAX CI;ESF\n"
        "202603;76543210;EMPRESA CHILENA S.A.;I;CLP;Pasivos corrientes totales;1000;TAX CI;ESF\n"
        "202603;76543210;EMPRESA CHILENA S.A.;I;CLP;Flujos de efectivo netos procedentes de (utilizados en) actividades de operación;300;TAX CI;EFE\n"
        "202603;76543210;EMPRESA CHILENA S.A.;I;CLP;Compras de propiedades, planta y equipo;80;TAX CI;EFE\n"
        "202603;76543210;EMPRESA CHILENA S.A.;I;CLP;Compras de activos intangibles;20;TAX CI;EFE\n"
    )
    result = analyze_company(parse_rows(extended))
    assert result["free_cash_flow"] == "200"
    assert result["liabilities_to_assets"] == 0.5
    assert result["current_coverage"] == 1.5


def test_valuation_only_computes_compatible_observed_multiple():
    clp = [{"period": "202512", "currency": "CLP", "analysis": {"basic_eps": "20"}}]
    assert evaluate_valuation(clp, "300")["status"] == "eps_unit_verification_required"
    clp_verified = {
        "rut": "76543210", "status": "verified", "metric": "basic_eps",
        "period": "202512", "unit": "CLP_PER_SHARE", "cmf_value": "20",
        "reported_value": "20", "cmf_value_multiplier": "1", "source_page": 10,
        "source_reference": "https://issuer.example/annual-report.pdf",
        "verification_method": "audited_annual_report_note",
        "source_sha256": "b" * 64, "verified_as_of": "2026-08-22",
    }
    result = evaluate_valuation(
        clp, "300", eps_unit_verification=clp_verified, issuer_rut="76543210")
    assert result["pe"] == 15
    assert result["fair_value"] is None
    assert result["buy_sell_recommendation"] is None
    usd = [{"period": "202512", "currency": "USD", "analysis": {"basic_eps": "1.2"}}]
    assert evaluate_valuation(usd, "6000")["status"] == "eps_unit_verification_required"
    usd_without_eps = [{"period": "202512", "currency": "USD", "analysis": {}}]
    assert evaluate_valuation(usd_without_eps, "6000")["status"] == "annual_eps_unavailable"
    verified = {
        "rut": "76543210", "status": "verified", "metric": "basic_eps", "period": "202512",
        "unit": "USD_PER_SHARE", "cmf_value": "1.2", "reported_value": "1.2",
        "cmf_value_multiplier": "1", "source_page": 10,
        "source_reference": "https://issuer.example/annual-report.pdf",
        "verification_method": "audited_annual_report_note",
        "source_sha256": "a" * 64, "verified_as_of": "2026-08-22",
    }
    converted = evaluate_valuation(
        usd, "6000", {"date": "2026-08-21", "clp_per_usd": "1000"}, verified,
        issuer_rut="76543210")
    assert converted["pe"] == 5
    assert converted["eps_clp_per_share"] == 1200
    assert evaluate_valuation(
        usd, "6000", None, verified, issuer_rut="76543210")["status"] == "official_fx_rate_required"


def _fx_payload():
    return json.dumps({
        "Codigo": 0, "Descripcion": "Success",
        "Series": {"seriesId": "F073.TCO.PRE.Z.D", "Obs": [
            {"indexDateString": "20-08-2026", "value": "933.92", "statusCode": "OK"},
            {"indexDateString": "21-08-2026", "value": "933.00", "statusCode": "OK"},
            {"indexDateString": "22-08-2026", "value": "NaN", "statusCode": "ND"},
        ]},
    }).encode()


def test_bcch_fx_adapter_is_redacted_causal_and_read_only(monkeypatch):
    url, redacted = validated_fx_url("2026-08-01", "2026-08-22", "private-token")
    assert "private-token" in url
    assert "private-token" not in redacted
    rows = parse_observed_dollar(_fx_payload())
    assert rows[-1] == {"date": "2026-08-21", "clp_per_usd": "933.00"}
    download = FxDownload(
        payload=_fx_payload(), effective_url_redacted=redacted,
        retrieved_at="2026-08-22T12:00:00+00:00", http_status=200,
        content_length=None, bytes_received=len(_fx_payload()),
    )
    data = build_fx_dataset(download)
    assert data["latest"] == rows[-1]
    assert rate_as_of(data, "2026-08-20")["clp_per_usd"] == "933.92"
    assert "private-token" not in json.dumps(data)
    monkeypatch.delenv("BCCH_API_TOKEN", raising=False)
    assert fx_availability()["key_present"] is False


def test_bcch_fx_cache_fails_closed_when_tampered(tmp_path):
    _, redacted = validated_fx_url("2026-08-01", "2026-08-22", "private-token")
    download = FxDownload(
        payload=_fx_payload(), effective_url_redacted=redacted,
        retrieved_at="2026-08-22T12:00:00+00:00", http_status=200,
        content_length=None, bytes_received=len(_fx_payload()),
    )
    data = build_fx_dataset(download)
    data["latest"]["clp_per_usd"] = "99999"
    path = tmp_path / "fx.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_fx_dataset(str(path)) is None
    assert rate_as_of(data, "2026-08-22") is None


def test_bcch_network_error_never_leaks_token(monkeypatch):
    def fail(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "bad token", {}, None)

    monkeypatch.setattr("modules.acciones_chile.fx.urllib.request.urlopen", fail)
    with pytest.raises(ValueError, match="consulta BCCh falló") as error:
        download_observed_dollar("2026-08-01", "2026-08-22", "never-print-this")
    assert "never-print-this" not in str(error.value)
    assert error.value.__cause__ is None


def test_bcch_public_table_is_strict_official_fallback(monkeypatch):
    html = b'''<html><table id="listaObsHtmlAll"><thead><tr><th>FECHA</th><th>VALOR</th></tr></thead>
    <tbody><tr><td>21.Ago.2026</td><td>923,23</td></tr>
    <tr><td>20.Ago.2026</td><td>920,26</td></tr></tbody></table></html>'''
    rows = parse_public_observed_dollar(html)
    assert rows[-1] == {"date": "2026-08-21", "clp_per_usd": "923.23"}

    class Response:
        headers = {}
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def geturl(self):
            return ("https://si3.bcentral.cl/Siete/ES/Siete/Cuadro/CAP_TIPO_CAMBIO/"
                    "MN_TIPO_CAMBIO4/DOLAR_OBS_ADO?idSerie=F073.TCO.PRE.Z.D")
        def read(self, size): return html

    monkeypatch.setattr("modules.acciones_chile.fx.urllib.request.urlopen",
                        lambda request, timeout: Response())
    download = download_public_observed_dollar()
    data = build_public_fx_dataset(download)
    assert data["ingestion_method"] == "public_bde_html"
    assert rate_as_of(data, "2026-08-22") == rows[-1]


def test_bcch_public_table_rejects_ambiguous_or_redirected_source(monkeypatch):
    duplicate = ('<table id="listaObsHtmlAll"><tr><td>21.Ago.2026</td><td>923,23</td></tr></table>' * 2)
    with pytest.raises(ValueError, match="no encontrada o ambigua"):
        parse_public_observed_dollar(duplicate)

    class Redirected:
        headers = {}
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def geturl(self): return "https://example.com/fx"
        def read(self, size): return b""

    monkeypatch.setattr("modules.acciones_chile.fx.urllib.request.urlopen",
                        lambda request, timeout: Redirected())
    with pytest.raises(ValueError, match="fuera del endpoint autorizado"):
        download_public_observed_dollar()


def test_eps_unit_requires_audited_hashed_evidence():
    valid = {"schema_version": "acciones-chile-eps-units-0.3.0", "entries": {
        "90412000": {
            "rut": "90412000", "status": "verified", "metric": "basic_eps", "period": "202512",
            "unit": "USD_PER_SHARE", "cmf_value": "1.3495",
            "reported_value": "1.3495", "cmf_value_multiplier": "1",
            "verification_method": "audited_annual_report_note",
            "source_reference": "https://issuer.example/annual-report.pdf",
            "source_page": 14, "source_sha256": "a" * 64,
            "verified_as_of": "2026-08-22",
        },
    }}
    assert validate_eps_unit_dataset(valid)["entries"]["90412000"]["unit"] == "USD_PER_SHARE"
    valid["entries"]["90412000"]["verification_method"] = "heuristic"
    with pytest.raises(ValueError, match="método de unidad EPS"):
        validate_eps_unit_dataset(valid)
    valid["entries"]["90412000"]["verification_method"] = "audited_annual_report_note"
    valid["entries"]["90412000"]["rut"] = "90690000"
    with pytest.raises(ValueError, match="identidad de emisor EPS"):
        validate_eps_unit_dataset(valid)


def test_packaged_eps_evidence_reconciles_copec_cmf_scale_and_minera_unit():
    root = Path(__file__).resolve().parents[1]
    evidence = validate_eps_unit_dataset(json.loads(
        (root / "config/acciones_chile_eps_units_v0.3.json").read_text(encoding="utf-8")))
    copec = evidence["entries"]["90690000"]
    assert Decimal(copec["cmf_value"]) * Decimal(copec["cmf_value_multiplier"]) == Decimal("0.67457")
    assert copec["reported_value"] == "0.674577"
    history = [{"period": "202512", "currency": "USD",
                "analysis": {"basic_eps": "674.57"}}]
    valuation = evaluate_valuation(
        history, "6600", {"date": "2026-08-21", "clp_per_usd": "933"}, copec,
        issuer_rut="90690000")
    assert valuation["eps_verified_per_share"] == 0.674577
    assert valuation["eps_clp_per_share"] == pytest.approx(629.380341)
    assert valuation["pe"] == pytest.approx(10.4865)
    assert evidence["entries"]["90412000"]["reported_value"] == "1.3495"
    aguas = evidence["entries"]["61808000"]
    aguas_valuation = evaluate_valuation(
        [{"period": "202512", "currency": "CLP", "analysis": {"basic_eps": "22.848"}}],
        "330", eps_unit_verification=aguas, issuer_rut="61808000")
    assert aguas_valuation["pe"] == pytest.approx(14.4433)
    assert aguas_valuation["eps_verified_unit"] == "CLP_PER_SHARE"
    status = eps_unit_availability(str(root / "config/acciones_chile_eps_units_v0.3.json"))
    assert status["mechanism_ready"] is True
    assert status["ready"] is False
    assert status["universe_complete"] is False


def test_strategy_rubric_is_explainable_and_never_emits_trade_order():
    observation = {"period": "202603", "analysis": {
        "revenue_growth_yoy": 0.12, "operating_margin": 0.15, "net_margin": 0.1,
        "operating_cash_flow": "300", "free_cash_flow": "220",
        "liabilities_to_assets": 0.5, "current_coverage": 1.8, "cash_conversion": 1.2,
    }}
    reading = evaluate_observation(observation)
    assert reading["fundamental_view"] == "FUNDAMENTOS FUERTES"
    assert reading["buy_sell_recommendation"] is None
    assert reading["buy_sell_gate"] == "waiting_for_authorized_price_and_valuation"
    assert reading["youtube_feature_allowed"] is False
    assert len(reading["source_videos"]) == 4


def test_decision_evidence_explains_missing_valuation_without_emitting_action():
    evidence = evaluate_decision_evidence(
        {"data_points": 7, "fundamental_view": "FUNDAMENTOS FUERTES",
         "portfolio_action_research": "MANTENER / EVALUAR CON VALORACIÓN"},
        {"market_price": 6600, "pe": 12.5, "fair_value": None,
         "margin_of_safety": None},
        {"statement_status": "latest_period_detected", "essential_notices_30d": 1},
        0.58,
    )
    assert evidence["operational_state"] == "blocked"
    assert evidence["checks_ready"] == 4
    assert evidence["blockers"] == ["valor justo sustentado", "margen de seguridad"]
    assert "concentración elevada" in evidence["warnings"][0]
    assert evidence["buy_recommendation"] is None
    assert evidence["sell_recommendation"] is None
    assert evidence["orders"] == "prohibited"


def test_portfolio_concentration_reports_risk_without_rebalance_recommendation():
    result = portfolio_concentration([
        {"ticker": "COPEC", "allocation_pct": 0.582},
        {"ticker": "MINERA", "allocation_pct": 0.231},
        {"ticker": "AGUAS-A", "allocation_pct": 0.187},
    ])
    assert result["largest_ticker"] == "COPEC"
    assert result["largest_weight"] == 0.582
    assert result["level"] == "high"
    assert result["effective_positions"] < 3
    assert result["recommendation"] is None


def test_radar_uses_one_comparable_period():
    data = build_dataset(_payload().encode())
    radar = build_radar(data)
    assert radar["period"] == "202603"
    assert radar["count"] == 1
    assert radar["rows"][0]["company"] == "EMPRESA CHILENA S.A."


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
        "average_cost": "52.5", "currency": "CLP", "initial_value": "525.0",
        "market_price": None, "market_value": None, "unrealized_pnl": None,
        "return_pct": None,
    }
    assert result["read_only"] is True


def test_portfolio_rejects_negative_positions():
    with pytest.raises(ValueError, match="negativos"):
        normalize_portfolio({"holdings": [{
            "ticker": "TEST", "quantity": Decimal("-1"), "average_cost": "1",
        }]})


def test_portfolio_computes_market_snapshot_server_side():
    result = normalize_portfolio({"available_cash": "2331", "holdings": [{
        "ticker": "COPEC", "quantity": "1525", "average_cost": "6047.82",
        "market_price": "6600", "market_value": "1",
    }]})
    holding = result["holdings"][0]
    assert holding["initial_value"] == "9222925.50"
    assert holding["market_value"] == "10065000"
    assert holding["unrealized_pnl"] == "842074.50"
    assert holding["return_pct"] == pytest.approx(0.09130232)
    assert result["available_cash"] == "2331"


def test_portfolio_discards_credentials_and_rejects_untrusted_metadata():
    result = normalize_portfolio({
        "source": "renta4_authenticated_web_snapshot", "as_of": "2026-08-22",
        "password": "never-store-this", "session_cookie": "never-store-this-either",
        "holdings": [{
            "ticker": "COPEC", "quantity": "1", "average_cost": "6000",
            "broker_token": "holding-secret",
        }],
    })
    serialized = json.dumps(result)
    assert "never-store" not in serialized
    assert "holding-secret" not in serialized
    with pytest.raises(ValueError, match="fuente de cartera no permitida"):
        normalize_portfolio({"source": "password=secret", "holdings": []})
    with pytest.raises(ValueError, match="fecha de cartera inválida"):
        normalize_portfolio({"as_of": "cookie=secret", "holdings": []})


def test_authenticated_user_can_save_own_read_only_portfolio(monkeypatch, tmp_path):
    monkeypatch.setattr(acciones_module, "PORTFOLIO_PATH", str(tmp_path / "portfolio.json"))
    context = SimpleNamespace(module_config={}, module_dir=str(tmp_path), log=lambda message: None)
    instance = acciones_module.AccionesChileModule(context)
    status, _, raw = instance.api_post("save-portfolio", {"holdings": [{
        "ticker": "ENELCHILE", "company_rut": "76.536.353-5",
        "quantity": "100", "average_cost": "52.5",
    }]}, {}, user={"uid": 7})
    assert status == 200
    assert json.loads(raw)["positions"] == 1
    saved = instance._read_portfolio(7)
    assert saved["holdings"][0]["ticker"] == "ENELCHILE"
    assert instance._read_portfolio(8) is None
    other_status, _, other_raw = instance.api("portfolio-monitor", {}, user={"uid": 8})
    assert other_status == 200
    assert json.loads(other_raw) == {"connected": False, "holdings": []}
    assert instance.api_post("save-portfolio", {"holdings": []}, {}, user=None)[0] == 401


def test_portfolio_monitor_summarizes_only_priced_positions(monkeypatch, tmp_path):
    monkeypatch.setattr(acciones_module, "PORTFOLIO_PATH", str(tmp_path / "portfolio.json"))
    context = SimpleNamespace(module_config={}, module_dir=str(tmp_path), log=lambda message: None)
    instance = acciones_module.AccionesChileModule(context)
    monkeypatch.setattr(instance, "_read_dataset", lambda: {})
    payload = {"available_cash": "2331", "holdings": [
        {"ticker": "COPEC", "quantity": "2", "average_cost": "100", "market_price": "120"},
        {"ticker": "MINERA", "quantity": "3", "average_cost": "50"},
    ]}
    assert instance.api_post("save-portfolio", payload, {}, user={"uid": 7})[0] == 200
    status, _, raw = instance.api("portfolio-monitor", {}, user={"uid": 7})
    result = json.loads(raw)
    assert status == 200
    assert result["summary"]["priced_positions"] == 1
    assert result["summary"]["initial_value"] == 200
    assert result["summary"]["market_value"] == 240
    assert result["summary"]["unrealized_pnl"] == 40
    assert result["summary"]["observed_multiple_positions"] == 0
    assert result["summary"]["fair_value_positions"] == 0
    assert result["summary"]["decision_ready"] is False
    assert result["summary"]["concentration"]["level"] == "high"
    assert result["holdings"][0]["decision_evidence"]["operational_state"] == "blocked"
    assert result["holdings"][0]["allocation_pct"] == 1


def test_bank_position_is_explicitly_blocked_without_separate_cmf_bank_data(monkeypatch, tmp_path):
    monkeypatch.setattr(acciones_module, "PORTFOLIO_PATH", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(acciones_module, "BANKS_PATH", str(tmp_path / "banks.json"))
    context = SimpleNamespace(module_config={}, module_dir=str(tmp_path), log=lambda message: None)
    instance = acciones_module.AccionesChileModule(context)
    monkeypatch.setattr(instance, "_read_dataset", lambda: {})
    assert instance.api_post("save-portfolio", {"holdings": [{
        "ticker": "CHILE", "quantity": "100", "average_cost": "100", "market_price": "110",
    }]}, {}, user={"uid": 7})[0] == 200
    status, _, raw = instance.api("portfolio-monitor", {}, user={"uid": 7})
    holding = json.loads(raw)["holdings"][0]
    assert status == 200
    assert holding["data_source_gate"]["code"] == "cmf_banks_accounting_required"
    assert holding["decision_evidence"]["operational_state"] == "blocked"
    assert "contabilidad bancaria CMF separada pendiente" in holding["decision_evidence"]["blockers"]


def test_company_history_exposes_same_explainable_decision_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(acciones_module, "PORTFOLIO_PATH", str(tmp_path / "portfolio.json"))
    context = SimpleNamespace(module_config={}, module_dir=str(tmp_path), log=lambda message: None)
    instance = acciones_module.AccionesChileModule(context)
    data = build_dataset(_payload().encode())
    monkeypatch.setattr(instance, "_read_dataset", lambda: data)
    monkeypatch.setattr(instance, "_read_telegram", lambda: {"events": [{
        "message_id": 1, "event_type": "financial_statement", "company": "EMPRESA CHILENA S.A.",
        "available_at": "2026-05-01T12:00:00+00:00", "period": "1T 2026",
    }]})
    assert instance.api_post("save-portfolio", {"holdings": [{
        "ticker": "TEST", "company_rut": "76543210", "quantity": "2",
        "average_cost": "100", "market_price": "120",
    }]}, {}, user={"uid": 7})[0] == 200
    status, _, raw = instance.api("company-history", {"rut": "76543210"}, user={"uid": 7})
    result = json.loads(raw)
    assert status == 200
    assert result["events"]["statement_status"] == "latest_period_detected"
    assert result["allocation_pct"] == 1
    assert result["decision_evidence"]["checks_total"] == 6
    assert result["decision_evidence"]["buy_recommendation"] is None
    assert result["decision_evidence"]["sell_recommendation"] is None


def test_token_authenticated_telegram_export_ingest(monkeypatch, tmp_path):
    target = tmp_path / "telegram.json"
    monkeypatch.setattr(acciones_module, "TELEGRAM_PATH", str(target))
    monkeypatch.setenv("NEXUX_CHILE_INGEST_TOKEN", "collector-secret")
    context = SimpleNamespace(module_config={}, module_dir=str(tmp_path), log=lambda message: None)
    instance = acciones_module.AccionesChileModule(context)
    export = {
        "schema_version": "acciones-chile-telegram-events-0.1.0",
        "source": "telegram:hechosesencialeschile",
        "event_count": 1,
        "events": [{"message_id": 1, "available_at": "2026-08-01T12:00:00+00:00",
                    "event_type": "financial_statement", "company": "EMPRESA S.A."}],
    }
    assert instance.api_post("ingest-telegram-events", export, {}, user=None)[0] == 401
    status, _, raw = instance.api_post(
        "ingest-telegram-events", export,
        {"x-nexux-token": "collector-secret"}, user=None)
    assert status == 200
    assert json.loads(raw)["events"] == 1
    assert json.loads(target.read_text())["events"][0]["message_id"] == 1
    invalid = {**export, "event_count": 2}
    assert instance.api_post(
        "ingest-telegram-events", invalid,
        {"x-nexux-token": "collector-secret"}, user=None)[0] == 400

    malformed_time = {**export, "events": [{**export["events"][0],
                                             "available_at": "MAÑANA"}]}
    assert instance.api_post(
        "ingest-telegram-events", malformed_time,
        {"x-nexux-token": "collector-secret"}, user=None)[0] == 400
    future_time = {**export, "events": [{**export["events"][0],
                                          "available_at": "2099-01-01T00:00:00+00:00"}]}
    assert instance.api_post(
        "ingest-telegram-events", future_time,
        {"x-nexux-token": "collector-secret"}, user=None)[0] == 400


def test_portfolio_ingest_uses_authenticated_session_uid(monkeypatch, tmp_path):
    monkeypatch.setattr(acciones_module, "PORTFOLIO_PATH", str(tmp_path / "portfolio.json"))
    context = SimpleNamespace(
        module_config={"portfolio_ingest_enabled": True}, module_dir=str(tmp_path),
        log=lambda message: None)
    instance = acciones_module.AccionesChileModule(context)
    payload = {"user_id": 999, "holdings": [{
        "ticker": "COPEC", "quantity": "1", "average_cost": "6000",
    }]}
    assert instance.api_post("ingest-portfolio", payload, {}, user=None)[0] == 401
    status, _, _ = instance.api_post(
        "ingest-portfolio", payload, {"x-nexux-token": "shared-token"}, user={"uid": 7})
    assert status == 200
    assert instance._read_portfolio(7)["holdings"][0]["ticker"] == "COPEC"
    assert instance._read_portfolio(999) is None


def test_portfolio_monitor_labels_unverified_listing(monkeypatch, tmp_path):
    monkeypatch.setattr(acciones_module, "PORTFOLIO_PATH", str(tmp_path / "portfolio.json"))
    context = SimpleNamespace(module_config={}, module_dir=str(tmp_path), log=lambda message: None)
    instance = acciones_module.AccionesChileModule(context)
    monkeypatch.setattr(instance, "_read_dataset", lambda: build_dataset(_payload().encode()))
    assert instance.api_post("save-portfolio", {"as_of": "2026-08-22", "holdings": [{
        "ticker": "TEST", "company_rut": "76543210", "quantity": "1",
        "average_cost": "100", "market_price": "120",
    }]}, {}, user={"uid": 7})[0] == 200
    status, _, raw = instance.api("portfolio-monitor", {}, user={"uid": 7})
    holding = json.loads(raw)["holdings"][0]
    assert status == 200
    assert holding["listing_status"] == "not_verified_by_available_snapshot"
    assert holding["universe_coverage"] == "partial_top_weight_constituents"
    assert holding["data_source_gate"]["code"] == "listing_not_verified"
    assert "cotización no verificada" in holding["decision_evidence"]["blockers"][-1]


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
        "202606", "202603", "202506", "202503",
    ]
    assert select_refresh_periods(
        ["202606", "202603", "202512", "202509", "202506", "202503"]
    ) == ["202606", "202603", "202512", "202509", "202506", "202503"]


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
    assert data["cmf"]["sources"][0]["url"].endswith("?inicio=202603&termino=202603")
    assert data["cmf"]["issuers"][0]["analysis"]["revenue_growth_yoy"] == 0.2
    assert data["youtube"]["entries"][0]["source_role"] == "secondary_thesis"


def test_cmf_sources_expose_numeric_issuer_coverage_and_persisted_artifact_hash():
    data = build_multi_period_dataset(
        {"202603": _payload().encode(), "202503": _payload("202503").encode()},
        source_metadata={"202603": {
            "raw_artifact_sha256": "b" * 64, "raw_artifact_bytes": 321,
            "gzip_reproducibility": "python_gzip_compresslevel_9_mtime_0",
        }},
    )
    source = next(item for item in data["cmf"]["sources"] if item["period"] == "202603")
    assert source["issuer_count"] == 1
    assert source["issuer_coverage_ratio_same_horizon"] == 1
    assert source["completeness_method"] == "row_yoy_and_same_horizon_issuer_threshold_0.70"
    assert source["raw_artifact_sha256"] == "b" * 64
    assert source["raw_artifact_sha256_scope"] == "persisted_deterministic_gzip_bytes"
    assert source["raw_artifact_bytes"] == 321
    assert data["cmf"]["metric_coverage_scope"].startswith("descriptive_latest_nonpartial")


def test_cmf_missing_content_length_requires_matching_redownload():
    calls = []

    def download(period, base_url):
        calls.append((period, base_url))
        return CMFDownload(
            period=period, payload=_payload().encode(), effective_url=base_url,
            retrieved_at="2026-08-22T12:00:00+00:00", http_status=200,
            content_length=None, bytes_received=len(_payload().encode()),
        )

    result, evidence = _download_with_integrity("202603", downloader=download)
    assert result.period == "202603"
    assert evidence["transport_integrity"] == "independent_redownload_sha256_match"
    assert evidence["verification_downloads"] == 2
    assert len(calls) == 2

    def inconsistent(period, base_url):
        payload = (_payload() if not getattr(inconsistent, "called", False)
                   else _payload().replace("1200", "1201")).encode()
        inconsistent.called = True
        return CMFDownload(
            period=period, payload=payload, effective_url=base_url,
            retrieved_at="2026-08-22T12:00:00+00:00", http_status=200,
            content_length=None, bytes_received=len(payload),
        )

    with pytest.raises(ValueError, match="descargas CMF inconsistentes"):
        _download_with_integrity("202603", downloader=inconsistent)


def test_deterministic_cmf_artifact_is_read_back_and_verified(tmp_path):
    path = tmp_path / "eifrs_202603.txt.gz"
    first = _persist_raw_artifact(str(path), _payload().encode())
    persisted = path.read_bytes()
    second = _persist_raw_artifact(str(path), _payload().encode())
    assert first == second
    assert first["raw_artifact_verified"] is True
    assert first["raw_artifact_sha256"] == __import__("hashlib").sha256(persisted).hexdigest()


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
    assert by_rut["76543210"]["months_covered"] == 3
    assert data["cmf"]["cross_section_comparable"] is False
    assert data["cmf"]["historical_observation_count"] == 3
    assert data["cmf"]["issuer_catalog_derivation"] == "union_of_distinct_ruts_across_all_loaded_periods"
    assert data["cmf"]["issuer_catalog_count"] == len({
        item["rut"] for item in data["cmf"]["observations"]})
    assert {item["period"] for item in data["cmf"]["observations"]} == {
        "202606", "202603", "202503",
    }
    assert data["feature_use"] == "forbidden_until_availability_join"
    assert by_rut["76543210"]["analysis"]["revenue_growth_yoy"] == 0.2


def test_metric_coverage_excludes_partial_latest_period():
    latest = (_payload("202606") +
              "202606;76543210;EMPRESA CHILENA S.A.;I;CLP;Total de activos;5000;TAX CI;ESF\n")
    reference = (_payload("202506") +
                 _payload("202506").replace("76543210", "11111111").replace(
                     "EMPRESA CHILENA S.A.", "SEGUNDA EMPRESA S.A."))
    data = build_multi_period_dataset({"202606": latest.encode(), "202506": reference.encode()})
    assert data["cmf"]["sources"][0]["partial"] is True
    assert data["cmf"]["metric_coverage"]["total_assets"] == 0
    assert data["cmf"]["metric_coverage_excluded_partial_periods"] == ["202606"]
    snapshot = build_audit_snapshot(data)
    assert snapshot["cmf"]["issuer_count"] == 2
    assert snapshot["boundaries"]["orders"] == "prohibited"
    assert snapshot["decision_layer"]["buy_sell_recommendation"] is None
    assert snapshot["youtube"]["member_methodology"]["transcripts_persisted"] is False
    assert "holdings" not in json.dumps(snapshot)


def test_partial_cmf_period_is_enforced_out_of_causal_features():
    partial = _payload("202606", "1400", "140")
    complete = _payload("202603", "1200", "120")
    data = build_multi_period_dataset({"202606": partial.encode(), "202603": complete.encode()})
    data["cmf"]["sources"][0]["partial"] = True
    telegram = {"events": [
        {"event_type": "financial_statement", "company": "EMPRESA CHILENA S.A.",
         "period": "2T 2026", "balance_type": "Individual", "message_id": 1,
         "available_at": "2026-08-01T12:00:00+00:00"},
        {"event_type": "financial_statement", "company": "EMPRESA CHILENA S.A.",
         "period": "1T 2026", "balance_type": "Individual", "message_id": 2,
         "available_at": "2026-05-01T12:00:00+00:00"},
    ]}
    records = build_feature_records(data, telegram)
    assert [record["period"] for record in records] == ["202603"]
    report = feature_join_report(data, telegram)
    assert report["reduction_manifest"]["partial_periods_excluded"] == ["202606"]
    assert report["reduction_manifest"]["fuzzy_matching"] is False


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


def test_portfolio_event_monitor_marks_feed_gaps_without_predicting_dates():
    events = [
        {"message_id": 1, "event_type": "financial_statement", "company": "AGUAS ANDINAS S.A.",
         "available_at": "2026-08-20T16:57:35+00:00", "period": "2T 2026"},
        {"message_id": 2, "event_type": "financial_statement", "company": "EMPRESAS COPEC S.A.",
         "available_at": "2026-05-08T01:54:49+00:00", "period": "1T 2026"},
        {"message_id": 3, "event_type": "essential_notice", "company": "EMPRESAS COPEC S.A.",
         "available_at": "2026-08-11T23:35:23+00:00", "subject": "Otros"},
    ]
    result = portfolio_event_monitor(events, ["AGUAS ANDINAS S.A.", "EMPRESAS COPEC S.A."])
    assert result["latest_market_period"] == "2T 2026"
    assert result["positions_current"] == 1
    assert result["positions_pending_in_feed"] == 1
    aguas = result["by_company"][normalize_company("AGUAS ANDINAS S.A.")]
    copec = result["by_company"][normalize_company("EMPRESAS COPEC S.A.")]
    assert aguas["statement_status"] == "latest_period_detected"
    assert copec["statement_status"] == "latest_period_not_detected_in_feed"
    assert copec["essential_notices_30d"] == 1
    assert copec["date_prediction"] is None


def test_predictor_readiness_fails_closed_without_history_and_prices():
    state = readiness({"events": [{
        "event_type": "financial_statement", "company": "ENEL CHILE S.A.",
        "available_at": "2026-08-17T22:44:03+00:00", "period": "2T 2026",
    }], "window_truncated": False})
    assert state["can_train"] is False
    assert state["can_generate_signal"] is False
    assert state["youtube_feature_allowed"] is False
    assert len(state["blockers"]) == 2


def test_real_cmf_fixture_covers_operating_profit():
    root = Path(__file__).resolve().parents[1]
    rows = parse_rows((root / "fixtures/cmf_enel_chile_202603_sample.txt").read_bytes())
    result = analyze_company(rows)
    assert result["operating_profit"] == "325120000"
    assert result["operating_margin"] > 0


def test_cmf_base_url_rejects_preexisting_query():
    with pytest.raises(ValueError, match="allowlisted"):
        _validated_url("https://www.cmfchile.cl/institucional/estadisticas/ver_archivo.php?x=1",
                       "202603")


def _bank_payload(year="2026", institution="001", total="1.234,50"):
    return json.dumps({"ReportesBancarios": {"CodigosEstadosDeResultado": {
        "CodigoEERRIFI": [{
            "CodigoCuenta": "4100000",
            "DescripcionCuenta": "INGRESOS POR INTERESES Y REAJUSTES",
            "CodigoInstitucion": institution,
            "NombreInstitucion": "BANCO DE CHILE",
            "Anho": year,
            "Mes": "3",
            "MonedaTotal": total,
        }],
    }}}).encode()


def test_cmf_banks_parser_and_dataset_keep_sources_separate_and_redacted():
    rows = parse_results(_bank_payload())
    assert rows[0].total == Decimal("1234.50")
    url, redacted = validated_bank_url(2026, "001", "secret-value")
    assert "secret-value" in url
    assert "secret-value" not in redacted
    download = BankDownload(
        year=2026, institution_code="001", payload=_bank_payload(),
        effective_url_redacted=redacted, retrieved_at="2026-05-01T00:00:00+00:00",
        http_status=200, content_length=None, bytes_received=len(_bank_payload()),
    )
    data = build_bank_dataset([download])
    assert data["schema_version"] == "acciones-chile-banks-0.1.0"
    assert data["observations"][0]["ticker"] == "CHILE"
    assert data["observations"][0]["analysis"]["interest_income"] == "1234.50"
    assert data["observations"][0]["available_at"] is None
    assert data["feature_use"] == "forbidden_until_availability_join"
    assert "secret-value" not in json.dumps(data)


def test_cmf_banks_fails_closed_without_key_or_on_unknown_bank(monkeypatch):
    monkeypatch.delenv("CMF_BANKS_API_KEY", raising=False)
    assert bank_availability()["key_present"] is False
    with pytest.raises(ValueError, match="falta CMF_BANKS_API_KEY"):
        validated_bank_url(2026, "001", "")
    with pytest.raises(ValueError, match="no allowlisted"):
        validated_bank_url(2026, "999", "secret")


def test_cmf_banks_parser_rejects_schema_drift():
    with pytest.raises(ValueError, match="CodigosEstadosDeResultado"):
        parse_results(b'{"ReportesBancarios": {}}')


def test_cmf_banks_network_error_does_not_leak_key(monkeypatch):
    from modules.acciones_chile.banks import download_results

    def fail(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "bad key", {}, None)

    monkeypatch.setattr("modules.acciones_chile.banks.urllib.request.urlopen", fail)
    with pytest.raises(ValueError, match="consulta CMF Bancos falló") as error:
        download_results(2026, "001", "top-secret")
    assert "top-secret" not in str(error.value)
    assert error.value.__cause__ is None


def test_causal_join_requires_matching_period_scope_and_event():
    dataset = build_dataset(_payload().encode())
    telegram = {"events": [{
        "event_type": "financial_statement", "company": "EMPRESA CHILENA S.A.",
        "available_at": "2026-05-01T12:00:00+00:00", "period": "1T 2026",
        "balance_type": "Individual", "message_id": 42,
    }]}
    records = build_feature_records(dataset, telegram)
    assert telegram_period_to_cmf("1T 2026") == "202603"
    assert telegram_period_to_cmf("4T 2025 (Anual)") == "202512"
    assert len(records) == 1
    assert records[0]["available_at"] == "2026-05-01T12:00:00+00:00"
    assert records[0]["feature_use"] == "causal_feature_candidate_no_price_label"
    report = feature_join_report(dataset, telegram)
    assert report["match_complete"] is True


def test_join_report_exposes_unmatched_company_instead_of_silent_no_news():
    dataset = build_dataset(_payload().encode())
    telegram = {"events": [{
        "event_type": "financial_statement", "company": "EMPRESA SIN MAPEO S.A.",
        "available_at": "2026-05-01T12:00:00+00:00", "period": "1T 2026",
        "balance_type": "Individual", "message_id": 99,
    }]}
    report = feature_join_report(dataset, telegram)
    assert report["match_complete"] is False
    assert report["unmatched_companies"] == ["EMPRESA SIN MAPEO"]


def test_acciones_chile_has_no_crypto_or_executor_imports():
    root = Path(__file__).resolve().parents[1] / "modules/acciones_chile"
    forbidden = ("modules.trading", "modules.bot", "modules.coinsignals", "executor")
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
        assert not any(any(name.startswith(prefix) for prefix in forbidden) for name in names), path


def test_acciones_chile_transitive_import_graph_excludes_crypto_and_executor():
    root = Path(__file__).resolve().parents[1]
    forbidden = ("modules.trading", "modules.bot", "modules.coinsignals")
    pending = [f"modules.acciones_chile.{path.stem}" for path in
               (root / "modules/acciones_chile").glob("*.py") if path.stem != "__init__"]
    visited = set()
    while pending:
        module_name = pending.pop()
        if module_name in visited:
            continue
        visited.add(module_name)
        assert not module_name.startswith(forbidden), module_name
        module_path = root.joinpath(*module_name.split(".")).with_suffix(".py")
        if not module_path.exists():
            package_path = root.joinpath(*module_name.split("."), "__init__.py")
            if not package_path.exists():
                continue
            module_path = package_path
        package = module_name.rsplit(".", 1)[0]
        for node in ast.walk(ast.parse(module_path.read_text(encoding="utf-8"))):
            discovered = []
            if isinstance(node, ast.Import):
                discovered = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base_parts = package.split(".")
                    base = ".".join(base_parts[:len(base_parts) - node.level + 1])
                    if node.module:
                        discovered = [f"{base}.{node.module}"]
                    else:
                        discovered = [f"{base}.{alias.name}" for alias in node.names]
                elif node.module:
                    discovered = [node.module]
            for dependency in discovered:
                assert not dependency.startswith(forbidden), (module_name, dependency)
                candidate = root.joinpath(*dependency.split(".")).with_suffix(".py")
                package_candidate = root.joinpath(*dependency.split("."), "__init__.py")
                if candidate.exists() or package_candidate.exists():
                    pending.append(dependency)


def test_acciones_chile_page_exposes_verifiable_project_progress():
    root = Path(__file__).resolve().parents[1]
    page = (root / "modules/acciones_chile/public/index.html").read_text(encoding="utf-8")
    for element_id in (
        "progress-cmf", "progress-telegram", "progress-join", "progress-banks",
        "progress-market", "progress-auditor", "bank-state", "bank-detail",
        "portfolio-asof", "kpi-decision", "kpi-decision-note",
        "portfolio-events-summary",
        "portfolio-allocation", "allocation-bar", "allocation-legend", "allocation-risk",
        "company-decision-checklist",
        "progress-fx",
    ):
        assert f'id="{element_id}"' in page
    assert "s.cmf_banks" in page
    assert "s.eps_units" in page
    assert "x.causal_feature_candidates" in page
    assert "./api/save-portfolio" in page
    assert "./api/radar" in page
    assert "no es una cotización en vivo" in page
    # El gate de unidad/escala EPS se explica en prosa, no con la etiqueta interna.
    assert "Falta validar en el PDF auditado la unidad y la escala del EPS" in page
    assert "Factor de escala CMF" in page
    assert "EPS verificado" in page
    assert "EPS del ejercicio" in page
    assert "cotización por confirmar" in page
    assert "no prueba que el emisor no lo haya publicado" in page
    assert "no implica orden de rebalanceo" in page


def test_versioned_universe_is_partial_and_blocks_survivorship_backtest():
    root = Path(__file__).resolve().parents[1]
    universe = load_universe(root / "config/acciones_chile_universe_v0.1.json")
    status = universe_status(universe, "2026-08-22")
    assert status["member_count"] == 10
    assert status["coverage"] == "partial_top_weight_constituents"
    assert status["current_snapshot_complete"] is False
    assert status["membership_history_complete"] is False
    assert status["public_change_event_count"] == 3
    assert status["public_change_history_from"] == "2024-03-18"
    assert status["survivorship_free_backtest_allowed"] is False
    with pytest.raises(UniverseIncompleteError, match="sesgo de supervivencia"):
        snapshot_as_of(universe, "2026-08-22")
    sqm = resolve_ticker(universe, "sqm-b", "2026-08-22", require_complete=False)
    assert sqm["rut"] == "93007000"
    assert sqm["rut_dv"] == "9"


def test_complete_universe_requires_hashed_authorized_constituent_source():
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "config/acciones_chile_universe_v0.1.json").read_text())
    snapshot = data["snapshots"][0]
    snapshot["coverage"] = "complete_index_constituents"
    data["sources"]["licensed_constituents"] = {
        "url": "local-authorized-export.csv", "access": "licensed_local_file",
        "sha256": "a" * 64, "retrieved_at": "2026-08-22T12:00:00-04:00",
    }
    snapshot["verification"] = {
        "constituent_source_ref": "licensed_constituents",
        "verified_as_of": "2026-08-22", "constituent_count": len(snapshot["members"]),
    }
    for member in snapshot["members"]:
        member["source_refs"].append("licensed_constituents")
    assert validate_universe(data)["snapshots"][0]["coverage"] == "complete_index_constituents"
    data["sources"]["licensed_constituents"]["access"] = "public_unverified_copy"
    with pytest.raises(ValueError, match="fuente autorizada o licenciada"):
        validate_universe(data)


def _market_manifest(license_status="owned_export"):
    return {
        "schema_version": "acciones-chile-market-data-0.1.0",
        "provider": "Bolsa de Santiago",
        "source_reference": "factura/export owner",
        "license_status": license_status,
        "adjustment_method": "provider_total_return",
        "benchmark": {"ticker": "IPSA-TR", "return_type": "total_return"},
    }


def test_market_data_contract_requires_authorization_adjustment_and_aligned_benchmark():
    payload = (
        "session_date,ticker,open,high,low,close,volume,total_return_close,source_available_at\n"
        "2026-08-20,COPEC,7600,7700,7500,7650,1000,8120,2026-08-20T21:00:00-04:00\n"
        "2026-08-20,IPSA-TR,10000,10100,9900,10050,0,15420,2026-08-20T21:00:00-04:00\n"
    ).encode()
    records, summary = parse_market_csv(payload, _market_manifest())
    assert len(records) == 2
    assert summary["benchmark_ready"] is True
    assert summary["label_ready"] is True
    assert len(summary["sha256"]) == 64


def test_market_data_contract_fails_closed_without_license_or_benchmark_session():
    payload = (
        "session_date,ticker,open,high,low,close,volume,total_return_close,source_available_at\n"
        "2026-08-20,COPEC,7600,7700,7500,7650,1000,8120,2026-08-20T21:00:00-04:00\n"
    ).encode()
    with pytest.raises(ValueError, match="adquisición o autorización"):
        parse_market_csv(payload, _market_manifest("unknown"))
    _, summary = parse_market_csv(payload, _market_manifest())
    assert summary["label_ready"] is False
    assert summary["missing_benchmark_session_count"] == 1


def _pagina_chile():
    root = Path(__file__).resolve().parents[1]
    return (root / "modules/acciones_chile/public/index.html").read_text(encoding="utf-8")


def test_la_glosa_del_pe_no_lo_convierte_en_plazo_de_recuperacion():
    """Un P/E es un múltiplo, no los años en que recuperas lo invertido.

    Decir "pagas N años de la utilidad" insinúa un payback que el dato no
    sostiene: la utilidad no se reparte entera ni se mantiene constante.
    """
    page = _pagina_chile()
    assert "veces la utilidad por acción" in page
    assert "años de la utilidad" not in page


def test_las_fechas_de_resultado_se_atribuyen_al_feed_y_no_al_emisor():
    """`available_at` es la hora del mensaje de Telegram, no la emisión.

    La interfaz no puede decir "publicó el X el Y" ni declarar a un emisor
    "al día": el feed sólo prueba detección, nunca ausencia de publicación.
    """
    page = _pagina_chile()
    assert "El feed detectó su" in page
    assert "no prueba que el emisor no lo haya publicado" in page
    assert "hora en que el bot de Telegram anunció el documento" in page
    for prohibido in ("Está al día", "Publicó el ${", "Todavía no le veo publicaciones",
                      "ya publicó", "ya publicaron", "si ya publicó resultados"):
        assert prohibido not in page, prohibido
    # El resumen de cartera atribuye la detección al feed, igual que las tarjetas.
    assert "El feed detectó el ${s.latest_market_period" in page


def test_ver_evidencia_conserva_toda_la_trazabilidad_exigida():
    """Esconder la evidencia tras un desplegable no puede perderla."""
    page = _pagina_chile()
    for campo in (
        "EPS como viene en el TXT CMF", "EPS del PDF auditado",
        "Factor de escala CMF", "Página del PDF", "EPS en pesos",
        "Dólar observado BCCh", "P/E observado", "Valor justo",
        "Margen de seguridad", "Precio del snapshot",
    ):
        assert campo in page, campo
    # Los seis controles de decisión se listan uno a uno, no como contador.
    assert "de.checks.forEach" in page
    assert "'✓ listo'" in page and "'✗ falta'" in page


def test_la_tarjeta_ofrece_un_control_enfocable_para_abrir_la_ficha():
    """Abrir la ficha no puede depender del mouse (A11Y-01)."""
    page = _pagina_chile()
    assert "node('button',h.ticker,'pos-tk pos-open')" in page
    assert "tk.setAttribute('aria-label'" in page
    assert ".pos-open:focus-visible" in page
