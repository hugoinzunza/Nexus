import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from modules.confluence import (
    CE1_SCHEMA,
    CE1ContractViolation,
    build_descriptive_synthesis,
    validate_dependency,
    validate_observation,
    validate_synthesis,
)
from modules.confluence.contracts import INDEPENDENCE_DEFINITION

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "confluence" / "ce1_cases.json"
)
FIXTURE_SHA256 = "6d74904ab689038d383ef75496c6f56922178099db8751c00f6841e08bdad924"
GOLDEN_SHA256 = "7413cb3962787f13d17bc4eb5eef5d8c306742926822d5ea748d664df06bdfda"


@pytest.fixture
def fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _observations(fixture):
    return {item["observation_id"]: item for item in fixture["observations"]}


def _synthesis(fixture):
    return build_descriptive_synthesis(
        fixture["observations"],
        dependencies=fixture["dependencies"],
        semantic_relations=fixture["semantic_relations"],
        expected_families=fixture["expected_families"],
        comparison_rule=fixture["comparison_rule"],
    )


def _dependency(result, left, right):
    pair = {left, right}
    return next(
        item
        for item in result["dependencies"]
        if {
            item["subject_observation_id"],
            item["related_observation_id"],
        }
        == pair
    )


def _states(result):
    return {
        item["observation"]["observation_id"]: item
        for item in result["observations"]
    }


def _validation_parity(observation):
    try:
        validate_observation(observation)
        runtime_valid = True
    except CE1ContractViolation:
        runtime_valid = False
    schema_valid = not list(
        Draft202012Validator(CE1_SCHEMA).iter_errors(observation)
    )
    return runtime_valid, schema_valid


def test_schema_candidato_es_valido_y_fixture_es_sintetico(fixture):
    Draft202012Validator.check_schema(CE1_SCHEMA)
    validator = Draft202012Validator(CE1_SCHEMA)
    for observation in fixture["observations"]:
        validator.validate(observation)
        assert observation["provenance"]["environment"] == "synthetic_fixture"
    for dependency in fixture["dependencies"]:
        validator.validate(dependency)
    for relation in fixture["semantic_relations"]:
        validator.validate(relation)
    validator.validate(fixture["comparison_rule"])


def test_observacion_serializa_y_deserializa_sin_perder_semantica(fixture):
    observation = fixture["observations"][0]
    restored = json.loads(
        json.dumps(observation, sort_keys=True, separators=(",", ":"))
    )
    assert validate_observation(restored) == observation
    assert restored["family"] == "price_structure"
    assert restored["lineage"]["raw_input_ids"] == ["raw.price.candles-a"]
    assert restored["time"]["available_at_ms"] == 1786000005000


def test_contrato_rechaza_campo_obligatorio_ausente(fixture):
    observation = copy.deepcopy(fixture["observations"][0])
    del observation["lineage"]
    with pytest.raises(CE1ContractViolation, match="faltan lineage"):
        validate_observation(observation)


def test_contrato_rechaza_familia_temporal_y_provenance_real(fixture):
    temporal_family = copy.deepcopy(fixture["observations"][0])
    temporal_family["family"] = "temporal_context"
    with pytest.raises(CE1ContractViolation, match="family invalida"):
        validate_observation(temporal_family)

    real_source = copy.deepcopy(fixture["observations"][0])
    real_source["provenance"]["environment"] = "production"
    with pytest.raises(CE1ContractViolation, match="synthetic_fixture"):
        validate_observation(real_source)


def test_available_at_es_distinto_y_respeta_orden_causal(fixture):
    observation = copy.deepcopy(fixture["observations"][0])
    assert (
        observation["time"]["effective_at_ms"]
        < observation["time"]["available_at_ms"]
    )
    assert (
        observation["time"]["available_at_ms"]
        < observation["time"]["observed_at_ms"]
    )

    observation["time"]["available_at_ms"] = observation["time"]["observed_at_ms"] + 1
    with pytest.raises(CE1ContractViolation, match="orden causal"):
        validate_observation(observation)


def test_parent_child_se_representa_como_derived(fixture):
    result = _synthesis(fixture)
    relation = _dependency(result, "obs.price.swing", "obs.price.pivot")
    assert relation["relation"] == "derived"
    assert relation["basis"] == "parent_child"
    assert relation["subject_observation_id"] == "obs.price.pivot"


