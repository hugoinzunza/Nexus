"""Evidencia inmutable para los escenarios dirigidos de Binance Demo.

Los artefactos viven junto al store Testnet, nunca en el libro productivo. El marker
es solo un indice: un escenario cuenta como aprobado unicamente si el artefacto existe,
su SHA-256 coincide y su contenido declara el mismo escenario y entorno Demo.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path


DEMO_URL = "https://demo-fapi.binance.com"
EVIDENCE_VERSION = "nexux.testnet-scenario-evidence.v1"
MARKER_PHASE = "testnet_scenario_readiness_v1"


def _canonical_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "xb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def record_scenario(data_dir: str | Path, scenario_id: str, details: dict,
                    *, status: str = "passed", observed_at_ms: int | None = None,
                    deployed_commit: str | None = None) -> dict:
    """Persiste un artefacto y actualiza atomicamente el indice de readiness."""
    if status not in {"passed", "failed"}:
        raise ValueError("status debe ser passed o failed")
    root = Path(data_dir).resolve()
    observed = int(observed_at_ms or time.time() * 1000)
    artifact = {
        "schema": EVIDENCE_VERSION,
        "scenario_id": scenario_id,
        "status": status,
        "observed_at_ms": observed,
        "environment": {"testnet": True, "base_url": DEMO_URL},
        "deployed_commit": deployed_commit,
        "details": details,
    }
    payload = _canonical_bytes(artifact)
    digest = hashlib.sha256(payload).hexdigest()
    evidence_dir = root / "scenario_evidence"
    artifact_path = evidence_dir / f"{observed}-{scenario_id}-{digest[:12]}.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with open(artifact_path, "xb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())

    marker_path = root / "live_readiness.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        marker = {}
    marker.setdefault("phase", MARKER_PHASE)
    marker.setdefault("started_at", observed // 1000)
    if deployed_commit:
        marker["deployed_commit"] = deployed_commit
    evidence = marker.setdefault("scenario_evidence", {})
    evidence[scenario_id] = {
        "status": status,
        "observed_at": observed // 1000,
        "evidence": {
            "artifact": str(artifact_path.relative_to(root)),
            "sha256": digest,
        },
    }
    _atomic_write(marker_path, _canonical_bytes(marker))
    return evidence[scenario_id]


def verify_scenario_record(data_dir: str | Path, scenario_id: str,
                           record: dict) -> bool:
    """Verifica referencia, hash y semantica minima del artefacto. Falla cerrado."""
    try:
        if record.get("status") != "passed" or not record.get("observed_at"):
            return False
        reference = record.get("evidence")
        if not isinstance(reference, dict):
            return False
        relative = Path(reference["artifact"])
        if relative.is_absolute() or ".." in relative.parts:
            return False
        root = Path(data_dir).resolve()
        artifact_path = (root / relative).resolve()
        evidence_root = (root / "scenario_evidence").resolve()
        if artifact_path.parent != evidence_root:
            return False
        payload = artifact_path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != reference.get("sha256"):
            return False
        artifact = json.loads(payload)
        return (
            artifact.get("schema") == EVIDENCE_VERSION
            and artifact.get("scenario_id") == scenario_id
            and artifact.get("status") == "passed"
            and artifact.get("environment") == {
                "testnet": True, "base_url": DEMO_URL,
            }
            and int(artifact.get("observed_at_ms") or 0) // 1000
            == int(record["observed_at"])
        )
    except (KeyError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
