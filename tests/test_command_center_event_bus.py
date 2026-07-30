import asyncio
import ast
import copy
from pathlib import Path

import pytest

from core.hub import ROOT
from core.module_base import ModuleContext
from modules.command_center.contracts import ContractViolation, replay
from modules.command_center.event_bus import (
    BusLimits,
    EventBusError,
    InMemoryEventBus,
    Publication,
    PublisherBindingError,
    ResyncRequired,
    SubscriptionClosed,
)
from modules.command_center.snapshot import (
    Projection,
    SnapshotComposer,
)
from modules.command_center.module import CommandCenterModule

NOW = 1_785_430_000_000
SUBJECT = "user:7"
TOPIC = "market.summary"
SOURCE = "test:market"


def _state(value=1):
    return {
        "state": {
            "health": "healthy",
            "freshness": "live",
            "mode": "not_applicable",
            "severity": "normal",
            "source": SOURCE,
            "as_of": NOW,
            "availability": "available",
            "degradation": None,
        },
        "data": {"value": value},
    }


def _publication(kind="snapshot", payload=None, **changes):
    values = {
        "topic": TOPIC,
        "kind": kind,
        "subject": SUBJECT,
        "observed_at": NOW,
        "stale_at": NOW + 10_000,
        "expires_at": NOW + 20_000,
        "severity": "normal",
        "payload": _state() if payload is None else payload,
    }
    values.update(changes)
    return Publication(**values)


def _run(coro):
    return asyncio.run(coro)


def test_publica_snapshot_patch_evento_con_secuencia_y_replay():
    async def scenario():
        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        publisher = await bus.register_publisher(SOURCE, [TOPIC])
        subscription = await bus.subscribe(SUBJECT, [TOPIC])

        snapshot_envelope = await publisher.publish(_publication())
        patch = await publisher.publish(
            _publication("patch", {"data": {"value": 2}})
        )
        event = await publisher.publish(
            _publication(
                "event",
                {"reason": "price-moved"},
                event_type="market.price-moved",
                event_version=1,
            )
        )

        assert [snapshot_envelope["seq"], patch["seq"], event["seq"]] == [0, 1, 2]
        assert [await subscription.receive() for _ in range(3)] == [
            snapshot_envelope,
            patch,
            event,
        ]

        snapshot = {
            "contract": "nexux.command-center.snapshot",
            "v": 1,
            "contract_fingerprint": (
                "b0a8a7efa623a1aae4b681c3cfc42790"
                "d36a6a14fbc689688026c523f2e49b46"
            ),
            "snapshot_id": "00000000-0000-4000-8000-000000000001",
            "subject": SUBJECT,
            "generated_at": NOW,
            "topics": {TOPIC: snapshot_envelope},
            "cursors": {TOPIC: 0},
        }
        state = replay(snapshot, [patch, event])
        assert state.topics[TOPIC]["data"]["value"] == 2
        assert state.cursors[TOPIC] == 2

    _run(scenario())


def test_aisla_tenants_y_filtra_topics_en_el_servidor():
    async def scenario():
        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        publisher = await bus.register_publisher(SOURCE, [TOPIC])
        right_user = await bus.subscribe(SUBJECT, [TOPIC])
        other_user = await bus.subscribe("user:8", [TOPIC])
        other_topic = await bus.subscribe(SUBJECT, ["system.session"])

        expected = await publisher.publish(_publication())
        assert await right_user.receive(timeout=0.01) == expected
        with pytest.raises(asyncio.TimeoutError):
            await other_user.receive(timeout=0.01)
        with pytest.raises(asyncio.TimeoutError):
            await other_topic.receive(timeout=0.01)

    _run(scenario())


def test_binding_impide_publicar_en_source_o_topic_ajenos():
    async def scenario():
        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        publisher = await bus.register_publisher(SOURCE, [TOPIC])
        with pytest.raises(PublisherBindingError):
            await publisher.publish(_publication(topic="bot.production"))
        with pytest.raises(PublisherBindingError):
            await bus.register_publisher(SOURCE, [TOPIC, "bot.production"])
        with pytest.raises(PublisherBindingError, match="otra source"):
            await bus.register_publisher("test:other", [TOPIC])

    _run(scenario())


def test_topic_nuevo_exige_snapshot_y_patch_invalido_no_avanza_cursor():
    async def scenario():
        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        publisher = await bus.register_publisher(SOURCE, [TOPIC])
        with pytest.raises(ContractViolation, match="topic nuevo exige snapshot"):
            await publisher.publish(_publication("patch", {"data": {"value": 2}}))

        first = await publisher.publish(_publication())
        broken = _publication(
            "patch",
            {"state": {"severity": "critical"}},
            severity="normal",
        )
        with pytest.raises(ContractViolation, match="severity contradice"):
            await publisher.publish(broken)
        valid = await publisher.publish(
            _publication("patch", {"data": {"value": 3}})
        )
        assert first["seq"] == 0
        assert valid["seq"] == 1

    _run(scenario())


