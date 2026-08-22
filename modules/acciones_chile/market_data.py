"""Contrato de importación para precios adquiridos o autorizados.

No descarga ni elude productos de datos. Convierte un CSV normalizado por el
owner a barras causales aptas para validación research-only.
"""
from __future__ import annotations

import csv
import hashlib
import io
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


SCHEMA_VERSION = "acciones-chile-market-data-0.1.0"
REQUIRED_COLUMNS = {
    "session_date", "ticker", "open", "high", "low", "close", "volume",
    "total_return_close", "source_available_at",
}
ALLOWED_LICENSE_STATUS = {"owned_export", "authorized_api"}
ALLOWED_ADJUSTMENTS = {"provider_total_return", "corporate_actions_rebuilt"}


def validate_manifest(manifest: dict) -> dict:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("manifest de precios no soportado")
    if manifest.get("license_status") not in ALLOWED_LICENSE_STATUS:
        raise ValueError("precios sin adquisición o autorización declarada")
    if manifest.get("adjustment_method") not in ALLOWED_ADJUSTMENTS:
        raise ValueError("método de ajuste corporativo no autorizado")
    if not manifest.get("provider") or not manifest.get("source_reference"):
        raise ValueError("manifest sin proveedor o referencia")
    benchmark = manifest.get("benchmark") or {}
    if not benchmark.get("ticker") or benchmark.get("return_type") != "total_return":
        raise ValueError("benchmark debe declarar ticker y retorno total")
    return manifest


def _decimal(value: str, field: str, *, positive: bool = True) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{field} inválido") from exc
    if not parsed.is_finite() or (positive and parsed <= 0) or (not positive and parsed < 0):
        raise ValueError(f"{field} fuera de rango")
    return parsed


def parse_market_csv(payload: bytes, manifest: dict) -> tuple[list[dict], dict]:
    validate_manifest(manifest)
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV debe usar UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    fields = set(reader.fieldnames or [])
    missing = REQUIRED_COLUMNS - fields
    if missing:
        raise ValueError(f"faltan columnas: {', '.join(sorted(missing))}")
    records, seen, by_ticker = [], set(), defaultdict(list)
    for row_number, row in enumerate(reader, start=2):
        try:
            session = date.fromisoformat(row["session_date"])
            available = datetime.fromisoformat(row["source_available_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"fecha inválida en fila {row_number}") from exc
        if available.tzinfo is None:
            raise ValueError(f"source_available_at sin zona en fila {row_number}")
        if available.date() < session:
            raise ValueError(f"source_available_at anterior a la rueda en fila {row_number}")
        ticker = (row["ticker"] or "").strip().upper()
        if not ticker:
            raise ValueError(f"ticker vacío en fila {row_number}")
        key = (session.isoformat(), ticker)
        if key in seen:
            raise ValueError(f"barra duplicada: {ticker} {session}")
        seen.add(key)
        prices = {field: _decimal(row[field], field) for field in ("open", "high", "low", "close")}
        volume = _decimal(row["volume"], "volume", positive=False)
        total_return = _decimal(row["total_return_close"], "total_return_close")
        if prices["low"] > min(prices["open"], prices["close"]):
            raise ValueError(f"low inconsistente en fila {row_number}")
        if prices["high"] < max(prices["open"], prices["close"]):
            raise ValueError(f"high inconsistente en fila {row_number}")
        record = {
            "session_date": session.isoformat(), "ticker": ticker,
            **{field: str(value) for field, value in prices.items()},
            "volume": str(volume), "total_return_close": str(total_return),
            "source_available_at": available.isoformat(),
        }
        records.append(record)
        by_ticker[ticker].append(session)
    if not records:
        raise ValueError("CSV de precios vacío")
    for ticker, sessions in by_ticker.items():
        if sessions != sorted(sessions):
            raise ValueError(f"fechas fuera de orden para {ticker}")
    benchmark_ticker = str(manifest["benchmark"]["ticker"]).upper()
    counts = Counter(record["ticker"] for record in records)
    benchmark_sessions = {
        record["session_date"] for record in records if record["ticker"] == benchmark_ticker}
    equity_sessions = {
        record["session_date"] for record in records if record["ticker"] != benchmark_ticker}
    missing_benchmark_sessions = sorted(equity_sessions - benchmark_sessions)
    benchmark_ready = bool(benchmark_sessions) and not missing_benchmark_sessions
    summary = {
        "schema_version": SCHEMA_VERSION,
        "provider": manifest["provider"],
        "license_status": manifest["license_status"],
        "adjustment_method": manifest["adjustment_method"],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "rows": len(records), "tickers": len(counts),
        "first_session": min(record["session_date"] for record in records),
        "last_session": max(record["session_date"] for record in records),
        "benchmark_ticker": benchmark_ticker,
        "benchmark_ready": benchmark_ready,
        "missing_benchmark_session_count": len(missing_benchmark_sessions),
        "label_ready": benchmark_ready,
        "blockers": [] if benchmark_ready else [
            "benchmark total-return ausente o sin cobertura para todas las ruedas"
        ],
    }
    return records, summary
