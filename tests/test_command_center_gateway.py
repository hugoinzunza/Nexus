import asyncio
import ast
import copy
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core.module_base import ModuleContext
from core.hub import ROOT
from modules.command_center.contracts import (
    CONTRACT_V1_FINGERPRINT,
    CONTRACT_VERSION,
)
from modules.command_center.event_bus import BusLimits, InMemoryEventBus, Publication
from modules.command_center.gateway import (
    CommandCenterGateway,
    GatewayLimits,
)
from modules.command_center.module import CommandCenterModule
from modules.command_center.snapshot import (
    ConfiguredModulesProjection,
    SessionProjection,
    SnapshotComposer,
)

NOW = 1_785_430_000_000
USER = {
    "uid": 7,
    "role": "admin",
    "email": "private@example.com",
    "name": "Hugo",
}


class FakePeer:
    def __init__(
        self,
        *,
        origin="http://testserver",
        host="testserver",
        scheme="ws",
    ):
        self.headers = {"origin": origin, "host": host}
        self.url = SimpleNamespace(scheme=scheme)
        self.incoming = asyncio.Queue()
        self.sent = []
        self.accepted = False
        self.closed = None

    async def accept(self, subprotocol=None):
        self.accepted = True

    async def receive(self):
        return await self.incoming.get()

    async def send_json(self, data, mode="text"):
        self.sent.append(copy.deepcopy(data))

    async def close(self, code=1000, reason=None):
        self.closed = (code, reason)

    async def control(self, payload):
        await self.incoming.put(
            {
                "type": "websocket.receive",
                "text": __import__("json").dumps(payload),
            }
        )

    async def disconnect(self):
        await self.incoming.put(
            {"type": "websocket.disconnect", "code": 1000}
        )


class BlockingPeer(FakePeer):
    def __init__(self):
        super().__init__()
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()
        self._blocked_once = False

    async def send_json(self, data, mode="text"):
        if (
            not self._blocked_once
            and isinstance(data, dict)
            and data.get("kind") == "event"
        ):
            self._blocked_once = True
            self.blocked.set()
            await self.release.wait()
        await super().send_json(data, mode)


class SlowEventPeer(FakePeer):
    async def send_json(self, data, mode="text"):
        if isinstance(data, dict) and data.get("kind") == "event":
            await asyncio.Event().wait()
        await super().send_json(data, mode)


def _composer():
    config = {
        "modules": {
            "command_center": {"enabled": True},
            "bot": {"enabled": True},
        }
    }
    return SnapshotComposer(
        [
            SessionProjection(),
            ConfiguredModulesProjection(lambda: config),
        ],
        clock_ms=lambda: NOW,
        id_factory=lambda: "00000000-0000-4000-8000-000000000001",
    )


def _gateway(*, bus=None, limits=None, user_loader=None):
    gateway = CommandCenterGateway(
        bus or InMemoryEventBus(clock_ms=lambda: NOW),
        _composer(),
        limits=limits,
        clock_ms=lambda: NOW,
    )
    return gateway, user_loader or (lambda: USER)


def _subscribe(topics=None, **changes):
    control = {
        "gateway_v": 1,
        "op": "subscribe",
        "contract_v": CONTRACT_VERSION,
        "fingerprint": CONTRACT_V1_FINGERPRINT,
        "topics": topics or ["system.session"],
    }
    control.update(changes)
    return control


async def _wait_sent(peer, count, timeout=0.5):
    async def wait():
        while len(peer.sent) < count:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout)


def _run(coro):
    return asyncio.run(coro)


