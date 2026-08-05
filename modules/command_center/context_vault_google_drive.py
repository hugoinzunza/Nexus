"""Context Vault cifrado sobre una carpeta oficial de Google Drive para macOS."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Callable

from core.vault import generate_keypair, seal, unseal

from .context_storage import (
    ContextStorageError,
    ContextStorageManager,
    RECEIPT_SCHEMA,
    VAULT_PAYLOAD_SCHEMA,
    VAULT_SCHEMA,
)


PROVIDER_SCHEMA = "nexux.context.google-drive-provider.v1"
SNAPSHOT_SCHEMA = "nexux.context.vault-snapshot.v1"
SNAPSHOT_ENVELOPE_SCHEMA = "nexux.context.vault-snapshot-envelope.v1"
BACKUP_REPORT_SCHEMA = "nexux.context.vault-backup-report.v1"
RESTORE_REPORT_SCHEMA = "nexux.context.vault-restore-report.v1"
KEY_METADATA_SCHEMA = "nexux.context.vault-key.v1"
CANARY_SCHEMA = "nexux.context.vault-canary.v1"


class ContextVaultError(ContextStorageError):
    """El Vault no puede continuar sin intervencion explicita."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("vault write made no progress")
            offset += written
        os.fsync(descriptor)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(descriptor)
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _document_hash(document: dict) -> str:
    unsigned = dict(document)
    for field in ("snapshot_hash", "report_hash", "metadata_hash"):
        unsigned.pop(field, None)
    return _sha256_bytes(_canonical(unsigned))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


class ContextVaultKeyManager:
    """Genera una KEK exclusiva; cada artefacto usa una data-key AES-256 nueva."""

    PRIVATE_NAME = "context-vault-private.pem"
    PUBLIC_NAME = "context-vault-public.pem"
    METADATA_NAME = "context-vault-key.json"

    @classmethod
    def generate(
        cls,
        key_root: str | Path,
        *,
        repo_root: str | Path,
        forbidden_roots: tuple[str | Path, ...] = (),
        clock_ms: Callable[[], int] | None = None,
    ) -> dict:
        root = Path(key_root).expanduser().resolve()
        blocked = (
            Path(repo_root).resolve(),
            Path.home() / "Library" / "CloudStorage",
        ) + tuple(
            Path(item).expanduser().resolve() for item in forbidden_roots
        )
        if any(_is_within(root, item) for item in blocked):
            raise ContextVaultError("vault keys must live outside repo and backup")
        private_path = root / cls.PRIVATE_NAME
        public_path = root / cls.PUBLIC_NAME
        metadata_path = root / cls.METADATA_NAME
        if any(path.exists() for path in (private_path, public_path, metadata_path)):
            raise ContextVaultError("vault key material already exists")
        root.mkdir(parents=True, exist_ok=False, mode=0o700)
        os.chmod(root, 0o700)
        private_pem, public_pem = generate_keypair()
        _atomic_write(private_path, private_pem.encode("ascii"), mode=0o600)
        _atomic_write(public_path, public_pem.encode("ascii"), mode=0o644)
        now = (clock_ms or (lambda: int(time.time() * 1000)))()
        metadata = {
            "schema": KEY_METADATA_SCHEMA,
            "created_at_ms": now,
            "algorithm": "RSA-OAEP-256+AES-256-GCM",
            "public_key_sha256": _sha256_bytes(public_pem.encode("ascii")),
            "private_key_location": "local_only",
            "recovery_copy_confirmed": False,
        }
        metadata["metadata_hash"] = _document_hash(metadata)
        _atomic_write(metadata_path, _canonical(metadata) + b"\n", mode=0o600)
        return {
            **metadata,
            "private_key_file": str(private_path),
            "public_key_file": str(public_path),
        }

    @classmethod
    def inspect(cls, key_root: str | Path) -> dict:
        root = Path(key_root).expanduser()
        private_path = root / cls.PRIVATE_NAME
        public_path = root / cls.PUBLIC_NAME
        metadata_path = root / cls.METADATA_NAME
        if not all(path.is_file() for path in (private_path, public_path, metadata_path)):
            return {"status": "unconfigured", "root": str(root)}
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        valid = (
            metadata.get("schema") == KEY_METADATA_SCHEMA
            and metadata.get("metadata_hash") == _document_hash(metadata)
            and metadata.get("public_key_sha256") == _sha256_file(public_path)
            and (os.stat(private_path).st_mode & 0o077) == 0
        )
        return {
            "status": "ready" if valid else "failed",
            "root": str(root),
            "public_key_sha256": metadata.get("public_key_sha256"),
            "private_key_present": private_path.is_file(),
            "recovery_copy_confirmed": bool(
                metadata.get("recovery_copy_confirmed", False)
            ),
        }


