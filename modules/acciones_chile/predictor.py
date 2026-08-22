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
        if available <= cutoff:
            known.append((available, event))
    known.sort(key=lambda item: item[0])
    statements = [(ts, event) for ts, event in known
                  if event.get("event_type") == "financial_statement"]
    notices_30d = sum(1 for ts, event in known
                      if event.get("event_type") == "essential_notice"
                      and ts >= cutoff - timedelta(days=30))
    last = statements[-1] if statements else None
    return {
        "company_key": wanted,
        "as_of": cutoff.isoformat(),
        "last_statement_available_at": last[0].isoformat() if last else None,
        "last_statement_period": last[1].get("period") if last else None,
        "days_since_last_statement": round((cutoff - last[0]).total_seconds() / 86400, 6)
        if last else None,
        "essential_notices_30d": notices_30d,
        "future_events_excluded": True,
    }


def readiness(telegram: dict | None, price_history_ready: bool = False) -> dict:
    events = (telegram or {}).get("events", [])
    statements = [event for event in events if event.get("event_type") == "financial_statement"]
    periods = sorted({event.get("period") for event in statements if event.get("period")})
    dates = sorted(event.get("available_at") for event in statements if event.get("available_at"))
    required_quarters = 8
    blockers = []
    if len(periods) < required_quarters:
        blockers.append(f"historia Telegram insuficiente: {len(periods)}/{required_quarters} trimestres")
    if not price_history_ready:
        blockers.append("falta fuente de precios ajustados y benchmark IPSA")
    return {
        "stage": "dataset_building",
        "can_train": not blockers,
        "can_generate_signal": False,
        "statement_events": len(statements),
        "companies": len({normalize_company(event.get("company", "")) for event in statements}),
        "periods": periods,
        "history_start": dates[0] if dates else None,
        "history_end": dates[-1] if dates else None,
        "minimum_quarters": required_quarters,
        "blockers": blockers,
        "youtube_feature_allowed": False,
        "portfolio_feature_allowed": False,
    }