def test_handshake_snapshot_evento_y_cierre_limpio():
    async def scenario():
        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        gateway, loader = _gateway(bus=bus)
        peer = FakePeer()
        task = asyncio.create_task(gateway.handle(peer, loader))

        await _wait_sent(peer, 1)
        ready = peer.sent[0]
        assert ready["op"] == "ready"
        assert ready["fingerprint"] == CONTRACT_V1_FINGERPRINT
        assert ready["available_topics"] == ["system.modules", "system.session"]
        await peer.control(_subscribe())
        await _wait_sent(peer, 2)
        snapshot = peer.sent[1]
        assert snapshot["contract"] == "nexux.command-center.snapshot"
        assert set(snapshot["topics"]) == {"system.session"}
        assert "private@example.com" not in str(snapshot)

        publisher = await bus.register_publisher(
            "nexux:auth", ["system.session"]
        )
        event = await publisher.publish(
            Publication(
                topic="system.session",
                kind="event",
                subject="user:7",
                observed_at=NOW,
                stale_at=NOW + 15_000,
                expires_at=NOW + 30_000,
                severity="normal",
                payload={"alive": True},
                event_type="system.heartbeat",
                event_version=1,
            )
        )
        await _wait_sent(peer, 3)
        assert peer.sent[2] == event
        await peer.disconnect()
        await task
        assert gateway.stats()["active_connections"] == 0
        assert gateway.stats()["closed"] == 1

    _run(scenario())


def test_rechaza_origin_ajeno_y_sesion_ausente_antes_de_accept():
    async def scenario():
        gateway, _loader = _gateway()
        evil = FakePeer(origin="https://evil.example")
        called = []
        await gateway.handle(evil, lambda: called.append(True) or USER)
        assert evil.accepted is False
        assert evil.closed[0] == 4403
        assert called == []

        anonymous = FakePeer()
        await gateway.handle(anonymous, lambda: None)
        assert anonymous.accepted is False
        assert anonymous.closed[0] == 4401
        assert gateway.stats()["rejected_origin"] == 1
        assert gateway.stats()["rejected_auth"] == 1

    _run(scenario())


def test_fingerprint_y_topics_se_validan_con_error_versionado():
    async def scenario():
        gateway, loader = _gateway()
        mismatch = FakePeer()
        task = asyncio.create_task(gateway.handle(mismatch, loader))
        await _wait_sent(mismatch, 1)
        await mismatch.control(_subscribe(fingerprint="0" * 64))
        await task
        assert mismatch.sent[1]["contract"] == "nexux.command-center.error"
        assert mismatch.sent[1]["code"] == "gateway.contract-mismatch"
        assert mismatch.closed[0] == 4400

        forbidden = FakePeer()
        task = asyncio.create_task(gateway.handle(forbidden, loader))
        await _wait_sent(forbidden, 1)
        await forbidden.control(_subscribe(["bot.production"]))
        await task
        assert forbidden.sent[1]["code"] == "gateway.topic-forbidden"
        assert forbidden.closed[0] == 4400

    _run(scenario())


def test_resync_y_cambio_de_suscripcion_entregan_checkpoint():
    async def scenario():
        gateway, loader = _gateway()
        peer = FakePeer()
        task = asyncio.create_task(gateway.handle(peer, loader))
        await _wait_sent(peer, 1)
        await peer.control(_subscribe())
        await _wait_sent(peer, 2)
        first = peer.sent[1]

        await peer.control({"gateway_v": 1, "op": "resync"})
        await _wait_sent(peer, 3)
        assert peer.sent[2]["contract"] == "nexux.command-center.snapshot"
        assert peer.sent[2]["cursors"] == first["cursors"]

        await peer.control(_subscribe(["system.modules"]))
        await _wait_sent(peer, 4)
        assert set(peer.sent[3]["topics"]) == {"system.modules"}
        assert gateway.stats()["resyncs"] == 2
        await peer.disconnect()
        await task

    _run(scenario())


