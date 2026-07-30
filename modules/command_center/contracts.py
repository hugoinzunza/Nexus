"""Contrato v1 congelado para snapshots y eventos del Command Center.

La compatibilidad dentro de v1 es aditiva: pueden aparecer campos opcionales,
pero no se eliminan campos requeridos ni cambian sus tipos o semántica.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

CONTRACT_VERSION = 1
SNAPSHOT_CONTRACT = "nexux.command-center.snapshot"
EVENT_CONTRACT = "nexux.command-center.event"

HEALTH_VALUES = frozenset({"healthy", "degraded", "failed", "unknown"})
FRESHNESS_VALUES = frozenset({"live", "current", "stale", "expired"})
MODE_VALUES = frozenset(
    {"live", "testnet", "dry", "shadow", "research", "disabled"}
)
SEVERITY_VALUES = frozenset(
    {"normal", "info", "warning", "critical", "unknown"}
)
KIND_VALUES = frozenset({"snapshot", "patch", "event"})

_TOPIC_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")

# Esta estructura es el contrato que queda congelado antes del EventBus. Cambiarla
# exige una decisión explícita de compatibilidad y actualizar el fingerprint.
CONTRACT_V1_SPEC = {
    "snapshot_required": [
        "contract",
        "v",
        "contract_fingerprint",
        "snapshot_id",
        "subject",
        "generated_at",
        "topics",
        "cursors",
    ],
    "envelope_required": [
        "contract",
        "v",
        "topic",
        "kind",
        "subject",
        "seq",
        "observed_at",
        "received_at",
        "expires_at",
        "severity",
        "source",
        "payload",
    ],
    "projection_state_required": [
        "health",
        "freshness",
        "mode",
        "severity",
        "source",
        "as_of",
    ],
    "snapshot_types": {
        "contract": "string",
        "v": "integer",
        "contract_fingerprint": "string",
        "snapshot_id": "string",
        "subject": "string",
        "generated_at": "integer",
        "topics": "object",
        "cursors": "object",
    },
    "envelope_types": {
        "contract": "string",
        "v": "integer",
        "topic": "string",
        "kind": "string",
        "subject": "string",
        "seq": "integer",
        "observed_at": "integer",
        "received_at": "integer",
        "expires_at": "integer",
        "severity": "string",
        "source": "string",
        "payload": "object",
    },
    "projection_payload_types": {"state": "object", "data": "object"},
    "enums": {
        "health": ["healthy", "degraded", "failed", "unknown"],
        "freshness": ["live", "current", "stale", "expired"],
        "mode": ["live", "testnet", "dry", "shadow", "research", "disabled"],
        "severity": ["normal", "info", "warning", "critical", "unknown"],
        "kind": ["snapshot", "patch", "event"],
    },
    "patch_semantics": "RFC7396 JSON Merge Patch",
    "sequence_semantics": "strictly contiguous per topic; duplicates ignored",
    "projection_consistency": (
        "envelope severity/source/observed_at equal "
        "payload.state severity/source/as_of"
    ),
    "compatibility": "v1 additive only",
}
CONTRACT_V1_FINGERPRINT = (
    "fa5892bd3fea247638a59a282aedbd80eebfcf6bbc6b034c1919a7cf5dae716d"
)


class ContractViolation(ValueError):
    """Un payload no cumple el contrato congelado."""


@dataclass(frozen=True)
class ReplayState:
    """Estado reconstruido únicamente desde snapshot y envelopes posteriores."""

    subject: str
    topics: dict[str, dict[str, Any]]
    cursors: dict[str, int]


def _fingerprint() -> str:
    canonical = json.dumps(
        CONTRACT_V1_SPEC, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def assert_contract_frozen() -> None:
    actual = _fingerprint()
    if actual != CONTRACT_V1_FINGERPRINT:
        raise RuntimeError(
            "el contrato v1 cambio sin actualizar su decision de compatibilidad "
            f"({actual})"
        )


def _required_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractViolation(f"{name} debe ser objeto")
    return value


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractViolation(f"{name} debe ser string no vacio")
    return value


def _required_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ContractViolation(f"{name} debe ser entero >= {minimum}")
    return value


def _require_fields(value: Mapping[str, Any], fields: Iterable[str], name: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise ContractViolation(f"{name} incompleto: faltan {', '.join(missing)}")


def validate_projection_payload(payload: Any) -> dict[str, Any]:
    data = _required_dict(payload, "payload")
    _require_fields(data, ("state", "data"), "payload")
    state = _required_dict(data["state"], "payload.state")
    _require_fields(
        state, CONTRACT_V1_SPEC["projection_state_required"], "payload.state"
    )
    if state["health"] not in HEALTH_VALUES:
        raise ContractViolation("health invalido")
    if state["freshness"] not in FRESHNESS_VALUES:
        raise ContractViolation("freshness invalido")
    if state["mode"] not in MODE_VALUES:
        raise ContractViolation("mode invalido")
    if state["severity"] not in SEVERITY_VALUES:
        raise ContractViolation("severity invalida")
    _required_string(state["source"], "payload.state.source")
    _required_int(state["as_of"], "payload.state.as_of")
    _required_dict(data["data"], "payload.data")
    return data


def _validate_projection_consistency(
    envelope: Mapping[str, Any], payload: Mapping[str, Any]
) -> None:
    state = payload["state"]
    if state["severity"] != envelope["severity"]:
        raise ContractViolation("severity contradice payload.state")
    if state["source"] != envelope["source"]:
        raise ContractViolation("source contradice payload.state")
    if state["as_of"] != envelope["observed_at"]:
        raise ContractViolation("observed_at contradice payload.state.as_of")


def validate_envelope(envelope: Any) -> dict[str, Any]:
    data = _required_dict(envelope, "envelope")
    _require_fields(data, CONTRACT_V1_SPEC["envelope_required"], "envelope")
    if data["contract"] != EVENT_CONTRACT:
        raise ContractViolation("contrato de envelope invalido")
    if data["v"] != CONTRACT_VERSION:
        raise ContractViolation("version de envelope no soportada")
    topic = _required_string(data["topic"], "topic")
    if not _TOPIC_RE.fullmatch(topic):
        raise ContractViolation("topic invalido")
    if data["kind"] not in KIND_VALUES:
        raise ContractViolation("kind invalido")
    _required_string(data["subject"], "subject")
    _required_int(data["seq"], "seq")
    _required_int(data["observed_at"], "observed_at")
    _required_int(data["received_at"], "received_at")
    expires_at = _required_int(data["expires_at"], "expires_at")
    if expires_at < data["observed_at"]:
        raise ContractViolation("expires_at anterior a observed_at")
    if data["severity"] not in SEVERITY_VALUES:
        raise ContractViolation("severity invalida")
    _required_string(data["source"], "source")
    _required_dict(data["payload"], "payload")
    if data["kind"] == "snapshot":
        projection = validate_projection_payload(data["payload"])
        _validate_projection_consistency(data, projection)
    return data


def validate_snapshot(snapshot: Any) -> dict[str, Any]:
    data = _required_dict(snapshot, "snapshot")
    _require_fields(data, CONTRACT_V1_SPEC["snapshot_required"], "snapshot")
    if data["contract"] != SNAPSHOT_CONTRACT:
        raise ContractViolation("contrato de snapshot invalido")
    if data["v"] != CONTRACT_VERSION:
        raise ContractViolation("version de snapshot no soportada")
    if data["contract_fingerprint"] != CONTRACT_V1_FINGERPRINT:
        raise ContractViolation("fingerprint de snapshot no soportado")
    _required_string(data["snapshot_id"], "snapshot_id")
    subject = _required_string(data["subject"], "subject")
    _required_int(data["generated_at"], "generated_at")
    topics = _required_dict(data["topics"], "topics")
    cursors = _required_dict(data["cursors"], "cursors")
    if set(topics) != set(cursors):
        raise ContractViolation("topics y cursors no coinciden")
    for topic, envelope in topics.items():
        validated = validate_envelope(envelope)
        if validated["topic"] != topic:
            raise ContractViolation("topic no coincide con su clave")
        if validated["subject"] != subject:
            raise ContractViolation("subject de topic no coincide con snapshot")
        if validated["kind"] != "snapshot":
            raise ContractViolation("snapshot inicial solo acepta kind=snapshot")
        cursor = _required_int(cursors[topic], f"cursor {topic}")
        if cursor != validated["seq"]:
            raise ContractViolation("cursor no coincide con seq")
    return data


def json_merge_patch(target: Any, patch: Any) -> Any:
    """Aplica RFC 7396 sin mutar target ni patch."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result = copy.deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = json_merge_patch(result.get(key), value)
    return result


