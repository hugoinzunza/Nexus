"""EventBus headless en proceso para el Command Center."""

from __future__ import annotations

import asyncio
import copy
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Protocol

from .contracts import (
    CONTRACT_V1_FINGERPRINT,
    CONTRACT_VERSION,
    EVENT_CONTRACT,
    LIMITS,
    SNAPSHOT_CONTRACT,
    ContractViolation,
    json_merge_patch,
    validate_envelope,
    validate_source_name,
    validate_subject_name,
    validate_topic_name,
)


class EventBusError(RuntimeError):
    """Error operacional del broker, fuera del Wire ABI."""


class PublisherBindingError(EventBusError):
    """El publisher intento salir de su source o topics declarados."""


class ResyncRequired(EventBusError):
    """El consumidor perdio continuidad y debe solicitar otro snapshot."""


class SubscriptionClosed(EventBusError):
    """La suscripcion ya no acepta lecturas."""


@dataclass(frozen=True)
class BusLimits:
    max_publishers: int = 128
    max_subscribers: int = 256
    max_topics_per_subscription: int = 32
    max_queue_per_subscription: int = 128

    def __post_init__(self) -> None:
        values = (
            self.max_publishers,
            self.max_subscribers,
            self.max_topics_per_subscription,
            self.max_queue_per_subscription,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("los limites del EventBus deben ser enteros positivos")
        if self.max_topics_per_subscription > LIMITS["max_topics"]:
            raise ValueError("max_topics_per_subscription excede el Wire ABI")


@dataclass(frozen=True)
class Publication:
    topic: str
    kind: str
    subject: str
    observed_at: int
    stale_at: int
    expires_at: int
    severity: str
    payload: Mapping[str, Any]
    event_type: str | None = None
    event_version: int | None = None


class PublisherHandle(Protocol):
    source: str
    topics: frozenset[str]

    async def publish(self, publication: Publication) -> dict[str, Any]: ...

    async def publish_coalesced(
        self, publications: Iterable[Publication]
    ) -> dict[str, Any]: ...


class EventSubscription(Protocol):
    subject: str
    topics: frozenset[str]

    async def receive(self, timeout: float | None = None) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class EventBroker(Protocol):
    limits: BusLimits

    async def register_publisher(
        self, source: str, topics: Iterable[str]
    ) -> PublisherHandle: ...

    async def subscribe(
        self,
        subject: str,
        topics: Iterable[str],
        *,
        max_queue: int | None = None,
    ) -> EventSubscription: ...

    async def seed_snapshot(self, snapshot: Mapping[str, Any]) -> None: ...

    async def checkpoint(
        self, subject: str, topics: Iterable[str] | None = None
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...


_CLOSED = object()


class Subscription:
    def __init__(
        self,
        bus: "InMemoryEventBus",
        subscription_id: str,
        subject: str,
        topics: frozenset[str],
        max_queue: int,
    ):
        self._bus = bus
        self.id = subscription_id
        self.subject = subject
        self.topics = topics
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=max_queue)
        self._closed_reason: str | None = None

    @property
    def closed(self) -> bool:
        return self._closed_reason is not None

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def _offer(self, envelope: Mapping[str, Any]) -> bool:
        if self.closed:
            return False
        try:
            self._queue.put_nowait(copy.deepcopy(envelope))
            return True
        except asyncio.QueueFull:
            self._terminate("resync")
            return False

    def _terminate(self, reason: str) -> None:
        if self.closed:
            return
        self._closed_reason = reason
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._queue.put_nowait(_CLOSED)

    async def receive(self, timeout: float | None = None) -> dict[str, Any]:
        try:
            item = (
                await self._queue.get()
                if timeout is None
                else await asyncio.wait_for(self._queue.get(), timeout)
            )
        except asyncio.TimeoutError:
            raise
        if item is _CLOSED:
            self._queue.put_nowait(_CLOSED)
            if self._closed_reason == "resync":
                raise ResyncRequired("backpressure: solicitar un snapshot nuevo")
            raise SubscriptionClosed("la suscripcion esta cerrada")
        return item

    async def close(self) -> None:
        await self._bus.unsubscribe(self)

    def __aiter__(self) -> "Subscription":
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return await self.receive()
        except SubscriptionClosed as exc:
            raise StopAsyncIteration from exc


class BoundPublisher:
    def __init__(
        self, bus: "InMemoryEventBus", source: str, topics: frozenset[str]
    ):
        self._bus = bus
        self.source = source
        self.topics = topics

    async def publish(self, publication: Publication) -> dict[str, Any]:
        return await self._bus.publish(self, publication)

    async def publish_coalesced(
        self, publications: Iterable[Publication]
    ) -> dict[str, Any]:
        """Colapsa patches en un snapshot completo antes de asignar un seq."""
        items = tuple(publications)
        return await self._bus.publish_coalesced(self, items)


class InMemoryEventBus:
    """Broker de un proceso; su interfaz permite reemplazarlo sin cambiar el ABI."""

    def __init__(
        self,
        *,
        limits: BusLimits | None = None,
        clock_ms=None,
        id_factory=None,
    ):
        self.limits = limits or BusLimits()
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._lock: asyncio.Lock | None = None
        self._publishers: dict[str, frozenset[str]] = {}
        self._topic_sources: dict[str, str] = {}
        self._subscribers: dict[str, Subscription] = {}
        self._cursors: dict[tuple[str, str], int] = {}
        self._states: dict[tuple[str, str], dict[str, Any]] = {}
        self._state_envelopes: dict[tuple[str, str], dict[str, Any]] = {}
        self._closed = False
        self._published = 0
        self._dropped_subscribers = 0
        self._coalesced_inputs = 0

    def stats(self) -> dict[str, Any]:
        return {
            "backend": "memory",
            "status": "closed" if self._closed else "ready",
            "publishers": len(self._publishers),
            "subscribers": len(self._subscribers),
            "streams": len(self._cursors),
            "published": self._published,
            "dropped_subscribers": self._dropped_subscribers,
            "coalesced_inputs": self._coalesced_inputs,
        }

    def _ensure_open(self) -> None:
        if self._closed:
            raise EventBusError("el EventBus esta cerrado")

    def _async_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def register_publisher(
        self, source: str, topics: Iterable[str]
    ) -> BoundPublisher:
        validate_source_name(source)
        topic_set = frozenset(topics)
        if not topic_set:
            raise ValueError("el publisher exige al menos un topic")
        if len(topic_set) > LIMITS["max_topics"]:
            raise ValueError("el publisher excede max_topics")
        for topic in topic_set:
            validate_topic_name(topic)
        async with self._async_lock():
            self._ensure_open()
            existing = self._publishers.get(source)
            if existing is not None and existing != topic_set:
                raise PublisherBindingError(
                    "una source registrada no puede ampliar o cambiar sus topics"
                )
            if existing is None and len(self._publishers) >= self.limits.max_publishers:
                raise EventBusError("limite de publishers alcanzado")
            for topic in topic_set:
                owner = self._topic_sources.get(topic)
                if owner is not None and owner != source:
                    raise PublisherBindingError(
                        f"el topic {topic} ya pertenece a otra source"
                    )
            self._publishers[source] = topic_set
            for topic in topic_set:
                self._topic_sources[topic] = source
        return BoundPublisher(self, source, topic_set)

    async def subscribe(
        self,
        subject: str,
        topics: Iterable[str],
        *,
        max_queue: int | None = None,
    ) -> Subscription:
        validate_subject_name(subject)
        topic_set = frozenset(topics)
        if not topic_set:
            raise ValueError("la suscripcion exige al menos un topic")
        if len(topic_set) > self.limits.max_topics_per_subscription:
            raise EventBusError("limite de topics por suscripcion alcanzado")
        for topic in topic_set:
            validate_topic_name(topic)
        queue_limit = (
            self.limits.max_queue_per_subscription
            if max_queue is None
            else max_queue
        )
        if (
            type(queue_limit) is not int
            or queue_limit <= 0
            or queue_limit > self.limits.max_queue_per_subscription
        ):
            raise ValueError("max_queue fuera de limite")
        async with self._async_lock():
            self._ensure_open()
            if len(self._subscribers) >= self.limits.max_subscribers:
                raise EventBusError("limite de suscriptores alcanzado")
            subscription = Subscription(
                self, self._id_factory(), subject, topic_set, queue_limit
            )
            if subscription.id in self._subscribers:
                raise EventBusError("id de suscripcion duplicado")
            self._subscribers[subscription.id] = subscription
            return subscription

    async def unsubscribe(self, subscription: Subscription) -> None:
        async with self._async_lock():
            current = self._subscribers.pop(subscription.id, None)
            if current is subscription:
                current._terminate("closed")
            elif current is not None:
                self._subscribers[current.id] = current

    async def seed_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        from .contracts import validate_snapshot

        validated = validate_snapshot(snapshot)
        subject = validated["subject"]
        async with self._async_lock():
            self._ensure_open()
            updates = []
            for topic, envelope in validated["topics"].items():
                key = (subject, topic)
                owner = self._topic_sources.get(topic)
                if owner is not None and owner != envelope["source"]:
                    raise PublisherBindingError(
                        f"el topic {topic} ya pertenece a otra source"
                    )
                incoming = validated["cursors"][topic]
                current = self._cursors.get(key, -1)
                if incoming < current:
                    continue
                if incoming == current and key in self._states:
                    if self._states[key] != envelope["payload"]:
                        raise EventBusError(
                            "snapshot contradice el estado del cursor existente"
                        )
                    continue
                updates.append((key, incoming, envelope))
            for key, incoming, envelope in updates:
                topic = key[1]
                self._cursors[key] = incoming
                self._states[key] = copy.deepcopy(envelope["payload"])
                self._state_envelopes[key] = copy.deepcopy(envelope)
                self._topic_sources[topic] = envelope["source"]

    async def checkpoint(
        self, subject: str, topics: Iterable[str] | None = None
    ) -> dict[str, Any]:
        validate_subject_name(subject)
        selected = None if topics is None else frozenset(topics)
        if selected is not None:
            if len(selected) > LIMITS["max_topics"]:
                raise ValueError("checkpoint excede max_topics")
            for topic in selected:
                validate_topic_name(topic)
        async with self._async_lock():
            self._ensure_open()
            generated_at = self._clock_ms()
            envelopes: dict[str, dict[str, Any]] = {}
            cursors: dict[str, int] = {}
            for (stream_subject, topic), payload in sorted(self._states.items()):
                if stream_subject != subject or (
                    selected is not None and topic not in selected
                ):
                    continue
                base = self._state_envelopes[(stream_subject, topic)]
                state_payload = copy.deepcopy(payload)
                if generated_at >= base["expires_at"]:
                    freshness = "expired"
                elif generated_at >= base["stale_at"]:
                    freshness = "stale"
                else:
                    freshness = state_payload["state"]["freshness"]
                state_payload["state"]["freshness"] = freshness
                envelope = {
                    **base,
                    "kind": "snapshot",
                    "seq": self._cursors[(stream_subject, topic)],
                    "received_at": generated_at,
                    "payload": state_payload,
                }
                envelope.pop("event_type", None)
                envelope.pop("event_version", None)
                envelopes[topic] = validate_envelope(envelope)
                cursors[topic] = envelope["seq"]
            snapshot = {
                "contract": SNAPSHOT_CONTRACT,
                "v": CONTRACT_VERSION,
                "contract_fingerprint": CONTRACT_V1_FINGERPRINT,
                "snapshot_id": self._id_factory(),
                "subject": subject,
                "generated_at": generated_at,
                "topics": envelopes,
                "cursors": cursors,
            }
            from .contracts import validate_snapshot

            return validate_snapshot(snapshot)

    async def publish(
        self, publisher: BoundPublisher, publication: Publication
    ) -> dict[str, Any]:
        if publication.topic not in publisher.topics:
            raise PublisherBindingError("publisher no autorizado para este topic")
        validate_subject_name(publication.subject)
        validate_topic_name(publication.topic)
        async with self._async_lock():
            self._ensure_open()
            self._validate_publisher(publisher)
            return self._publish_locked(publisher, publication)

    async def publish_coalesced(
        self,
        publisher: BoundPublisher,
        publications: tuple[Publication, ...],
    ) -> dict[str, Any]:
        if not publications:
            raise ValueError("coalescing exige al menos un patch")
        first = publications[0]
        if any(
            item.kind != "patch"
            or item.subject != first.subject
            or item.topic != first.topic
            for item in publications
        ):
            raise ValueError("solo se pueden coalescer patches del mismo destino")
        if first.topic not in publisher.topics:
            raise PublisherBindingError("publisher no autorizado para este topic")
        validate_subject_name(first.subject)
        validate_topic_name(first.topic)
        async with self._async_lock():
            self._ensure_open()
            self._validate_publisher(publisher)
            key = (first.subject, first.topic)
            current_state = self._states.get(key)
            if current_state is None:
                raise ContractViolation("patch sin snapshot base")
            next_state = copy.deepcopy(current_state)
            seq = self._cursors[key] + 1
            for item in publications:
                validated = self._build_envelope(
                    publisher, item, seq, self._clock_ms()
                )
                next_state = json_merge_patch(next_state, validated["payload"])
                validate_envelope(
                    {
                        **validated,
                        "kind": "snapshot",
                        "payload": next_state,
                    }
                )
            collapsed = replace(
                publications[-1],
                kind="snapshot",
                payload=next_state,
                event_type=None,
                event_version=None,
            )
            envelope = self._publish_locked(publisher, collapsed)
            self._coalesced_inputs += len(publications)
            return envelope

    def _validate_publisher(self, publisher: BoundPublisher) -> None:
        registered = self._publishers.get(publisher.source)
        if registered != publisher.topics:
            raise PublisherBindingError("publisher no registrado o alterado")

    def _build_envelope(
        self,
        publisher: BoundPublisher,
        publication: Publication,
        seq: int,
        received_at: int,
    ) -> dict[str, Any]:
        envelope = {
            "contract": EVENT_CONTRACT,
            "v": CONTRACT_VERSION,
            "topic": publication.topic,
            "kind": publication.kind,
            "subject": publication.subject,
            "seq": seq,
            "observed_at": publication.observed_at,
            "received_at": received_at,
            "stale_at": publication.stale_at,
            "expires_at": publication.expires_at,
            "severity": publication.severity,
            "source": publisher.source,
            "payload": copy.deepcopy(dict(publication.payload)),
        }
        if publication.event_type is not None:
            envelope["event_type"] = publication.event_type
        if publication.event_version is not None:
            envelope["event_version"] = publication.event_version
        return validate_envelope(envelope)

    def _publish_locked(
        self, publisher: BoundPublisher, publication: Publication
    ) -> dict[str, Any]:
        key = (publication.subject, publication.topic)
        current = self._cursors.get(key)
        if current is None and publication.kind != "snapshot":
            raise ContractViolation("topic nuevo exige snapshot")
        seq = 0 if current is None else current + 1
        validated = self._build_envelope(
            publisher, publication, seq, self._clock_ms()
        )

        if publication.kind == "snapshot":
            next_state = copy.deepcopy(validated["payload"])
        elif publication.kind == "patch":
            current_state = self._states.get(key)
            if current_state is None:
                raise ContractViolation("patch sin snapshot base")
            next_state = json_merge_patch(current_state, validated["payload"])
            validate_envelope(
                {
                    **validated,
                    "kind": "snapshot",
                    "payload": next_state,
                }
            )
        else:
            next_state = self._states.get(key)

        self._cursors[key] = seq
        if next_state is not None:
            self._states[key] = next_state
        if publication.kind in {"snapshot", "patch"}:
            self._state_envelopes[key] = copy.deepcopy(validated)
        self._published += 1

        for subscription_id, subscription in tuple(self._subscribers.items()):
            if (
                subscription.subject == publication.subject
                and publication.topic in subscription.topics
                and not subscription._offer(validated)
            ):
                self._subscribers.pop(subscription_id, None)
                self._dropped_subscribers += 1
        return copy.deepcopy(validated)

    async def close(self) -> None:
        async with self._async_lock():
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(self._subscribers.values())
            self._subscribers.clear()
            for subscription in subscriptions:
                subscription._terminate("closed")
