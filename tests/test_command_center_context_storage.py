import errno
import json
import os
from pathlib import Path

import pytest

from core.vault import generate_keypair
from modules.command_center import context_recorder as recorder_module
from modules.command_center.context_recorder import MarketContextRecorder
from modules.command_center.context_storage import (
    ContextStorageError,
    ContextStorageManager,
)
from modules.command_center.context_storage_cli import main as storage_cli


NOW = 1_800_000_000_000


def _snapshot(timestamp, price):
    return {
        "generated_at_ms": timestamp,
        "assets": [
            {
                "id": "btcusdt",
                "price": price,
                "change_pct": 1.0,
                "observed_at_ms": timestamp,
                "freshness": "live",
                "source": "Binance Futures",
                "kind": "futures",
            }
        ],
        "provider_errors": [],
    }


def _recorder(manager, clock, previous=None):
    return MarketContextRecorder(
        manager.active_path,
        clock_ms=lambda: clock[0],
        previous_event=previous,
        coordination_lock_path=manager.coordination_lock_path,
    )


def _write_events(manager, points, previous=None):
    clock = [points[0][0]]
    recorder = _recorder(manager, clock, previous=previous)
    for timestamp, price in points:
        clock[0] = timestamp
        recorder.record(_snapshot(timestamp, price))
    return recorder


def test_storage_exige_una_ruta_fuera_del_repositorio(tmp_path):
    repo = tmp_path / "repo"
    root = repo / "data" / "context"
    repo.mkdir()
    manager = ContextStorageManager(root, repo_root=repo)

    with pytest.raises(ContextStorageError):
        manager.initialize()

    assert not root.exists()


def test_rotacion_publica_segmento_inmutable_y_conserva_continuidad(tmp_path):
    clock = [NOW]
    manager = ContextStorageManager(
        tmp_path / "storage",
        min_free_bytes=1,
        clock_ms=lambda: clock[0],
    )
    manager.initialize()
    _write_events(
        manager,
        [(NOW, 70_000), (NOW + 30_000, 70_100), (NOW + 60_000, 70_200)],
    )
    clock[0] = NOW + 60_000

    manifest = manager.rotate_if_needed(force=True)

    assert manifest["segment_id"] == "segment-000001"
    segment = manager.segments_dir / manifest["file"]
    assert os.stat(segment).st_mode & 0o777 == 0o400
    assert not manager.active_path.exists()
    closed_events = manager.load_all_events()
    assert [event["sequence"] for event in closed_events] == [1, 2, 3]

    previous = closed_events[-1]
    clock[0] = NOW + 90_000
    _write_events(manager, [(clock[0], 70_300)], previous=previous)
    report = manager.audit()
    assert report["segment_count"] == 1
    assert report["active_event_count"] == 1
    assert report["last_sequence"] == 4
    assert [event["sequence"] for event in manager.load_all_events()] == [1, 2, 3, 4]

    restarted = _recorder(
        manager,
        clock,
        previous=manager.last_closed_event(),
    )
    assert restarted.stats()["sequence"] == 4

    second = manager.rotate_if_needed(force=True)
    report = manager.audit()
    assert second["segment_index"] == 2
    assert second["previous_manifest_hash"] == manifest["manifest_hash"]
    assert report["segment_count"] == 2
    assert manager.last_closed_event()["sequence"] == 4


def test_audit_detecta_segmento_alterado_y_segmento_huerfano(tmp_path):
    manager = ContextStorageManager(tmp_path / "storage", min_free_bytes=1)
    manager.initialize()
    _write_events(manager, [(NOW, 70_000)])
    manifest = manager.rotate_if_needed(force=True)
    segment = manager.segments_dir / manifest["file"]
    segment.chmod(0o600)
    segment.write_bytes(segment.read_bytes() + b"x")

    with pytest.raises(ContextStorageError, match="size differs"):
        manager.audit()

    orphan_root = tmp_path / "orphan"
    orphan = ContextStorageManager(orphan_root, min_free_bytes=1)
    orphan.initialize()
    (orphan.segments_dir / "segment-000001.jsonl").write_text("orphan")
    with pytest.raises(ContextStorageError, match="orphan"):
        orphan.audit()


def test_snapshot_consistente_es_autoverificable(tmp_path):
    manager = ContextStorageManager(
        tmp_path / "storage",
        min_free_bytes=1,
        clock_ms=lambda: NOW,
    )
    manager.initialize()
    _write_events(manager, [(NOW, 70_000)])

    snapshot_path = manager.create_consistency_snapshot()
    document = json.loads(snapshot_path.read_text())

    assert document["schema"].endswith("storage-snapshot.v1")
    assert document["active"]["event_count"] == 1
    assert document["active"]["last_sequence"] == 1
    assert os.stat(snapshot_path).st_mode & 0o777 == 0o400


