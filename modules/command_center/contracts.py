"""Validador y semántica del ABI v1 del NEXUX Command Center."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

CONTRACT_VERSION = 1
SNAPSHOT_CONTRACT = "nexux.command-center.snapshot"
EVENT_CONTRACT = "nexux.command-center.event"
ERROR_CONTRACT = "nexux.command-center.error"

_SCHEMA_PATH = Path(__file__).with_name("schemas") / "v1.json"
with _SCHEMA_PATH.open(encoding="utf-8") as _fh:
    CONTRACT_V1_SPEC = json.load(_fh)

_DEFS = CONTRACT_V1_SPEC["$defs"]
_META = CONTRACT_V1_SPEC["x-nexux"]
LIMITS = _META["limits"]
CLOCK_SKEW_MS = _META["time"]["allowed_future_clock_skew_ms"]

HEALTH_VALUES = frozenset(_DEFS["projectionState"]["properties"]["health"]["enum"])
FRESHNESS_VALUES = frozenset(
    _DEFS["projectionState"]["properties"]["freshness"]["enum"]
)
MODE_VALUES = frozenset(_DEFS["projectionState"]["properties"]["mode"]["enum"])
SEVERITY_VALUES = frozenset(
    _DEFS["projectionState"]["properties"]["severity"]["enum"]
)
AVAILABILITY_VALUES = frozenset(
    _DEFS["projectionState"]["properties"]["availability"]["enum"]
)
DEGRADATION_CATEGORIES = frozenset(
    _DEFS["degradation"]["oneOf"][1]["properties"]["category"]["enum"]
)
KIND_VALUES = frozenset(_DEFS["envelope"]["properties"]["kind"]["enum"])

_TOPIC_RE = re.compile(_DEFS["topic"]["pattern"])
_SOURCE_RE = re.compile(_DEFS["source"]["pattern"])
_SUBJECT_RE = re.compile(_DEFS["subject"]["pattern"])
_SEMANTIC_NAME_RE = re.compile(_DEFS["semanticName"]["pattern"])
_UUID_RE = re.compile(_DEFS["uuid"]["pattern"])
_MAX_INT = _DEFS["timestamp"]["maximum"]

# ABI v1 congelado el 2026-07-30. Todo cambio del Wire ABI exige una nueva version.
CONTRACT_V1_FINGERPRINT = (
    "b0a8a7efa623a1aae4b681c3cfc42790d36a6a14fbc689688026c523f2e49b46"
)


class ContractViolation(ValueError):
    """Un documento no cumple el ABI publicado."""


@dataclass(frozen=True)
class ReplayState:
    subject: str
    topics: dict[str, dict[str, Any]]
    cursors: dict[str, int]


def _fingerprint() -> str:
    canonical = json.dumps(
        CONTRACT_V1_SPEC, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def schema_fingerprint() -> str:
    """Calcula el fingerprint del schema normativo publicado."""
    return _fingerprint()


def assert_contract_frozen() -> None:
    actual = schema_fingerprint()
    if actual != CONTRACT_V1_FINGERPRINT:
        raise RuntimeError(
            "el schema del Wire ABI v1 congelado fue modificado; "
            "publique una nueva version contractual"
        )


def _required_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractViolation(f"{name} debe ser objeto")
    return value


def _required_string(value: Any, name: str, maximum: int | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise ContractViolation(f"{name} debe ser string no vacio")
    if maximum is not None and len(value.encode("utf-8")) > maximum:
        raise ContractViolation(f"{name} excede el limite")
    return value


def _required_int(
    value: Any, name: str, minimum: int = 0, maximum: int = _MAX_INT
) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise ContractViolation(
            f"{name} debe ser entero entre {minimum} y {maximum}"
        )
    return value


def _require_fields(value: Mapping[str, Any], fields: Iterable[str], name: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise ContractViolation(f"{name} incompleto: faltan {', '.join(missing)}")


def _compact_size(value: Any, name: str) -> int:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractViolation(f"{name} no es JSON valido") from exc
    return len(encoded)


def _validate_json_limits(value: Any, name: str, depth: int = 0) -> None:
    if depth > LIMITS["max_json_depth"]:
        raise ContractViolation(f"{name} excede profundidad JSON")
    if isinstance(value, dict):
        if len(value) > LIMITS["max_object_keys"]:
            raise ContractViolation(f"{name} excede claves por objeto")
        for key, child in value.items():
            if not isinstance(key, str):
                raise ContractViolation(f"{name} contiene clave no string")
            if len(key.encode("utf-8")) > LIMITS["max_string_bytes"]:
                raise ContractViolation(f"{name} contiene clave demasiado larga")
            _validate_json_limits(child, name, depth + 1)
    elif isinstance(value, list):
        if len(value) > LIMITS["max_array_items"]:
            raise ContractViolation(f"{name} excede items por lista")
        for child in value:
            _validate_json_limits(child, name, depth + 1)
    elif isinstance(value, str):
        if len(value.encode("utf-8")) > LIMITS["max_string_bytes"]:
            raise ContractViolation(f"{name} contiene string demasiado largo")
    elif value is not None and type(value) not in (bool, int, float):
        raise ContractViolation(f"{name} contiene tipo no JSON")


def _validate_pattern(
    value: Any, name: str, pattern: re.Pattern[str], maximum: int = 128
) -> str:
    text = _required_string(value, name, maximum)
    if not pattern.fullmatch(text):
        raise ContractViolation(f"{name} no usa la forma canonica")
    return text


def validate_topic_name(value: Any) -> str:
    return _validate_pattern(value, "topic", _TOPIC_RE)


def validate_source_name(value: Any) -> str:
    return _validate_pattern(value, "source", _SOURCE_RE)


def validate_subject_name(value: Any) -> str:
    return _validate_pattern(value, "subject", _SUBJECT_RE)


def _validate_degradation(value: Any, availability: str) -> None:
    if availability == "available":
        if value is not None:
            raise ContractViolation("estado available exige degradation=null")
        return
    degradation = _required_dict(value, "payload.state.degradation")
    _require_fields(
        degradation,
        ("category", "code", "retryable", "since"),
        "payload.state.degradation",
    )
    if degradation["category"] not in DEGRADATION_CATEGORIES:
        raise ContractViolation("categoria de degradacion invalida")
    _validate_pattern(
        degradation["code"],
        "payload.state.degradation.code",
        _SEMANTIC_NAME_RE,
    )
    if type(degradation["retryable"]) is not bool:
        raise ContractViolation("degradation.retryable debe ser boolean")
    _required_int(degradation["since"], "degradation.since")


def _validate_availability_consistency(health: str, availability: str) -> None:
    expected = {
        "healthy": {"available"},
        "degraded": {"degraded"},
        "failed": {"unavailable"},
        "unknown": {"degraded", "unavailable"},
    }
    if availability not in expected[health]:
        raise ContractViolation("health contradice availability")


def validate_projection_payload(payload: Any) -> dict[str, Any]:
    data = _required_dict(payload, "payload")
    _validate_json_limits(data, "projection payload")
    if _compact_size(data, "projection payload") > LIMITS["max_projection_bytes"]:
        raise ContractViolation("projection excede max_projection_bytes")
    _require_fields(data, ("state", "data"), "payload")
    state = _required_dict(data["state"], "payload.state")
    required = _DEFS["projectionState"]["required"]
    _require_fields(state, required, "payload.state")
    if state["health"] not in HEALTH_VALUES:
        raise ContractViolation("health invalido")
    if state["freshness"] not in FRESHNESS_VALUES:
        raise ContractViolation("freshness invalido")
    if state["mode"] not in MODE_VALUES:
        raise ContractViolation("mode invalido")
    if state["severity"] not in SEVERITY_VALUES:
        raise ContractViolation("severity invalida")
    if state["availability"] not in AVAILABILITY_VALUES:
        raise ContractViolation("availability invalida")
    validate_source_name(state["source"])
    _required_int(state["as_of"], "payload.state.as_of")
    _validate_availability_consistency(state["health"], state["availability"])
    _validate_degradation(state["degradation"], state["availability"])
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
    received = envelope["received_at"]
    if received >= envelope["expires_at"]:
        expected = {"expired"}
    elif received >= envelope["stale_at"]:
        expected = {"stale"}
    else:
        expected = {"live", "current"}
    if state["freshness"] not in expected:
        raise ContractViolation("freshness contradice stale_at/expires_at")


def validate_envelope(envelope: Any) -> dict[str, Any]:
    data = _required_dict(envelope, "envelope")
    _validate_json_limits(data, "envelope")
    if _compact_size(data, "envelope") > LIMITS["max_envelope_bytes"]:
        raise ContractViolation("envelope excede max_envelope_bytes")
    _require_fields(data, _DEFS["envelope"]["required"], "envelope")
    if data["contract"] != EVENT_CONTRACT or data["v"] != CONTRACT_VERSION:
        raise ContractViolation("contrato de envelope no soportado")
    validate_topic_name(data["topic"])
    _validate_pattern(data["subject"], "subject", _SUBJECT_RE)
    validate_source_name(data["source"])
    if data["kind"] not in KIND_VALUES:
        raise ContractViolation("kind invalido")
    _required_int(data["seq"], "seq")
    observed = _required_int(data["observed_at"], "observed_at")
    received = _required_int(data["received_at"], "received_at")
    stale = _required_int(data["stale_at"], "stale_at")
    expires = _required_int(data["expires_at"], "expires_at")
    if observed > received + CLOCK_SKEW_MS:
        raise ContractViolation("observed_at excede tolerancia de reloj")
    if not observed <= stale <= expires:
        raise ContractViolation("orden temporal invalido")
    if data["severity"] not in SEVERITY_VALUES:
        raise ContractViolation("severity invalida")
    payload = _required_dict(data["payload"], "payload")

    if data["kind"] == "event":
        _require_fields(data, ("event_type", "event_version"), "evento")
        _validate_pattern(data["event_type"], "event_type", _SEMANTIC_NAME_RE)
        _required_int(data["event_version"], "event_version", 1, 65535)
        if _compact_size(payload, "event payload") > LIMITS["max_event_payload_bytes"]:
            raise ContractViolation("evento excede max_event_payload_bytes")
    elif "event_type" in data or "event_version" in data:
        raise ContractViolation("event_type/event_version solo aplican a kind=event")

    if data["kind"] == "patch":
        if _compact_size(payload, "patch payload") > LIMITS["max_patch_payload_bytes"]:
            raise ContractViolation("patch excede max_patch_payload_bytes")
    elif data["kind"] == "snapshot":
        projection = validate_projection_payload(payload)
        _validate_projection_consistency(data, projection)
    return data


def validate_snapshot(snapshot: Any) -> dict[str, Any]:
    data = _required_dict(snapshot, "snapshot")
    _validate_json_limits(data, "snapshot")
    if _compact_size(data, "snapshot") > LIMITS["max_snapshot_bytes"]:
        raise ContractViolation("snapshot excede max_snapshot_bytes")
    _require_fields(data, _DEFS["snapshot"]["required"], "snapshot")
    if data["contract"] != SNAPSHOT_CONTRACT or data["v"] != CONTRACT_VERSION:
        raise ContractViolation("contrato de snapshot no soportado")
    if data["contract_fingerprint"] != CONTRACT_V1_FINGERPRINT:
        raise ContractViolation("fingerprint del contrato no coincide")
    _validate_pattern(data["snapshot_id"], "snapshot_id", _UUID_RE)
    subject = _validate_pattern(data["subject"], "subject", _SUBJECT_RE)
    generated = _required_int(data["generated_at"], "generated_at")
    topics = _required_dict(data["topics"], "topics")
    cursors = _required_dict(data["cursors"], "cursors")
    if len(topics) > LIMITS["max_topics"]:
        raise ContractViolation("snapshot excede max_topics")
    if set(topics) != set(cursors):
        raise ContractViolation("topics y cursors no coinciden")
    for topic, envelope in topics.items():
        _validate_pattern(topic, "clave de topic", _TOPIC_RE)
        validated = validate_envelope(envelope)
        if validated["topic"] != topic:
            raise ContractViolation("topic no coincide con su clave")
        if validated["subject"] != subject:
            raise ContractViolation("subject de topic no coincide con snapshot")
        if validated["kind"] != "snapshot":
            raise ContractViolation("snapshot inicial solo acepta kind=snapshot")
        if validated["received_at"] != generated:
            raise ContractViolation("received_at inicial no coincide con generated_at")
        cursor = _required_int(cursors[topic], f"cursor {topic}")
        if cursor != validated["seq"]:
            raise ContractViolation("cursor no coincide con seq")
    return data


def error_document(
    code: str,
    message: str,
    status: int,
    *,
    retryable: bool = False,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = {
        "contract": ERROR_CONTRACT,
        "v": CONTRACT_VERSION,
        "code": code,
        "message": message,
        "status": status,
        "retryable": retryable,
        "request_id": request_id or str(uuid.uuid4()),
    }
    if details:
        document["details"] = details
    return validate_error(document)


def validate_error(document: Any) -> dict[str, Any]:
    data = _required_dict(document, "error")
    _validate_json_limits(data, "error")
    if _compact_size(data, "error") > LIMITS["max_error_bytes"]:
        raise ContractViolation("error excede max_error_bytes")
    _require_fields(data, _DEFS["error"]["required"], "error")
    if data["contract"] != ERROR_CONTRACT or data["v"] != CONTRACT_VERSION:
        raise ContractViolation("contrato de error no soportado")
    _validate_pattern(data["code"], "error.code", _SEMANTIC_NAME_RE)
    _required_string(data["message"], "error.message", 240)
    _required_int(data["status"], "error.status", 400, 599)
    if type(data["retryable"]) is not bool:
        raise ContractViolation("error.retryable debe ser boolean")
    _validate_pattern(data["request_id"], "error.request_id", _UUID_RE)
    if "details" in data:
        _required_dict(data["details"], "error.details")
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


def replay(
    snapshot: Mapping[str, Any], envelopes: Iterable[Mapping[str, Any]]
) -> ReplayState:
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
        cursors[topic] = envelope["seq"]

    return ReplayState(subject=subject, topics=topics, cursors=cursors)


assert_contract_frozen()