def test_coalescing_ocurre_antes_de_asignar_secuencia():
    async def scenario():
        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        publisher = await bus.register_publisher(SOURCE, [TOPIC])
        await publisher.publish(
            _publication(
                payload={
                    **_state(),
                    "data": {"left": 0, "untouched": True},
                }
            )
        )
        combined = await publisher.publish_coalesced(
            [
                _publication("patch", {"data": {"left": 1}}),
                _publication("patch", {"data": {"right": 2}}),
                _publication("patch", {"data": {"left": None, "last": 3}}),
            ]
        )
        assert combined["seq"] == 1
        assert combined["kind"] == "snapshot"
        assert combined["payload"]["data"] == {
            "untouched": True,
            "right": 2,
            "last": 3,
        }
        checkpoint = await bus.checkpoint(SUBJECT)
        assert checkpoint["topics"][TOPIC]["payload"]["data"] == {
            "untouched": True,
            "right": 2,
            "last": 3,
        }
        assert bus.stats()["coalesced_inputs"] == 3
        assert bus.stats()["published"] == 2

    _run(scenario())


def test_backpressure_cierra_sin_perder_eventos_en_silencio():
    async def scenario():
        bus = InMemoryEventBus(
            limits=BusLimits(max_queue_per_subscription=1),
            clock_ms=lambda: NOW,
        )
        publisher = await bus.register_publisher(SOURCE, [TOPIC])
        subscription = await bus.subscribe(SUBJECT, [TOPIC], max_queue=1)
        await publisher.publish(_publication())
        await publisher.publish(_publication("patch", {"data": {"value": 2}}))

        assert subscription.closed is True
        with pytest.raises(ResyncRequired):
            await subscription.receive()
        assert bus.stats()["dropped_subscribers"] == 1
        assert bus.stats()["subscribers"] == 0

    _run(scenario())


def test_timeout_habilita_heartbeat_del_gateway_y_close_despierta_lector():
    async def scenario():
        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        subscription = await bus.subscribe(SUBJECT, [TOPIC])
        with pytest.raises(asyncio.TimeoutError):
            await subscription.receive(timeout=0.001)
        await bus.close()
        with pytest.raises(SubscriptionClosed):
            await subscription.receive()
        assert bus.stats()["status"] == "closed"
        with pytest.raises(EventBusError):
            await bus.subscribe(SUBJECT, [TOPIC])

    _run(scenario())


def test_seed_snapshot_no_retrocede_cursor_ni_acepta_contradiccion():
    class Provider:
        topic = TOPIC
        source = SOURCE
        allowed_roles = None

        def read(self, actor, now_ms):
            return Projection(
                topic=TOPIC,
                source=SOURCE,
                observed_at=now_ms,
                stale_at=now_ms + 10_000,
                expires_at=now_ms + 20_000,
                health="healthy",
                freshness="live",
                mode="not_applicable",
                severity="normal",
                availability="available",
                degradation=None,
                data={"value": 1},
            )

    async def scenario():
        composer = SnapshotComposer(
            [Provider()],
            clock_ms=lambda: NOW,
            id_factory=lambda: "00000000-0000-4000-8000-000000000001",
        )
        snapshot = composer.compose({"uid": 7, "role": "beta"})
        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        await bus.seed_snapshot(snapshot)
        publisher = await bus.register_publisher(SOURCE, [TOPIC])
        patch = await publisher.publish(
            _publication("patch", {"data": {"value": 2}})
        )
        assert patch["seq"] == 1

        await bus.seed_snapshot(snapshot)
        next_patch = await publisher.publish(
            _publication("patch", {"data": {"value": 3}})
        )
        assert next_patch["seq"] == 2

        contradictory = copy.deepcopy(snapshot)
        contradictory["topics"][TOPIC]["payload"]["data"]["value"] = 99
        with pytest.raises(EventBusError, match="contradice"):
            fresh = InMemoryEventBus(clock_ms=lambda: NOW)
            await fresh.seed_snapshot(snapshot)
            await fresh.seed_snapshot(contradictory)

    _run(scenario())


def test_seed_snapshot_es_atomico_si_un_topic_tiene_source_conflictiva():
    class Provider:
        allowed_roles = None

        def __init__(self, topic, source):
            self.topic = topic
            self.source = source

        def read(self, actor, now_ms):
            return Projection(
                topic=self.topic,
                source=self.source,
                observed_at=now_ms,
                stale_at=now_ms + 10_000,
                expires_at=now_ms + 20_000,
                health="healthy",
                freshness="live",
                mode="not_applicable",
                severity="normal",
                availability="available",
                degradation=None,
                data={"value": 1},
            )

    async def scenario():
        composer = SnapshotComposer(
            [
                Provider("market.first", "test:first"),
                Provider("market.second", "test:conflict"),
            ],
            clock_ms=lambda: NOW,
            id_factory=lambda: "00000000-0000-4000-8000-000000000001",
        )
        snapshot = composer.compose({"uid": 7, "role": "beta"})
        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        await bus.register_publisher("test:owner", ["market.second"])
        with pytest.raises(PublisherBindingError, match="otra source"):
            await bus.seed_snapshot(snapshot)
        checkpoint = await bus.checkpoint(SUBJECT)
        assert checkpoint["topics"] == {}

    _run(scenario())


