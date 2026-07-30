import copy
import json

import pytest
from fastapi.testclient import TestClient

from core.hub import ROOT
from core.module_base import ModuleContext
from core.module_loader import load_modules
from modules.command_center.contracts import (
    CONTRACT_V1_SPEC,
    CONTRACT_V1_FINGERPRINT,
    ContractViolation,
    assert_contract_frozen,
    replay,
    validate_envelope,
    validate_snapshot,
)
from modules.command_center.module import CommandCenterModule
from modules.command_center.snapshot import (
    ConfiguredModulesProjection,
    Projection,
    SessionProjection,
    SnapshotComposer,
)

NOW = 1_785_430_000_000


def _config():
    return {
        "modules": {
            "trading": {"enabled": True},
            "bot": {"enabled": True},
            "command_center": {"enabled": True},
        }
    }


def _composer(*providers):
    return SnapshotComposer(
        providers or [SessionProjection(), ConfiguredModulesProjection(_config)],
        clock_ms=lambda: NOW,
        id_factory=lambda: "snapshot-test-1",
    )


def _user(uid=7, role="beta"):
    return {"uid": uid, "role": role, "email": "private@example.com"}


def test_contract_v1_esta_congelado():
    assert len(CONTRACT_V1_FINGERPRINT) == 64
    assert_contract_frozen()
    assert set(CONTRACT_V1_SPEC["enums"]["health"]) == {
        "healthy", "degraded", "failed", "unknown"
    }
    assert set(CONTRACT_V1_SPEC["enums"]["kind"]) == {
        "snapshot", "patch", "event"
    }


def test_snapshot_oficial_es_valido_y_no_filtra_email():
    snapshot = _composer().compose(_user())
    assert validate_snapshot(snapshot) is snapshot
    assert snapshot["contract"] == "nexux.command-center.snapshot"
    assert snapshot["v"] == 1
    assert snapshot["contract_fingerprint"] == CONTRACT_V1_FINGERPRINT
    assert snapshot["subject"] == "user:7"
    assert set(snapshot["topics"]) == {"system.session", "system.modules"}
    assert snapshot["cursors"] == {"system.session": 0, "system.modules": 0}
    assert "private@example.com" not in json.dumps(snapshot)


def test_compatibilidad_v1_es_aditiva_pero_no_permite_quitar_requeridos():
    snapshot = _composer().compose(_user())
    additive = copy.deepcopy(snapshot)
    additive["future_optional"] = {"ok": True}
    additive["topics"]["system.session"]["payload"]["data"]["new_field"] = 1
    validate_snapshot(additive)

    broken = copy.deepcopy(snapshot)
    del broken["topics"]["system.session"]["expires_at"]
    with pytest.raises(ContractViolation, match="incompleto"):
        validate_snapshot(broken)


def test_envelope_no_puede_contradecir_estado_interno():
    snapshot = _composer().compose(_user())
    contradictory = copy.deepcopy(snapshot)
    contradictory["topics"]["system.session"]["severity"] = "critical"
    with pytest.raises(ContractViolation, match="severity contradice"):
        validate_snapshot(contradictory)


def test_replay_reconstruye_patch_ignora_duplicado_y_detecta_hueco():
    snapshot = _composer().compose(_user())
    base = snapshot["topics"]["system.session"]
    patch = {
        **base,
        "kind": "patch",
        "seq": 1,
        "payload": {"data": {"connected": True}},
    }
    validate_envelope(patch)
    state = replay(snapshot, [patch, patch])
    assert state.topics["system.session"]["data"]["connected"] is True
    assert state.topics["system.session"]["data"]["authenticated"] is True
    assert state.cursors["system.session"] == 1

    gap = {**patch, "seq": 3}
    with pytest.raises(ContractViolation, match="hueco"):
        replay(snapshot, [gap])


