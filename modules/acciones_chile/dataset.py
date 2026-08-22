"""Construcción y persistencia del dataset compacto de Acciones Chile."""
from __future__ import annotations

import hashlib
import gzip
import json
import os
import time
from collections import defaultdict

from .cmf import DEFAULT_URL, available_periods, download_period_details, parse_rows
from .fundamentals import analyze_company
from .youtube import FEED_URL, fetch_feed, parse_feed


SCHEMA_VERSION = "acciones-chile-dataset-0.5.0"


def _download_with_integrity(period: str, base_url: str = DEFAULT_URL,
                             downloader=None):
    """Exige una señal independiente cuando el servidor omite Content-Length."""
    fetch = downloader or download_period_details
    first = fetch(period, base_url=base_url)
    if first.content_length is not None:
        return first, {
            "transport_integrity": "content_length_exact_match",
            "verification_downloads": 1,
        }
    second = fetch(period, base_url=base_url)
    first_hash = hashlib.sha256(first.payload).hexdigest()
    second_hash = hashlib.sha256(second.payload).hexdigest()
    if first_hash != second_hash or first.bytes_received != second.bytes_received:
        raise ValueError(f"descargas CMF inconsistentes para {period}")
    return first, {
        "transport_integrity": "independent_redownload_sha256_match",
        "verification_downloads": 2,
        "verification_sha256": second_hash,
    }


def _persist_raw_artifact(artifact: str, payload: bytes) -> dict:
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    temp = artifact + ".tmp"
    with open(temp, "wb") as handle:
        handle.write(compressed)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, artifact)
    with open(artifact, "rb") as handle:
        persisted = handle.read()
    if persisted != compressed or gzip.decompress(persisted) != payload:
        raise ValueError("artefacto CMF persistido no reproduce la descarga")
    return {
        "raw_artifact_sha256": hashlib.sha256(persisted).hexdigest(),
        "raw_artifact_bytes": len(persisted),
        "gzip_reproducibility": "python_gzip_compresslevel_9_mtime_0",
        "raw_artifact_verified": True,
    }


def select_comparison_periods(periods: list[str]) -> tuple[str, str | None]:
    if not periods:
        raise ValueError("la CMF no informó períodos individuales")
    current = periods[0]
    prior = str(int(current) - 100)
    return current, prior if prior in periods else None


def select_refresh_periods(periods: list[str]) -> list[str]:
    """Todos los cierres trimestrales que la CMF expone, sin duplicados."""
    if not periods:
        raise ValueError("la CMF no informó períodos individuales")
    selected = []
    for period in periods:
        if len(period) != 6 or not period.isdigit() or period[-2:] not in {"03", "06", "09", "12"}:
            raise ValueError(f"período CMF inválido: {period}")
        if period not in selected:
            selected.append(period)
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


def _preferred_scope(rows):
    scopes = {row.scope for row in rows}
    selected = "C" if "C" in scopes else sorted(scopes)[0]
    return [row for row in rows if row.scope == selected], selected, sorted(scopes)


def _months_covered(period: str) -> int:
    return int(period[-2:])