def replay(snapshot: Mapping[str, Any], envelopes: Iterable[Mapping[str, Any]]) -> ReplayState:
    """Reconstruye estado y cursores; no conoce semántica de dominio."""
    validated = validate_snapshot(snapshot)
    subject = validated["subject"]
    topics = {
        topic: copy.deepcopy(envelope["payload"])
        for topic, envelope in validated["topics"].items()
    }
    cursors = dict(validated["cursors"])

    for candidate in envelopes:
        envelope = validate_envelope(candidate)
        if envelope["subject"] != subject:
            raise ContractViolation("evento de otro subject")
        topic = envelope["topic"]
        current = cursors.get(topic)
        if current is None:
            if envelope["kind"] != "snapshot":
                raise ContractViolation("topic nuevo exige snapshot")
        else:
            if envelope["seq"] <= current:
                continue
            if envelope["seq"] != current + 1:
                raise ContractViolation("hueco de secuencia")

        if envelope["kind"] == "snapshot":
            topics[topic] = copy.deepcopy(envelope["payload"])
        elif envelope["kind"] == "patch":
            if topic not in topics:
                raise ContractViolation("patch sin snapshot base")
            patched = json_merge_patch(topics[topic], envelope["payload"])
            projection = validate_projection_payload(patched)
            _validate_projection_consistency(envelope, projection)
            topics[topic] = projection
        # kind=event es efimero: avanza el cursor, pero no altera el read model.
        cursors[topic] = envelope["seq"]

    return ReplayState(subject=subject, topics=topics, cursors=cursors)


assert_contract_frozen()