def test_rotacion_respeta_limites_y_no_necesita_force(tmp_path):
    manager = ContextStorageManager(
        tmp_path / "storage",
        max_segment_bytes=1,
        min_free_bytes=1,
    )
    manager.initialize()
    _write_events(manager, [(NOW, 70_000)])

    manifest = manager.rotate_if_needed()

    assert manifest["event_count"] == 1
    assert manager.audit()["segment_count"] == 1


def test_backup_cifrado_restaura_y_verifica_la_misma_cadena(tmp_path):
    clock = [NOW]
    source = ContextStorageManager(
        tmp_path / "source",
        min_free_bytes=1,
        clock_ms=lambda: clock[0],
    )
    source.initialize()
    _write_events(source, [(NOW, 70_000), (NOW + 30_000, 70_100)])
    clock[0] = NOW + 30_000
    source.rotate_if_needed(force=True)
    private_pem, public_pem = generate_keypair()

    receipts = source.backup_closed_segments(tmp_path / "external", public_pem)
    vaults = sorted((tmp_path / "external").glob("segment-*.vault.json"))
    restored = ContextStorageManager.restore_vaults(
        vaults,
        tmp_path / "restored",
        private_pem,
        clock_ms=lambda: NOW + 60_000,
    )

    assert len(receipts) == 1
    assert b"70000" not in vaults[0].read_bytes()
    assert source.policy_path.read_bytes() == restored.policy_path.read_bytes()
    assert source.load_all_events() == restored.load_all_events()
    receipt = source.verify_restore_drill(restored.root)
    assert receipt["segment_count"] == 1
    assert source.health()["restore_drill_verified"] is True


def test_drill_aislado_valida_storage_vacio_sin_contaminarlo(tmp_path):
    primary = ContextStorageManager(tmp_path / "primary", min_free_bytes=1)
    primary.initialize()
    source = ContextStorageManager(tmp_path / "drill-source", min_free_bytes=1)
    source.initialize()
    _write_events(source, [(NOW, 70_000)])
    source.rotate_if_needed(force=True)
    private_pem, public_pem = generate_keypair()
    source.backup_closed_segments(tmp_path / "external", public_pem)
    restored = ContextStorageManager.restore_vaults(
        (tmp_path / "external").glob("segment-*.vault.json"),
        tmp_path / "drill-restored",
        private_pem,
    )

    receipt = primary.record_isolated_restore_drill(source.root, restored.root)

    assert receipt["scope"] == "isolated_pre_activation"
    assert primary.audit()["segment_count"] == 0
    assert primary.health()["backup_complete"] is True
    assert primary.health()["restore_drill_verified"] is True


def test_drill_aislado_se_invalida_si_desaparece_evidencia_o_nace_historia(
    tmp_path,
):
    primary = ContextStorageManager(tmp_path / "primary", min_free_bytes=1)
    primary.initialize()
    source = ContextStorageManager(tmp_path / "drill-source", min_free_bytes=1)
    source.initialize()
    _write_events(source, [(NOW, 70_000)])
    source.rotate_if_needed(force=True)
    private_pem, public_pem = generate_keypair()
    source.backup_closed_segments(tmp_path / "external", public_pem)
    restored = ContextStorageManager.restore_vaults(
        (tmp_path / "external").glob("segment-*.vault.json"),
        tmp_path / "drill-restored",
        private_pem,
    )
    primary.record_isolated_restore_drill(source.root, restored.root)

    restored_manifest = next(restored.manifests_dir.glob("segment-*.json"))
    restored_manifest.chmod(0o600)
    restored_manifest.unlink()
    assert primary.health()["restore_drill_verified"] is False

    restored = ContextStorageManager.restore_vaults(
        (tmp_path / "external").glob("segment-*.vault.json"),
        tmp_path / "drill-restored-2",
        private_pem,
    )
    primary.record_isolated_restore_drill(source.root, restored.root)
    _write_events(primary, [(NOW + 30_000, 70_100)])
    primary.rotate_if_needed(force=True)

    assert primary.health()["restore_drill_verified"] is False


def test_drill_aislado_rechaza_fuente_vacia_o_raices_reutilizadas(tmp_path):
    primary = ContextStorageManager(tmp_path / "primary", min_free_bytes=1)
    primary.initialize()
    empty_source = ContextStorageManager(
        tmp_path / "empty-source",
        min_free_bytes=1,
    )
    empty_source.initialize()
    empty_restored = ContextStorageManager(
        tmp_path / "empty-restored",
        min_free_bytes=1,
    )
    empty_restored.initialize()

    with pytest.raises(ContextStorageError, match="not equivalent"):
        primary.record_isolated_restore_drill(
            empty_source.root,
            empty_restored.root,
        )
    with pytest.raises(ContextStorageError, match="distinct"):
        primary.record_isolated_restore_drill(primary.root, empty_source.root)


