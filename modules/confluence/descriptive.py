"""Sintesis pura de representacion descriptiva para fixtures de CE-1."""

from __future__ import annotations

import copy
import hashlib
from itertools import combinations
from typing import Any, Iterable, Mapping

from .contracts import (
    CE1_CONTRACT,
    CE1_SCHEMA_VERSION,
    CE1ContractViolation,
    EVIDENCE_FAMILIES,
    INDEPENDENCE_DEFINITION,
    index_dependencies,
    index_observations,
    validate_comparison_rule,
    validate_dependency,
    validate_semantic_relation,
    validate_synthesis,
)


def build_descriptive_synthesis(
    observations: Iterable[dict[str, Any]],
    *,
    dependencies: Iterable[dict[str, Any]],
    semantic_relations: Iterable[dict[str, Any]],
    expected_families: Iterable[str],
    comparison_rule: dict[str, Any],
) -> dict[str, Any]:
    """Normaliza relaciones sin producir fuerza, ranking ni inferencia futura."""
    rule = copy.deepcopy(validate_comparison_rule(comparison_rule))
    indexed = index_observations(copy.deepcopy(tuple(observations)))

    declared = _index_dependencies(dependencies, indexed)
    resolved = _resolve_all_dependencies(indexed, declared)
    temporal = {
        observation_id: _temporal_state(observation, rule)
        for observation_id, observation in indexed.items()
    }

    accepted_relations = []
    abstentions = []
    semantic_identifiers = set()
    for raw_relation in semantic_relations:
        relation = copy.deepcopy(validate_semantic_relation(raw_relation))
        relation_id = relation["relation_id"]
        if relation_id in semantic_identifiers:
            raise CE1ContractViolation("semantic relation_id duplicado")
        semantic_identifiers.add(relation_id)
        relation["observation_ids"] = sorted(relation["observation_ids"])
        unknown_ids = sorted(set(relation["observation_ids"]) - set(indexed))
        if unknown_ids:
            raise CE1ContractViolation(
                "semantic relation referencia observacion desconocida"
            )
        unavailable = [
            observation_id
            for observation_id in relation["observation_ids"]
            if temporal[observation_id]["temporal_state"] != "observed"
        ]
        if unavailable:
            abstentions.append(
                {
                    "scope": "semantic_relation",
                    "subject_id": relation_id,
                    "reason": "observations_not_comparable",
                    "observation_ids": sorted(unavailable),
                }
            )
            continue
        accepted_relations.append(relation)

    expected = tuple(sorted(set(expected_families)))
    invalid_families = [
        family for family in expected if family not in EVIDENCE_FAMILIES
    ]
    if invalid_families:
        raise CE1ContractViolation("expected_families contiene familia invalida")
    represented_families = {item["family"] for item in indexed.values()}
    missing = [
        {"family": family, "state": "missing"}
        for family in expected
        if family not in represented_families
    ]

    observation_states = [temporal[key] for key in sorted(temporal)]
    for item in observation_states:
        if item["temporal_state"] != "observed":
            observation_id = item["observation"]["observation_id"]
            abstentions.append(
                {
                    "scope": "observation",
                    "subject_id": observation_id,
                    "reason": item["reason"],
                    "observation_ids": [observation_id],
                }
            )
    for item in missing:
        abstentions.append(
            {
                "scope": "family",
                "subject_id": item["family"],
                "reason": "missing",
                "observation_ids": [],
            }
        )

    result = {
        "contract": CE1_CONTRACT,
        "schema_version": CE1_SCHEMA_VERSION,
        "document_type": "descriptive_synthesis",
        "status": (
            "observed"
            if any(item["temporal_state"] == "observed" for item in observation_states)
            else "abstained"
        ),
        "comparison_rule": dict(rule),
        "observations": observation_states,
        "dependencies": resolved,
        "semantic_relations": sorted(
            accepted_relations, key=lambda item: item["relation_id"]
        ),
        "missing_evidence": missing,
        "abstentions": sorted(
            abstentions,
            key=lambda item: (item["scope"], item["subject_id"], item["reason"]),
        ),
    }
    return validate_synthesis(result)


def _index_dependencies(
    dependencies: Iterable[dict[str, Any]],
    observations: Mapping[str, Mapping[str, Any]],
) -> dict[frozenset[str], dict[str, Any]]:
    return index_dependencies(copy.deepcopy(tuple(dependencies)), observations)