def test_heartbeat_revalida_sesion_y_pong_no_oculta_evento():
    async def scenario():
        calls = []

        def loader():
            calls.append(True)
            return USER

        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        limits = GatewayLimits(
            heartbeat_interval_seconds=0.01,
            heartbeat_timeout_seconds=0.05,
        )
        gateway, _ = _gateway(bus=bus, limits=limits)
        peer = FakePeer()
        task = asyncio.create_task(gateway.handle(peer, loader))
        await _wait_sent(peer, 1)
        await peer.control(_subscribe())
        await _wait_sent(peer, 2)
        await _wait_sent(peer, 3)
        assert peer.sent[2]["op"] == "ping"
        assert len(calls) >= 2

        publisher = await bus.register_publisher(
            "nexux:auth", ["system.session"]
        )
        await peer.control({"gateway_v": 1, "op": "pong"})
        event = await publisher.publish(
            Publication(
                topic="system.session",
                kind="event",
                subject="user:7",
                observed_at=NOW,
                stale_at=NOW + 15_000,
                expires_at=NOW + 30_000,
                severity="normal",
                payload={"alive": True},
                event_type="system.heartbeat",
                event_version=1,
            )
        )
        await _wait_sent(peer, 4)
        assert event in peer.sent
        await peer.disconnect()
        await task

    _run(scenario())


def test_revocacion_de_sesion_cierra_con_4401():
    async def scenario():
        users = [USER, None]

        def loader():
            return users.pop(0) if users else None

        gateway, _ = _gateway(
            limits=GatewayLimits(
                heartbeat_interval_seconds=0.01,
                heartbeat_timeout_seconds=0.05,
            )
        )
        peer = FakePeer()
        task = asyncio.create_task(gateway.handle(peer, loader))
        await _wait_sent(peer, 1)
        await peer.control(_subscribe())
        await task
        assert peer.sent[-1]["code"] == "auth.session-changed"
        assert peer.closed[0] == 4401

    _run(scenario())


def test_eventos_continuos_no_postergan_revalidacion_de_sesion():
    async def scenario():
        users = [USER, None]

        def loader():
            return users.pop(0) if users else None

        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        gateway, _ = _gateway(
            bus=bus,
            limits=GatewayLimits(
                heartbeat_interval_seconds=0.01,
                heartbeat_timeout_seconds=0.05,
            ),
        )
        peer = FakePeer()
        task = asyncio.create_task(gateway.handle(peer, loader))
        await _wait_sent(peer, 1)
        await peer.control(_subscribe())
        await _wait_sent(peer, 2)
        publisher = await bus.register_publisher(
            "nexux:auth", ["system.session"]
        )

        index = 0
        while not task.done() and index < 100:
            await publisher.publish(
                Publication(
                    topic="system.session",
                    kind="event",
                    subject="user:7",
                    observed_at=NOW,
                    stale_at=NOW + 15_000,
                    expires_at=NOW + 30_000,
                    severity="normal",
                    payload={"index": index},
                    event_type="system.heartbeat",
                    event_version=1,
                )
            )
            index += 1
            await asyncio.sleep(0.001)
        await asyncio.wait_for(task, 0.5)
        assert peer.sent[-1]["code"] == "auth.session-changed"
        assert peer.closed[0] == 4401

    _run(scenario())


def test_backpressure_envia_resync_versionado_y_cierra_1013():
    async def scenario():
        bus = InMemoryEventBus(
            limits=BusLimits(max_queue_per_subscription=1),
            clock_ms=lambda: NOW,
        )
        gateway, loader = _gateway(bus=bus)
        peer = BlockingPeer()
        task = asyncio.create_task(gateway.handle(peer, loader))
        await _wait_sent(peer, 1)
        await peer.control(_subscribe())
        await _wait_sent(peer, 2)
        publisher = await bus.register_publisher(
            "nexux:auth", ["system.session"]
        )

        async def publish(index):
            return await publisher.publish(
                Publication(
                    topic="system.session",
                    kind="event",
                    subject="user:7",
                    observed_at=NOW,
                    stale_at=NOW + 15_000,
                    expires_at=NOW + 30_000,
                    severity="normal",
                    payload={"index": index},
                    event_type="system.heartbeat",
                    event_version=1,
                )
            )

        await publish(1)
        await asyncio.wait_for(peer.blocked.wait(), 0.5)
        await publish(2)
        await publish(3)
        peer.release.set()
        await task
        assert peer.sent[-1]["code"] == "gateway.resync-required"
        assert peer.sent[-1]["retryable"] is True
        assert peer.closed[0] == 1013
        assert gateway.stats()["resyncs"] == 1

    _run(scenario())


