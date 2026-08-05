"""Almacenamiento segmentado, verificable y recuperable para contexto NexUX."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterable

from core.vault import seal, unseal

from .context_recorder import (
    decode_verified_events,
    load_verified_events,
)


STORAGE_SCHEMA = "nexux.context.storage.v1"
MANIFEST_SCHEMA = "nexux.context.segment-manifest.v1"
SNAPSHOT_SCHEMA = "nexux.context.storage-snapshot.v1"
VAULT_SCHEMA = "nexux.context.vault.v1"
VAULT_PAYLOAD_SCHEMA = "nexux.context.vault-payload.v1"
RECEIPT_SCHEMA = "nexux.context.backup-receipt.v1"
RESTORE_SCHEMA = "nexux.context.restore-drill.v1"
_GENESIS_HASH = "0" * 64


class ContextStorageError(RuntimeError):
    """La evidencia no puede continuar sin intervencion explicita."""


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
    descriptor = os.open(
        temporary,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        mode,
    )
    try:
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("atomic write made no progress")
            written += count
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
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class ContextStorageManager:
    """Gestiona segmentos; nunca interpreta ni modifica eventos cerrados."""

    def __init__(
        self,
        root: str | Path,
        *,
        repo_root: str | Path | None = None,
        max_segment_bytes: int = 64 * 1024 * 1024,
        max_segment_age_ms: int = 24 * 60 * 60_000,
        retention_days: int = 90,
        min_free_bytes: int = 2 * 1024 * 1024 * 1024,
        clock_ms: Callable[[], int] | None = None,
    ):
        self.root = Path(root).expanduser()
        self.repo_root = Path(repo_root).resolve() if repo_root else None
        self.max_segment_bytes = int(max_segment_bytes)
        self.max_segment_age_ms = int(max_segment_age_ms)
        self.retention_days = int(retention_days)
        self.min_free_bytes = int(min_free_bytes)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        if min(
            self.max_segment_bytes,
            self.max_segment_age_ms,
            self.retention_days,
            self.min_free_bytes,
        ) <= 0:
            raise ValueError("storage limits must be positive")

    @property
    def active_path(self) -> Path:
        return self.root / "active" / "context-current.jsonl"

    @property
    def coordination_lock_path(self) -> Path:
        return self.root / ".context-storage.lock"

    @property
    def segments_dir(self) -> Path:
        return self.root / "segments"

    @property
    def manifests_dir(self) -> Path:
        return self.root / "manifests"

    @property
    def receipts_dir(self) -> Path:
        return self.root / "backup-receipts"

    @property
    def recovery_dir(self) -> Path:
        return self.root / "recovery"

    @property
    def snapshots_dir(self) -> Path:
        return self.root / "snapshots"

    @property
    def policy_path(self) -> Path:
        return self.root / "storage-policy.json"

    def initialize(self) -> dict:
        """Crea el layout vacio; no activa ningun productor."""
        if not self.is_outside_repo():
            raise ContextStorageError("context storage must live outside the repo")
        for directory in (
            self.root,
            self.active_path.parent,
            self.segments_dir,
            self.manifests_dir,
            self.receipts_dir,
            self.recovery_dir,
            self.snapshots_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)
        expected = self._policy_document()
        if self.policy_path.exists():
            actual = json.loads(self.policy_path.read_text(encoding="utf-8"))
            if actual != expected:
                raise ContextStorageError("storage policy differs from initialized root")
        else:
            _atomic_write(self.policy_path, _canonical(expected) + b"\n")
        return self.health()

    def is_outside_repo(self) -> bool:
        if self.repo_root is None:
            return True
        try:
            self.root.resolve().relative_to(self.repo_root)
            return False
        except ValueError:
            return True

    def load_all_events(self) -> list[dict]:
        """Reconstruye la historia uniendo segmentos y activo bajo un lock."""
        with self._coordination_lock(shared=True, create=False):
            report = self._audit_unlocked(include_events=True)
        return report["events"]

    def last_event(self) -> dict | None:
        events = self.load_all_events()
        return events[-1] if events else None

    def last_closed_event(self) -> dict | None:
        with self._coordination_lock(shared=True, create=False):
            report = self._audit_unlocked(include_events=True)
        closed_count = sum(item["event_count"] for item in report["manifests"])
        return report["events"][closed_count - 1] if closed_count else None

    def audit(self) -> dict:
        if not self.root.exists():
            return self._uninitialized_report()
        with self._coordination_lock(shared=True, create=False):
            report = self._audit_unlocked(include_events=False)
        return report

    def ensure_capacity(self) -> int:
        free_bytes = self._disk_free_bytes()
        if free_bytes < self.min_free_bytes:
            raise ContextStorageError("context storage has insufficient free space")
        return free_bytes

    def health(self) -> dict:
        try:
            report = self.audit()
            status = report["status"]
            error = None
        except Exception as exc:  # noqa: BLE001
            report = self._uninitialized_report()
            status = "failed"
            error = type(exc).__name__
        manifests = report.get("manifests", [])
        initialized = self.root.exists() and self.policy_path.exists()
        backup_complete = initialized and all(
            self._valid_receipt(item["segment_id"], manifest=item) is not None
            for item in manifests
        )
        restore_verified = self._valid_restore_receipt(manifests)
        return {
            "schema": STORAGE_SCHEMA,
            "status": status,
            "initialized": initialized,
            "root": str(self.root),
            "outside_repo": self.is_outside_repo(),
            "segment_count": report.get("segment_count", 0),
            "active_event_count": report.get("active_event_count", 0),
            "last_sequence": report.get("last_sequence"),
            "free_bytes": report.get("free_bytes"),
            "minimum_free_bytes": self.min_free_bytes,
            "low_space": report.get("low_space", False),
            "backup_receipts": self._count_json(self.receipts_dir),
            "backup_complete": backup_complete,
            "restore_drill_verified": restore_verified,
            "last_error": error,
        }

    def rotate_if_needed(self, *, force: bool = False) -> dict | None:
        """Cierra el activo de forma atomica y publica su manifest inmutable."""
        self._require_initialized()
        with self._coordination_lock(shared=False, create=True):
            report = self._audit_unlocked(include_events=True)
            active_events = report["active_events"]
            if not active_events:
                return None
            size_bytes = self.active_path.stat().st_size
            age_ms = (
                active_events[-1]["captured_at_ms"]
                - active_events[0]["captured_at_ms"]
            )
            if not force and (
                size_bytes < self.max_segment_bytes
                and age_ms < self.max_segment_age_ms
            ):
                return None
            index = report["segment_count"] + 1
            segment_id = f"segment-{index:06d}"
            segment_path = self.segments_dir / f"{segment_id}.jsonl"
            manifest_path = self.manifests_dir / f"{segment_id}.json"
            if segment_path.exists() or manifest_path.exists():
                raise ContextStorageError("next segment identifier already exists")

            os.replace(self.active_path, segment_path)
            os.chmod(segment_path, 0o400)
            _fsync_directory(self.active_path.parent)
            _fsync_directory(self.segments_dir)
            previous_manifest_hash = (
                report["manifests"][-1]["manifest_hash"]
                if report["manifests"]
                else _GENESIS_HASH
            )
            manifest = {
                "schema": MANIFEST_SCHEMA,
                "segment_id": segment_id,
                "segment_index": index,
                "file": segment_path.name,
                "closed_at_ms": self._clock_ms(),
                "event_count": len(active_events),
                "first_sequence": active_events[0]["sequence"],
                "last_sequence": active_events[-1]["sequence"],
                "first_previous_hash": active_events[0]["previous_hash"],
                "first_event_hash": active_events[0]["event_hash"],
                "last_event_hash": active_events[-1]["event_hash"],
                "first_capture_ms": active_events[0]["captured_at_ms"],
                "last_capture_ms": active_events[-1]["captured_at_ms"],
                "size_bytes": segment_path.stat().st_size,
                "sha256": _sha256_file(segment_path),
                "previous_manifest_hash": previous_manifest_hash,
            }
            manifest["manifest_hash"] = self._document_hash(manifest)
            _atomic_write(manifest_path, _canonical(manifest) + b"\n", mode=0o400)
            return manifest

    def create_consistency_snapshot(self) -> Path:
        """Publica un inventario atomico de segmentos y del activo observado."""
        self._require_initialized()
        with self._coordination_lock(shared=True, create=False):
            report = self._audit_unlocked(include_events=False)
            active = None
            if self.active_path.exists():
                active = {
                    "file": self.active_path.name,
                    "size_bytes": self.active_path.stat().st_size,
                    "sha256": _sha256_file(self.active_path),
                    "event_count": report["active_event_count"],
                    "last_sequence": report["last_sequence"],
                }
            document = {
                "schema": SNAPSHOT_SCHEMA,
                "created_at_ms": self._clock_ms(),
                "storage_policy_hash": _sha256_file(self.policy_path),
                "segments": [
                    {
                        "segment_id": item["segment_id"],
                        "manifest_hash": item["manifest_hash"],
                        "sha256": item["sha256"],
                    }
                    for item in report["manifests"]
                ],
                "active": active,
            }
            document["snapshot_hash"] = self._document_hash(document)
        path = self.snapshots_dir / (
            f"snapshot-{document['created_at_ms']}.json"
        )
        _atomic_write(path, _canonical(document) + b"\n", mode=0o400)
        return path

    def backup_closed_segments(
        self,
        destination: str | Path,
        public_pem: str,
    ) -> list[dict]:
        """Cifra cada segmento cerrado y deja recibos verificables locales."""
        self._require_initialized()
        destination_path = Path(destination).expanduser()
        try:
            destination_path.resolve().relative_to(self.root.resolve())
            raise ContextStorageError(
                "encrypted backup must live outside primary storage"
            )
        except ValueError:
            pass
        destination_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(destination_path, 0o700)
        report = self.audit()
        receipts = []
        for manifest in report["manifests"]:
            existing = self._valid_receipt(
                manifest["segment_id"],
                manifest=manifest,
            )
            if existing is not None:
                receipts.append(existing)
                continue
            segment_path = self.segments_dir / manifest["file"]
            payload = {
                "schema": VAULT_PAYLOAD_SCHEMA,
                "storage_policy": json.loads(
                    self.policy_path.read_text(encoding="utf-8")
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
            vault_path = destination_path / f"{manifest['segment_id']}.vault.json"
            _atomic_write(vault_path, _canonical(vault) + b"\n")
            artifact_hash = _sha256_file(vault_path)
            receipt = {
                "schema": RECEIPT_SCHEMA,
                "created_at_ms": self._clock_ms(),
                "segment_id": manifest["segment_id"],
                "segment_sha256": manifest["sha256"],
                "manifest_hash": manifest["manifest_hash"],
                "vault_file": str(vault_path),
                "vault_sha256": artifact_hash,
            }
            receipt["receipt_hash"] = self._document_hash(receipt)
            _atomic_write(
                self.receipts_dir / f"{manifest['segment_id']}.json",
                _canonical(receipt) + b"\n",
                mode=0o400,
            )
            receipts.append(receipt)
        self._write_vault_index(destination_path, receipts)
        return receipts

    @classmethod
    def restore_vaults(
        cls,
        vault_paths: Iterable[str | Path],
        target_root: str | Path,
        private_pem: str,
        *,
        clock_ms: Callable[[], int] | None = None,
    ) -> "ContextStorageManager":
        """Restaura una cadena completa en un destino vacio y la audita."""
        target = Path(target_root).expanduser()
        if target.exists() and any(target.iterdir()):
            raise ContextStorageError("restore target must be empty")
        decoded = []
        storage_policy = None
        for raw_path in vault_paths:
            vault_path = Path(raw_path)
            vault = json.loads(vault_path.read_text(encoding="utf-8"))
            if vault.get("schema") != VAULT_SCHEMA:
                raise ContextStorageError("invalid vault schema")
            plaintext = unseal(vault["envelope"], private_pem)
            if _sha256_bytes(plaintext) != vault.get("payload_sha256"):
                raise ContextStorageError("vault plaintext hash mismatch")
            payload = json.loads(plaintext)
            if payload.get("schema") != VAULT_PAYLOAD_SCHEMA:
                raise ContextStorageError("invalid vault payload schema")
            if storage_policy is None:
                storage_policy = payload.get("storage_policy")
            elif payload.get("storage_policy") != storage_policy:
                raise ContextStorageError("vault storage policies differ")
            manifest = payload["manifest"]
            if manifest.get("manifest_hash") != vault.get("manifest_hash"):
                raise ContextStorageError("vault manifest binding mismatch")
            segment = base64.b64decode(payload["segment_b64"], validate=True)
            if _sha256_bytes(segment) != manifest.get("sha256"):
                raise ContextStorageError("restored segment hash mismatch")
            decoded.append((manifest, segment, _sha256_file(vault_path)))
        if not decoded or not isinstance(storage_policy, dict):
            raise ContextStorageError("restore requires at least one complete vault")
        decoded.sort(key=lambda item: item[0]["segment_index"])
        manager = cls(
            target,
            max_segment_bytes=storage_policy["max_segment_bytes"],
            max_segment_age_ms=storage_policy["max_segment_age_ms"],
            retention_days=storage_policy["retention_days"],
            min_free_bytes=storage_policy["minimum_free_bytes"],
            clock_ms=clock_ms,
        )
        manager.initialize()
        for manifest, segment, _artifact_hash in decoded:
            segment_path = manager.segments_dir / manifest["file"]
            manifest_path = manager.manifests_dir / (
                f"{manifest['segment_id']}.json"
            )
            _atomic_write(segment_path, segment, mode=0o400)
            _atomic_write(manifest_path, _canonical(manifest) + b"\n", mode=0o400)
        manager.audit()
        receipt = {
            "schema": RESTORE_SCHEMA,
            "scope": "restored_copy",
            "verified_at_ms": manager._clock_ms(),
            "segment_count": len(decoded),
            "manifest_hashes": [item[0]["manifest_hash"] for item in decoded],
            "vault_sha256": [item[2] for item in decoded],
        }
        receipt["receipt_hash"] = manager._document_hash(receipt)
        _atomic_write(
            manager.recovery_dir / "restore-drill-latest.json",
            _canonical(receipt) + b"\n",
            mode=0o400,
        )
        return manager

    def verify_restore_drill(self, restored_root: str | Path) -> dict:
        """Compara manifests restaurados y registra la prueba en el origen."""
        source = self.audit()
        restored_manager = self.from_existing(restored_root)
        restored = restored_manager.audit()
        source_hashes = [item["manifest_hash"] for item in source["manifests"]]
        restored_hashes = [item["manifest_hash"] for item in restored["manifests"]]
        if not source_hashes or source_hashes != restored_hashes:
            raise ContextStorageError("restore drill does not match source manifests")
        receipt = {
            "schema": RESTORE_SCHEMA,
            "scope": "primary_history",
            "verified_at_ms": self._clock_ms(),
            "segment_count": len(source_hashes),
            "manifest_hashes": source_hashes,
        }
        receipt["receipt_hash"] = self._document_hash(receipt)
        _atomic_write(
            self.recovery_dir / "restore-drill-latest.json",
            _canonical(receipt) + b"\n",
            mode=0o400,
        )
        return receipt

    def record_isolated_restore_drill(
        self,
        drill_source_root: str | Path,
        drill_restored_root: str | Path,
    ) -> dict:
        """Registra un ensayo externo sin introducir canarios en el primario."""
        self._require_initialized()
        if self.audit()["segment_count"] != 0:
            raise ContextStorageError(
                "isolated drill is only valid before primary history exists"
            )
        source_root = Path(drill_source_root).expanduser().resolve()
        restored_root = Path(drill_restored_root).expanduser().resolve()
        if source_root == restored_root or self.root.resolve() in (
            source_root,
            restored_root,
        ):
            raise ContextStorageError("isolated drill roots must be distinct")
        source = self.from_existing(source_root).audit()
        restored = self.from_existing(restored_root).audit()
        source_hashes = [item["manifest_hash"] for item in source["manifests"]]
        restored_hashes = [item["manifest_hash"] for item in restored["manifests"]]
        if not source_hashes or source_hashes != restored_hashes:
            raise ContextStorageError("isolated restore drill is not equivalent")
        receipt = {
            "schema": RESTORE_SCHEMA,
            "scope": "isolated_pre_activation",
            "verified_at_ms": self._clock_ms(),
            "segment_count": len(source_hashes),
            "source_root": str(source_root),
            "restored_root": str(restored_root),
            "source_manifest_hashes": source_hashes,
            "restored_manifest_hashes": restored_hashes,
        }
        receipt["receipt_hash"] = self._document_hash(receipt)
        _atomic_write(
            self.recovery_dir / "restore-drill-latest.json",
            _canonical(receipt) + b"\n",
            mode=0o400,
        )
        return receipt

    def retention_candidates(self, *, now_ms: int | None = None) -> list[dict]:
        """Informa candidatos; nunca elimina evidencia automaticamente."""
        report = self.audit()
        cutoff = (now_ms or self._clock_ms()) - self.retention_days * 86_400_000
        candidates = []
        for manifest in report["manifests"]:
            if manifest["closed_at_ms"] > cutoff:
                continue
            receipt = self._valid_receipt(
                manifest["segment_id"],
                manifest=manifest,
            )
            if receipt is not None:
                candidates.append(
                    {
                        "segment_id": manifest["segment_id"],
                        "closed_at_ms": manifest["closed_at_ms"],
                        "backup_receipt_hash": receipt["receipt_hash"],
                        "action": "eligible_for_manual_review",
                    }
                )
        return candidates

    def recover_incomplete_tail(self) -> dict | None:
        """Aisla bytes incompletos y trunca solo mediante reparacion explicita."""
        self._require_initialized()
        if not self.active_path.exists():
            return None
        with self._coordination_lock(shared=False, create=True):
            payload = self.active_path.read_bytes()
            if not payload or payload.endswith(b"\n"):
                return None
            newline = payload.rfind(b"\n")
            valid_payload = payload[: newline + 1] if newline >= 0 else b""
            partial = payload[newline + 1 :]
            previous = self._last_closed_event_unlocked()
            decode_verified_events(valid_payload, previous_event=previous)
            stamp = self._clock_ms()
            quarantine = self.recovery_dir / f"partial-{stamp}.bin"
            _atomic_write(quarantine, partial, mode=0o400)
            descriptor = os.open(self.active_path, os.O_RDWR)
            try:
                os.ftruncate(descriptor, len(valid_payload))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            receipt = {
                "schema": "nexux.context.tail-recovery.v1",
                "recovered_at_ms": stamp,
                "removed_bytes": len(partial),
                "removed_sha256": _sha256_bytes(partial),
                "quarantine_file": quarantine.name,
            }
            receipt["receipt_hash"] = self._document_hash(receipt)
            _atomic_write(
                self.recovery_dir / f"partial-{stamp}.json",
                _canonical(receipt) + b"\n",
                mode=0o400,
            )
            return receipt

    def _audit_unlocked(self, *, include_events: bool) -> dict:
        self._validate_policy()
        manifests = []
        events = []
        previous_event = None
        previous_manifest_hash = _GENESIS_HASH
        manifest_paths = sorted(self.manifests_dir.glob("segment-*.json"))
        expected_segment_files = set()
        for expected_index, manifest_path in enumerate(manifest_paths, start=1):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self._validate_manifest(
                manifest,
                expected_index=expected_index,
                previous_manifest_hash=previous_manifest_hash,
            )
            segment_path = self.segments_dir / manifest["file"]
            expected_segment_files.add(segment_path.name)
            if not segment_path.is_file():
                raise ContextStorageError("manifest references a missing segment")
            if segment_path.stat().st_size != manifest["size_bytes"]:
                raise ContextStorageError("segment size differs from manifest")
            if _sha256_file(segment_path) != manifest["sha256"]:
                raise ContextStorageError("segment hash differs from manifest")
            segment_events = load_verified_events(
                segment_path,
                previous_event=previous_event,
            )
            self._validate_segment_events(manifest, segment_events)
            previous_event = segment_events[-1]
            if include_events:
                events.extend(segment_events)
            manifests.append(manifest)
            previous_manifest_hash = manifest["manifest_hash"]
        actual_segment_files = {
            path.name for path in self.segments_dir.glob("segment-*.jsonl")
        }
        if actual_segment_files != expected_segment_files:
            raise ContextStorageError("orphan or unmanifested segment detected")

        active_events = []
        if self.active_path.exists() and self.active_path.stat().st_size:
            active_events = load_verified_events(
                self.active_path,
                previous_event=previous_event,
            )
            if include_events:
                events.extend(active_events)
            previous_event = active_events[-1]
        free_bytes = self._disk_free_bytes()
        return {
            "schema": STORAGE_SCHEMA,
            "status": "low_space" if free_bytes < self.min_free_bytes else "ready",
            "segment_count": len(manifests),
            "active_event_count": len(active_events),
            "last_sequence": previous_event["sequence"] if previous_event else None,
            "free_bytes": free_bytes,
            "low_space": free_bytes < self.min_free_bytes,
            "manifests": manifests,
            "active_events": active_events,
            "events": events,
        }

    def _last_closed_event_unlocked(self) -> dict | None:
        previous = None
        for manifest_path in sorted(self.manifests_dir.glob("segment-*.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            events = load_verified_events(
                self.segments_dir / manifest["file"],
                previous_event=previous,
            )
            previous = events[-1]
        return previous

    def _validate_policy(self) -> None:
        if not self.policy_path.is_file():
            raise ContextStorageError("storage policy is missing")
        policy = json.loads(self.policy_path.read_text(encoding="utf-8"))
        if policy != self._policy_document():
            raise ContextStorageError("storage policy mismatch")

    def _policy_document(self) -> dict:
        return {
            "schema": STORAGE_SCHEMA,
            "segment_format": "jsonl",
            "max_segment_bytes": self.max_segment_bytes,
            "max_segment_age_ms": self.max_segment_age_ms,
            "retention_days": self.retention_days,
            "minimum_free_bytes": self.min_free_bytes,
            "retention_action": "manual_review_only",
        }

    def _validate_manifest(
        self,
        manifest: dict,
        *,
        expected_index: int,
        previous_manifest_hash: str,
    ) -> None:
        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise ContextStorageError("invalid segment manifest schema")
        if manifest.get("segment_index") != expected_index:
            raise ContextStorageError("segment manifest index is not continuous")
        if manifest.get("segment_id") != f"segment-{expected_index:06d}":
            raise ContextStorageError("segment id does not match its index")
        if manifest.get("previous_manifest_hash") != previous_manifest_hash:
            raise ContextStorageError("segment manifest chain is broken")
        if manifest.get("manifest_hash") != self._document_hash(manifest):
            raise ContextStorageError("segment manifest hash is invalid")

    @staticmethod
    def _validate_segment_events(manifest: dict, events: list[dict]) -> None:
        if not events or len(events) != manifest["event_count"]:
            raise ContextStorageError("segment event count differs from manifest")
        checks = (
            (events[0]["sequence"], manifest["first_sequence"]),
            (events[-1]["sequence"], manifest["last_sequence"]),
            (events[0]["previous_hash"], manifest["first_previous_hash"]),
            (events[0]["event_hash"], manifest["first_event_hash"]),
            (events[-1]["event_hash"], manifest["last_event_hash"]),
            (events[0]["captured_at_ms"], manifest["first_capture_ms"]),
            (events[-1]["captured_at_ms"], manifest["last_capture_ms"]),
        )
        if any(actual != expected for actual, expected in checks):
            raise ContextStorageError("segment boundaries differ from manifest")

    def _valid_receipt(
        self,
        segment_id: str,
        *,
        manifest: dict | None = None,
    ) -> dict | None:
        path = self.receipts_dir / f"{segment_id}.json"
        if not path.is_file():
            return None
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            if receipt.get("schema") != RECEIPT_SCHEMA:
                return None
            if receipt.get("segment_id") != segment_id:
                return None
            if receipt.get("receipt_hash") != self._document_hash(receipt):
                return None
            if manifest is not None and (
                receipt.get("segment_sha256") != manifest.get("sha256")
                or receipt.get("manifest_hash") != manifest.get("manifest_hash")
            ):
                return None
            vault_path = Path(receipt["vault_file"])
            if not vault_path.is_file():
                return None
            if _sha256_file(vault_path) != receipt["vault_sha256"]:
                return None
            return receipt
        except Exception:  # noqa: BLE001
            return None

    def _valid_restore_receipt(self, manifests: list[dict]) -> bool:
        path = self.recovery_dir / "restore-drill-latest.json"
        if not path.is_file():
            return False
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            if receipt.get("schema") != RESTORE_SCHEMA:
                return False
            if receipt.get("receipt_hash") != self._document_hash(receipt):
                return False
            expected = [item["manifest_hash"] for item in manifests]
            if expected:
                return (
                    receipt.get("scope") == "primary_history"
                    and receipt.get("manifest_hashes") == expected
                )
            if (
                receipt.get("scope") != "isolated_pre_activation"
                or receipt.get("segment_count", 0) <= 0
            ):
                return False
            source = self.from_existing(receipt["source_root"]).audit()
            restored = self.from_existing(receipt["restored_root"]).audit()
            source_hashes = [
                item["manifest_hash"] for item in source["manifests"]
            ]
            restored_hashes = [
                item["manifest_hash"] for item in restored["manifests"]
            ]
            return (
                source_hashes
                and source_hashes == restored_hashes
                and source_hashes == receipt.get("source_manifest_hashes")
                and restored_hashes == receipt.get("restored_manifest_hashes")
            )
        except Exception:  # noqa: BLE001
            return False

    def _write_vault_index(self, destination: Path, receipts: list[dict]) -> None:
        index = {
            "schema": "nexux.context.vault-index.v1",
            "updated_at_ms": self._clock_ms(),
            "artifacts": [
                {
                    "segment_id": item["segment_id"],
                    "manifest_hash": item["manifest_hash"],
                    "vault_sha256": item["vault_sha256"],
                    "file": Path(item["vault_file"]).name,
                }
                for item in receipts
            ],
        }
        index["index_hash"] = self._document_hash(index)
        _atomic_write(destination / "vault-index.json", _canonical(index) + b"\n")

    @staticmethod
    def _document_hash(document: dict) -> str:
        unsigned = dict(document)
        for field in (
            "manifest_hash",
            "snapshot_hash",
            "receipt_hash",
            "index_hash",
        ):
            unsigned.pop(field, None)
        return _sha256_bytes(_canonical(unsigned))

    def _require_initialized(self) -> None:
        if not self.root.exists() or not self.policy_path.is_file():
            raise ContextStorageError("context storage is not initialized")

    def _disk_free_bytes(self) -> int:
        probe = self.root if self.root.exists() else self.root.parent
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        return shutil.disk_usage(probe).free

    def _uninitialized_report(self) -> dict:
        free_bytes = self._disk_free_bytes()
        return {
            "schema": STORAGE_SCHEMA,
            "status": "uninitialized",
            "segment_count": 0,
            "active_event_count": 0,
            "last_sequence": None,
            "free_bytes": free_bytes,
            "low_space": free_bytes < self.min_free_bytes,
            "manifests": [],
        }

    @contextmanager
    def _coordination_lock(self, *, shared: bool, create: bool):
        if not self.root.exists() and not create:
            yield None
            return
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(
            self.coordination_lock_path,
            os.O_CREAT | os.O_RDWR,
            0o600,
        )
        try:
            try:
                import fcntl

                operation = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
                fcntl.flock(descriptor, operation)
            except ImportError:
                pass
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _count_json(path: Path) -> int:
        return len(list(path.glob("*.json"))) if path.is_dir() else 0

    @classmethod
    def from_existing(
        cls,
        root: str | Path,
        *,
        repo_root: str | Path | None = None,
    ) -> "ContextStorageManager":
        root_path = Path(root).expanduser()
        policy_path = root_path / "storage-policy.json"
        if not policy_path.is_file():
            raise ContextStorageError("restored storage policy is missing")
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        if policy.get("schema") != STORAGE_SCHEMA:
            raise ContextStorageError("restored storage policy is invalid")
        return cls(
            root_path,
            repo_root=repo_root,
            max_segment_bytes=policy["max_segment_bytes"],
            max_segment_age_ms=policy["max_segment_age_ms"],
            retention_days=policy["retention_days"],
            min_free_bytes=policy["minimum_free_bytes"],
        )