class GoogleDriveVaultProvider:
    """Destino filesystem de Drive for desktop, sin API privada ni scheduler."""

    def __init__(
        self,
        root: str | Path,
        *,
        cloud_storage_root: str | Path | None = None,
        require_google_drive: bool = True,
        clock_ms: Callable[[], int] | None = None,
    ):
        self.root = Path(root).expanduser()
        self.cloud_storage_root = Path(
            cloud_storage_root
            or Path.home() / "Library" / "CloudStorage"
        ).expanduser()
        self.require_google_drive = require_google_drive
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    @classmethod
    def discover(
        cls,
        cloud_storage_root: str | Path | None = None,
    ) -> list[Path]:
        root = Path(
            cloud_storage_root
            or Path.home() / "Library" / "CloudStorage"
        ).expanduser()
        if not root.is_dir():
            return []
        return sorted(
            path
            for path in root.iterdir()
            if path.is_dir() and path.name.startswith("GoogleDrive-")
        )

    @property
    def provider_path(self) -> Path:
        return self.root / "provider.json"

    def initialize(self) -> dict:
        self._validate_location()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        expected = {
            "schema": PROVIDER_SCHEMA,
            "provider": "google-drive-for-desktop",
            "created_at_ms": self._clock_ms(),
            "encrypted_payloads_only": True,
            "automatic_sync_authorized": False,
        }
        if self.provider_path.exists():
            actual = json.loads(self.provider_path.read_text(encoding="utf-8"))
            if actual.get("schema") != PROVIDER_SCHEMA:
                raise ContextVaultError("invalid Google Drive Vault marker")
        else:
            _atomic_write(self.provider_path, _canonical(expected) + b"\n")
        return self.health()

    def put_immutable(self, relative: str | Path, payload: bytes) -> dict:
        self.require_ready()
        path = self.resolve_artifact(relative)
        expected_hash = _sha256_bytes(payload)
        if path.exists():
            if not path.is_file() or _sha256_file(path) != expected_hash:
                raise ContextVaultError("immutable Vault artifact already differs")
            return {
                "path": str(path),
                "sha256": expected_hash,
                "size_bytes": path.stat().st_size,
                "created": False,
            }
        _atomic_write(path, payload)
        if _sha256_file(path) != expected_hash:
            raise ContextVaultError("Google Drive readback hash mismatch")
        return {
            "path": str(path),
            "sha256": expected_hash,
            "size_bytes": path.stat().st_size,
            "created": True,
        }

    def read_verified(self, relative: str | Path, expected_hash: str) -> bytes:
        self.require_ready()
        path = self.resolve_artifact(relative)
        if not path.is_file() or _sha256_file(path) != expected_hash:
            raise ContextVaultError("Vault artifact is missing or corrupt")
        return path.read_bytes()

    def health(self) -> dict:
        try:
            self._validate_location()
            if not self.provider_path.is_file():
                raise ContextVaultError("provider is not initialized")
            marker = json.loads(self.provider_path.read_text(encoding="utf-8"))
            if marker.get("schema") != PROVIDER_SCHEMA:
                raise ContextVaultError("provider marker is invalid")
            artifacts = [
                path
                for path in self.root.rglob("*.vault.json")
                if path.is_file()
            ]
            usage = shutil.disk_usage(self.root)
            return {
                "status": "ready",
                "provider": "google-drive-for-desktop",
                "root": str(self.root),
                "artifact_count": len(artifacts),
                "total_size_bytes": sum(path.stat().st_size for path in artifacts),
                "free_bytes": usage.free,
                "last_error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "unavailable",
                "provider": "google-drive-for-desktop",
                "root": str(self.root),
                "artifact_count": 0,
                "total_size_bytes": 0,
                "free_bytes": None,
                "last_error": type(exc).__name__,
            }

    def _validate_location(self) -> None:
        if not self.require_google_drive:
            return
        mounts = self.discover(self.cloud_storage_root)
        if not mounts or not any(_is_within(self.root, mount) for mount in mounts):
            raise ContextVaultError("Google Drive for desktop is not mounted")

    def require_ready(self) -> None:
        if self.health()["status"] != "ready":
            raise ContextVaultError("Google Drive Vault provider is unavailable")

    def resolve_artifact(self, relative: str | Path) -> Path:
        raw = Path(relative)
        if raw.is_absolute() or ".." in raw.parts:
            raise ContextVaultError("Vault artifact path is unsafe")
        path = self.root / raw
        if not _is_within(path, self.root):
            raise ContextVaultError("Vault artifact escapes provider root")
        return path