def test_vault_alterado_invalida_recibo_y_backup_completo(tmp_path):
    manager = ContextStorageManager(tmp_path / "storage", min_free_bytes=1)
    manager.initialize()
    _write_events(manager, [(NOW, 70_000)])
    manager.rotate_if_needed(force=True)
    _private, public = generate_keypair()
    manager.backup_closed_segments(tmp_path / "external", public)
    vault = next((tmp_path / "external").glob("segment-*.vault.json"))

    assert manager.health()["backup_complete"] is True
    vault.write_bytes(vault.read_bytes() + b"x")

    assert manager.health()["backup_complete"] is False


def test_restore_rechaza_clave_incorrecta_y_destino_no_vacio(tmp_path):
    source = ContextStorageManager(tmp_path / "source", min_free_bytes=1)
    source.initialize()
    _write_events(source, [(NOW, 70_000)])
    source.rotate_if_needed(force=True)
    private_pem, public_pem = generate_keypair()
    wrong_private, _wrong_public = generate_keypair()
    source.backup_closed_segments(tmp_path / "external", public_pem)
    vaults = list((tmp_path / "external").glob("segment-*.vault.json"))

    with pytest.raises(Exception):
        ContextStorageManager.restore_vaults(
            vaults,
            tmp_path / "wrong-key",
            wrong_private,
        )

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep").write_text("data")
    with pytest.raises(ContextStorageError, match="empty"):
        ContextStorageManager.restore_vaults(vaults, occupied, private_pem)


def test_retencion_solo_informa_y_exige_backup_verificado(tmp_path):
    old = NOW - 100 * 86_400_000
    clock = [old]
    manager = ContextStorageManager(
        tmp_path / "storage",
        retention_days=90,
        min_free_bytes=1,
        clock_ms=lambda: clock[0],
    )
    manager.initialize()
    _write_events(manager, [(old, 70_000)])
    manager.rotate_if_needed(force=True)

    assert manager.retention_candidates(now_ms=NOW) == []
    _private, public = generate_keypair()
    manager.backup_closed_segments(tmp_path / "external", public)
    candidates = manager.retention_candidates(now_ms=NOW)

    assert candidates[0]["action"] == "eligible_for_manual_review"
    assert (manager.segments_dir / "segment-000001.jsonl").exists()


def test_recovery_de_cola_parcial_es_explicita_y_deja_cuarentena(tmp_path):
    manager = ContextStorageManager(tmp_path / "storage", min_free_bytes=1)
    manager.initialize()
    _write_events(manager, [(NOW, 70_000)])
    with manager.active_path.open("ab") as target:
        target.write(b'{"event":"partial"')

    with pytest.raises(Exception):
        manager.audit()
    receipt = manager.recover_incomplete_tail()

    assert receipt["removed_bytes"] > 0
    assert (manager.recovery_dir / receipt["quarantine_file"]).exists()
    assert manager.audit()["last_sequence"] == 1


def test_recorder_revierte_una_escritura_parcial_en_enospc(tmp_path, monkeypatch):
    manager = ContextStorageManager(tmp_path / "storage", min_free_bytes=1)
    manager.initialize()
    clock = [NOW]
    recorder = _recorder(manager, clock)
    real_write = recorder_module.os.write
    calls = [0]

    def partial_then_full(descriptor, payload):
        calls[0] += 1
        if calls[0] == 1:
            return real_write(descriptor, payload[:8])
        raise OSError(errno.ENOSPC, "disk full")

    monkeypatch.setattr(recorder_module.os, "write", partial_then_full)
    with pytest.raises(OSError) as error:
        recorder.record(_snapshot(NOW, 70_000))

    assert error.value.errno == errno.ENOSPC
    assert manager.active_path.read_bytes() == b""
    assert recorder.stats()["status"] == "failed"


def test_health_declara_espacio_insuficiente_sin_escribir(tmp_path):
    manager = ContextStorageManager(
        tmp_path / "storage",
        min_free_bytes=10**30,
    )
    manager.initialize()

    health = manager.health()

    assert health["status"] == "low_space"
    assert health["low_space"] is True


def test_cli_prepara_y_audita_sin_ofrecer_activacion(tmp_path, capsys):
    root = tmp_path / "storage"

    assert storage_cli(
        [
            "init",
            "--root",
            str(root),
            "--minimum-free-gib",
            "1",
        ]
    ) == 0
    assert storage_cli(["audit", "--root", str(root)]) == 0

    output = capsys.readouterr().out
    assert '"status": "ready"' in output
    assert "activate" not in output.lower()


def test_cli_no_repara_cola_sin_confirmacion_explicita(tmp_path, capsys):
    root = tmp_path / "storage"
    manager = ContextStorageManager(root, min_free_bytes=1)
    manager.initialize()

    code = storage_cli(["recover-tail", "--root", str(root)])

    assert code == 2
    assert "explicit confirmation" in capsys.readouterr().out
