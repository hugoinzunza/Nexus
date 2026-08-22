"""Universo bursátil versionado y resolución temporal ticker↔RUT."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path


SCHEMA_VERSION = "acciones-chile-universe-0.1.0"
COMPLETE_COVERAGE = "complete_index_constituents"
ALLOWED_COVERAGE = {COMPLETE_COVERAGE, "partial_top_weight_constituents"}
AUTHORIZED_SOURCE_ACCESS = {"licensed_local_file", "authorized_export"}


class UniverseIncompleteError(ValueError):
    """El snapshot existe, pero no sirve para un backtest sin supervivencia."""


def _rut_dv(rut: str) -> str:
    total, factor = 0, 2
    for digit in reversed(rut):
        total += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1
    result = 11 - total % 11
    return "0" if result == 11 else "K" if result == 10 else str(result)


def _iso_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} debe usar YYYY-MM-DD") from exc


def validate_universe(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("schema de universo no soportado")
    sources = data.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("universo sin fuentes")
    if not isinstance(data.get("membership_history_complete"), bool):
        raise ValueError("membership_history_complete debe ser booleano")
    changes = data.get("change_events", [])
    if not isinstance(changes, list):
        raise ValueError("change_events debe ser una lista")
    previous_change = None
    for change in changes:
        effective = _iso_date(change.get("effective_from"), "change effective_from")
        if previous_change and effective <= previous_change:
            raise ValueError("change_events deben estar ordenados y ser únicos")
        previous_change = effective
        additions = change.get("additions") or []
        deletions = change.get("deletions") or []
        if any(not re.fullmatch(r"[A-Z0-9-]{1,20}", ticker) for ticker in additions + deletions):
            raise ValueError("ticker inválido en change_events")
        if set(additions) & set(deletions):
            raise ValueError("un ticker no puede entrar y salir en el mismo cambio")
        refs = change.get("source_refs") or []
        if not refs or any(ref not in sources for ref in refs):
            raise ValueError("fuente inválida en change_events")
    snapshots = data.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("universo sin snapshots")
    previous_from = None
    previous_to = None
    for snapshot in snapshots:
        effective_from = _iso_date(snapshot.get("effective_from"), "effective_from")
        effective_to = (_iso_date(snapshot["effective_to"], "effective_to")
                        if snapshot.get("effective_to") else None)
        if effective_to and effective_to < effective_from:
            raise ValueError("effective_to anterior a effective_from")
        if previous_from and effective_from <= previous_from:
            raise ValueError("snapshots deben estar ordenados y ser únicos")
        if previous_from and previous_to is None:
            raise ValueError("snapshot abierto no puede tener sucesor")
        if previous_to and effective_from <= previous_to:
            raise ValueError("snapshots temporales se superponen")
        previous_from = effective_from
        previous_to = effective_to
        coverage = snapshot.get("coverage")
        if coverage not in ALLOWED_COVERAGE:
            raise ValueError("coverage de universo inválida")
        members = snapshot.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("snapshot sin miembros")
        if snapshot.get("declared_member_count") != len(members):
            raise ValueError("declared_member_count no coincide")
        if coverage == COMPLETE_COVERAGE:
            verification = snapshot.get("verification") or {}
            source_ref = verification.get("constituent_source_ref")
            source = sources.get(source_ref) or {}
            if source.get("access") not in AUTHORIZED_SOURCE_ACCESS:
                raise ValueError("snapshot completo requiere fuente autorizada o licenciada")
            if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256") or "")):
                raise ValueError("snapshot completo requiere SHA-256 de la fuente")
            _iso_date(verification.get("verified_as_of"), "verification verified_as_of")
            if verification.get("constituent_count") != len(members):
                raise ValueError("conteo verificado de componentes no coincide")
        tickers, ruts = set(), set()
        for member in members:
            ticker = str(member.get("ticker") or "")
            rut = str(member.get("rut") or "")
            dv = str(member.get("rut_dv") or "").upper()
            if not re.fullmatch(r"[A-Z0-9-]{1,20}", ticker):
                raise ValueError(f"ticker inválido: {ticker}")
            if not re.fullmatch(r"\d{7,8}", rut) or _rut_dv(rut) != dv:
                raise ValueError(f"RUT inválido para {ticker}")
            if ticker in tickers or rut in ruts:
                raise ValueError("ticker o RUT duplicado en snapshot")
            tickers.add(ticker)
            ruts.add(rut)
            refs = member.get("source_refs") or []
            if not refs or any(ref not in sources for ref in refs):
                raise ValueError(f"fuente inválida para {ticker}")
            if coverage == COMPLETE_COVERAGE and source_ref not in refs:
                raise ValueError(f"{ticker} no referencia la fuente completa autorizada")
    return data


def load_universe(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return validate_universe(json.load(handle))


def snapshot_as_of(data: dict, as_of: str | date, require_complete: bool = True) -> dict:
    validate_universe(data)
    target = _iso_date(as_of, "as_of") if isinstance(as_of, str) else as_of
    matches = []
    for snapshot in data["snapshots"]:
        start = _iso_date(snapshot["effective_from"], "effective_from")
        end = _iso_date(snapshot["effective_to"], "effective_to") if snapshot.get("effective_to") else None
        if start <= target and (end is None or target <= end):
            matches.append(snapshot)
    if len(matches) != 1:
        raise ValueError(f"no existe un snapshot único para {target.isoformat()}")
    snapshot = matches[0]
    if require_complete and snapshot["coverage"] != COMPLETE_COVERAGE:
        raise UniverseIncompleteError(
            f"universo {snapshot['coverage']}: prohibido para backtest sin sesgo de supervivencia")
    return snapshot


def resolve_ticker(data: dict, ticker: str, as_of: str | date,
                   require_complete: bool = True) -> dict | None:
    snapshot = snapshot_as_of(data, as_of, require_complete=require_complete)
    wanted = ticker.strip().upper()
    return next((member for member in snapshot["members"] if member["ticker"] == wanted), None)


def universe_status(data: dict, as_of: str | date) -> dict:
    snapshot = snapshot_as_of(data, as_of, require_complete=False)
    complete = snapshot["coverage"] == COMPLETE_COVERAGE
    history_complete = data["membership_history_complete"]
    backtest_allowed = complete and history_complete
    blockers = []
    if not complete:
        blockers.append("snapshot parcial: faltan componentes vigentes")
    if not history_complete:
        blockers.append("falta membresía histórica del índice para todo el período de backtest")
    return {
        "as_of": str(as_of),
        "effective_from": snapshot["effective_from"],
        "effective_to": snapshot.get("effective_to"),
        "coverage": snapshot["coverage"],
        "member_count": len(snapshot["members"]),
        "current_snapshot_complete": complete,
        "membership_history_complete": history_complete,
        "public_change_event_count": len(data.get("change_events", [])),
        "public_change_history_from": (data["change_events"][0]["effective_from"]
                                       if data.get("change_events") else None),
        "survivorship_free_backtest_allowed": backtest_allowed,
        "blockers": blockers,
    }