def test_mismo_raw_input_no_se_convierte_en_independencia(fixture):
    result = _synthesis(fixture)
    relation = _dependency(result, "obs.price.swing", "obs.price.momentum")
    assert relation["relation"] == "shared_source"
    assert relation["basis"] == "shared_raw_input"

    invalid = {
        "contract": "nexux.confluence.ce1",
        "schema_version": "1.0.0-candidate",
        "document_type": "dependency_relation",
        "dependency_id": "dep.invalid.independent",
        "subject_observation_id": "obs.price.swing",
        "related_observation_id": "obs.price.momentum",
        "relation": "independent",
        "basis": "represented_lineage_only",
        "definition": INDEPENDENCE_DEFINITION,
        "rationale": "Declaracion deliberadamente invalida para el test.",
    }
    with pytest.raises(CE1ContractViolation, match="dependencia estructural"):
        validate_dependency(invalid, _observations(fixture))


def test_shared_source_del_book_permanece_explicito(fixture):
    result = _synthesis(fixture)
    relation = _dependency(result, "obs.book.wall", "obs.book.imbalance")
    assert relation["relation"] == "shared_source"
    assert relation["definition"] is None


def test_dependencia_parcial_no_se_reduce_a_booleano(fixture):
    result = _synthesis(fixture)
    relation = _dependency(
        result,
        "obs.derivatives.oi-delayed",
        "obs.flow.selling",
    )
    assert relation["relation"] == "partially_dependent"
    assert relation["basis"] == "known_common_driver"


def test_ausencia_de_relacion_conocida_permanece_unknown(fixture):
    result = _synthesis(fixture)
    relation = _dependency(result, "obs.price.swing", "obs.derivatives.oi-delayed")
    assert relation["relation"] == "unknown"
    assert relation["basis"] == "unassessed"
    assert relation["definition"] is None


def test_independent_usa_solo_la_definicion_reconciliada(fixture):
    result = _synthesis(fixture)
    relation = _dependency(result, "obs.cross.vix-stale", "obs.book.wall")
    assert relation["relation"] == "independent"
    assert relation["definition"] == INDEPENDENCE_DEFINITION

    changed = copy.deepcopy(fixture["dependencies"][1])
    changed["definition"] = "statistically_independent"
    with pytest.raises(CE1ContractViolation, match="definicion no autorizada"):
        validate_dependency(changed, _observations(fixture))


def test_availability_futura_impide_coocurrencia(fixture):
    result = _synthesis(fixture)
    state = _states(result)["obs.derivatives.oi-delayed"]
    assert state["temporal_state"] == "unavailable"
    assert state["reason"] == "not_yet_available"
    assert state["observation"]["family"] == "derivatives_positioning"
    assert "semantic.oi-flow-cooccurring" not in {
        item["relation_id"] for item in result["semantic_relations"]
    }
    assert any(
        item["subject_id"] == "semantic.oi-flow-cooccurring"
        and item["reason"] == "observations_not_comparable"
        for item in result["abstentions"]
    )


def test_stale_es_descriptivo_y_no_se_convierte_en_current(fixture):
    result = _synthesis(fixture)
    state = _states(result)["obs.cross.vix-stale"]
    assert state["temporal_state"] == "stale"
    assert state["reason"] == "stale"


def test_availability_desconocida_produce_abstencion(fixture):
    result = _synthesis(fixture)
    state = _states(result)["obs.liquidity.visual-unknown"]
    assert state["temporal_state"] == "unknown"
    assert state["reason"] == "availability_unknown"
    assert any(
        item["subject_id"] == "semantic.visual-book-cooccurring"
        for item in result["abstentions"]
    )
    dependency = _dependency(
        result,
        "obs.liquidity.visual-unknown",
        "obs.book.wall",
    )
    assert dependency["relation"] == "unknown"


def test_alignment_y_contradiccion_son_relaciones_descriptivas(fixture):
    result = _synthesis(fixture)
    states = {
        item["relation_id"]: item["state"]
        for item in result["semantic_relations"]
    }
    assert states == {
        "semantic.price-aligned": "aligned",
        "semantic.price-flow-contradictory": "contradictory",
    }
    assert all("weight" not in item for item in result["semantic_relations"])


