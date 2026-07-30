import copy
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from core.hub import ROOT
from core.module_base import ModuleContext
from core.module_loader import load_modules
from modules.command_center.contracts import (
    CONTRACT_V1_FINGERPRINT,
    CONTRACT_V1_SPEC,
    ContractViolation,
    assert_contract_candidate,
    candidate_fingerprint,
    error_document,
    replay,
    validate_envelope,
    validate_error,
    validate_snapshot,
)
from modules.command_center.module import CommandCenterModule
from modules.command_center.snapshot import (
    ActorContext,
    ConfiguredModulesProjection,
    Projection,
    SessionProjection,
    SnapshotComposer,
)

NOW = 1_785_430_000_000
SNAPSHOT_ID = "00000000-0000-4000-8000-000000000001"


def _config():
    return {
        "modules": {
            "trading": {"enabled": True},
            "bot": {"enabled": True},
            "command_center": {"enabled": True},
        }
    }


def _composer(*providers, on_error=None):
    return SnapshotComposer(
        providers or [SessionProjection(), ConfiguredModulesProjection(_config)],
        clock_ms=lambda: NOW,
        id_factory=lambda: SNAPSHOT_ID,
        on_provider_error=on_error,
    )


def _user(uid=7, role="beta"):
    return {"uid": uid, "role": role, "email": "private@example.com"}


def _event_from(base, **changes):
    event = {
        **base,
        "kind": "event",
        "seq": base["seq"] + 1,
        "event_type": "system.heartbeat",
        "event_version": 1,
        "payload": {"alive": True},
    }
    event.update(changes)
    return event


def test_schema_es_autosuficiente_y_fingerprint_sigue_candidato():
    assert CONTRACT_V1_FINGERPRINT == "__PENDING_FREEZE__"
    assert_contract_candidate()
    assert CONTRACT_V1_SPEC["$schema"].endswith("draft/2020-12/schema")
    assert "$defs" in CONTRACT_V1_SPEC
    assert "x-nexux" in CONTRACT_V1_SPEC
    assert len(candidate_fingerprint()) == 64
    assert CONTRACT_V1_SPEC["x-nexux"]["time"]["unit"] == "unix_ms"
    assert CONTRACT_V1_SPEC["x-nexux"]["limits"]["max_topics"] == 128
    assert (
        CONTRACT_V1_SPEC["x-nexux"]["compatibility"]["wire_policy"]
        == "immutable-after-freeze"
    )
    Draft202012Validator.check_schema(CONTRACT_V1_SPEC)