def _resolve_all_dependencies(
    observations: Mapping[str, Mapping[str, Any]],
    declared: Mapping[frozenset[str], dict[str, Any]],
) -> list[dict[str, Any]]:
    resolved = []
    for left_id, right_id in combinations(sorted(observations), 2):
        pair = frozenset({left_id, right_id})
        if pair in declared:
            resolved.append(declared[pair])
            continue
        left = observations[left_id]
        right = observations[right_id]
        relation, basis, subject_id, related_id, rationale = _known_relation(
            left, right
        )
        dependency = {
            "contract": CE1_CONTRACT,
            "schema_version": CE1_SCHEMA_VERSION,
            "document_type": "dependency_relation",
            "dependency_id": _auto_dependency_id(left_id, right_id),
            "subject_observation_id": subject_id,
            "related_observation_id": related_id,
            "relation": relation,
            "basis": basis,
            "definition": (
                INDEPENDENCE_DEFINITION if relation == "independent" else None
            ),
            "rationale": rationale,
        }
        resolved.append(validate_dependency(dependency, observations))
    return sorted(resolved, key=lambda item: item["dependency_id"])


def _auto_dependency_id(left_id: str, right_id: str) -> str:
    payload = f"{left_id}\x00{right_id}".encode("utf-8")
    return f"dep.auto.{hashlib.sha256(payload).hexdigest()[:20]}"


def _known_relation(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> tuple[str, str, str, str, str]:
    left_lineage = left["lineage"]
    right_lineage = right["lineage"]
    if right["observation_id"] in left_lineage["parent_observation_ids"]:
        return (
            "derived",
            "parent_child",
            left["observation_id"],
            right["observation_id"],
            "El lineage fixture declara parent/child.",
        )
    if left["observation_id"] in right_lineage["parent_observation_ids"]:
        return (
            "derived",
            "parent_child",
            right["observation_id"],
            left["observation_id"],
            "El lineage fixture declara parent/child.",
        )
    left_inputs = set(left_lineage["raw_input_ids"])
    right_inputs = set(right_lineage["raw_input_ids"])
    if left_inputs & right_inputs:
        return (
            "shared_source",
            "shared_raw_input",
            left["observation_id"],
            right["observation_id"],
            "Las observaciones comparten raw input representado.",
        )
    if (
        left_lineage["lineage_group_id"] is not None
        and left_lineage["lineage_group_id"]
        == right_lineage["lineage_group_id"]
    ):
        return (
            "shared_source",
            "shared_lineage_group",
            left["observation_id"],
            right["observation_id"],
            "Las observaciones comparten lineage group representado.",
        )
    if (
        left["provenance"]["provider"] == right["provenance"]["provider"]
        and left["provenance"]["origin"] == right["provenance"]["origin"]
    ):
        return (
            "shared_source",
            "shared_provider",
            left["observation_id"],
            right["observation_id"],
            "Las observaciones comparten provider y origin representados.",
        )
    if _lookbacks_overlap(left_lineage, right_lineage) and (
        left_lineage["raw_input_class"] is not None
        and left_lineage["raw_input_class"] == right_lineage["raw_input_class"]
    ):
        return (
            "partially_dependent",
            "overlapping_lookback",
            left["observation_id"],
            right["observation_id"],
            "Las ventanas se solapan dentro de la misma clase de raw input.",
        )
    return (
        "unknown",
        "unassessed",
        left["observation_id"],
        right["observation_id"],
        "El lineage representado no permite clasificar la dependencia.",
    )


def _lookbacks_overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    values = (
        left["lookback_start_ms"],
        left["lookback_end_ms"],
        right["lookback_start_ms"],
        right["lookback_end_ms"],
    )
    if any(value is None for value in values):
        return False
    return max(values[0], values[2]) <= min(values[1], values[3])


def _temporal_state(
    observation: Mapping[str, Any],
    rule: Mapping[str, Any],
) -> dict[str, Any]:
    timing = observation["time"]
    result = {
        "observation": copy.deepcopy(observation),
        "temporal_state": "observed",
        "reason": None,
    }
    if timing["causal_availability"] == "unknown":
        result.update(temporal_state="unknown", reason="availability_unknown")
        return result
    reference = rule["reference_at_ms"]
    if timing["available_at_ms"] > reference or timing["observed_at_ms"] > reference:
        result.update(temporal_state="unavailable", reason="not_yet_available")
        return result
    if timing["computed_at_ms"] > reference:
        result.update(temporal_state="unavailable", reason="not_yet_computed")
        return result
    if reference >= timing["expires_at_ms"]:
        result.update(temporal_state="unavailable", reason="expired")
        return result
    if reference >= timing["stale_at_ms"]:
        result.update(temporal_state="stale", reason="stale")
        return result
    if reference < timing["valid_from_ms"]:
        result.update(temporal_state="unavailable", reason="not_yet_valid")
        return result
    if rule["mode"] == "effective_time_within_window":
        comparable = (
            rule["window_start_ms"]
            <= timing["effective_at_ms"]
            <= rule["window_end_ms"]
        )
    else:
        comparable = (
            max(rule["window_start_ms"], timing["valid_from_ms"])
            <= min(rule["window_end_ms"], timing["expires_at_ms"])
        )
    if not comparable:
        result.update(
            temporal_state="unavailable",
            reason="not_temporally_comparable",
        )
    return result
