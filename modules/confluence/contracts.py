"""Contrato candidato de representacion descriptiva para CE-1.

Este modulo no es una fuente de mercado ni un modulo productivo de NexUX. Solo
valida documentos deterministas usados por fixtures congelados del Gate CE-1.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

CE1_CONTRACT = "nexux.confluence.ce1"
CE1_SCHEMA_VERSION = "1.0.0-candidate"
INDEPENDENCE_DEFINITION = (
    "no_known_structural_dependency_within_represented_lineage"
)

_SCHEMA_PATH = Path(__file__).with_name("schemas") / "ce1-v1-candidate.json"
with _SCHEMA_PATH.open(encoding="utf-8") as _fh:
    CE1_SCHEMA = json.load(_fh)

EVIDENCE_FAMILIES = frozenset(
    {
        "price_structure",
        "derivatives_positioning",
        "liquidity_microstructure",
        "volume_flow",
        "macro_context",
        "cross_market_context",
    }
)
MEASUREMENT_TYPES = frozenset({"direct", "proxy", "derived"})
LINEAGE_STATUSES = frozenset({"known", "partial", "unknown"})
DEPENDENCY_RELATIONS = frozenset(
    {
        "derived",
        "shared_source",
        "partially_dependent",
        "independent",
        "unknown",
    }
)
DEPENDENCY_BASES = {
    "derived": frozenset({"parent_child"}),
    "shared_source": frozenset(
        {"shared_raw_input", "shared_lineage_group", "shared_provider"}
    ),
    "partially_dependent": frozenset(
        {"overlapping_inputs", "overlapping_lookback", "known_common_driver"}
    ),
    "independent": frozenset({"represented_lineage_only"}),
    "unknown": frozenset({"insufficient_lineage", "unassessed"}),
}
SEMANTIC_RELATIONS = frozenset(
    {"aligned", "co-occurring", "divergent", "contradictory"}
)
COMPARISON_MODES = frozenset(
    {"effective_time_within_window", "validity_overlap"}
)
TEMPORAL_STATES = frozenset({"observed", "unavailable", "stale", "unknown"})
SYNTHESIS_STATUSES = frozenset({"observed", "abstained"})

_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")
_VERSION_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)(?:-candidate)?$"
)


class CE1ContractViolation(ValueError):
    """Un documento contradice el contrato candidato reconciliado de CE-1."""


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CE1ContractViolation(f"{name} debe ser objeto")
    return value


def _exact_fields(
    value: Mapping[str, Any],
    required: Iterable[str],
    name: str,
) -> None:
    expected = set(required)
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        raise CE1ContractViolation(f"{name} incompleto: faltan {', '.join(missing)}")
    if extra:
        raise CE1ContractViolation(
            f"{name} contiene campos no permitidos: {', '.join(extra)}"
        )


def _string(value: Any, name: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value:
        raise CE1ContractViolation(f"{name} debe ser string no vacio")
    if len(value.encode("utf-8")) > maximum:
        raise CE1ContractViolation(f"{name} excede el limite")
    return value


def _identifier(value: Any, name: str) -> str:
    text = _string(value, name, maximum=128)
    if not _ID_RE.fullmatch(text):
        raise CE1ContractViolation(f"{name} no usa la forma canonica")
    return text


def _timestamp(value: Any, name: str, *, nullable: bool = False) -> int | None:
    if nullable and value is None:
        return None
    if type(value) is not int or value < 0:
        raise CE1ContractViolation(f"{name} debe ser unix milliseconds")
    return value


def _string_list(value: Any, name: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list):
        raise CE1ContractViolation(f"{name} debe ser lista")
    if not allow_empty and not value:
        raise CE1ContractViolation(f"{name} no puede estar vacio")
    result = [_identifier(item, f"{name}[]") for item in value]
    if len(result) != len(set(result)):
        raise CE1ContractViolation(f"{name} contiene duplicados")
    return result


def _json_value(value: Any, name: str, depth: int = 0) -> None:
    if depth > 8:
        raise CE1ContractViolation(f"{name} excede profundidad JSON")
    if isinstance(value, dict):
        for key, child in value.items():
            _identifier(key, f"{name}.key")
            _json_value(child, name, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _json_value(child, name, depth + 1)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise CE1ContractViolation(f"{name} contiene numero no finito")
    elif value is not None and type(value) not in (str, bool, int):
        raise CE1ContractViolation(f"{name} contiene tipo no JSON")


def _contract_header(document: Mapping[str, Any], document_type: str) -> None:
    if document.get("contract") != CE1_CONTRACT:
        raise CE1ContractViolation("contract no soportado")
    if document.get("schema_version") != CE1_SCHEMA_VERSION:
        raise CE1ContractViolation("schema_version no soportada")
    if document.get("document_type") != document_type:
        raise CE1ContractViolation(f"document_type debe ser {document_type}")


def _validate_subject(value: Any) -> None:
    subject = _object(value, "subject")
    _exact_fields(subject, ("symbol", "venue", "market"), "subject")
    for field in ("symbol", "venue", "market"):
        _identifier(subject[field], f"subject.{field}")


def _validate_provenance(value: Any) -> None:
    source = _object(value, "provenance")
    _exact_fields(
        source,
        ("provider", "origin", "method", "source_ref", "environment"),
        "provenance",
    )
    for field in ("provider", "origin", "method", "source_ref"):
        _identifier(source[field], f"provenance.{field}")
    if source["environment"] != "synthetic_fixture":
        raise CE1ContractViolation("CE-1 solo admite provenance synthetic_fixture")


def _validate_lineage(value: Any, observation_id: str) -> None:
    lineage = _object(value, "lineage")
    _exact_fields(
        lineage,
        (
            "status",
            "lineage_group_id",
            "raw_input_class",
            "raw_input_ids",
            "transformation_id",
            "transformation_version",
            "parent_observation_ids",
            "lookback_start_ms",
            "lookback_end_ms",
        ),
        "lineage",
    )
    status = lineage["status"]
    if status not in LINEAGE_STATUSES:
        raise CE1ContractViolation("lineage.status invalido")
    group = lineage["lineage_group_id"]
    raw_class = lineage["raw_input_class"]
    if group is not None:
        _identifier(group, "lineage.lineage_group_id")
    if raw_class is not None:
        _identifier(raw_class, "lineage.raw_input_class")
    raw_ids = _string_list(lineage["raw_input_ids"], "lineage.raw_input_ids")
    parents = _string_list(
        lineage["parent_observation_ids"],
        "lineage.parent_observation_ids",
    )
    if observation_id in parents:
        raise CE1ContractViolation("una observacion no puede derivar de si misma")
    _identifier(lineage["transformation_id"], "lineage.transformation_id")
    version = _string(
        lineage["transformation_version"], "lineage.transformation_version"
    )
    if not _VERSION_RE.fullmatch(version):
        raise CE1ContractViolation("transformation_version debe usar semver")
    start = _timestamp(
        lineage["lookback_start_ms"],
        "lineage.lookback_start_ms",
        nullable=True,
    )
    end = _timestamp(
        lineage["lookback_end_ms"],
        "lineage.lookback_end_ms",
        nullable=True,
    )
    if (start is None) != (end is None):
        raise CE1ContractViolation("lineage lookback debe estar completo o ausente")
    if start is not None and start > end:
        raise CE1ContractViolation("lineage lookback tiene orden invalido")
    if status == "known" and (group is None or raw_class is None or not raw_ids):
        raise CE1ContractViolation("lineage known exige grupo, clase e inputs")
    if status == "unknown" and (group is not None or raw_class is not None or raw_ids):
        raise CE1ContractViolation("lineage unknown no puede inventar origen")


def _validate_time(value: Any) -> None:
    timing = _object(value, "time")
    _exact_fields(
        timing,
        (
            "effective_at_ms",
            "source_timestamp_ms",
            "observed_at_ms",
            "available_at_ms",
            "computed_at_ms",
            "valid_from_ms",
            "stale_at_ms",
            "expires_at_ms",
            "causal_availability",
        ),
        "time",
    )
    effective = _timestamp(timing["effective_at_ms"], "time.effective_at_ms")
    source_time = _timestamp(
        timing["source_timestamp_ms"],
        "time.source_timestamp_ms",
        nullable=True,
    )
    observed = _timestamp(timing["observed_at_ms"], "time.observed_at_ms")
    available = _timestamp(
        timing["available_at_ms"],
        "time.available_at_ms",
        nullable=True,
    )
    computed = _timestamp(timing["computed_at_ms"], "time.computed_at_ms")
    valid_from = _timestamp(
        timing["valid_from_ms"], "time.valid_from_ms", nullable=True
    )
    stale = _timestamp(timing["stale_at_ms"], "time.stale_at_ms", nullable=True)
    expires = _timestamp(
        timing["expires_at_ms"], "time.expires_at_ms", nullable=True
    )
    availability = timing["causal_availability"]
    if availability not in {"known", "unknown"}:
        raise CE1ContractViolation("time.causal_availability invalido")
    if source_time is not None and source_time > observed:
        raise CE1ContractViolation("source_timestamp ocurre despues de observed_at")
    if observed > computed:
        raise CE1ContractViolation("computed_at ocurre antes de observed_at")
    if availability == "known":
        if None in (available, valid_from, stale, expires):
            raise CE1ContractViolation(
                "causal availability known exige relojes completos"
            )
        if not effective <= available <= observed <= computed:
            raise CE1ContractViolation("orden causal invalido")
        if not available <= valid_from <= stale <= expires:
            raise CE1ContractViolation("orden de validez invalido")
    elif any(item is not None for item in (available, valid_from, stale, expires)):
        raise CE1ContractViolation(
            "causal availability unknown exige relojes desconocidos"
        )


def validate_observation(value: Any) -> dict[str, Any]:
    observation = _object(value, "observation")
    _exact_fields(
        observation,
        (
            "contract",
            "schema_version",
            "document_type",
            "observation_id",
            "subject",
            "family",
            "subfamily",
            "phenomenon",
            "measurement_type",
            "value",
            "temporal_context",
            "time",
            "provenance",
            "lineage",
            "evidence_status",
        ),
        "observation",
    )
    _contract_header(observation, "market_observation")
    observation_id = _identifier(observation["observation_id"], "observation_id")
    _validate_subject(observation["subject"])
    if observation["family"] not in EVIDENCE_FAMILIES:
        raise CE1ContractViolation("family invalida")
    _identifier(observation["subfamily"], "subfamily")
    _identifier(observation["phenomenon"], "phenomenon")
    if observation["measurement_type"] not in MEASUREMENT_TYPES:
        raise CE1ContractViolation("measurement_type invalido")
    _json_value(_object(observation["value"], "value"), "value")
    temporal_context = _object(observation["temporal_context"], "temporal_context")
    _json_value(temporal_context, "temporal_context")
    if "family" in temporal_context:
        raise CE1ContractViolation("temporal_context no es evidence family")
    _validate_time(observation["time"])
    _validate_provenance(observation["provenance"])
    _validate_lineage(observation["lineage"], observation_id)
    if observation["evidence_status"] != "descriptive_unvalidated":
        raise CE1ContractViolation("evidence_status debe ser descriptive_unvalidated")
    return observation


def validate_dependency(
    value: Any,
    observations: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    dependency = _object(value, "dependency")
    _exact_fields(
        dependency,
        (
            "contract",
            "schema_version",
            "document_type",
            "dependency_id",
            "subject_observation_id",
            "related_observation_id",
            "relation",
            "basis",
            "definition",
            "rationale",
        ),
        "dependency",
    )
    _contract_header(dependency, "dependency_relation")
    _identifier(dependency["dependency_id"], "dependency_id")
    subject_id = _identifier(
        dependency["subject_observation_id"], "subject_observation_id"
    )
    related_id = _identifier(
        dependency["related_observation_id"], "related_observation_id"
    )
    if subject_id == related_id:
        raise CE1ContractViolation("dependency no puede referirse a si misma")
    relation = dependency["relation"]
    if relation not in DEPENDENCY_RELATIONS:
        raise CE1ContractViolation("dependency.relation invalida")
    if dependency["basis"] not in DEPENDENCY_BASES[relation]:
        raise CE1ContractViolation("dependency.basis contradice relation")
    definition = dependency["definition"]
    if relation == "independent":
        if definition != INDEPENDENCE_DEFINITION:
            raise CE1ContractViolation("independent usa una definicion no autorizada")
    elif definition is not None:
        raise CE1ContractViolation("definition solo aplica a independent")
    _string(dependency["rationale"], "dependency.rationale", maximum=512)

    if observations is None:
        return dependency
    try:
        subject = observations[subject_id]
        related = observations[related_id]
    except KeyError as exc:
        raise CE1ContractViolation(
            "dependency referencia observacion desconocida"
        ) from exc
    _validate_dependency_semantics(dependency, subject, related)
    return dependency


def _validate_dependency_semantics(
    dependency: Mapping[str, Any],
    subject: Mapping[str, Any],
    related: Mapping[str, Any],
) -> None:
    left = subject["lineage"]
    right = related["lineage"]
    left_inputs = set(left["raw_input_ids"])
    right_inputs = set(right["raw_input_ids"])
    shared_inputs = left_inputs & right_inputs
    same_group = (
        left["lineage_group_id"] is not None
        and left["lineage_group_id"] == right["lineage_group_id"]
    )
    parent_child = (
        related["observation_id"] in left["parent_observation_ids"]
        or subject["observation_id"] in right["parent_observation_ids"]
    )
    same_provenance_source = (
        subject["provenance"]["provider"]
        == related["provenance"]["provider"]
        and subject["provenance"]["origin"]
        == related["provenance"]["origin"]
    )
    overlapping_input_class = (
        left["raw_input_class"] is not None
        and left["raw_input_class"] == right["raw_input_class"]
        and _lineage_lookbacks_overlap(left, right)
    )
    relation = dependency["relation"]
    basis = dependency["basis"]
    if relation == "derived" and not parent_child:
        raise CE1ContractViolation("derived exige parent/child lineage")
    if relation == "shared_source":
        supported = {
            "shared_raw_input": bool(shared_inputs),
            "shared_lineage_group": same_group,
            "shared_provider": same_provenance_source,
        }
        if not supported[basis]:
            raise CE1ContractViolation(
                "shared_source basis no esta respaldado por lineage"
            )
    if relation == "partially_dependent":
        supported = {
            "overlapping_inputs": bool(shared_inputs)
            and left_inputs != right_inputs,
            "overlapping_lookback": overlapping_input_class,
            "known_common_driver": (
                left["status"] != "unknown" and right["status"] != "unknown"
            ),
        }
        if not supported[basis]:
            raise CE1ContractViolation(
                "partially_dependent basis no esta respaldado por lineage"
            )
    if relation == "independent":
        if left["status"] != "known" or right["status"] != "known":
            raise CE1ContractViolation("independent exige lineage conocido")
        if (
            shared_inputs
            or same_group
            or parent_child
            or same_provenance_source
            or overlapping_input_class
        ):
            raise CE1ContractViolation("independent contradice dependencia estructural")
    if relation == "unknown" and (
        shared_inputs
        or same_group
        or parent_child
        or same_provenance_source
        or overlapping_input_class
    ):
        raise CE1ContractViolation("unknown no puede ocultar dependencia conocida")


def _lineage_lookbacks_overlap(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> bool:
    values = (
        left["lookback_start_ms"],
        left["lookback_end_ms"],
        right["lookback_start_ms"],
        right["lookback_end_ms"],
    )
    if any(value is None for value in values):
        return False
    return max(values[0], values[2]) <= min(values[1], values[3])


def validate_comparison_rule(value: Any) -> dict[str, Any]:
    rule = _object(value, "comparison_rule")
    _exact_fields(
        rule,
        (
            "contract",
            "schema_version",
            "document_type",
            "rule_id",
            "rule_version",
            "reference_at_ms",
            "window_start_ms",
            "window_end_ms",
            "mode",
        ),
        "comparison_rule",
    )
    _contract_header(rule, "temporal_comparison_rule")
    _identifier(rule["rule_id"], "rule_id")
    version = _string(rule["rule_version"], "rule_version")
    if not _VERSION_RE.fullmatch(version):
        raise CE1ContractViolation("rule_version debe usar semver")
    reference = _timestamp(rule["reference_at_ms"], "reference_at_ms")
    start = _timestamp(rule["window_start_ms"], "window_start_ms")
    end = _timestamp(rule["window_end_ms"], "window_end_ms")
    if not start <= end <= reference:
        raise CE1ContractViolation("ventana temporal invalida")
    if rule["mode"] not in COMPARISON_MODES:
        raise CE1ContractViolation("comparison mode invalido")
    return rule


def validate_semantic_relation(value: Any) -> dict[str, Any]:
    relation = _object(value, "semantic_relation")
    _exact_fields(
        relation,
        (
            "contract",
            "schema_version",
            "document_type",
            "relation_id",
            "observation_ids",
            "state",
            "predicate_id",
            "predicate_version",
        ),
        "semantic_relation",
    )
    _contract_header(relation, "semantic_relation")
    _identifier(relation["relation_id"], "relation_id")
    ids = _string_list(
        relation["observation_ids"], "observation_ids", allow_empty=False
    )
    if len(ids) < 2:
        raise CE1ContractViolation("semantic relation exige al menos dos observaciones")
    if relation["state"] not in SEMANTIC_RELATIONS:
        raise CE1ContractViolation("semantic relation state invalido")
    _identifier(relation["predicate_id"], "predicate_id")
    version = _string(relation["predicate_version"], "predicate_version")
    if not _VERSION_RE.fullmatch(version):
        raise CE1ContractViolation("predicate_version debe usar semver")
    return relation


def validate_synthesis(value: Any) -> dict[str, Any]:
    synthesis = _object(value, "synthesis")
    _exact_fields(
        synthesis,
        (
            "contract",
            "schema_version",
            "document_type",
            "status",
            "comparison_rule",
            "observations",
            "dependencies",
            "semantic_relations",
            "missing_evidence",
            "abstentions",
        ),
        "synthesis",
    )
    _contract_header(synthesis, "descriptive_synthesis")
    if synthesis["status"] not in SYNTHESIS_STATUSES:
        raise CE1ContractViolation("synthesis status invalido")
    validate_comparison_rule(synthesis["comparison_rule"])
    for field in (
        "observations",
        "dependencies",
        "semantic_relations",
        "missing_evidence",
        "abstentions",
    ):
        if not isinstance(synthesis[field], list):
            raise CE1ContractViolation(f"synthesis.{field} debe ser lista")
    for item in synthesis["observations"]:
        entry = _object(item, "synthesis.observations[]")
        _exact_fields(
            entry,
            ("observation", "temporal_state", "reason"),
            "synthesis.observations[]",
        )
        validate_observation(entry["observation"])
        if entry["temporal_state"] not in TEMPORAL_STATES:
            raise CE1ContractViolation("temporal_state invalido")
        if entry["reason"] is not None:
            _identifier(entry["reason"], "reason")
    for dependency in synthesis["dependencies"]:
        validate_dependency(dependency)
    for relation in synthesis["semantic_relations"]:
        validate_semantic_relation(relation)
    for item in synthesis["missing_evidence"]:
        entry = _object(item, "synthesis.missing_evidence[]")
        _exact_fields(entry, ("family", "state"), "synthesis.missing_evidence[]")
        if entry["family"] not in EVIDENCE_FAMILIES or entry["state"] != "missing":
            raise CE1ContractViolation("missing_evidence invalida")
    for item in synthesis["abstentions"]:
        entry = _object(item, "synthesis.abstentions[]")
        _exact_fields(
            entry,
            ("scope", "subject_id", "reason", "observation_ids"),
            "synthesis.abstentions[]",
        )
        if entry["scope"] not in {"observation", "semantic_relation", "family"}:
            raise CE1ContractViolation("abstention scope invalido")
        _identifier(entry["subject_id"], "abstention.subject_id")
        _identifier(entry["reason"], "abstention.reason")
        _string_list(entry["observation_ids"], "abstention.observation_ids")
    return synthesis