def test_toda_regla_normativa_cambia_el_fingerprint_candidato():
    changed = copy.deepcopy(CONTRACT_V1_SPEC)
    changed["x-nexux"]["limits"]["max_topics"] = 129
    canonical = json.dumps(
        changed, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    assert hashlib.sha256(canonical.encode("ascii")).hexdigest() != candidate_fingerprint()


def test_snapshot_oficial_es_valido_y_no_filtra_email():
    snapshot = _composer().compose(_user())
    assert validate_snapshot(snapshot) is snapshot
    Draft202012Validator(CONTRACT_V1_SPEC).validate(snapshot)
    assert snapshot["contract_fingerprint"] == candidate_fingerprint()
    assert snapshot["snapshot_id"] == SNAPSHOT_ID
    assert snapshot["subject"] == "user:7"
    assert set(snapshot["topics"]) == {"system.session", "system.modules"}
    assert snapshot["cursors"] == {"system.session": 0, "system.modules": 0}
    assert "private@example.com" not in json.dumps(snapshot)
    session = snapshot["topics"]["system.session"]["payload"]["state"]
    assert session["mode"] == "not_applicable"
    assert session["availability"] == "available"
    assert session["degradation"] is None


def test_compatibilidad_es_aditiva_pero_no_permite_quitar_requeridos():
    snapshot = _composer().compose(_user())
    additive = copy.deepcopy(snapshot)
    additive["future_optional"] = {"ok": True}
    additive["topics"]["system.session"]["payload"]["data"]["new_field"] = 1
    validate_snapshot(additive)

    broken = copy.deepcopy(snapshot)
    del broken["topics"]["system.session"]["stale_at"]
    with pytest.raises(ContractViolation, match="incompleto"):
        validate_snapshot(broken)


def test_nombres_canonicos_rechazan_underscore_y_source_ajena():
    snapshot = _composer().compose(_user())
    invalid = copy.deepcopy(snapshot["topics"]["system.session"])
    invalid["topic"] = "system_bad"
    with pytest.raises(ContractViolation, match="forma canonica"):
        validate_envelope(invalid)

    invalid = copy.deepcopy(snapshot["topics"]["system.session"])
    invalid["source"] = "NexUX:Auth"
    with pytest.raises(ContractViolation, match="forma canonica"):
        validate_envelope(invalid)


def test_tiempo_exige_orden_y_tolera_solo_30_segundos_de_futuro():
    base = _composer().compose(_user())["topics"]["system.session"]
    wrong_order = {**base, "stale_at": base["observed_at"] - 1}
    with pytest.raises(ContractViolation, match="orden temporal"):
        validate_envelope(wrong_order)

    future = {
        **base,
        "observed_at": base["received_at"] + 30_001,
        "stale_at": base["received_at"] + 30_001,
        "expires_at": base["received_at"] + 30_002,
        "payload": copy.deepcopy(base["payload"]),
    }
    future["payload"]["state"]["as_of"] = future["observed_at"]
    with pytest.raises(ContractViolation, match="tolerancia de reloj"):
        validate_envelope(future)


def test_evento_exige_identidad_semantica_y_version():
    base = _composer().compose(_user())["topics"]["system.session"]
    event = _event_from(base)
    validate_envelope(event)
    Draft202012Validator(CONTRACT_V1_SPEC).validate(event)

    missing = copy.deepcopy(event)
    del missing["event_type"]
    with pytest.raises(ContractViolation, match="faltan event_type"):
        validate_envelope(missing)

    ambiguous = {**base, "event_type": "system.heartbeat", "event_version": 1}
    with pytest.raises(ContractViolation, match="solo aplican"):
        validate_envelope(ambiguous)


def test_replay_reconstruye_patch_ignora_duplicado_y_detecta_hueco():
    snapshot = _composer().compose(_user())
    base = snapshot["topics"]["system.session"]
    patch = {
        **base,
        "kind": "patch",
        "seq": 1,
        "payload": {"data": {"connected": True}},
    }
    state = replay(snapshot, [patch, patch])
    assert state.topics["system.session"]["data"]["connected"] is True
    assert state.topics["system.session"]["data"]["authenticated"] is True
    assert state.cursors["system.session"] == 1

    gap = {**patch, "seq": 3}
    with pytest.raises(ContractViolation, match="hueco"):
        replay(snapshot, [gap])


def test_replay_evento_efimero_no_muta_estado_y_rechaza_otro_subject():
    snapshot = _composer().compose(_user())
    base = snapshot["topics"]["system.session"]
    event = _event_from(base)
    before = copy.deepcopy(base["payload"])
    state = replay(snapshot, [event])
    assert state.topics["system.session"] == before
    assert state.cursors["system.session"] == 1

    foreign = {**event, "subject": "user:99"}
    with pytest.raises(ContractViolation, match="otro subject"):
        replay(snapshot, [foreign])


def test_degradacion_es_observable_sin_filtrar_error_interno():
    seen = []

    class BrokenProvider:
        topic = "market.summary"
        source = "test:broken"
        allowed_roles = None

        def read(self, actor, now_ms):
            raise RuntimeError("clave-secreta")

    snapshot = _composer(
        BrokenProvider(), on_error=lambda topic, exc: seen.append((topic, type(exc)))
    ).compose(_user())
    projection = snapshot["topics"]["market.summary"]["payload"]
    assert projection["state"]["availability"] == "unavailable"
    assert projection["state"]["degradation"] == {
        "category": "provider-failure",
        "code": "provider.read-failed",
        "retryable": True,
        "since": NOW,
    }
    assert projection["data"] == {"available": False}
    assert "clave-secreta" not in json.dumps(snapshot)
    assert seen == [("market.summary", RuntimeError)]


def test_available_exige_degradation_null_y_unavailable_exige_codigo():
    snapshot = _composer().compose(_user())
    state = snapshot["topics"]["system.session"]["payload"]["state"]
    state["degradation"] = {
        "category": "unknown",
        "code": "state.invalid",
        "retryable": False,
        "since": NOW,
    }
    with pytest.raises(ContractViolation, match="degradation=null"):
        validate_snapshot(snapshot)


def test_health_y_freshness_no_pueden_contradecir_estado_temporal():
    snapshot = _composer().compose(_user())
    state = snapshot["topics"]["system.session"]["payload"]["state"]
    state["health"] = "failed"
    with pytest.raises(ContractViolation, match="health contradice"):
        validate_snapshot(snapshot)

    snapshot = _composer().compose(_user())
    envelope = snapshot["topics"]["system.session"]
    envelope["stale_at"] = envelope["received_at"]
    with pytest.raises(ContractViolation, match="freshness contradice"):
        validate_snapshot(snapshot)


def test_provider_recibe_actor_minimo_sin_email():
    captured = []

    class InspectProvider:
        topic = "market.summary"
        source = "test:inspect"
        allowed_roles = None

        def read(self, actor, now_ms):
            captured.append(actor)
            assert isinstance(actor, ActorContext)
            return Projection(
                self.topic,
                self.source,
                now_ms,
                now_ms + 1_000,
                now_ms + 2_000,
                "healthy",
                "live",
                "not_applicable",
                "normal",
                "available",
                None,
                {},
            )

    _composer(InspectProvider()).compose(_user())
    assert captured == [ActorContext("user:7", 7, "beta", False)]
    assert not hasattr(captured[0], "email")


def test_provider_no_autorizado_no_se_ejecuta_ni_se_publica():
    calls = []

    class AdminProvider:
        topic = "bot.production"
        source = "nexux:bot"
        allowed_roles = frozenset({"admin"})

        def read(self, actor, now_ms):
            calls.append(actor.role)
            return Projection(
                self.topic,
                self.source,
                now_ms,
                now_ms + 1_000,
                now_ms + 2_000,
                "healthy",
                "live",
                "live",
                "normal",
                "available",
                None,
                {},
            )

    assert _composer(AdminProvider()).compose(_user(role="beta"))["topics"] == {}
    assert calls == []
    admin = _composer(AdminProvider()).compose(_user(role="admin"))
    assert set(admin["topics"]) == {"bot.production"}
    assert calls == ["admin"]


def test_provider_debe_declarar_allowed_roles():
    class AmbiguousProvider:
        topic = "market.summary"
        source = "test:ambiguous"

    with pytest.raises(ValueError, match="sin allowed_roles"):
        _composer(AmbiguousProvider())


def test_providers_duplicados_o_con_declaracion_invalida_fallan_al_arrancar():
    with pytest.raises(ValueError, match="topic duplicado"):
        _composer(SessionProjection(), SessionProjection())

    class InvalidTopic:
        topic = "market_bad"
        source = "test:invalid"
        allowed_roles = None

    with pytest.raises(ContractViolation, match="forma canonica"):
        _composer(InvalidTopic())

    class InvalidRoles:
        topic = "market.summary"
        source = "test:invalid"
        allowed_roles = {"admin"}

    with pytest.raises(ValueError, match="allowed_roles invalido"):
        _composer(InvalidRoles())


def test_provider_no_puede_cambiar_topic_ni_source():
    class ImpersonatingProvider:
        topic = "market.summary"
        source = "test:expected"
        allowed_roles = None

        def read(self, actor, now_ms):
            return Projection(
                self.topic,
                "nexux:bot",
                now_ms,
                now_ms,
                now_ms,
                "healthy",
                "live",
                "not_applicable",
                "normal",
                "available",
                None,
                {"unsafe": True},
            )

    snapshot = _composer(ImpersonatingProvider()).compose(_user())
    projection = snapshot["topics"]["market.summary"]["payload"]
    assert projection["state"]["health"] == "failed"
    assert projection["data"] == {"available": False}


def test_limites_rechazan_payload_grande_y_profundidad_excesiva():
    base = _composer().compose(_user())["topics"]["system.session"]
    event = _event_from(base, payload={"blob": "x" * 17_000})
    with pytest.raises(ContractViolation, match="string demasiado largo"):
        validate_envelope(event)

    nested = {}
    cursor = nested
    for _ in range(18):
        cursor["next"] = {}
        cursor = cursor["next"]
    event = _event_from(base, payload=nested)
    with pytest.raises(ContractViolation, match="profundidad"):
        validate_envelope(event)


def test_limites_rechazan_envelope_patch_snapshot_y_exceso_de_topics():
    snapshot = _composer().compose(_user())
    base = snapshot["topics"]["system.session"]

    patch = {
        **base,
        "kind": "patch",
        "seq": 1,
        "payload": {"a": "x" * 9_000, "b": "y" * 9_000},
    }
    with pytest.raises(ContractViolation, match="max_patch_payload_bytes"):
        validate_envelope(patch)

    oversized_envelope = copy.deepcopy(base)
    oversized_envelope["payload"]["data"]["rows"] = ["x" * 300] * 300
    with pytest.raises(ContractViolation, match="max_envelope_bytes"):
        validate_envelope(oversized_envelope)

    oversized_snapshot = copy.deepcopy(snapshot)
    oversized_snapshot["topics"]["system.session"]["payload"]["data"]["rows"] = [
        "x" * 300
    ] * 2_000
    with pytest.raises(ContractViolation, match="max_snapshot_bytes"):
        validate_snapshot(oversized_snapshot)

    too_many = copy.deepcopy(snapshot)
    too_many["topics"] = {}
    too_many["cursors"] = {}
    for index in range(129):
        topic = f"test.topic-{index}"
        envelope = copy.deepcopy(base)
        envelope["topic"] = topic
        too_many["topics"][topic] = envelope
        too_many["cursors"][topic] = 0
    with pytest.raises(ContractViolation, match="max_topics"):
        validate_snapshot(too_many)


def test_resultado_de_merge_patch_tambien_respeta_limite_de_proyeccion():
    snapshot = _composer().compose(_user())
    base = snapshot["topics"]["system.session"]
    patches = [
        {
            **base,
            "kind": "patch",
            "seq": index + 1,
            "payload": {
                "data": {f"chunk-{index}": [str(index) * 300] * 45}
            },
        }
        for index in range(5)
    ]
    with pytest.raises(ContractViolation, match="max_projection_bytes"):
        replay(snapshot, patches)


def test_documento_de_error_es_versionado_y_validable():
    document = error_document(
        "snapshot.compose-failed",
        "No fue posible construir el snapshot.",
        500,
        retryable=True,
        request_id=SNAPSHOT_ID,
    )
    assert validate_error(document) is document
    assert document["contract"] == "nexux.command-center.error"
    assert document["retryable"] is True
    Draft202012Validator(CONTRACT_V1_SPEC).validate(document)

    too_large = copy.deepcopy(document)
    too_large["details"] = {"a": "x" * 9_000, "b": "y" * 9_000}
    with pytest.raises(ContractViolation, match="max_error_bytes"):
        validate_error(too_large)


def test_endpoint_exige_sesion_y_subject_siempre_sale_del_servidor(monkeypatch):
    from core import app

    context = ModuleContext(
        "command_center", "modules/command_center", {}, lambda _message: None
    )
    module = CommandCenterModule(context)
    module._composer = _composer()
    monkeypatch.setitem(app.hub.modules_by_slug, "command-center", module)
    monkeypatch.setattr(app.auth, "enabled", lambda: True)
    monkeypatch.setattr(app.auth, "current_user", lambda request: None)
    client = TestClient(app.app)
    unauthorized = client.get("/m/command-center/api/snapshot")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["contract"] == "nexux.command-center.error"
    assert unauthorized.json()["code"] == "auth.required"

    monkeypatch.setattr(app.auth, "current_user", lambda request: _user(uid=42))
    response = client.get(
        "/m/command-center/api/snapshot?user_id=999",
        headers={"X-User-Id": "999"},
    )
    assert response.status_code == 200
    assert response.json()["subject"] == "user:42"
    contract = client.get("/m/command-center/api/contract/v1")
    assert contract.status_code == 200
    assert contract.json()["status"] == "candidate"
    assert contract.json()["candidate_fingerprint"] == candidate_fingerprint()
    assert contract.json()["schema"]["$schema"].endswith("draft/2020-12/schema")


def test_error_de_composicion_es_500_y_no_401():
    class BrokenComposer:
        def compose(self, user):
            raise RuntimeError("boom")

    context = ModuleContext(
        "command_center", "modules/command_center", {}, lambda _message: None
    )
    module = CommandCenterModule(context)
    module._composer = BrokenComposer()
    status, _ctype, body = module.api("snapshot", {}, user=_user())
    document = json.loads(body)
    assert status == 500
    assert document["code"] == "snapshot.compose-failed"

    status, _ctype, body = module.api("does-not-exist", {}, user=_user())
    assert status == 404
    assert json.loads(body)["code"] == "endpoint.not-found"


def test_registry_respeta_rol_y_loader_publica_slug_correcto():
    beta = _composer().compose(_user(role="beta"))
    admin = _composer().compose(_user(role="admin"))
    beta_slugs = {
        row["slug"]
        for row in beta["topics"]["system.modules"]["payload"]["data"]["modules"]
    }
    admin_slugs = {
        row["slug"]
        for row in admin["topics"]["system.modules"]["payload"]["data"]["modules"]
    }
    assert "bot" not in beta_slugs
    assert "bot" in admin_slugs

    modules = load_modules(
        f"{ROOT}/modules",
        {"modules": {"command_center": {"enabled": True}}},
        lambda _message: None,
    )
    assert len(modules) == 1
    assert modules[0].slug == "command-center"