def test_replay_evento_efimero_no_muta_estado_y_rechaza_otro_usuario():
    snapshot = _composer().compose(_user())
    base = snapshot["topics"]["system.session"]
    event = {
        **base,
        "kind": "event",
        "seq": 1,
        "payload": {"name": "heartbeat"},
    }
    before = copy.deepcopy(snapshot["topics"]["system.session"]["payload"])
    state = replay(snapshot, [event])
    assert state.topics["system.session"] == before
    assert state.cursors["system.session"] == 1

    foreign = {**event, "subject": "user:99"}
    with pytest.raises(ContractViolation, match="otro subject"):
        replay(snapshot, [foreign])


def test_provider_caido_degrada_sin_romper_snapshot():
    class BrokenProvider:
        topic = "market.summary"
        source = "test:broken"

        def read(self, user, now_ms):
            raise RuntimeError("secreto que no debe salir")

    snapshot = _composer(BrokenProvider()).compose(_user())
    projection = snapshot["topics"]["market.summary"]["payload"]
    assert projection["state"]["health"] == "failed"
    assert projection["state"]["freshness"] == "expired"
    assert projection["data"] == {"available": False}
    assert "secreto" not in json.dumps(snapshot)


def test_provider_no_puede_escribir_en_topic_ajeno():
    class ConfusedProvider:
        topic = "market.summary"
        source = "test:confused"

        def read(self, user, now_ms):
            return Projection(
                topic="bot.production",
                source=self.source,
                observed_at=now_ms,
                expires_at=now_ms + 1_000,
                health="healthy",
                freshness="live",
                mode="live",
                severity="normal",
                data={"unsafe": True},
            )

    snapshot = _composer(ConfusedProvider()).compose(_user())
    assert set(snapshot["topics"]) == {"market.summary"}
    projection = snapshot["topics"]["market.summary"]["payload"]
    assert projection["state"]["health"] == "failed"
    assert projection["data"] == {"available": False}


def test_provider_con_estado_fuera_de_contrato_tambien_degrada():
    class InvalidProvider:
        topic = "market.summary"
        source = "test:invalid"

        def read(self, user, now_ms):
            return Projection(
                topic=self.topic,
                source=self.source,
                observed_at=now_ms,
                expires_at=now_ms + 1_000,
                health="perfect",
                freshness="live",
                mode="live",
                severity="normal",
                data={},
            )

    snapshot = _composer(InvalidProvider()).compose(_user())
    state = snapshot["topics"]["market.summary"]["payload"]["state"]
    assert state["health"] == "failed"
    assert state["freshness"] == "expired"


def test_topics_duplicados_fallan_cerrado():
    with pytest.raises(ValueError, match="topic duplicado"):
        _composer(SessionProjection(), SessionProjection()).compose(_user())


def test_registry_respeta_rol_y_no_publica_bot_a_beta():
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
    assert "command-center" in beta_slugs


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
    assert client.get("/m/command-center/api/snapshot").status_code == 401

    monkeypatch.setattr(app.auth, "current_user", lambda request: _user(uid=42))
    response = client.get(
        "/m/command-center/api/snapshot?user_id=999",
        headers={"X-User-Id": "999"},
    )
    assert response.status_code == 200
    assert response.json()["subject"] == "user:42"
    contract = client.get("/m/command-center/api/contract/v1")
    assert contract.status_code == 200
    assert contract.json()["fingerprint"] == CONTRACT_V1_FINGERPRINT


def test_modo_local_tiene_identidad_estable():
    snapshot = _composer().compose(
        {"uid": None, "role": "admin", "synthetic": True}
    )
    assert snapshot["subject"] == "user:local"


def test_loader_descubre_modulo_con_slug_publico():
    modules = load_modules(
        f"{ROOT}/modules",
        {"modules": {"command_center": {"enabled": True}}},
        lambda _message: None,
    )
    assert len(modules) == 1
    assert modules[0].slug == "command-center"