def test_missing_permanece_missing_y_no_neutral(fixture):
    result = _synthesis(fixture)
    assert result["missing_evidence"] == [
        {"family": "macro_context", "state": "missing"}
    ]
    assert any(
        item["scope"] == "family"
        and item["subject_id"] == "macro_context"
        and item["reason"] == "missing"
        for item in result["abstentions"]
    )


def test_comparabilidad_exige_regla_explicita(fixture):
    changed = copy.deepcopy(fixture)
    changed["comparison_rule"]["window_end_ms"] = (
        changed["comparison_rule"]["reference_at_ms"] + 1
    )
    with pytest.raises(CE1ContractViolation, match="ventana temporal invalida"):
        _synthesis(changed)


def test_resultado_es_determinista_y_valido_bajo_schema(fixture):
    first = _synthesis(copy.deepcopy(fixture))
    second = _synthesis(copy.deepcopy(fixture))
    assert first == second
    Draft202012Validator(CE1_SCHEMA).validate(first)
    assert first["status"] == "observed"
    pivot = _states(first)["obs.price.pivot"]["observation"]
    assert pivot["provenance"]["source_ref"] == "fixture.price.raw-a"
    assert pivot["lineage"]["parent_observation_ids"] == ["obs.price.swing"]


def test_fixture_y_golden_output_preservan_digests(fixture):
    fixture_digest = hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    golden = json.dumps(_synthesis(fixture), sort_keys=True).encode("utf-8")
    golden_digest = hashlib.sha256(golden).hexdigest()

    assert fixture_digest == FIXTURE_SHA256
    assert golden_digest == GOLDEN_SHA256


def test_resultado_no_comparte_estado_mutable_con_el_fixture(fixture):
    original = copy.deepcopy(fixture)
    result = _synthesis(fixture)
    fixture["observations"][0]["value"]["price"] = 1.0
    fixture["semantic_relations"][0]["observation_ids"].reverse()

    assert fixture != original
    swing = _states(result)["obs.price.swing"]["observation"]
    assert swing["value"]["price"] == 64000.0
    relation = next(
        item
        for item in result["semantic_relations"]
        if item["relation_id"] == "semantic.price-aligned"
    )
    assert relation["observation_ids"] == sorted(relation["observation_ids"])


def test_sintesis_completa_se_abstiene_si_nada_estaba_disponible(fixture):
    changed = copy.deepcopy(fixture)
    changed["comparison_rule"].update(
        reference_at_ms=1785999000000,
        window_start_ms=1785998990000,
        window_end_ms=1785999000000,
    )
    result = _synthesis(changed)
    assert result["status"] == "abstained"
    assert not result["semantic_relations"]
    assert all(
        item["temporal_state"] != "observed"
        for item in result["observations"]
    )


def test_sintesis_no_expone_semantica_predictiva(fixture):
    encoded = json.dumps(_synthesis(fixture), sort_keys=True).lower()
    forbidden = (
        "score",
        "probability",
        "confidence",
        "prediction",
        "expected_return",
        "signal_strength",
        "confirmation",
        "supportive",
        "adverse",
        "position_size",
        "risk_multiplier",
    )
    assert all(term not in encoded for term in forbidden)


def test_documento_completo_revalida_dependency_con_mapa_real(fixture):
    result = _synthesis(fixture)
    dependency = _dependency(
        result,
        "obs.price.swing",
        "obs.price.momentum",
    )
    dependency.update(
        relation="independent",
        basis="represented_lineage_only",
        definition=INDEPENDENCE_DEFINITION,
    )

    with pytest.raises(CE1ContractViolation, match="dependencia estructural"):
        validate_synthesis(result)


@pytest.mark.parametrize(
    "reference_field",
    ("subject_observation_id", "related_observation_id"),
    ids=("source-fantasma", "target-fantasma"),
)
def test_documento_completo_rechaza_extremo_fantasma(
    fixture, reference_field
):
    result = _synthesis(fixture)
    result["dependencies"][0][reference_field] = "obs.ghost"

    with pytest.raises(CE1ContractViolation, match="observacion desconocida"):
        validate_synthesis(result)


def test_documento_completo_rechaza_observation_id_fantasma(fixture):
    result = _synthesis(fixture)
    result["semantic_relations"][0]["observation_ids"][0] = "obs.ghost"

    with pytest.raises(CE1ContractViolation, match="observacion desconocida"):
        validate_synthesis(result)


