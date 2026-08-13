import hashlib
import json

from modules.bot.testnet_evidence import record_scenario, verify_scenario_record


def test_record_crea_artefacto_inmutable_y_marker_verificable(tmp_path):
    record = record_scenario(
        tmp_path, "native_stop_confirmed", {"algo_id": "123", "qty": 0.1},
        observed_at_ms=123_000, deployed_commit="abc123",
    )

    artifact = tmp_path / record["evidence"]["artifact"]
    payload = artifact.read_bytes()
    marker = json.loads((tmp_path / "live_readiness.json").read_text())

    assert hashlib.sha256(payload).hexdigest() == record["evidence"]["sha256"]
    assert marker["deployed_commit"] == "abc123"
    assert verify_scenario_record(tmp_path, "native_stop_confirmed", record)


def test_record_no_sobrescribe_artefacto_existente(tmp_path):
    kwargs = {
        "data_dir": tmp_path,
        "scenario_id": "native_stop_confirmed",
        "details": {"same": True},
        "observed_at_ms": 123_000,
    }
    record_scenario(**kwargs)

    try:
        record_scenario(**kwargs)
    except FileExistsError:
        pass
    else:
        raise AssertionError("un artefacto de evidencia no puede sobrescribirse")


def test_verify_rechaza_escenario_o_entorno_incompatibles(tmp_path):
    record = record_scenario(
        tmp_path, "native_stop_confirmed", {}, observed_at_ms=123_000,
    )

    assert not verify_scenario_record(tmp_path, "partial_stop_resized", record)
    assert not verify_scenario_record(tmp_path, "native_stop_confirmed", {
        **record, "evidence": "texto libre",
    })
