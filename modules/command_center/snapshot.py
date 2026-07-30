"""Composición pura del snapshot inicial oficial del Command Center."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol

from .contracts import (
    CONTRACT_V1_FINGERPRINT,
    CONTRACT_VERSION,
    EVENT_CONTRACT,
    SNAPSHOT_CONTRACT,
    validate_envelope,
    validate_snapshot,
)


@dataclass(frozen=True)
class Projection:
    topic: str
    source: str
    observed_at: int
    expires_at: int
    health: str
    freshness: str
    mode: str
    severity: str
    data: dict[str, Any]
    seq: int = 0


class ProjectionProvider(Protocol):
    topic: str
    source: str

    def read(self, user: dict[str, Any], now_ms: int) -> Projection: ...


def subject_for_user(user: dict[str, Any] | None) -> str:
    if not user:
        raise ValueError("snapshot sin usuario autenticado")
    uid = user.get("uid")
    if uid is not None:
        return f"user:{int(uid)}"
    if user.get("synthetic") is True:
        return "user:local"
    raise ValueError("sesion sin identidad estable")


def projection_envelope(projection: Projection, subject: str, received_at: int) -> dict:
    envelope = {
        "contract": EVENT_CONTRACT,
        "v": CONTRACT_VERSION,
        "topic": projection.topic,
        "kind": "snapshot",
        "subject": subject,
        "seq": projection.seq,
        "observed_at": projection.observed_at,
        "received_at": received_at,
        "expires_at": projection.expires_at,
        "severity": projection.severity,
        "source": projection.source,
        "payload": {
            "state": {
                "health": projection.health,
                "freshness": projection.freshness,
                "mode": projection.mode,
                "severity": projection.severity,
                "source": projection.source,
                "as_of": projection.observed_at,
            },
            "data": projection.data,
        },
    }
    return validate_envelope(envelope)


class SessionProjection:
    topic = "system.session"
    source = "nexux:auth"

    def read(self, user: dict[str, Any], now_ms: int) -> Projection:
        return Projection(
            topic=self.topic,
            source=self.source,
            observed_at=now_ms,
            expires_at=now_ms + 30_000,
            health="healthy",
            freshness="live",
            mode="live",
            severity="normal",
            data={
                "authenticated": True,
                "role": str(user.get("role") or "unknown"),
                "synthetic": user.get("synthetic") is True,
            },
        )


class ConfiguredModulesProjection:
    topic = "system.modules"
    source = "nexux:config"

    def __init__(self, config_loader: Callable[[], dict[str, Any]]):
        self._config_loader = config_loader

    def read(self, user: dict[str, Any], now_ms: int) -> Projection:
        config = self._config_loader()
        configured = config.get("modules") if isinstance(config, dict) else {}
        configured = configured if isinstance(configured, dict) else {}
        is_admin = user.get("role") == "admin"
        modules = []
        for config_slug, settings in sorted(configured.items()):
            settings = settings if isinstance(settings, dict) else {}
            public_slug = (
                "command-center" if config_slug == "command_center" else config_slug
            )
            if public_slug == "bot" and not is_admin:
                continue
            modules.append(
                {
                    "slug": public_slug,
                    "configured": True,
                    "enabled": settings.get("enabled", True) is True,
                    "access": "admin" if public_slug == "bot" else "authenticated",
                }
            )
        return Projection(
            topic=self.topic,
            source=self.source,
            observed_at=now_ms,
            expires_at=now_ms + 60_000,
            health="healthy",
            freshness="current",
            mode="live",
            severity="normal",
            data={"modules": modules},
        )


class SnapshotComposer:
    def __init__(
        self,
        providers: Iterable[ProjectionProvider],
        clock_ms: Callable[[], int] | None = None,
        id_factory: Callable[[], str] | None = None,
    ):
        self._providers = tuple(providers)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))

    def compose(self, user: dict[str, Any] | None) -> dict[str, Any]:
        subject = subject_for_user(user)
        generated_at = self._clock_ms()
        topics: dict[str, dict[str, Any]] = {}
        cursors: dict[str, int] = {}

        for provider in self._providers:
            if provider.topic in topics:
                raise ValueError(f"topic duplicado: {provider.topic}")
            try:
                projection = provider.read(user, generated_at)
                if projection.topic != provider.topic:
                    raise ValueError("provider devolvio otro topic")
                envelope = projection_envelope(projection, subject, generated_at)
            except Exception:  # noqa: BLE001
                projection = Projection(
                    topic=provider.topic,
                    source=provider.source,
                    observed_at=generated_at,
                    expires_at=generated_at,
                    health="failed",
                    freshness="expired",
                    mode="disabled",
                    severity="unknown",
                    data={"available": False},
                )
                envelope = projection_envelope(projection, subject, generated_at)
            topics[provider.topic] = envelope
            cursors[provider.topic] = projection.seq

        snapshot = {
            "contract": SNAPSHOT_CONTRACT,
            "v": CONTRACT_VERSION,
            "contract_fingerprint": CONTRACT_V1_FINGERPRINT,
            "snapshot_id": self._id_factory(),
            "subject": subject,
            "generated_at": generated_at,
            "topics": topics,
            "cursors": cursors,
        }
        return validate_snapshot(snapshot)
