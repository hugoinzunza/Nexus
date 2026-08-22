"""Preparación causal del predictor; no entrena ni emite recomendaciones."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone


LEGAL_SUFFIX = re.compile(r"\b(S A|SA|SPA|S A A|LTDA)\b")


def normalize_company(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char)).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return " ".join(LEGAL_SUFFIX.sub(" ", text).split())


def event_features(events: list[dict], company: str, as_of: str) -> dict:
    """Features observables hasta `as_of`; descarta estrictamente el futuro."""
    cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    wanted = normalize_company(company)
    known = []
    for event in events:
        if normalize_company(event.get("company", "")) != wanted:
            continue
        available = datetime.fromisoformat(event["available_at"].replace("Z", "+00:00"))
        if available < cutoff:
            known.append((available, event))
    known.sort(key=lambda item: item[0])
    statements = [(ts, event) for ts, event in known
                  if event.get("event_type") == "financial_statement"]
    notices_30d = sum(1 for ts, event in known
                      if event.get("event_type") == "essential_notice"
                      and ts >= cutoff - timedelta(days=30))
    last = statements[-1] if statements else None
    future_count = sum(1 for event in events
                       if normalize_company(event.get("company", "")) == wanted
                       and datetime.fromisoformat(event["available_at"].replace("Z", "+00:00")) >= cutoff)
    return {
        "company_key": wanted,
        "as_of": cutoff.isoformat(),
        "last_statement_available_at": last[0].isoformat() if last else None,
        "last_statement_period": last[1].get("period") if last else None,
        "days_since_last_statement": round((cutoff - last[0]).total_seconds() / 86400, 6)
        if last else None,
        "essential_notices_30d": notices_30d,
        "future_events_excluded": future_count > 0,
        "excluded_future_event_count": future_count,
    }


def telegram_period_to_cmf(label: str | None) -> str | None:
    match = re.fullmatch(
        r"([1-4])T\s+(\d{4})(?:\s*\(ANUAL\))?",
        (label or "").strip(), flags=re.IGNORECASE,
    )
    if not match:
        return None
    return f"{match.group(2)}{int(match.group(1)) * 3:02d}"


def _period_label(period: str | None) -> str | None:
    if not period or len(period) != 6 or not period.isdigit():
        return None
    month = int(period[-2:])
    if month not in {3, 6, 9, 12}:
        return None
    return f"{month // 3}T {period[:4]}"


def portfolio_event_monitor(events: list[dict], companies: list[str]) -> dict:
    """Resume eventos causales del feed para una cartera, sin predecir fechas."""
    dated = []
    for event in events:
        try:
            available = datetime.fromisoformat(str(event["available_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if available.tzinfo is None:
            available = available.replace(tzinfo=timezone.utc)
        dated.append((available, event))
    cutoff = max((available for available, _ in dated), default=None)
    statements = [(available, event, telegram_period_to_cmf(event.get("period")))
                  for available, event in dated
                  if event.get("event_type") == "financial_statement"]
    latest_market_period = max((period for _, _, period in statements if period), default=None)
    results = {}
    for company in companies:
        key = normalize_company(company)
        company_events = [(available, event) for available, event in dated
                          if normalize_company(event.get("company", "")) == key]
        company_statements = [(available, event, telegram_period_to_cmf(event.get("period")))
                              for available, event in company_events
                              if event.get("event_type") == "financial_statement"]
        company_notices = [(available, event) for available, event in company_events
                           if event.get("event_type") == "essential_notice"]
        last_statement = max(company_statements, default=None, key=lambda item: item[0])
        last_notice = max(company_notices, default=None, key=lambda item: item[0])
        last_period = last_statement[2] if last_statement else None
        if latest_market_period and last_period == latest_market_period:
            statement_status = "latest_period_detected"
        elif last_statement:
            statement_status = "latest_period_not_detected_in_feed"
        else:
            statement_status = "no_statement_detected"
        notices_30d = (sum(1 for available, _ in company_notices
                           if cutoff and available >= cutoff - timedelta(days=30)))
        results[key] = {
            "statement_status": statement_status,
            "latest_market_period": _period_label(latest_market_period),
            "last_statement_period": last_statement[1].get("period") if last_statement else None,
            "last_statement_available_at": last_statement[0].isoformat() if last_statement else None,
            "last_notice_available_at": last_notice[0].isoformat() if last_notice else None,
            "last_notice_subject": last_notice[1].get("subject") if last_notice else None,
            "essential_notices_30d": notices_30d,
            "source_role": "publication_availability_monitor",
            "date_prediction": None,
        }
    current = sum(item["statement_status"] == "latest_period_detected" for item in results.values())
    pending = sum(item["statement_status"] != "latest_period_detected" for item in results.values())
    recent = sum(item["essential_notices_30d"] > 0 for item in results.values())
    return {
        "as_of": cutoff.isoformat() if cutoff else None,
        "latest_market_period": _period_label(latest_market_period),
        "positions_current": current,
        "positions_pending_in_feed": pending,
        "positions_with_recent_notice": recent,
        "by_company": results,
        "disclaimer": "ausencia en el feed no demuestra que el emisor no haya publicado",
    }


def build_feature_records(dataset: dict, telegram: dict | None) -> list[dict]:
    """Une CMF↔Telegram; solo devuelve fundamentales con disponibilidad demostrada."""
    events = (telegram or {}).get("events", [])
    event_index = {}
    for event in events:
        if event.get("event_type") != "financial_statement":
            continue
        period = telegram_period_to_cmf(event.get("period"))
        if not period:
            continue
        key = (normalize_company(event.get("company", "")), period,
               "C" if event.get("balance_type") == "Consolidado" else "I")
        current = event_index.get(key)
        if current is None or event["available_at"] < current["available_at"]:
            event_index[key] = event
    records = []
    cmf = dataset.get("cmf") or {}
    partial_periods = {
        str(source.get("period")) for source in cmf.get("sources", [])
        if source.get("partial")
    }
    fundamentals = cmf.get("observations") or cmf.get("issuers", [])
    for issuer in fundamentals:
        period = issuer.get("period") or issuer.get("latest_available_period")
        # Enforcement, no solo metadato: un cierre CMF incompleto nunca entra al
        # conjunto candidato aunque Telegram ya haya anunciado su publicación.
        if str(period) in partial_periods:
            continue
        key = (normalize_company(issuer.get("company", "")), period, issuer.get("scope"))
        event = event_index.get(key)
        if not event:
            continue
        records.append({
            "rut": issuer["rut"], "company": issuer["company"],
            "period": period,
            "months_covered": issuer.get("months_covered"),
            "available_at": event["available_at"],
            "source_message_id": event["message_id"],
            "fundamentals": issuer["analysis"],
            "feature_use": "causal_feature_candidate_no_price_label",
        })
    return records


def feature_join_report(dataset: dict, telegram: dict | None) -> dict:
    records = build_feature_records(dataset, telegram)
    cmf = dataset.get("cmf") or {}
    fundamentals = cmf.get("observations") or cmf.get("issuers", [])
    partial_periods = sorted(str(source.get("period")) for source in cmf.get("sources", [])
                             if source.get("partial"))
    statement_companies = {
        normalize_company(event.get("company", ""))
        for event in (telegram or {}).get("events", [])
        if event.get("event_type") == "financial_statement"
    }
    matched_companies = {normalize_company(record["company"]) for record in records}
    unmatched = sorted(statement_companies - matched_companies)
    return {
        "candidate_records": len(records),
        "cmf_catalog_issuers": len(cmf.get("issuers", [])),
        "cmf_historical_observations": len(fundamentals),
        "telegram_companies": len(statement_companies),
        "matched_companies": len(matched_companies),
        "unmatched_companies": unmatched,
        "match_complete": not unmatched,
        "reduction_manifest": {
            "cmf_catalog_role": "all issuers with CMF IFRS observations; not a trading universe",
            "telegram_company_role": "companies announced by the bot; not a subset selected from CMF",
            "join_keys": ["normalized exact company name", "period", "consolidated_or_individual_scope"],
            "fuzzy_matching": False,
            "unmatched_policy": "exclude; never fabricate or approximate a match",
            "partial_periods_excluded": partial_periods,
            "candidate_role": "causal research record without price label",
        },
    }


def readiness(telegram: dict | None, price_history_ready: bool = False) -> dict:
    events = (telegram or {}).get("events", [])
    statements = [event for event in events if event.get("event_type") == "financial_statement"]
    observations = {}
    for event in statements:
        key = (normalize_company(event.get("company", "")), event.get("period"))
        if key[0] and key[1]:
            current = observations.get(key)
            if current is None or event.get("available_at", "") < current.get("available_at", ""):
                observations[key] = event
    periods = sorted({period for _, period in observations})
    by_company = {}
    for company, period in observations:
        by_company.setdefault(company, set()).add(period)
    counts = sorted(len(company_periods) for company_periods in by_company.values())
    dates = sorted(event.get("available_at") for event in statements if event.get("available_at"))
    required_quarters = 8
    blockers = []
    minimum_company_quarters = counts[0] if counts else 0
    maximum_company_quarters = counts[-1] if counts else 0
    eligible_companies = sum(count >= required_quarters for count in counts)
    if minimum_company_quarters < required_quarters:
        blockers.append(
            f"historia por empresa insuficiente: mínimo {minimum_company_quarters}/{required_quarters} trimestres")
    if (telegram or {}).get("window_truncated", True):
        blockers.append("historial Telegram todavía truncado; backfill incompleto")
    if not price_history_ready:
        blockers.append("falta fuente de precios ajustados y benchmark IPSA")
    return {
        "stage": "dataset_building",
        "can_train": not blockers,
        "can_generate_signal": False,
        "statement_events": len(statements),
        "distinct_observations": len(observations),
        "companies": len(by_company),
        "minimum_company_quarters_observed": minimum_company_quarters,
        "median_company_quarters_observed": counts[len(counts) // 2] if counts else 0,
        "maximum_company_quarters_observed": maximum_company_quarters,
        "eligible_companies_with_minimum_quarters": eligible_companies,
        "periods": periods,
        "history_start": dates[0] if dates else None,
        "history_end": dates[-1] if dates else None,
        "minimum_quarters": required_quarters,
        "window_truncated": (telegram or {}).get("window_truncated", True),
        "blockers": blockers,
        "youtube_feature_allowed": False,
        "portfolio_feature_allowed": False,
    }
