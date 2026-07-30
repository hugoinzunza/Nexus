"""Composición pura del snapshot oficial del Command Center."""

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
    validate_source_name,
    validate_topic_name,
    validate_envelope,
    validate_snapshot,
)


class IdentityError(ValueError):
    """La sesión no permite construir una identidad estable."""


@dataclass(frozen=True)
class ActorContext:
    """Contexto mínimo entregado a providers; nunca contiene email o cookies."""

    subject: str
    uid: int | None
    role: str
    synthetic: bool


@dataclass(frozen=True)
class Projection:
    topic: str
    source: str
    observed_at: int
    stale_at: int
    expires_at: int
    health: str
    freshness: str
    mode: str
    severity: str
    availability: str
    degradation: dict[str, Any] | None
    data: dict[str, Any]
    seq: int = 0


class ProjectionProvider(Protocol):
    topic: str
    source: str
    allowed_roles: frozenset[str] | None

    def read(self, actor: ActorContext, now_ms: int) -> Projection: ...


def actor_for_user(user: dict[str, Any] | None) -> ActorContext:
    if not user:
        raise IdentityError("snapshot sin usuario autenticado")
    uid = user.get("uid")
    if uid is not None:
        try:
            numeric_uid = int(uid)
        except (TypeError, ValueError) as exc:
            raise IdentityError("uid invalido") from exc
        if numeric_uid <= 0:
            raise IdentityError("uid invalido")
        subject = f"user:{numeric_uid}"
    elif user.get("synthetic") is True:
        numeric_uid = None
        subject = "user:local"
    else:
        raise IdentityError("sesion sin identidad estable")
    return ActorContext(
        subject=subject,
        uid=numeric_uid,
        role=str(user.get("role") or "unknown"),
        synthetic=user.get("synthetic") is True,
    )


def projection_envelope(
    projection: Projection, subject: str, received_at: int
) -> dict[str, Any]:
    envelope = {
        "contract": EVENT_CONTRACT,
        "v": CONTRACT_VERSION,
        "topic": projection.topic,
        "kind": "snapshot",
        "subject": subject,
        "seq": projection.seq,
        "observed_at": projection.observed_at,
        "received_at": received_at,
        "stale_at": projection.stale_at,
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
                "availability": projection.availability,
                "degradation": projection.degradation,
            },
            "data": projection.data,
        },
    }
    return validate_envelope(envelope)


class SessionProjection:
    topic = "system.session"
    source = "nexux:auth"
    allowed_roles = None

    def read(self, actor: ActorContext, now_ms: int) -> Projection:
        return Projection(
            topic=self.topic,
            source=self.source,
            observed_at=now_ms,
            stale_at=now_ms + 15_000,
            expires_at=now_ms + 30_000,
            health="healthy",
            freshness="live",
            mode="not_applicable",
            severity="normal",
            availability="available",
            degradation=None,
            data={
                "authenticated": True,
                "role": actor.role,
                "synthetic": actor.synthetic,
            },
        )


class ConfiguredModulesProjection:
    topic = "system.modules"
    source = "nexux:config"
    allowed_roles = None

    def __init__(self, config_loader: Callable[[], dict[str, Any]]):
        self._config_loader = config_loader

    def read(self, actor: ActorContext, now_ms: int) -> Projection:
        config = self._config_loader()
        configured = config.get("modules") if isinstance(config, dict) else {}
        configured = configured if isinstance(configured, dict) else {}
        is_admin = actor.role == "admin"
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
            stale_at=now_ms + 30_000,
            expires_at=now_ms + 60_000,
            health="healthy",
            freshness="current",
            mode="not_applicable",
            severity="normal",
            availability="available",
            degradation=None,
            data={"modules": modules},
        )


class SnapshotComposer:
    def __init__(
        self,
        providers: Iterable[ProjectionProvider],
        clock_ms: Callable[[], int] | None = None,
        id_factory: Callable[[], str] | None = None,
        on_provider_error: Callable[[str, Exception], None] | None = None,
    ):
        self._providers = tuple(providers)
        seen_topics = set()
        for provider in self._providers:
            if not hasattr(provider, "allowed_roles"):
                raise ValueError(
                    f"provider {getattr(provider, 'topic', '?')} sin allowed_roles"
                )
            validate_topic_name(provider.topic)
            validate_source_name(provider.source)
            if provider.topic in seen_topics:
                raise ValueError(f"topic duplicado: {provider.topic}")
            seen_topics.add(provider.topic)
            roles = provider.allowed_roles
            if roles is not None and (
                type(roles) is not frozenset
                or not roles
                or any(not isinstance(role, str) or not role for role in roles)
            ):
                raise ValueError(f"provider {provider.topic} con allowed_roles invalido")
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._on_provider_error = on_provider_error or (lambda _topic, _exc: None)

    @staticmethod
    def _authorized(provider: ProjectionProvider, actor: ActorContext) -> bool:
        roles = provider.allowed_roles
        return roles is None or actor.role in roles

    def compose(self, user: dict[str, Any] | None) -> dict[str, Any]:
        actor = actor_for_user(user)
        generated_at = self._clock_ms()
        topics: dict[str, dict[str, Any]] = {}
        cursors: dict[str, int] = {}

        for provider in self._providers:
            if not self._authorized(provider, actor):
                continue
            try:
                projection = provider.read(actor, generated_at)
                if projection.topic != provider.topic:
                    raise ValueError("provider devolvio otro topic")
                if projection.source != provider.source:
                    raise ValueError("provider devolvio otra source")
                envelope = projection_envelope(
                    projection, actor.subject, generated_at
                )
            except Exception as exc:  # noqa: BLE001
                try:
                    self._on_provider_error(provider.topic, exc)
                except Exception:  # noqa: BLE001
                    pass
                projection = Projection(
                    topic=provider.topic,
                    source=provider.source,
                    observed_at=generated_at,
                    stale_at=generated_at,
                    expires_at=generated_at,
                    health="failed",
                    freshness="expired",
                    mode="not_applicable",
                    severity="unknown",
                    availability="unavailable",
                    degradation={
                        "category": "provider-failure",
                        "code": "provider.read-failed",
                        "retryable": True,
                        "since": generated_at,
                    },
                    data={"available": False},
                )
                envelope = projection_envelope(
                    projection, actor.subject, generated_at
                )
            topics[provider.topic] = envelope
            cursors[provider.topic] = projection.seq

        snapshot = {
            "contract": SNAPSHOT_CONTRACT,
            "v": CONTRACT_VERSION,
            "contract_fingerprint": CONTRACT_V1_FINGERPRINT,
            "snapshot_id": self._id_factory(),
            "subject": actor.subject,
            "generated_at": generated_at,
            "topics": topics,
            "cursors": cursors,
        }
        return validate_snapshot(snapshot)
