"""Registro causal append-only para snapshots de contexto de mercado."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Callable


SCHEMA = "nexux.context.market.v1"
_GENESIS_HASH = "0" * 64
_MAX_CAPTURE_LAG_MS = 2 * 60_000
_CLOCK_TOLERANCE_MS = 30_000


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class ContextRecorderIntegrityError(RuntimeError):
    """El log no puede continuar sin romper su cadena causal."""


class MarketContextRecorder:
    """Persiste observaciones nuevas sin reconstruir historia previa."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock_ms: Callable[[], int] | None = None,
        strict_existing: bool = True,
    ):
        self.path = Path(path)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._lock = threading.Lock()
        self._last_event: dict | None = None
        self._status = "idle"
        self._last_error: str | None = None
        self._writes = 0
        self._duplicates = 0
        self._rejected = 0
        self._blocked = False
        try:
            self._load_existing()
        except ContextRecorderIntegrityError:
            self._blocked = True
            if strict_existing:
                raise

    def record(self, snapshot: dict) -> bool:
        """Agrega una observacion nueva; devuelve False si ya fue registrada."""
        captured_at_ms = self._clock_ms()
        try:
            normalized = self._normalize(snapshot, captured_at_ms)
            fingerprint = _digest(normalized)
        except (TypeError, ValueError):
            with self._lock:
                self._status = "failed"
                self._last_error = "ValueError"
                self._rejected += 1
            raise

        with self._lock:
            if self._blocked:
                raise ContextRecorderIntegrityError(
                    "context log is blocked after an integrity failure"
                )
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(
                    self.path,
                    os.O_APPEND | os.O_CREAT | os.O_RDWR,
                    0o600,
                )
                try:
                    self._lock_file(descriptor)
                    disk_last = self._read_last_event(descriptor)
                    if disk_last is not None:
                        self._validate_link(disk_last)
                        self._last_event = disk_last
                    if (
                        self._last_event
                        and self._last_event["snapshot_fingerprint"] == fingerprint
                    ):
                        self._duplicates += 1
                        self._status = "ready"
                        self._last_error = None
                        return False

                    sequence = (
                        int(self._last_event["sequence"]) + 1
                        if self._last_event
                        else 1
                    )
                    event = {
                        "schema": SCHEMA,
                        "sequence": sequence,
                        "captured_at_ms": captured_at_ms,
                        "previous_hash": (
                            self._last_event["event_hash"]
                            if self._last_event
                            else _GENESIS_HASH
                        ),
                        "snapshot_fingerprint": fingerprint,
                        "snapshot": normalized,
                    }
                    event["event_hash"] = _digest(event)
                    os.write(descriptor, _canonical(event) + b"\n")
                    os.fsync(descriptor)
                    self._last_event = event
                    self._writes += 1
                    self._status = "ready"
                    self._last_error = None
                    return True
                finally:
                    os.close(descriptor)
            except Exception as exc:
                self._status = "failed"
                self._last_error = type(exc).__name__
                if isinstance(exc, (ValueError, ContextRecorderIntegrityError)):
                    self._rejected += 1
                raise

    def stats(self) -> dict:
        with self._lock:
            return {
                "status": self._status,
                "schema": SCHEMA,
                "file": self.path.name,
                "sequence": (
                    int(self._last_event["sequence"]) if self._last_event else 0
                ),
                "last_capture_ms": (
                    int(self._last_event["captured_at_ms"])
                    if self._last_event
                    else None
                ),
                "writes": self._writes,
                "duplicates": self._duplicates,
                "rejected": self._rejected,
                "last_error": self._last_error,
            }

    def _normalize(self, snapshot: dict, captured_at_ms: int) -> dict:
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot must be an object")
        generated_at_ms = snapshot.get("generated_at_ms")
        if not isinstance(generated_at_ms, int):
            raise ValueError("generated_at_ms must be an integer")
        if generated_at_ms > captured_at_ms + _CLOCK_TOLERANCE_MS:
            raise ValueError("snapshot timestamp is in the future")
        if generated_at_ms < captured_at_ms - _MAX_CAPTURE_LAG_MS:
            raise ValueError("historical snapshots cannot enter the forward log")

        assets = []
        for source in snapshot.get("assets", []):
            if not isinstance(source, dict):
                raise ValueError("asset must be an object")
            observed_at_ms = source.get("observed_at_ms")
            if (
                observed_at_ms is not None
                and (
                    not isinstance(observed_at_ms, int)
                    or observed_at_ms > captured_at_ms + _CLOCK_TOLERANCE_MS
                )
            ):
                raise ValueError("asset timestamp is invalid")
            assets.append(
                {
                    "id": str(source.get("id") or ""),
                    "price": self._number_or_none(source.get("price")),
                    "change_pct": self._number_or_none(
                        source.get("change_pct")
                    ),
                    "observed_at_ms": observed_at_ms,
                    "freshness": str(source.get("freshness") or "unknown"),
                    "source": source.get("source"),
                    "kind": str(source.get("kind") or "unknown"),
                }
            )
        errors = [
            {
                "provider": str(error.get("provider") or "unknown"),
                "code": str(error.get("code") or "unknown"),
            }
            for error in snapshot.get("provider_errors", [])
            if isinstance(error, dict)
        ]
        return {
            "generated_at_ms": generated_at_ms,
            "assets": assets,
            "provider_errors": errors,
            "quality": {
                "asset_count": len(assets),
                "priced_asset_count": sum(
                    asset["price"] is not None for asset in assets
                ),
                "provider_error_count": len(errors),
            },
            "provenance": "command-center.market-ribbon.forward",
        }

    def _load_existing(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        previous = None
        try:
            with self.path.open("r", encoding="utf-8") as source:
                for line_number, line in enumerate(source, start=1):
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    self._validate_event(event, previous, line_number)
                    previous = event
            self._last_event = previous
            self._status = "ready"
        except Exception as exc:
            self._status = "failed"
            self._last_error = type(exc).__name__
            raise ContextRecorderIntegrityError(
                "existing context log failed validation"
            ) from exc

    @staticmethod
    def _number_or_none(value):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("market value must be numeric or null")
        if not math.isfinite(value):
            raise ValueError("market value must be finite")
        return value

    def _validate_event(
        self,
        event: dict,
        previous: dict | None,
        line_number: int,
    ) -> None:
        if not isinstance(event, dict) or event.get("schema") != SCHEMA:
            raise ContextRecorderIntegrityError(f"invalid schema at line {line_number}")
        expected_sequence = int(previous["sequence"]) + 1 if previous else 1
        expected_previous = previous["event_hash"] if previous else _GENESIS_HASH
        if event.get("sequence") != expected_sequence:
            raise ContextRecorderIntegrityError(f"invalid sequence at line {line_number}")
        if event.get("previous_hash") != expected_previous:
            raise ContextRecorderIntegrityError(f"invalid link at line {line_number}")
        unsigned = dict(event)
        event_hash = unsigned.pop("event_hash", None)
        if event_hash != _digest(unsigned):
            raise ContextRecorderIntegrityError(f"invalid hash at line {line_number}")

    def _validate_link(self, event: dict) -> None:
        if self._last_event and event["sequence"] < self._last_event["sequence"]:
            raise ContextRecorderIntegrityError("context log sequence regressed")
        unsigned = dict(event)
        event_hash = unsigned.pop("event_hash", None)
        if event_hash != _digest(unsigned):
            raise ContextRecorderIntegrityError("last event hash is invalid")

    @staticmethod
    def _read_last_event(descriptor: int) -> dict | None:
        size = os.lseek(descriptor, 0, os.SEEK_END)
        if size == 0:
            return None
        read_size = min(size, 256 * 1024)
        os.lseek(descriptor, size - read_size, os.SEEK_SET)
        tail = os.read(descriptor, read_size).decode("utf-8")
        lines = [line for line in tail.splitlines() if line.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])

    @staticmethod
    def _lock_file(descriptor: int) -> None:
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except ImportError:
            return