def build_multi_period_dataset(payloads: dict[str, bytes], videos_payload: bytes | None = None,
                               source_metadata: dict[str, dict] | None = None) -> dict:
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
    if not periods:
        raise ValueError("dataset CMF vacío")
    all_ruts = sorted({rut for period in periods for rut in rows_by_period_rut[period]})
    observations = []
    for period in periods:
        for rut, raw_rows in rows_by_period_rut[period].items():
            rows, selected_scope, scopes = _preferred_scope(raw_rows)
            previous_raw = rows_by_period_rut.get(str(int(period) - 100), {}).get(rut, [])
            previous = [row for row in previous_raw if row.scope == selected_scope]
            observations.append({
                "rut": rut, "company": rows[0].company, "scope": selected_scope,
                "scopes_available": scopes, "currency": rows[0].currency,
                "period": period, "months_covered": _months_covered(period),
                "analysis": analyze_company(rows, previous),
                "available_at": None,
                "feature_use": "forbidden_until_telegram_join",
            })
    observations.sort(key=lambda item: (item["period"], item["company"].casefold()), reverse=True)
    issuers = []
    for rut in all_ruts:
        current_period = next(period for period in periods if rut in rows_by_period_rut[period])
        rows, selected_scope, scopes = _preferred_scope(rows_by_period_rut[current_period][rut])
        previous_raw = rows_by_period_rut.get(str(int(current_period) - 100), {}).get(rut, [])
        previous = [row for row in previous_raw if row.scope == selected_scope]
        analysis = analyze_company(rows, previous)
        latest_period = periods[0]
        periods_behind = max(0, ((int(latest_period[:4]) - int(current_period[:4])) * 12
                                 + int(latest_period[-2:]) - int(current_period[-2:])) // 3)
        issuers.append({
            "rut": rut, "company": rows[0].company, "scope": selected_scope,
            "scopes_available": scopes,
            "currency": rows[0].currency, "analysis": analysis,
            "latest_available_period": current_period,
            "months_covered": _months_covered(current_period),
            "periods_behind": periods_behind,
            "stale": periods_behind >= 4,
            "available_at": None,
            "feature_use": "forbidden_until_telegram_join",
        })
    issuers.sort(key=lambda item: item["company"].casefold())
    sources = []
    source_metadata = source_metadata or {}
    issuer_counts = {period: len(rows_by_period_rut[period]) for period in periods}
    issuer_reference_by_horizon = {
        horizon: max(count for period, count in issuer_counts.items() if period[-2:] == horizon)
        for horizon in {period[-2:] for period in periods}
    }
    for period in periods:
        prior_year = str(int(period) - 100)
        baseline_rows = len(parsed_by_period.get(prior_year, []))
        ratio = round(len(parsed_by_period[period]) / baseline_rows, 6) if baseline_rows else None
        issuer_reference = issuer_reference_by_horizon[period[-2:]]
        issuer_ratio = (round(issuer_counts[period] / issuer_reference, 6)
                        if issuer_reference else None)
        meta = source_metadata.get(period, {})
        partial = bool((ratio is not None and ratio < 0.7)
                       or (issuer_ratio is not None and issuer_ratio < 0.7))
        sources.append({
            "period": period,
            "url": meta.get("effective_url") or f"{DEFAULT_URL}?inicio={period}&termino={period}",
            "retrieved_at": meta.get("retrieved_at"),
            "http_status": meta.get("http_status"),
            "content_length": meta.get("content_length"),
            "content_length_status": ("provided_by_server" if meta.get("content_length") is not None
                                      else "absent_from_server_response"),
            "bytes_received": meta.get("bytes_received", len(payloads[period])),
            "sha256": hashlib.sha256(payloads[period]).hexdigest(),
            "sha256_scope": "downloaded_uncompressed_ifrs_txt_bytes",
            "raw_artifact_encoding": "gzip",
            "raw_artifact_sha256": meta.get("raw_artifact_sha256"),
            "raw_artifact_sha256_scope": (
                "persisted_deterministic_gzip_bytes" if meta.get("raw_artifact_sha256") else None),
            "raw_artifact_bytes": meta.get("raw_artifact_bytes"),
            "gzip_reproducibility": meta.get("gzip_reproducibility"),
            "raw_artifact_verified": meta.get("raw_artifact_verified", False),
            "transport_integrity": meta.get("transport_integrity"),
            "verification_downloads": meta.get("verification_downloads"),
            "verification_sha256": meta.get("verification_sha256"),
            "rows": len(parsed_by_period[period]),
            "months_covered": _months_covered(period),
            "completeness_ratio_yoy": ratio,
            "issuer_count": issuer_counts[period],
            "issuer_reference_max_same_horizon": issuer_reference,
            "issuer_coverage_ratio_same_horizon": issuer_ratio,
            "completeness_method": (
                "row_yoy_and_same_horizon_issuer_threshold_0.70" if ratio is not None
                else "same_horizon_issuer_threshold_0.70_no_row_yoy_baseline"),
            "partial": partial,
            "raw_artifact": meta.get("raw_artifact"),
        })
    metric_coverage = {}
    for metric in ("revenue", "operating_profit", "net_income", "basic_eps", "operating_cash_flow",
                   "free_cash_flow", "total_assets", "total_liabilities"):
        present = sum(item["analysis"].get(metric) is not None for item in issuers)
        metric_coverage[metric] = round(present / len(issuers), 6) if issuers else 0.0
    months = sorted({item["months_covered"] for item in issuers if not item["stale"]})
    videos = parse_feed(videos_payload) if videos_payload else []
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_ms": int(time.time() * 1000),
        "feature_use": "forbidden_until_availability_join",
        "cmf": {
            "periods": periods, "sources": sources, "issuers": issuers,
            "observations": observations,
            "historical_observation_count": len(observations),
            "metric_coverage": metric_coverage,
            "metric_coverage_scope": (
                "descriptive_latest_record_per_issuer_mixed_horizons_not_feature_or_radar_input"),
            "cross_section_comparable": len(months) <= 1,
            "months_covered_present": months,
        },
        "youtube": {"url": FEED_URL, "entries": videos, "source_role": "secondary_thesis"},
    }