def test_documento_rechaza_relaciones_incompatibles_para_mismo_par(fixture):
    result = _synthesis(fixture)
    existing = _dependency(result, "obs.cross.vix-stale", "obs.book.wall")
    conflict = copy.deepcopy(existing)
    conflict.update(
        dependency_id="dep.conflict.same-pair",
        relation="unknown",
        basis="unassessed",
        definition=None,
        rationale="Segunda relacion deliberadamente incompatible.",
    )
    result["dependencies"].append(conflict)

    with pytest.raises(CE1ContractViolation, match="mismo par"):
        validate_synthesis(result)


@pytest.mark.parametrize(
    "value",
    (
        {"score": 0.8},
        {"nested": {"probability": 0.7}},
        {"items": [{"signal": "up"}]},
        {"metrics": {"expected_return": 1.2}},
        {"edge": True},
        {"label": "buy"},
    ),
    ids=(
        "score",
        "probability-nested",
        "signal-in-array",
        "expected-return",
        "edge",
        "action-label",
    ),
)
def test_value_rechaza_semantica_predictiva_en_cualquier_nivel(fixture, value):
    observation = copy.deepcopy(fixture["observations"][0])
    observation["value"] = value

    with pytest.raises(CE1ContractViolation, match="no permitid"):
        validate_observation(observation)
    assert list(Draft202012Validator(CE1_SCHEMA).iter_errors(observation))


def test_unknown_y_partial_siguen_validos_en_documento_completo(fixture):
    result = _synthesis(fixture)
    assert validate_synthesis(result) is result
    assert (
        _dependency(
            result,
            "obs.price.swing",
            "obs.derivatives.oi-delayed",
        )["relation"]
        == "unknown"
    )
    assert (
        _dependency(
            result,
            "obs.derivatives.oi-delayed",
            "obs.flow.selling",
        )["relation"]
        == "partially_dependent"
    )


@pytest.mark.parametrize(
    "value",
    (
        {"scores": [0.1]},
        {"probabilities": [0.1]},
        {"edges": [0.1]},
        {"signals": ["up"]},
        {"weights": [0.1]},
        {"winrates": [0.5]},
        {"predictions": ["up"]},
        {"qualities": [0.5]},
        {"p_win": 0.5},
        {"expected_return": 0.5},
    ),
    ids=(
        "scores",
        "probabilities",
        "edges",
        "signals",
        "weights",
        "winrates",
        "predictions",
        "qualities",
        "p-win",
        "expected-return",
    ),
)
def test_vocabulario_predictivo_plural_y_compuesto_tiene_paridad(
    fixture, value
):
    observation = copy.deepcopy(fixture["observations"][0])
    observation["value"] = value

    assert _validation_parity(observation) == (False, False)


@pytest.mark.parametrize(
    "label",
    (
        "bullish",
        "bearish",
        "long",
        "short",
        "Bullish",
        "BULLISH",
        "Bearish",
        "BEARISH",
        "Long",
        "SHORT",
    ),
)
def test_direccion_predictiva_y_casing_tienen_paridad(fixture, label):
    observation = copy.deepcopy(fixture["observations"][0])
    observation["value"] = {"direction": label}

    assert _validation_parity(observation) == (False, False)


@pytest.mark.parametrize(
    "temporal_context",
    (
        {"scores": [0.1]},
        {"nested": {"probabilities": [0.2]}},
        {"direction": "bearish"},
        {"direction": "Bullish"},
        {"family": "price_structure"},
    ),
    ids=(
        "scores",
        "nested-probabilities",
        "bearish",
        "bullish-case",
        "evidence-family",
    ),
)
def test_temporal_context_aplica_paridad_semantica(
    fixture, temporal_context
):
    observation = copy.deepcopy(fixture["observations"][0])
    observation["temporal_context"] = temporal_context

    assert _validation_parity(observation) == (False, False)


def test_valores_descriptivos_existentes_siguen_autorizados(fixture):
    for observation in fixture["observations"]:
        assert _validation_parity(observation) == (True, True)

    changed = copy.deepcopy(fixture["observations"][0])
    changed["value"] = {"direction": "down", "side": "ask"}
    changed["temporal_context"] = {"session": "synthetic-session"}
    assert _validation_parity(changed) == (True, True)
