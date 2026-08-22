"""Construcción y persistencia del dataset compacto de Acciones Chile."""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import defaultdict

from .cmf import DEFAULT_URL, available_periods, download_period, parse_rows
from .fundamentals import analyze_company
from .youtube import FEED_URL, fetch_feed, parse_feed


SCHEMA_VERSION = "acciones-chile-dataset-0.1.0"


def select_comparison_periods(periods: list[str]) -> tuple[str, str | None]:
    if not periods:
        raise ValueError("la CMF no informó períodos individuales")
    current = periods[0]
    prior = str(int(current) - 100)
    return current, prior if prior in periods else None


def select_refresh_periods(periods: list[str]) -> list[str]:
    """Últimos dos cierres y sus comparables interanuales, sin duplicados."""
    if not periods:
        raise ValueError("la CMF no informó períodos individuales")
    selected = []
    for period in periods[:2]:
        for candidate in (period, str(int(period) - 100)):
            if candidate in periods and candidate not in selected:
                selected.append(candidate)
    return selected


def build_dataset(current_payload: bytes, previous_payload: bytes | None = None,
                  videos_payload: bytes | None = None) -> dict:
    current_rows = parse_rows(current_payload)
    payloads = {current_rows[0].period: current_payload} if current_rows else {}
    if previous_payload:
        previous_rows = parse_rows(previous_payload)
        if previous_rows:
            payloads[previous_rows[0].period] = previous_payload
    return build_multi_period_dataset(payloads, videos_payload)


def build_multi_period_dataset(payloads: dict[str, bytes], videos_payload: bytes | None = None) -> dict:
    rows_by_period_rut = defaultdict(lambda: defaultdict(list))
    parsed_by_period = {}
    for expected_period, payload in payloads.items():
        rows = parse_rows(payload)
        if rows and any(row.period != expected_period for row in rows):
            raise ValueError("archivo CMF mezcla o contradice el período solicitado")
        parsed_by_period[expected_period] = rows
        for row in rows:
            rows_by_period_rut[expected_period][row.rut].append(row)
    periods = sorted(parsed_by_period, reverse=True)
    all_ruts = sorted({rut for period in periods for rut in rows_by_period_rut[period]})
    issuers = []
    for rut in all_ruts:
        current_period = next(period for period in periods if rut in rows_by_period_rut[period])
        rows = rows_by_period_rut[current_period][rut]
        previous = rows_by_period_rut.get(str(int(current_period) - 100), {}).get(rut, [])
        analysis = analyze_company(rows, previous)
        issuers.append({
            "rut": rut, "company": rows[0].company, "scope": rows[0].scope,
            "currency": rows[0].currency, "analysis": analysis,
            "latest_available_period": current_period,
        })
    issuers.sort(key=lambda item: item["company"].casefold())
    sources = [{
        "period": period, "url": DEFAULT_URL,
        "sha256": hashlib.sha256(payloads[period]).hexdigest(),
        "rows": len(parsed_by_period[period]),
    } for period in periods]
    videos = parse_feed(videos_payload) if videos_payload else []
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_ms": int(time.time() * 1000),
        "cmf": {"periods": periods, "sources": sources, "issuers": issuers},
        "youtube": {"url": FEED_URL, "entries": videos, "source_role": "secondary_thesis"},
    }


def build_audit_snapshot(data: dict) -> dict:
    """Snapshot sin cartera ni datos personales para revisión externa."""
    cmf = data.get("cmf", {})
    youtube = data.get("youtube", {})
    return {
        "scope": "NexUX Acciones Chile progress audit",
        "schema_version": data.get("schema_version"),
        "generated_at_ms": data.get("generated_at_ms"),
        "boundaries": {
            "orders": "prohibited", "broker_credentials": "not_stored",
            "crypto_dependency": "prohibited", "auditor_authority": "advisory_only",
        },
        "cmf": {
            "periods": cmf.get("periods", []),
            "issuer_count": len(cmf.get("issuers", [])),
            "sources": cmf.get("sources", []),
            "known_gap": "listed banks require the separate CMF Bancos source",
        },
        "youtube": {
            "entry_count": len(youtube.get("entries", [])),
            "source_role": youtube.get("source_role"),
            "url": youtube.get("url"),
        },
        "claims": [
            "CMF values are primary evidence with source hashes",
            "YouTube content is secondary thesis material, never ground truth",
            "latest available period is selected per issuer to tolerate partial reporting",
        ],
    }


def refresh_dataset(path: str, base_url: str = DEFAULT_URL) -> dict:
    periods = available_periods()
    selected = select_refresh_periods(periods)
    payloads = {period: download_period(period, base_url=base_url) for period in selected}
    dataset = build_multi_period_dataset(payloads, fetch_feed())
    write_dataset(path, dataset)
    return dataset


def read_dataset(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if data.get("schema_version") == SCHEMA_VERSION else None
    except (FileNotFoundError, OSError, ValueError, AttributeError):
        return None


def write_dataset(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
