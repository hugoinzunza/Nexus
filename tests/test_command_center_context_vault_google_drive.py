import json
import os
from pathlib import Path

import pytest

from core.vault import unseal
from modules.command_center.context_recorder import MarketContextRecorder
from modules.command_center.context_storage import ContextStorageManager
from modules.command_center.context_vault_cli import main as vault_cli
from modules.command_center.context_vault_google_drive import (
    ContextVaultError,
    ContextVaultKeyManager,
    ContextVaultManager,
    GoogleDriveVaultProvider,
    SNAPSHOT_ENVELOPE_SCHEMA,
    run_canary_restore,
)


NOW = 1_800_000_000_000


def _snapshot(timestamp, price=70_000):
    return {
        "generated_at_ms": timestamp,
        "assets": [
            {
                "id": "btcusdt",
                "price": price,
                "change_pct": 1.25,
                "observed_at_ms": timestamp,
                "freshness": "live",
                "source": "Binance Futures",
                "kind": "futures",
            }
        ],
        "provider_errors": [],
    }


def _key_material(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    key_root = tmp_path / "keys"
    result = ContextVaultKeyManager.generate(key_root, repo_root=repo)
    return key_root, result


def _storage(tmp_path, clock):
    manager = ContextStorageManager(
        tmp_path / "storage",
        min_free_bytes=1,
        clock_ms=lambda: clock[0],
    )
    manager.initialize()
    recorder = MarketContextRecorder(
        manager.active_path,
        clock_ms=lambda: clock[0],
        coordination_lock_path=manager.coordination_lock_path,
    )
    recorder.record(_snapshot(clock[0]))
    manager.rotate_if_needed(force=True)
    return manager


def _provider(tmp_path, clock):
    provider = GoogleDriveVaultProvider(
        tmp_path / "fake-drive" / "NexUX" / "ContextVault",
        require_google_drive=False,
        clock_ms=lambda: clock[0],
    )
    provider.initialize()
    return provider


def test_provider_real_exige_mount_oficial_de_google_drive(tmp_path):
    cloud = tmp_path / "CloudStorage"
    cloud.mkdir()
    provider = GoogleDriveVaultProvider(
        cloud / "NotGoogle" / "Vault",
        cloud_storage_root=cloud,
    )

    with pytest.raises(ContextVaultError, match="not mounted"):
        provider.initialize()

    mount = cloud / "GoogleDrive-user@example.com"
    mount.mkdir()
    official = GoogleDriveVaultProvider(
        mount / "My Drive" / "NexUX" / "ContextVault",
        cloud_storage_root=cloud,
    )
    assert official.initialize()["status"] == "ready"


def test_clave_exclusiva_vive_fuera_de_repo_y_backup(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    backup = tmp_path / "backup"
    backup.mkdir()

    with pytest.raises(ContextVaultError, match="outside repo and backup"):
        ContextVaultKeyManager.generate(repo / "keys", repo_root=repo)
    with pytest.raises(ContextVaultError, match="outside repo and backup"):
        ContextVaultKeyManager.generate(
            backup / "keys",
            repo_root=repo,
            forbidden_roots=(backup,),
        )

    key_root = tmp_path / "keys"
    generated = ContextVaultKeyManager.generate(
        key_root,
        repo_root=repo,
        forbidden_roots=(backup,),
        clock_ms=lambda: NOW,
    )
    health = ContextVaultKeyManager.inspect(key_root)

    assert generated["algorithm"] == "RSA-OAEP-256+AES-256-GCM"
    assert health["status"] == "ready"
    assert os.stat(key_root / "context-vault-private.pem").st_mode & 0o077 == 0
    assert not (backup / "context-vault-private.pem").exists()


def test_provider_no_sobrescribe_artefactos_y_verifica_readback(tmp_path):
    clock = [NOW]
    provider = _provider(tmp_path, clock)

    first = provider.put_immutable("segments/a.vault.json", b"ciphertext")
    second = provider.put_immutable("segments/a.vault.json", b"ciphertext")

    assert first["created"] is True
    assert second["created"] is False
    assert provider.read_verified("segments/a.vault.json", first["sha256"]) == b"ciphertext"
    with pytest.raises(ContextVaultError, match="already differs"):
        provider.put_immutable("segments/a.vault.json", b"different")


def test_backup_incremental_snapshot_cifrado_y_restore_completo(tmp_path):
    clock = [NOW]
    storage = _storage(tmp_path, clock)
    provider = _provider(tmp_path, clock)
    key_root, _generated = _key_material(tmp_path)
    manager = ContextVaultManager(
        storage,
        provider,
        public_key_file=key_root / "context-vault-public.pem",
        clock_ms=lambda: clock[0],
    )

    first = manager.backup_incremental(provenance="test-causal")
    clock[0] += 60_000
    recorder = MarketContextRecorder(
        storage.active_path,
        clock_ms=lambda: clock[0],
        previous_event=storage.last_closed_event(),
        coordination_lock_path=storage.coordination_lock_path,
    )
    recorder.record(_snapshot(clock[0], 71_000))
    storage.rotate_if_needed(force=True)
    second = manager.backup_incremental(provenance="test-causal")

    assert first["segments_uploaded"] == 1
    assert second["segments_uploaded"] == 1
    assert second["segments_reused"] == 1
    snapshot_path = provider.root / second["snapshot_artifact"]
    assert b"70000" not in snapshot_path.read_bytes()
    envelope = json.loads(snapshot_path.read_text())
    assert envelope["schema"] == SNAPSHOT_ENVELOPE_SCHEMA

    restore = manager.restore_snapshot(
        second["snapshot_artifact"],
        tmp_path / "restored",
        private_key_file=key_root / "context-vault-private.pem",
    )
    restored = ContextStorageManager.from_existing(tmp_path / "restored")

    assert restore["status"] == "verified"
    assert restore["segment_count"] == 2
    assert restored.load_all_events() == storage.load_all_events()
    assert manager.health()["status"] == "ready"
    assert manager.health()["hash_verified"] is True


def test_snapshot_declara_manifests_metadata_tamano_y_provenance(tmp_path):
    clock = [NOW]
    storage = _storage(tmp_path, clock)
    provider = _provider(tmp_path, clock)
    key_root, _generated = _key_material(tmp_path)
    manager = ContextVaultManager(
        storage,
        provider,
        public_key_file=key_root / "context-vault-public.pem",
        clock_ms=lambda: clock[0],
    )
    backup = manager.backup_incremental(provenance="nexux-context-canary")
    envelope = json.loads(
        (provider.root / backup["snapshot_artifact"]).read_text()
    )
    private = (key_root / "context-vault-private.pem").read_text()
    snapshot = json.loads(unseal(envelope["envelope"], private))

    assert snapshot["version"] == 1
    assert snapshot["created_at_ms"] == NOW
    assert snapshot["provenance"] == "nexux-context-canary"
    assert snapshot["total_plaintext_size_bytes"] > 0
    assert snapshot["segments"][0]["manifest"]["segment_id"] == "segment-000001"
    assert snapshot["segments"][0]["vault_sha256"]


def test_restore_detecta_corrupcion_sin_crear_destino_valido(tmp_path):
    clock = [NOW]
    storage = _storage(tmp_path, clock)
    provider = _provider(tmp_path, clock)
    key_root, _generated = _key_material(tmp_path)
    manager = ContextVaultManager(
        storage,
        provider,
        public_key_file=key_root / "context-vault-public.pem",
        clock_ms=lambda: clock[0],
    )
    backup = manager.backup_incremental(provenance="test")
    segment = next((provider.root / "segments").glob("*.vault.json"))
    segment.write_bytes(segment.read_bytes() + b"corrupt")

    with pytest.raises(ContextVaultError, match="missing or corrupt"):
        manager.restore_snapshot(
            backup["snapshot_artifact"],
            tmp_path / "restore-corrupt",
            private_key_file=key_root / "context-vault-private.pem",
        )
    assert not (tmp_path / "restore-corrupt" / "storage-policy.json").exists()


def test_backup_no_migra_un_recibo_previo_a_otro_destino(tmp_path):
    clock = [NOW]
    storage = _storage(tmp_path, clock)
    first_provider = _provider(tmp_path, clock)
    key_root, _generated = _key_material(tmp_path)
    ContextVaultManager(
        storage,
        first_provider,
        public_key_file=key_root / "context-vault-public.pem",
        clock_ms=lambda: clock[0],
    ).backup_incremental(provenance="first")
    second_provider = GoogleDriveVaultProvider(
        tmp_path / "other-drive" / "ContextVault",
        require_google_drive=False,
        clock_ms=lambda: clock[0],
    )
    second_provider.initialize()
    second_manager = ContextVaultManager(
        storage,
        second_provider,
        public_key_file=key_root / "context-vault-public.pem",
        clock_ms=lambda: clock[0],
    )

    with pytest.raises(ContextVaultError, match="different or missing"):
        second_manager.backup_incremental(provenance="second")


def test_canary_es_sintetico_aislado_y_restaura_eventos_identicos(tmp_path):
    clock = [NOW]
    key_root, _generated = _key_material(tmp_path)
    result = run_canary_restore(
        tmp_path / "fake-drive" / "ContextVault",
        key_root,
        tmp_path / "canary-workspace",
        require_google_drive=False,
        clock_ms=lambda: clock[0],
    )

    assert result["status"] == "verified"
    assert result["provider"] == "local-contract-emulation"
    assert result["synthetic_only"] is True
    assert result["events_equal"] is True
    assert result["hash_verified"] is True
    assert "canary" in result["provider_root"]


def test_cli_no_ofrece_activacion_scheduler_ni_coleccion(tmp_path, capsys):
    assert vault_cli(["discover-google-drive"]) == 0
    output = capsys.readouterr().out.lower()

    assert "mounts" in output
    assert "activate" not in output
    assert "schedule" not in output
    assert "launchd" not in output