class ContextVaultManager:
    """Backup incremental y restore completo; nunca inicia coleccion."""

    def __init__(
        self,
        storage: ContextStorageManager,
        provider: GoogleDriveVaultProvider,
        *,
        public_key_file: str | Path,
        clock_ms: Callable[[], int] | None = None,
    ):
        self.storage = storage
        self.provider = provider
        self.public_key_file = Path(public_key_file).expanduser()
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    @property
    def backup_report_path(self) -> Path:
        return self.storage.recovery_dir / "google-drive-backup-latest.json"

    @property
    def restore_report_path(self) -> Path:
        return self.storage.recovery_dir / "google-drive-restore-latest.json"

    def backup_incremental(self, *, provenance: str) -> dict:
        report = self.storage.audit()
        manifests = report["manifests"]
        if not manifests:
            raise ContextVaultError("backup requires at least one closed segment")
        self.provider.require_ready()
        if not self.public_key_file.is_file():
            raise ContextVaultError("Context Vault public key is missing")
        public_pem = self.public_key_file.read_text(encoding="utf-8")
        uploaded = 0
        reused = 0
        entries = []
        for manifest in manifests:
            entry, created = self._backup_segment(manifest, public_pem)
            entries.append(entry)
            uploaded += int(created)
            reused += int(not created)
        snapshot = {
            "schema": SNAPSHOT_SCHEMA,
            "version": 1,
            "created_at_ms": self._clock_ms(),
            "provenance": str(provenance),
            "storage_schema": report["schema"],
            "storage_policy_sha256": _sha256_file(self.storage.policy_path),
            "segment_count": len(entries),
            "total_plaintext_size_bytes": sum(
                item["segment_size_bytes"] for item in entries
            ),
            "head_manifest_hash": manifests[-1]["manifest_hash"],
            "segments": entries,
        }
        snapshot["snapshot_hash"] = _document_hash(snapshot)
        plaintext = _canonical(snapshot)
        envelope = {
            "schema": SNAPSHOT_ENVELOPE_SCHEMA,
            "snapshot_id": (
                f"snapshot-{snapshot['created_at_ms']}-"
                f"{snapshot['snapshot_hash'][:12]}"
            ),
            "created_at_ms": snapshot["created_at_ms"],
            "payload_sha256": _sha256_bytes(plaintext),
            "envelope": seal(plaintext, public_pem),
        }
        artifact = self.provider.put_immutable(
            f"snapshots/{envelope['snapshot_id']}.vault.json",
            _canonical(envelope) + b"\n",
        )
        backup_report = {
            "schema": BACKUP_REPORT_SCHEMA,
            "status": "verified",
            "completed_at_ms": self._clock_ms(),
            "snapshot_id": envelope["snapshot_id"],
            "snapshot_hash": snapshot["snapshot_hash"],
            "snapshot_artifact": str(
                Path(artifact["path"]).relative_to(self.provider.root)
            ),
            "snapshot_artifact_sha256": artifact["sha256"],
            "segment_count": len(entries),
            "segments_uploaded": uploaded,
            "segments_reused": reused,
            "hash_verified": True,
            "manifest_verified": True,
            "total_size_bytes": self.provider.health()["total_size_bytes"],
        }
        backup_report["report_hash"] = _document_hash(backup_report)
        _atomic_write(
            self.backup_report_path,
            _canonical(backup_report) + b"\n",
            mode=0o400,
        )
        return backup_report

    def restore_snapshot(
        self,
        snapshot_artifact: str | Path,
        target_root: str | Path,
        *,
        private_key_file: str | Path,
        report_path: str | Path | None = None,
    ) -> dict:
        private_path = Path(private_key_file).expanduser()
        if not private_path.is_file():
            raise ContextVaultError("Context Vault private key is missing")
        relative = Path(snapshot_artifact)
        envelope_path = self.provider.resolve_artifact(relative)
        if not envelope_path.is_file():
            raise ContextVaultError("snapshot artifact does not exist")
        envelope_bytes = envelope_path.read_bytes()
        envelope = json.loads(envelope_bytes)
        if envelope.get("schema") != SNAPSHOT_ENVELOPE_SCHEMA:
            raise ContextVaultError("invalid snapshot envelope")
        private_pem = private_path.read_text(encoding="utf-8")
        plaintext = unseal(envelope["envelope"], private_pem)
        if _sha256_bytes(plaintext) != envelope.get("payload_sha256"):
            raise ContextVaultError("snapshot payload hash mismatch")
        snapshot = json.loads(plaintext)
        if (
            snapshot.get("schema") != SNAPSHOT_SCHEMA
            or snapshot.get("snapshot_hash") != _document_hash(snapshot)
        ):
            raise ContextVaultError("snapshot manifest is invalid")
        vault_paths = []
        for item in snapshot["segments"]:
            artifact_bytes = self.provider.read_verified(
                item["vault_artifact"],
                item["vault_sha256"],
            )
            artifact_path = self.provider.resolve_artifact(item["vault_artifact"])
            if artifact_path.read_bytes() != artifact_bytes:
                raise ContextVaultError("Vault artifact changed during restore")
            vault_paths.append(artifact_path)
        restored = ContextStorageManager.restore_vaults(
            vault_paths,
            target_root,
            private_pem,
            clock_ms=self._clock_ms,
        )
        restored_report = restored.audit()
        restored_manifests = restored_report["manifests"]
        expected_manifests = [item["manifest"] for item in snapshot["segments"]]
        if restored_manifests != expected_manifests:
            raise ContextVaultError("restored manifests differ from snapshot")
        restore_report = {
            "schema": RESTORE_REPORT_SCHEMA,
            "status": "verified",
            "completed_at_ms": self._clock_ms(),
            "snapshot_id": envelope["snapshot_id"],
            "snapshot_hash": snapshot["snapshot_hash"],
            "segment_count": len(restored_manifests),
            "hash_verified": True,
            "manifest_verified": True,
            "target_root": str(Path(target_root).expanduser()),
        }
        restore_report["report_hash"] = _document_hash(restore_report)
        destination = Path(report_path) if report_path else self.restore_report_path
        _atomic_write(destination, _canonical(restore_report) + b"\n", mode=0o400)
        return restore_report

    def health(self) -> dict:
        provider = self.provider.health()
        key_available = self.public_key_file.is_file()
        backup = self._verified_backup_report()
        restore = self._verified_restore_report()
        status = "ready"
        if not key_available:
            status = "unconfigured"
        elif provider["status"] != "ready":
            status = "unavailable"
        elif not backup:
            status = "not_tested"
        elif not restore:
            status = "restore_pending"
        elif not (
            backup.get("hash_verified")
            and backup.get("manifest_verified")
            and restore.get("hash_verified")
            and restore.get("manifest_verified")
        ):
            status = "failed"
        return {
            "status": status,
            "provider": provider,
            "public_key_available": key_available,
            "public_key_sha256": (
                _sha256_file(self.public_key_file) if key_available else None
            ),
            "last_backup_ms": backup.get("completed_at_ms") if backup else None,
            "last_restore_ms": restore.get("completed_at_ms") if restore else None,
            "hash_verified": bool(
                backup
                and restore
                and backup.get("hash_verified")
                and restore.get("hash_verified")
            ),
            "manifest_verified": bool(
                backup
                and restore
                and backup.get("manifest_verified")
                and restore.get("manifest_verified")
            ),
            "free_bytes": provider.get("free_bytes"),
            "total_size_bytes": provider.get("total_size_bytes", 0),
            "automatic_backup_enabled": False,
            "collection_enabled": False,
        }

    def _verified_backup_report(self) -> dict | None:
        report = self._read_report(self.backup_report_path, BACKUP_REPORT_SCHEMA)
        if not report:
            return None
        try:
            self.provider.read_verified(
                report["snapshot_artifact"],
                report["snapshot_artifact_sha256"],
            )
            if not self.storage.health()["backup_complete"]:
                return None
            return report
        except Exception:  # noqa: BLE001
            return None

    def _verified_restore_report(self) -> dict | None:
        report = self._read_report(self.restore_report_path, RESTORE_REPORT_SCHEMA)
        if not report:
            return None
        try:
            restored = ContextStorageManager.from_existing(report["target_root"])
            audit = restored.audit()
            if audit["segment_count"] != report["segment_count"]:
                return None
            return report
        except Exception:  # noqa: BLE001
            return None

    def _backup_segment(self, manifest: dict, public_pem: str) -> tuple[dict, bool]:
        segment_path = self.storage.segments_dir / manifest["file"]
        receipt_path = self.storage.receipts_dir / f"{manifest['segment_id']}.json"
        relative = Path("segments") / f"{manifest['segment_id']}.vault.json"
        artifact_path = self.provider.resolve_artifact(relative)
        if artifact_path.exists():
            if not receipt_path.is_file():
                raise ContextVaultError("existing Vault segment has no local receipt")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (
                receipt.get("schema") != RECEIPT_SCHEMA
                or receipt.get("receipt_hash")
                != self.storage._document_hash(receipt)
                or receipt.get("manifest_hash") != manifest["manifest_hash"]
                or receipt.get("segment_sha256") != manifest["sha256"]
                or Path(receipt.get("vault_file", "")).resolve()
                != artifact_path.resolve()
                or receipt.get("vault_sha256") != _sha256_file(artifact_path)
            ):
                raise ContextVaultError("existing Vault receipt is invalid")
            created = False
        else:
            if receipt_path.exists():
                raise ContextVaultError(
                    "local receipt is bound to a different or missing Vault"
                )
            payload = {
                "schema": VAULT_PAYLOAD_SCHEMA,
                "storage_policy": json.loads(
                    self.storage.policy_path.read_text(encoding="utf-8")
                ),
                "manifest": manifest,
                "segment_b64": base64.b64encode(
                    segment_path.read_bytes()
                ).decode("ascii"),
            }
            plaintext = _canonical(payload)
            vault = {
                "schema": VAULT_SCHEMA,
                "created_at_ms": self._clock_ms(),
                "segment_id": manifest["segment_id"],
                "segment_index": manifest["segment_index"],
                "manifest_hash": manifest["manifest_hash"],
                "payload_sha256": _sha256_bytes(plaintext),
                "envelope": seal(plaintext, public_pem),
            }
            stored = self.provider.put_immutable(relative, _canonical(vault) + b"\n")
            receipt = {
                "schema": RECEIPT_SCHEMA,
                "created_at_ms": self._clock_ms(),
                "segment_id": manifest["segment_id"],
                "segment_sha256": manifest["sha256"],
                "manifest_hash": manifest["manifest_hash"],
                "vault_file": stored["path"],
                "vault_sha256": stored["sha256"],
            }
            receipt["receipt_hash"] = self.storage._document_hash(receipt)
            _atomic_write(receipt_path, _canonical(receipt) + b"\n", mode=0o400)
            created = True
        return (
            {
                "segment_id": manifest["segment_id"],
                "segment_size_bytes": manifest["size_bytes"],
                "segment_sha256": manifest["sha256"],
                "manifest": manifest,
                "manifest_hash": manifest["manifest_hash"],
                "vault_artifact": str(relative),
                "vault_sha256": receipt["vault_sha256"],
                "vault_size_bytes": artifact_path.stat().st_size,
            },
            created,
        )

    @staticmethod
    def _read_report(path: Path, schema: str) -> dict | None:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if (
                report.get("schema") != schema
                or report.get("report_hash") != _document_hash(report)
            ):
                return None
            return report
        except Exception:  # noqa: BLE001
            return None


