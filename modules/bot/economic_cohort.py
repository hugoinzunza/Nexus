"""Contrato operativo para la cohorte economica dry ECON-COHORT-001.

La cohorte no decide ni activa live. Durante la recoleccion solo valida que la
politica siga congelada y ata cada apertura a hashes reproducibles.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL_PATH = ROOT / "config" / "bot_econ_cohort_001.frozen.json"


class EconomicCohortError(ValueError):
    """La configuracion ya no coincide con el protocolo congelado."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def policy_projection(bot_config: dict[str, Any]) -> dict[str, Any]:
    """Configuracion completa, quitando solo el checksum autorreferente."""
    projected = json.loads(json.dumps(bot_config))
    cohort = projected.get("economic_cohort")
    if isinstance(cohort, dict):
        cohort.pop("protocol_sha256", None)
    return projected


def load_and_validate(
    bot_config: dict[str, Any], protocol_path: str | Path = DEFAULT_PROTOCOL_PATH
) -> tuple[dict[str, Any], str]:
    path = Path(protocol_path)
    try:
        raw = path.read_bytes()
        protocol = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise EconomicCohortError(f"protocolo ECON ilegible: {exc}") from exc

    cohort_cfg = bot_config.get("economic_cohort") or {}
    if not cohort_cfg.get("enabled"):
        raise EconomicCohortError("ECON-COHORT-001 no esta habilitada")
    if bot_config.get("live"):
        raise EconomicCohortError("ECON-COHORT-001 es exclusivamente dry")
    if not protocol.get("frozen") or protocol.get("cohort_id") != cohort_cfg.get("cohort_id"):
        raise EconomicCohortError("identidad o estado del protocolo ECON invalido")

    protocol_sha = hashlib.sha256(raw).hexdigest()
    if protocol_sha != cohort_cfg.get("protocol_sha256"):
        raise EconomicCohortError("hash del protocolo ECON no coincide")

    policy = policy_projection(bot_config)
    policy_path = ROOT / str(protocol.get("frozen_bot_policy_path") or "")
    try:
        frozen_policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EconomicCohortError(f"snapshot de politica ECON ilegible: {exc}") from exc
    policy_sha = sha256_value(policy)
    if policy_sha != protocol.get("frozen_bot_policy_sha256"):
        raise EconomicCohortError("la politica completa del bot cambio; se requiere cohorte nueva")
    if sha256_value(frozen_policy) != protocol.get("frozen_bot_policy_sha256"):
        raise EconomicCohortError("hash del snapshot de politica ECON no coincide")
    if policy != frozen_policy:
        raise EconomicCohortError("el snapshot de politica ECON no coincide")
    return protocol, protocol_sha


def trade_metadata(
    bot_config: dict[str, Any], now_ms: int | None = None
) -> dict[str, Any]:
    protocol, protocol_sha = load_and_validate(bot_config)
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    if now_ms < int(protocol["activation"]["start_at_ms"]):
        raise EconomicCohortError("ECON-COHORT-001 aun no alcanza su inicio pre-registrado")
    return {
        "economic_cohort_id": protocol["cohort_id"],
        "economic_protocol_sha256": protocol_sha,
        "economic_policy_sha256": protocol["frozen_bot_policy_sha256"],
    }


def operational_status(
    trades: list[dict[str, Any]], bot_config: dict[str, Any], now_ms: int | None = None
) -> dict[str, Any]:
    """Expone conteos, nunca resultados, antes de la unica evaluacion final."""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    try:
        protocol, protocol_sha = load_and_validate(bot_config)
    except EconomicCohortError as exc:
        return {"status": "invalid", "reason": str(exc), "automatic_live": False}

    cohort_id = protocol["cohort_id"]
    start_ms = int(protocol["activation"]["start_at_ms"])
    eligible = []
    for trade in trades:
        opened = float(trade.get("opened_at") or 0)
        opened_ms = int(opened * 1000 if opened < 1_000_000_000_000 else opened)
        if trade.get("economic_cohort_id") == cohort_id and opened_ms >= start_ms:
            eligible.append(trade)
    closed = sorted(
        (t for t in eligible if t.get("status") == "cerrada"),
        key=lambda row: (int(row.get("closed_at") or 0), str(row.get("setup_id") or "")),
    )
    target = int(protocol["stopping_rule"]["exact_closed_trades"])
    deadline_ms = int(protocol["stopping_rule"]["deadline_ms"])
    reached_target = len(closed) >= target
    reached_deadline = now_ms >= deadline_ms
    started = now_ms >= start_ms
    return {
        "cohort_id": cohort_id,
        "protocol_sha256": protocol_sha,
        "status": (
            "scheduled" if not started else
            "ready_for_single_evaluation" if (reached_target or reached_deadline) else
            "collecting"
        ),
        "opened": len(eligible),
        "closed": min(len(closed), target),
        "target_closed": target,
        "deadline_ms": deadline_ms,
        "start_at_ms": start_ms,
        "stop_reason": "n_exact" if reached_target else ("deadline" if reached_deadline else None),
        "outcome_metrics_hidden_until_close": True,
        "automatic_live": False,
    }