def build_audit_snapshot(data: dict) -> dict:
    """Snapshot sin cartera ni datos personales para revisión externa."""
    from .strategy import SOURCE_VIDEOS, STRATEGY_VERSION

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
        "enforcement_evidence": {
            "partial_periods": "excluded in build_feature_records and single-period radar",
            "radar_comparability": (
                "build_radar selects one non-partial accounting close; the issuer catalog "
                "cross_section_comparable flag is false when latest issuer records mix horizons"),
            "artifact_integrity": (
                "sha256 covers exact downloaded uncompressed IFRS TXT bytes; raw artifact is "
                "read back and decompressed after deterministic gzip persistence; transport Content-Length "
                "is checked when present, otherwise two independent downloads must have equal SHA-256"),
            "universe_history": "price label readiness requires survivorship_free_backtest_allowed",
            "youtube": "youtube_feature_allowed=false; rubric emits research reading only",
            "portfolio_privacy": "stored by authenticated uid; excluded from audit snapshots and model features",
            "portfolio_events": (
                "Telegram is used only to monitor publication availability and recent notices; "
                "date_prediction=null and feed absence is not treated as proof of non-publication"),
            "explainable_decision": (
                "per-position checklist separates price, publication, fundamentals, observed multiple, "
                "fair value and margin of safety; buy/sell stay null and concentration is warning-only"),
            "fx_and_eps_units": (
                "USD conversion requires an official BCCh rate as-of price plus independently verified "
                "per-issuer EPS unit; neither missing input is inferred"),
            "module_isolation": (
                "first-party transitive import graph from acciones_chile reaches no crypto or "
                "order-executor modules"),
            "negative_tests": [
                "test_partial_cmf_period_is_enforced_out_of_causal_features",
                "test_versioned_universe_is_partial_and_blocks_survivorship_backtest",
                "test_acciones_chile_has_no_crypto_or_executor_imports",
                "test_authenticated_user_can_save_own_read_only_portfolio",
                "test_portfolio_discards_credentials_and_rejects_untrusted_metadata",
                "test_portfolio_event_monitor_marks_feed_gaps_without_predicting_dates",
                "test_decision_evidence_explains_missing_valuation_without_emitting_action",
                "test_portfolio_concentration_reports_risk_without_rebalance_recommendation",
                "test_bank_position_is_explicitly_blocked_without_separate_cmf_bank_data",
                "test_bcch_fx_adapter_is_redacted_causal_and_read_only",
                "test_bcch_fx_cache_fails_closed_when_tampered",
                "test_eps_unit_requires_audited_hashed_evidence",
                "test_cmf_missing_content_length_requires_matching_redownload",
                "test_deterministic_cmf_artifact_is_read_back_and_verified",
                "test_acciones_chile_transitive_import_graph_excludes_crypto_and_executor",
            ],
        },
        "cmf": {
            "periods": cmf.get("periods", []),
            "issuer_count": len(cmf.get("issuers", [])),
            "historical_observation_count": len(cmf.get("observations", [])),
            "sources": cmf.get("sources", []),
            "known_gap": "listed banks require the separate CMF Bancos source",
            "feature_use": data.get("feature_use"),
            "metric_coverage": cmf.get("metric_coverage", {}),
            "metric_coverage_scope": cmf.get("metric_coverage_scope"),
            "cross_section_comparable": cmf.get("cross_section_comparable"),
            "radar_contract": "one_non_partial_period_only",
        },
        "youtube": {
            "entry_count": len(youtube.get("entries", [])),
            "source_role": youtube.get("source_role"),
            "url": youtube.get("url"),
            "member_methodology": {
                "strategy_version": STRATEGY_VERSION,
                "sources": SOURCE_VIDEOS,
                "transcripts_persisted": False,
                "status": "editorial_interpretation_not_independently_reproducible",
                "feature_authority": "none",
                "rules": [
                    "evaluate several quarters before treating a weak result as thesis failure",
                    "review revenue, margins, profit, operating cash flow, free cash flow and balance quality",
                    "require sector-appropriate valuation and margin of safety before a buy/sell conclusion",
                    "allow several moderate warnings to combine or one critical factor to trigger thesis review",
                ],
            },
        },
        "decision_layer": {
            "current_output": "fundamental research signal only",
            "buy_sell_recommendation": None,
            "gate": "authorized prices, valuation and verified listed universe required",
        },
        "claims": [
            "CMF values are primary evidence with artifact hashes; transport Content-Length may be absent",
            "YouTube content is secondary thesis material, never ground truth",
            "mixed accounting horizons are labeled and forbidden for feature use",
        ],
    }


def refresh_dataset(path: str, base_url: str = DEFAULT_URL) -> dict:
    periods = available_periods()
    selected = select_refresh_periods(periods)
    verified = {period: _download_with_integrity(period, base_url=base_url)
                for period in selected}
    downloads = {period: result[0] for period, result in verified.items()}
    payloads = {period: item.payload for period, item in downloads.items()}
    metadata = {}
    raw_dir = os.path.join(os.path.dirname(path), "acciones_chile_cmf_raw")
    os.makedirs(raw_dir, exist_ok=True)
    for period, item in downloads.items():
        artifact = os.path.join(raw_dir, f"eifrs_{period}.txt.gz")
        artifact_evidence = _persist_raw_artifact(artifact, item.payload)
        metadata[period] = {
            "effective_url": item.effective_url, "retrieved_at": item.retrieved_at,
            "http_status": item.http_status, "content_length": item.content_length,
            "bytes_received": item.bytes_received,
            "raw_artifact": os.path.relpath(artifact, os.path.dirname(path)),
            **artifact_evidence,
            **verified[period][1],
        }
    dataset = build_multi_period_dataset(payloads, fetch_feed(), metadata)
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