def test_cliente_que_no_drena_socket_cierra_por_send_timeout():
    async def scenario():
        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        gateway, loader = _gateway(
            bus=bus,
            limits=GatewayLimits(send_timeout_seconds=0.01),
        )
        peer = SlowEventPeer()
        task = asyncio.create_task(gateway.handle(peer, loader))
        await _wait_sent(peer, 1)
        await peer.control(_subscribe())
        await _wait_sent(peer, 2)
        publisher = await bus.register_publisher(
            "nexux:auth", ["system.session"]
        )
        await publisher.publish(
            Publication(
                topic="system.session",
                kind="event",
                subject="user:7",
                observed_at=NOW,
                stale_at=NOW + 15_000,
                expires_at=NOW + 30_000,
                severity="normal",
                payload={"blocked": True},
                event_type="system.heartbeat",
                event_version=1,
            )
        )
        await asyncio.wait_for(task, 0.5)
        assert peer.sent[-1]["code"] == "gateway.send-timeout"
        assert peer.closed[0] == 1013

    _run(scenario())


def test_gateway_no_entrega_eventos_de_otro_usuario():
    async def scenario():
        bus = InMemoryEventBus(clock_ms=lambda: NOW)
        gateway, loader = _gateway(bus=bus)
        peer = FakePeer()
        task = asyncio.create_task(gateway.handle(peer, loader))
        await _wait_sent(peer, 1)
        await peer.control(_subscribe())
        await _wait_sent(peer, 2)
        publisher = await bus.register_publisher(
            "nexux:auth", ["system.session"]
        )

        def event_for(subject):
            return Publication(
                topic="system.session",
                kind="event",
                subject=subject,
                observed_at=NOW,
                stale_at=NOW + 15_000,
                expires_at=NOW + 30_000,
                severity="normal",
                payload={"subject": subject},
                event_type="system.heartbeat",
                event_version=1,
            )

        await publisher.publish(
            Publication(
                topic="system.session",
                kind="snapshot",
                subject="user:8",
                observed_at=NOW,
                stale_at=NOW + 15_000,
                expires_at=NOW + 30_000,
                severity="normal",
                payload={
                    "state": {
                        "health": "healthy",
                        "freshness": "live",
                        "mode": "not_applicable",
                        "severity": "normal",
                        "source": "nexux:auth",
                        "as_of": NOW,
                        "availability": "available",
                        "degradation": None,
                    },
                    "data": {"authenticated": True},
                },
            )
        )
        await publisher.publish(event_for("user:8"))
        await asyncio.sleep(0.01)
        assert len(peer.sent) == 2
        mine = await publisher.publish(event_for("user:7"))
        await _wait_sent(peer, 3)
        assert peer.sent[2] == mine
        await peer.disconnect()
        await task

    _run(scenario())


def test_timeout_de_subscribe_y_origen_forwarded_https():
    async def scenario():
        limits = GatewayLimits(subscribe_timeout_seconds=0.01)
        gateway, loader = _gateway(limits=limits)
        timeout_peer = FakePeer()
        await gateway.handle(timeout_peer, loader)
        assert timeout_peer.sent[-1]["code"] == "gateway.subscribe-timeout"
        assert timeout_peer.closed[0] == 4400

        forwarded = FakePeer(
            origin="https://nexux.cl",
            host="nexux.cl",
            scheme="ws",
        )
        forwarded.headers["x-forwarded-proto"] = "https"
        task = asyncio.create_task(gateway.handle(forwarded, loader))
        await _wait_sent(forwarded, 1)
        assert forwarded.accepted is True
        await forwarded.disconnect()
        await task

    _run(scenario())