def test_checkpoint_reconstruye_estado_y_cursor_despues_de_evento():
    async def scenario():
        bus = InMemoryEventBus(
            clock_ms=lambda: NOW,
            id_factory=lambda: "00000000-0000-4000-8000-000000000001",
        )
        publisher = await bus.register_publisher(SOURCE, [TOPIC])
        await publisher.publish(_publication())
        await publisher.publish(_publication("patch", {"data": {"value": 2}}))
        await publisher.publish(
            _publication(
                "event",
                {"reason": "price-moved"},
                event_type="market.price-moved",
                event_version=1,
            )
        )

        checkpoint = await bus.checkpoint(SUBJECT, [TOPIC])
        assert checkpoint["cursors"] == {TOPIC: 2}
        envelope = checkpoint["topics"][TOPIC]
        assert envelope["kind"] == "snapshot"
        assert envelope["seq"] == 2
        assert envelope["payload"]["data"]["value"] == 2

        next_patch = await publisher.publish(
            _publication("patch", {"data": {"value": 3}})
        )
        state = replay(checkpoint, [next_patch])
        assert state.cursors[TOPIC] == 3
        assert state.topics[TOPIC]["data"]["value"] == 3

    _run(scenario())


def test_publicaciones_concurrentes_tienen_secuencia_unica_y_contigua():
    async def scenario():
        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        publisher = await bus.register_publisher(SOURCE, [TOPIC])
        await publisher.publish(_publication())
        results = await asyncio.gather(
            *[
                publisher.publish(
                    _publication("patch", {"data": {f"value-{index}": index}})
                )
                for index in range(40)
            ]
        )
        assert sorted(item["seq"] for item in results) == list(range(1, 41))
        checkpoint = await bus.checkpoint(SUBJECT)
        assert checkpoint["cursors"][TOPIC] == 40
        assert len(checkpoint["topics"][TOPIC]["payload"]["data"]) == 41

    _run(scenario())


def test_limites_se_validan_sin_truncar_en_silencio():
    async def scenario():
        bus = InMemoryEventBus(
            limits=BusLimits(
                max_publishers=1,
                max_subscribers=1,
                max_topics_per_subscription=1,
                max_queue_per_subscription=2,
            )
        )
        await bus.register_publisher(SOURCE, [TOPIC])
        with pytest.raises(EventBusError, match="publishers"):
            await bus.register_publisher("test:second", ["system.session"])
        await bus.subscribe(SUBJECT, [TOPIC])
        with pytest.raises(EventBusError, match="suscriptores"):
            await bus.subscribe("user:8", [TOPIC])

        other = InMemoryEventBus(limits=BusLimits(max_topics_per_subscription=1))
        with pytest.raises(EventBusError, match="topics"):
            await other.subscribe(SUBJECT, [TOPIC, "system.session"])
        with pytest.raises(ValueError, match="max_queue"):
            await other.subscribe(SUBJECT, [TOPIC], max_queue=0)

    _run(scenario())


def test_checkpoint_actualiza_frescura_sin_mezclar_usuarios():
    async def scenario():
        now = [NOW]
        bus = InMemoryEventBus(clock_ms=lambda: now[0])
        publisher = await bus.register_publisher(SOURCE, [TOPIC])
        await publisher.publish(_publication())
        now[0] = NOW + 15_000
        stale = await bus.checkpoint(SUBJECT)
        assert (
            stale["topics"][TOPIC]["payload"]["state"]["freshness"] == "stale"
        )
        empty = await bus.checkpoint("user:8")
        assert empty["topics"] == {}
        assert empty["cursors"] == {}
        now[0] = NOW + 25_000
        expired = await bus.checkpoint(SUBJECT)
        assert (
            expired["topics"][TOPIC]["payload"]["state"]["freshness"]
            == "expired"
        )

    _run(scenario())


def test_event_bus_no_importa_bot_ejecutor_ni_ui():
    path = Path(ROOT) / "modules" / "command_center" / "event_bus.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(name.startswith("modules.bot") for name in imports)
    assert not any(name in {"fastapi", "starlette"} for name in imports)


def test_modulo_expone_salud_headless_del_event_bus():
    context = ModuleContext(
        "command_center",
        "modules/command_center",
        {},
        lambda _message: None,
    )
    health = CommandCenterModule(context).health()
    assert health["contract_status"] == "frozen"
    assert health["event_bus"] == {
        "backend": "memory",
        "status": "ready",
        "publishers": 0,
        "subscribers": 0,
        "streams": 0,
        "published": 0,
        "dropped_subscribers": 0,
        "coalesced_inputs": 0,
    }
