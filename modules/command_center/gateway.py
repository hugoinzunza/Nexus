"""Gateway WebSocket autenticado del NEXUX Command Center."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit

from .contracts import (
    CONTRACT_V1_FINGERPRINT,
    CONTRACT_VERSION,
    error_document,
    validate_snapshot,
)
from .event_bus import (
    EventBusError,
    EventBroker,
    EventSubscription,
    ResyncRequired,
)
from .snapshot import IdentityError, SnapshotComposer, actor_for_user

GATEWAY_VERSION = 1


class WebSocketPeer(Protocol):
    headers: Mapping[str, str]
    url: Any

    async def accept(self, subprotocol: str | None = None) -> None: ...

    async def receive(self) -> dict[str, Any]: ...

    async def send_json(self, data: Any, mode: str = "text") -> None: ...

    async def close(self, code: int = 1000, reason: str | None = None) -> None: ...


class GatewayProtocolError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class PeerDisconnected(Exception):
    pass


class GatewaySendTimeout(TimeoutError):
    pass


@dataclass(frozen=True)
class GatewayLimits:
    max_connections: int = 64
    max_connections_per_subject: int = 4
    max_message_bytes: int = 8_192
    max_messages_per_minute: int = 120
    subscribe_timeout_seconds: float = 5.0
    send_timeout_seconds: float = 5.0
    heartbeat_interval_seconds: float = 15.0
    heartbeat_timeout_seconds: float = 45.0

    def __post_init__(self) -> None:
        integer_values = (
            self.max_connections,
            self.max_connections_per_subject,
            self.max_message_bytes,
            self.max_messages_per_minute,
        )
        if any(type(value) is not int or value <= 0 for value in integer_values):
            raise ValueError("los limites enteros del Gateway deben ser positivos")
        time_values = (
            self.subscribe_timeout_seconds,
            self.send_timeout_seconds,
            self.heartbeat_interval_seconds,
            self.heartbeat_timeout_seconds,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value <= 0
            for value in time_values
        ):
            raise ValueError("los tiempos del Gateway deben ser positivos")
        if self.heartbeat_timeout_seconds <= self.heartbeat_interval_seconds:
            raise ValueError("heartbeat_timeout debe superar heartbeat_interval")


def _canonical_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password or parsed.path not in {"", "/"}:
        return None
    if parsed.query or parsed.fragment:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    default = 443 if parsed.scheme == "https" else 80
    host = parsed.hostname.lower()
    return (
        f"{parsed.scheme}://{host}"
        if port in {None, default}
        else f"{parsed.scheme}://{host}:{port}"
    )


def _request_origin(peer: WebSocketPeer) -> str | None:
    host = (peer.headers.get("host") or "").strip()
    if not host or "," in host or "/" in host:
        return None
    forwarded_proto = (peer.headers.get("x-forwarded-proto") or "").strip()
    if "," in forwarded_proto:
        return None
    if forwarded_proto:
        scheme = forwarded_proto
    else:
        scheme = "https" if getattr(peer.url, "scheme", "") == "wss" else "http"
    return _canonical_origin(f"{scheme}://{host}")


class CommandCenterGateway:
    def __init__(
        self,
        event_bus: EventBroker,
        composer: SnapshotComposer,
        *,
        limits: GatewayLimits | None = None,
        clock_ms=None,
        monotonic=None,
        allowed_origins: set[str] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        self._bus = event_bus
        self._composer = composer
        self.limits = limits or GatewayLimits()
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._monotonic = monotonic or time.monotonic
        configured = allowed_origins
        if configured is None:
            configured = {
                item.strip()
                for item in os.environ.get(
                    "NEXUS_ALLOWED_WS_ORIGINS", ""
                ).split(",")
                if item.strip()
            }
        self._allowed_origins = {
            canonical
            for value in configured
            if (canonical := _canonical_origin(value)) is not None
        }
        self._on_error = on_error or (lambda _code: None)
        self._counter_lock: asyncio.Lock | None = None
        self._active = 0
        self._active_by_subject: dict[str, int] = {}
        self._accepted = 0
        self._closed = 0
        self._rejected_origin = 0
        self._rejected_auth = 0
        self._rejected_limit = 0
        self._protocol_errors = 0
        self._heartbeats = 0
        self._resyncs = 0
        self._snapshots_sent = 0
        self._envelopes_sent = 0
        self._last_source_lag_ms: int | None = None
        self._max_source_lag_ms: int | None = None

    def stats(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "gateway_v": GATEWAY_VERSION,
            "active_connections": self._active,
            "accepted": self._accepted,
            "closed": self._closed,
            "rejected_origin": self._rejected_origin,
            "rejected_auth": self._rejected_auth,
            "rejected_limit": self._rejected_limit,
            "protocol_errors": self._protocol_errors,
            "heartbeats": self._heartbeats,
            "resyncs": self._resyncs,
            "snapshots_sent": self._snapshots_sent,
            "envelopes_sent": self._envelopes_sent,
            "last_source_lag_ms": self._last_source_lag_ms,
            "max_source_lag_ms": self._max_source_lag_ms,
        }

    def _origin_allowed(self, peer: WebSocketPeer) -> bool:
        origin = _canonical_origin((peer.headers.get("origin") or "").strip())
        if origin is None:
            return False
        expected = _request_origin(peer)
        return origin == expected or origin in self._allowed_origins

    def _async_counter_lock(self) -> asyncio.Lock:
        if self._counter_lock is None:
            self._counter_lock = asyncio.Lock()
        return self._counter_lock

    async def _reserve_global_slot(self) -> bool:
        async with self._async_counter_lock():
            if self._active >= self.limits.max_connections:
                return False
            self._active += 1
            return True

    async def _reserve_subject(self, subject: str) -> bool:
        async with self._async_counter_lock():
            current = self._active_by_subject.get(subject, 0)
            if current >= self.limits.max_connections_per_subject:
                return False
            self._active_by_subject[subject] = current + 1
            self._accepted += 1
            return True

    async def _release_connection(
        self, subject: str | None, *, accepted: bool
    ) -> None:
        async with self._async_counter_lock():
            self._active -= 1
            if accepted and subject is not None:
                remaining = self._active_by_subject.get(subject, 1) - 1
                if remaining > 0:
                    self._active_by_subject[subject] = remaining
                else:
                    self._active_by_subject.pop(subject, None)
                self._closed += 1

    async def _load_user(self, loader: Callable[[], dict | None]) -> dict | None:
        return await asyncio.to_thread(loader)

    async def _close(self, peer: WebSocketPeer, code: int, reason: str) -> None:
        try:
            await asyncio.wait_for(
                peer.close(code=code, reason=reason[:120]),
                timeout=self.limits.send_timeout_seconds,
            )
        except Exception:  # noqa: BLE001
            pass

    async def _send_json(self, peer: WebSocketPeer, payload: Any) -> None:
        try:
            await asyncio.wait_for(
                peer.send_json(payload),
                timeout=self.limits.send_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise GatewaySendTimeout from exc

    async def _send_error(
        self,
        peer: WebSocketPeer,
        code: str,
        message: str,
        status: int,
        *,
        retryable: bool = False,
    ) -> None:
        try:
            await self._send_json(
                peer,
                error_document(
                    code,
                    message,
                    status,
                    retryable=retryable,
                )
            )
        except Exception:  # noqa: BLE001
            pass

    async def _receive_control(
        self,
        peer: WebSocketPeer,
        message_times: deque[float],
    ) -> dict[str, Any]:
        message = await peer.receive()
        if message.get("type") == "websocket.disconnect":
            raise PeerDisconnected
        if message.get("type") != "websocket.receive" or "text" not in message:
            raise GatewayProtocolError(
                "gateway.binary-unsupported",
                "El Gateway acepta controles JSON de texto.",
            )
        raw = message.get("text")
        if not isinstance(raw, str):
            raise GatewayProtocolError(
                "gateway.protocol-invalid",
                "El control WebSocket no es texto valido.",
            )
        if len(raw.encode("utf-8")) > self.limits.max_message_bytes:
            raise GatewayProtocolError(
                "gateway.message-too-large",
                "El control WebSocket excede el limite.",
                413,
            )
        now = self._monotonic()
        while message_times and now - message_times[0] >= 60:
            message_times.popleft()
        if len(message_times) >= self.limits.max_messages_per_minute:
            raise GatewayProtocolError(
                "gateway.rate-limit",
                "Demasiados controles WebSocket.",
                429,
            )
        message_times.append(now)
        try:
            control = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise GatewayProtocolError(
                "gateway.json-invalid",
                "El control WebSocket no contiene JSON valido.",
            ) from exc
        if not isinstance(control, dict) or control.get("gateway_v") != GATEWAY_VERSION:
            raise GatewayProtocolError(
                "gateway.protocol-invalid",
                "Version de control WebSocket no soportada.",
            )
        return control

    def _topics_from_control(
        self,
        control: Mapping[str, Any],
        allowed_topics: set[str],
    ) -> frozenset[str]:
        if control.get("op") != "subscribe":
            raise GatewayProtocolError(
                "gateway.subscribe-required",
                "La primera operacion debe ser subscribe.",
            )
        if control.get("contract_v") != CONTRACT_VERSION or control.get(
            "fingerprint"
        ) != CONTRACT_V1_FINGERPRINT:
            raise GatewayProtocolError(
                "gateway.contract-mismatch",
                "El cliente no soporta el Wire ABI activo.",
                409,
            )
        topics = control.get("topics")
        if (
            not isinstance(topics, list)
            or not topics
            or any(not isinstance(topic, str) for topic in topics)
        ):
            raise GatewayProtocolError(
                "gateway.topics-invalid",
                "La suscripcion exige una lista no vacia de topics.",
            )
        topic_set = frozenset(topics)
        if len(topic_set) != len(topics):
            raise GatewayProtocolError(
                "gateway.topics-invalid",
                "La suscripcion contiene topics duplicados.",
            )
        if len(topic_set) > self._bus.limits.max_topics_per_subscription:
            raise GatewayProtocolError(
                "gateway.topics-limit",
                "La suscripcion excede el limite de topics.",
                413,
            )
        if not topic_set.issubset(allowed_topics):
            raise GatewayProtocolError(
                "gateway.topic-forbidden",
                "La sesion no autoriza uno o mas topics.",
                403,
            )
        return topic_set

    async def _authorization_snapshot(self, user: dict) -> dict[str, Any]:
        snapshot = await asyncio.to_thread(self._composer.compose, user)
        return validate_snapshot(snapshot)

    async def _ensure_seeded(
        self,
        snapshot: Mapping[str, Any],
        topics: frozenset[str],
    ) -> None:
        subject = snapshot["subject"]
        existing = await self._bus.checkpoint(subject, topics)
        missing = topics.difference(existing["topics"])
        if not missing:
            return
        partial = {
            **snapshot,
            "topics": {
                topic: snapshot["topics"][topic]
                for topic in missing
            },
            "cursors": {
                topic: snapshot["cursors"][topic]
                for topic in missing
            },
        }
        try:
            await self._bus.seed_snapshot(validate_snapshot(partial))
        except EventBusError:
            # Otra conexion pudo sembrar los mismos streams entre checkpoint y seed.
            current = await self._bus.checkpoint(subject, missing)
            if set(current["topics"]) != set(missing):
                raise

    async def _subscribe(
        self,
        user: dict,
        topics: frozenset[str],
        snapshot: Mapping[str, Any],
    ) -> tuple[EventSubscription, dict[str, Any]]:
        subject = snapshot["subject"]
        await self._ensure_seeded(snapshot, topics)
        subscription = await self._bus.subscribe(subject, topics)
        checkpoint = await self._bus.checkpoint(subject, topics)
        return subscription, checkpoint

    async def _send_snapshot(
        self, peer: WebSocketPeer, snapshot: Mapping[str, Any]
    ) -> None:
        await self._send_json(peer, snapshot)
        self._snapshots_sent += 1

    async def _send_envelope(
        self, peer: WebSocketPeer, envelope: Mapping[str, Any]
    ) -> None:
        await self._send_json(peer, envelope)
        lag = envelope["received_at"] - envelope["observed_at"]
        self._last_source_lag_ms = lag
        self._max_source_lag_ms = (
            lag
            if self._max_source_lag_ms is None
            else max(self._max_source_lag_ms, lag)
        )
        self._envelopes_sent += 1

    async def _refresh_identity(
        self,
        loader: Callable[[], dict | None],
        expected_subject: str,
        expected_role: str,
    ) -> dict:
        user = await self._load_user(loader)
        if not user:
            raise IdentityError("sesion revocada")
        actor = actor_for_user(user)
        if actor.subject != expected_subject or actor.role != expected_role:
            raise IdentityError("identidad o rol cambio")
        return user

    async def handle(
        self,
        peer: WebSocketPeer,
        user_loader: Callable[[], dict | None],
    ) -> None:
        if not self._origin_allowed(peer):
            self._rejected_origin += 1
            await self._close(peer, 4403, "origin not allowed")
            return
        if not await self._reserve_global_slot():
            self._rejected_limit += 1
            await self._close(peer, 4429, "connection limit")
            return
        try:
            user = await self._load_user(user_loader)
        except Exception:  # noqa: BLE001
            await self._release_connection(None, accepted=False)
            self._rejected_auth += 1
            await self._close(peer, 1011, "authentication unavailable")
            return
        try:
            actor = actor_for_user(user)
        except IdentityError:
            await self._release_connection(None, accepted=False)
            self._rejected_auth += 1
            await self._close(peer, 4401, "authentication required")
            return
        if not await self._reserve_subject(actor.subject):
            await self._release_connection(None, accepted=False)
            self._rejected_limit += 1
            await self._close(peer, 4429, "subject connection limit")
            return

        subscription: EventSubscription | None = None
        try:
            await peer.accept()
            authorization = await self._authorization_snapshot(user)
            allowed_topics = set(authorization["topics"])
            await self._send_json(
                peer,
                {
                    "gateway_v": GATEWAY_VERSION,
                    "op": "ready",
                    "contract_v": CONTRACT_VERSION,
                    "fingerprint": CONTRACT_V1_FINGERPRINT,
                    "available_topics": sorted(allowed_topics),
                    "heartbeat_ms": int(
                        self.limits.heartbeat_interval_seconds * 1000
                    ),
                    "max_topics": self._bus.limits.max_topics_per_subscription,
                    "max_message_bytes": self.limits.max_message_bytes,
                }
            )
            message_times: deque[float] = deque()
            try:
                first = await asyncio.wait_for(
                    self._receive_control(peer, message_times),
                    timeout=self.limits.subscribe_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise GatewayProtocolError(
                    "gateway.subscribe-timeout",
                    "No se recibio subscribe dentro del plazo.",
                    408,
                ) from exc
            topics = self._topics_from_control(first, allowed_topics)
            subscription, checkpoint = await self._subscribe(
                user, topics, authorization
            )
            await self._send_snapshot(peer, checkpoint)
            last_client_activity = self._monotonic()
            next_heartbeat = (
                last_client_activity
                + self.limits.heartbeat_interval_seconds
            )

            while True:
                event_task = asyncio.create_task(subscription.receive())
                control_task = asyncio.create_task(
                    self._receive_control(peer, message_times)
                )
                done, pending = await asyncio.wait(
                    {event_task, control_task},
                    timeout=max(0.0, next_heartbeat - self._monotonic()),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

                reconfigured = False
                if control_task in done:
                    control = control_task.result()
                    last_client_activity = self._monotonic()
                    op = control.get("op")
                    if op not in {"pong", "subscribe", "resync"}:
                        raise GatewayProtocolError(
                            "gateway.operation-unsupported",
                            "Operacion WebSocket no soportada.",
                        )
                    if op != "pong":
                        user = await self._refresh_identity(
                            user_loader, actor.subject, actor.role
                        )
                        authorization = await self._authorization_snapshot(user)
                        allowed_topics = set(authorization["topics"])
                        if op == "subscribe":
                            new_topics = self._topics_from_control(
                                control, allowed_topics
                            )
                        else:
                            new_topics = topics
                            if not new_topics.issubset(allowed_topics):
                                raise GatewayProtocolError(
                                    "gateway.topic-forbidden",
                                    "La sesion ya no autoriza la suscripcion.",
                                    403,
                                )
                        await subscription.close()
                        subscription, checkpoint = await self._subscribe(
                            user, new_topics, authorization
                        )
                        topics = new_topics
                        await self._send_snapshot(peer, checkpoint)
                        self._resyncs += 1
                        reconfigured = True

                if event_task in done and not reconfigured:
                    try:
                        envelope = event_task.result()
                    except ResyncRequired:
                        self._resyncs += 1
                        await self._send_error(
                            peer,
                            "gateway.resync-required",
                            "La conexion perdio continuidad; solicite otro snapshot.",
                            409,
                            retryable=True,
                        )
                        await self._close(peer, 1013, "resync required")
                        return
                    await self._send_envelope(peer, envelope)

                now = self._monotonic()
                if now >= next_heartbeat:
                    if (
                        now - last_client_activity
                        >= self.limits.heartbeat_timeout_seconds
                    ):
                        await self._close(peer, 4408, "heartbeat timeout")
                        return
                    await self._refresh_identity(
                        user_loader, actor.subject, actor.role
                    )
                    await self._send_json(
                        peer,
                        {
                            "gateway_v": GATEWAY_VERSION,
                            "op": "ping",
                            "sent_at": self._clock_ms(),
                        }
                    )
                    self._heartbeats += 1
                    next_heartbeat = (
                        now + self.limits.heartbeat_interval_seconds
                    )
        except PeerDisconnected:
            return
        except GatewayProtocolError as exc:
            self._protocol_errors += 1
            self._on_error(exc.code)
            await self._send_error(
                peer,
                exc.code,
                exc.message,
                exc.status,
                retryable=exc.status in {408, 409, 429},
            )
            await self._close(
                peer,
                1009 if exc.status == 413 else 4400,
                exc.code,
            )
        except IdentityError:
            self._rejected_auth += 1
            await self._send_error(
                peer,
                "auth.session-changed",
                "La sesion cambio o fue revocada.",
                401,
            )
            await self._close(peer, 4401, "session changed")
        except GatewaySendTimeout:
            self._on_error("gateway.send-timeout")
            await self._send_error(
                peer,
                "gateway.send-timeout",
                "El cliente no recibio datos dentro del plazo.",
                503,
                retryable=True,
            )
            await self._close(peer, 1013, "send timeout")
        except Exception as exc:  # noqa: BLE001
            self._on_error(f"gateway.internal:{type(exc).__name__}")
            await self._send_error(
                peer,
                "gateway.internal-error",
                "El Gateway no pudo mantener la conexion.",
                500,
                retryable=True,
            )
            await self._close(peer, 1011, "internal error")
        finally:
            if subscription is not None:
                try:
                    await subscription.close()
                except Exception:  # noqa: BLE001
                    pass
            await self._release_connection(actor.subject, accepted=True)