def test_limites_de_conexion_mensaje_y_frecuencia():
    async def scenario():
        limits = GatewayLimits(
            max_connections=1,
            max_connections_per_subject=1,
            max_message_bytes=256,
            max_messages_per_minute=1,
        )
        gateway, loader = _gateway(limits=limits)
        first = FakePeer()
        first_task = asyncio.create_task(gateway.handle(first, loader))
        await _wait_sent(first, 1)

        second = FakePeer()
        await gateway.handle(second, loader)
        assert second.closed[0] == 4429

        await first.control(_subscribe())
        await _wait_sent(first, 2)
        await first.control({"gateway_v": 1, "op": "pong"})
        await first_task
        assert first.sent[-1]["code"] == "gateway.rate-limit"

        large_gateway, loader = _gateway(
            limits=GatewayLimits(max_message_bytes=64)
        )
        large = FakePeer()
        task = asyncio.create_task(large_gateway.handle(large, loader))
        await _wait_sent(large, 1)
        await large.incoming.put(
            {
                "type": "websocket.receive",
                "text": "x" * 65,
            }
        )
        await task
        assert large.sent[-1]["code"] == "gateway.message-too-large"
        assert large.closed[0] == 1009

    _run(scenario())


def test_limite_global_reserva_cupo_antes_de_autenticar():
    async def scenario():
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def slow_loader():
            calls.append(True)
            entered.set()
            release.wait(timeout=1)
            return USER

        gateway, _ = _gateway(limits=GatewayLimits(max_connections=1))
        first = FakePeer()
        first_task = asyncio.create_task(gateway.handle(first, slow_loader))
        await asyncio.to_thread(entered.wait, 0.5)

        second = FakePeer()
        await gateway.handle(second, slow_loader)
        assert second.closed[0] == 4429
        assert len(calls) == 1

        release.set()
        await _wait_sent(first, 1)
        await first.disconnect()
        await first_task
        assert gateway.stats()["active_connections"] == 0

    _run(scenario())


def test_ruta_fastapi_usa_identidad_del_servidor(monkeypatch):
    from core import app

    context = ModuleContext(
        "command_center",
        "modules/command_center",
        {},
        lambda _message: None,
    )
    module = CommandCenterModule(context)
    module._composer = _composer()
    module.gateway = CommandCenterGateway(module.event_bus, module._composer)
    monkeypatch.setitem(app.hub.modules_by_slug, "command-center", module)
    monkeypatch.setattr(app.auth, "current_user", lambda request: USER)

    client = TestClient(app.app)
    with client.websocket_connect(
        "/m/command-center/ws",
        headers={"origin": "http://testserver"},
    ) as websocket:
        ready = websocket.receive_json()
        assert ready["op"] == "ready"
        websocket.send_json(_subscribe())
        snapshot = websocket.receive_json()
        assert snapshot["subject"] == "user:7"
        assert "private@example.com" not in str(snapshot)


def test_health_declara_gateway_headless():
    context = ModuleContext(
        "command_center",
        "modules/command_center",
        {},
        lambda _message: None,
    )
    health = CommandCenterModule(context).health()
    assert health["gateway"]["status"] == "ready"
    assert health["gateway"]["active_connections"] == 0
    assert health["gateway"]["envelopes_sent"] == 0


def test_gateway_no_importa_bot_ejecutor_ni_dominios():
    path = Path(ROOT) / "modules" / "command_center" / "gateway.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    forbidden = (
        "modules.bot",
        "modules.trading",
        "modules.coinglass",
        "modules.coinsignals",
        "modules.journal",
    )
    assert not any(
        name == prefix or name.startswith(prefix + ".")
        for name in imports
        for prefix in forbidden
    )


def test_entrypoints_limitan_frames_antes_del_gateway():
    expected = "--ws-max-size 8192"
    for name in ("railway.json", "Procfile", "start.sh"):
        content = (Path(ROOT) / name).read_text(encoding="utf-8")
        assert expected in content
        assert "--ws-max-queue 32" in content