def default_google_drive_vault_root() -> Path | None:
    mounts = GoogleDriveVaultProvider.discover()
    if len(mounts) != 1:
        return None
    return mounts[0] / "My Drive" / "NexUX" / "ContextVault"


def run_canary_restore(
    provider_root: str | Path,
    key_root: str | Path,
    workspace_root: str | Path,
    *,
    require_google_drive: bool = True,
    clock_ms: Callable[[], int] | None = None,
) -> dict:
    """Ejecuta backup y restore sinteticos sin tocar la historia primaria."""
    clock = clock_ms or (lambda: int(time.time() * 1000))
    run_id = f"canary-{clock()}"
    workspace = Path(workspace_root).expanduser() / run_id
    if workspace.exists():
        raise ContextVaultError("canary workspace already exists")
    source = ContextStorageManager(
        workspace / "source",
        min_free_bytes=1,
        clock_ms=clock,
    )
    source.initialize()
    from .context_recorder import MarketContextRecorder

    recorder = MarketContextRecorder(
        source.active_path,
        clock_ms=clock,
        coordination_lock_path=source.coordination_lock_path,
    )
    timestamp = clock()
    recorder.record(
        {
            "generated_at_ms": timestamp,
            "assets": [
                {
                    "id": "canary-synthetic",
                    "price": 12345.67,
                    "change_pct": 0.25,
                    "observed_at_ms": timestamp,
                    "freshness": "canary",
                    "source": "nexux-canary",
                    "kind": "synthetic",
                }
            ],
            "provider_errors": [],
        }
    )
    source.rotate_if_needed(force=True)
    provider = GoogleDriveVaultProvider(
        Path(provider_root).expanduser() / "canary" / run_id,
        require_google_drive=require_google_drive,
        clock_ms=clock,
    )
    provider.initialize()
    key_path = Path(key_root).expanduser()
    manager = ContextVaultManager(
        source,
        provider,
        public_key_file=key_path / ContextVaultKeyManager.PUBLIC_NAME,
        clock_ms=clock,
    )
    backup = manager.backup_incremental(provenance="synthetic-canary")
    restore_report_path = workspace / "canary-restore-report.json"
    restore = manager.restore_snapshot(
        backup["snapshot_artifact"],
        workspace / "restored",
        private_key_file=key_path / ContextVaultKeyManager.PRIVATE_NAME,
        report_path=restore_report_path,
    )
    source_events = source.load_all_events()
    restored = ContextStorageManager.from_existing(workspace / "restored")
    if restored.load_all_events() != source_events:
        raise ContextVaultError("canary restore differs from synthetic source")
    result = {
        "schema": CANARY_SCHEMA,
        "status": "verified",
        "completed_at_ms": clock(),
        "run_id": run_id,
        "provider": (
            "google-drive-for-desktop"
            if require_google_drive
            else "local-contract-emulation"
        ),
        "provider_root": str(provider.root),
        "synthetic_only": True,
        "segment_count": backup["segment_count"],
        "snapshot_hash": backup["snapshot_hash"],
        "backup_report_hash": backup["report_hash"],
        "restore_report_hash": restore["report_hash"],
        "hash_verified": True,
        "manifest_verified": True,
        "events_equal": True,
    }
    result["report_hash"] = _document_hash(result)
    _atomic_write(
        workspace / "canary-result.json",
        _canonical(result) + b"\n",
        mode=0o400,
    )
    return result
