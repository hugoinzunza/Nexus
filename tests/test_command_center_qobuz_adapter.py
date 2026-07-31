import asyncio
import ast
import sys
from pathlib import Path

import pytest

from modules.command_center import QobuzAdapter as PublicAdapter
from modules.command_center.conformance import (
    HeadlessIntegrationHarness,
    verify_media_controller,
)
from modules.command_center.media_controller import (
    MediaAckStatus,
    MediaAction,
    MediaCapability,
    MediaCapabilityError,
    MediaCommand,
    MediaCommandConflict,
    MediaLifecycle,
    MediaLifecycleError,
)
from modules.command_center.module_registry import ModuleLifecycle
from modules.command_center.operations import OperationContext
from modules.command_center.qobuz_adapter import (
    DesktopPlaybackSnapshot,
    OsaScriptQobuzPort,
    QobuzAdapter,
    QobuzPortError,
)

NOW = 1_785_430_000_000


def _run(coro):
    return asyncio.run(coro)


class RecordingPort:
    def __init__(self):
        self.running = True
        self.version = "8.2.0-b033"
        self.probe_calls = 0
        self.open_calls = 0
        self.running_error = None
        self.probe_error = None
        self.open_error = None
        self.helper = True
        self.snapshot = DesktopPlaybackSnapshot(
            "playing",
            "De Onda",
            "Bersuit Vergarabat",
            "Libertinaje",
            "qobuz:TRACK",
        )
        self.effects = []
        self.known_playbacks = []

    def helper_available(self):
        return self.helper

    async def is_running(self, context):
        if self.running_error:
            raise self.running_error
        return self.running

    async def probe_app(self, context):
        self.probe_calls += 1
        if self.probe_error:
            raise self.probe_error
        return self.version

    async def open_app(self, context):
        self.open_calls += 1
        if self.open_error:
            raise self.open_error
        self.running = True

    async def current_state(self, context):
        return self.snapshot

    async def execute(self, action, context, known_playback=None):
        self.effects.append(action)
        self.known_playbacks.append(known_playback)


def _command(command_id="qobuz-1", *, issued_at_ms=NOW):
    return MediaCommand(
        command_id,
        MediaAction.OPEN_APP,
        issued_at_ms,
    )


def test_adapter_publico_declara_capacidades_del_puente_accesible():
    port = RecordingPort()
    adapter = QobuzAdapter(port, clock_ms=lambda: NOW)
    assert PublicAdapter is QobuzAdapter
    assert adapter.capabilities() == frozenset(
        {
            MediaCapability.CURRENT_STATE,
            MediaCapability.PLAY,
            MediaCapability.PAUSE,
            MediaCapability.NEXT,
            MediaCapability.PREVIOUS,
            MediaCapability.OPEN_APP,
        }
    )
    assert port.open_calls == 0
    assert port.probe_calls == 0


def test_health_distingue_ready_unavailable_degraded_y_revoked():
    async def scenario():
        port = RecordingPort()
        adapter = QobuzAdapter(port, clock_ms=lambda: NOW)
        ready = await adapter.health(OperationContext())
        assert ready.lifecycle is MediaLifecycle.READY
        assert port.probe_calls == 1
        assert adapter.stats()["app_version"] == "8.2.0-b033"

        port.running = False
        unavailable = await adapter.health(OperationContext())
        assert unavailable.lifecycle is MediaLifecycle.UNAVAILABLE
        assert unavailable.code == "qobuz.not-running"
        assert adapter.stats()["app_version"] is None
        assert adapter.stats()["last_error_code"] is None

        port.running = True
        port.probe_error = QobuzPortError(
            "qobuz.probe-failed",
            "fallo",
            retryable=True,
        )
        degraded = await adapter.health(OperationContext())
        assert degraded.lifecycle is MediaLifecycle.DEGRADED
        assert degraded.retryable is True
        assert adapter.stats()["app_version"] is None

        port.probe_error = QobuzPortError(
            "qobuz.permission-denied",
            "denegado",
            retryable=False,
        )
        revoked = await adapter.health(OperationContext())
        assert revoked.lifecycle is MediaLifecycle.REVOKED
        assert revoked.retryable is False

    _run(scenario())


def test_current_state_y_playback_provienen_del_puente_local():
    async def scenario():
        port = RecordingPort()
        adapter = QobuzAdapter(port, clock_ms=lambda: NOW)
        state = await adapter.current_state(OperationContext())
        assert state.playback == "playing"
        assert state.item_ref == "qobuz:TRACK"
        assert adapter.metadata(state.item_ref) == {
            "item_ref": "qobuz:TRACK",
            "track": "De Onda",
            "artist": "Bersuit Vergarabat",
            "album": "Libertinaje",
        }
        for action in (
            MediaAction.PLAY,
            MediaAction.PAUSE,
            MediaAction.NEXT,
            MediaAction.PREVIOUS,
        ):
            ack = await adapter.execute(
                MediaCommand(f"qobuz-{action.value}", action, NOW),
                OperationContext(),
            )
            assert ack.status is MediaAckStatus.APPLIED
        assert port.effects == [
            MediaAction.PLAY,
            MediaAction.PAUSE,
            MediaAction.NEXT,
            MediaAction.PREVIOUS,
        ]
        assert port.known_playbacks == ["playing", "playing", None, None]
        with pytest.raises(MediaCapabilityError):
            await adapter.execute(
                MediaCommand(
                    "unsupported-volume",
                    MediaAction.SET_VOLUME,
                    NOW,
                    {"volume": 0.5},
                ),
                OperationContext(),
            )

    _run(scenario())


def test_open_app_es_explicito_idempotente_y_detecta_conflicto():
    async def scenario():
        port = RecordingPort()
        port.running = False
        adapter = QobuzAdapter(port, clock_ms=lambda: NOW)
        command = _command()
        first = await adapter.execute(command, OperationContext())
        second = await adapter.execute(command, OperationContext())
        assert first.status is MediaAckStatus.APPLIED
        assert second is first
        assert port.open_calls == 1
        assert adapter.stats()["cache_hits"] == 1

        with pytest.raises(MediaCommandConflict):
            await adapter.execute(
                _command(issued_at_ms=NOW + 1),
                OperationContext(),
            )

    _run(scenario())


def test_timeout_ambiguo_se_conserva_sin_repetir_apertura():
    async def scenario():
        port = RecordingPort()
        port.open_error = QobuzPortError(
            "qobuz.timeout",
            "timeout",
            retryable=True,
            ambiguous=True,
        )
        adapter = QobuzAdapter(port, clock_ms=lambda: NOW)
        command = _command("qobuz-timeout")
        first = await adapter.execute(command, OperationContext())
        port.open_error = None
        second = await adapter.execute(command, OperationContext())
        assert first.status is MediaAckStatus.UNKNOWN
        assert second is first
        assert port.open_calls == 1
        assert adapter.stats()["unknown_results"] == 1

    _run(scenario())


def test_close_no_cierra_qobuz_y_bloquea_el_adaptador():
    async def scenario():
        port = RecordingPort()
        adapter = QobuzAdapter(port, clock_ms=lambda: NOW)
        await adapter.close(OperationContext())
        assert port.running is True
        assert (
            await adapter.health(OperationContext())
        ).lifecycle is MediaLifecycle.CLOSED
        with pytest.raises(MediaLifecycleError):
            await adapter.current_state(OperationContext())
        with pytest.raises(MediaLifecycleError):
            await adapter.execute(_command(), OperationContext())

    _run(scenario())


def test_supera_harness_con_estado_y_controles_accesibles():
    async def scenario():
        read_port = RecordingPort()
        read_report = await verify_media_controller(
            QobuzAdapter(read_port, clock_ms=lambda: NOW)
        )
        assert read_report.operations == ("health", "current_state")
        assert read_port.open_calls == 0

        command_port = RecordingPort()
        command_report = await verify_media_controller(
            QobuzAdapter(command_port, clock_ms=lambda: NOW),
            include_commands=True,
        )
        assert command_report.operations == (
            "health",
            "current_state",
            "play",
            "pause",
            "next",
            "previous",
            "open_app",
        )
        assert command_port.open_calls == 1

    _run(scenario())


def test_registro_conserva_degradacion_y_recuperacion():
    async def scenario():
        port = RecordingPort()
        port.running = False
        adapter = QobuzAdapter(port, clock_ms=lambda: NOW)
        harness = HeadlessIntegrationHarness(
            media_factory=lambda: adapter,
            media_capabilities=adapter.capabilities(),
        )
        await harness.start()
        unavailable = harness.registry.status("media.controller")
        assert unavailable.lifecycle is ModuleLifecycle.DEGRADED
        assert unavailable.code == "qobuz.not-running"

        port.running = True
        await harness.registry.refresh_health()
        recovered = harness.registry.status("media.controller")
        assert recovered.lifecycle is ModuleLifecycle.READY
        assert recovered.code == "media.available"
        await harness.shutdown()

    _run(scenario())


def test_puerto_real_usa_agente_fijo_sin_shell_ni_api_remota():
    path = (
        Path(__file__).parents[1]
        / "modules"
        / "command_center"
        / "qobuz_adapter.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }
    assert "create_subprocess_exec" in calls
    assert "create_subprocess_shell" not in calls
    assert "shell=True" not in source
    assert 'OSASCRIPT = "/usr/bin/osascript"' in source
    assert 'OPEN = "/usr/bin/open"' in source
    assert "requests." not in source
    assert "qobuz-connect" not in source.lower()
    assert "api.qobuz" not in source.lower()
    assert '"--media-server"' in source
    assert '"kind": "state"' in source
    assert '"kind": "command"' in source
    assert OsaScriptQobuzPort is not None


def test_puerto_reutiliza_helper_persistente_y_lo_cierra(tmp_path):
    helper = tmp_path / "fake-media-agent"
    helper.write_text(
        f"""#!{sys.executable}
import json
import os
import sys

for line in sys.stdin:
    request = json.loads(line)
    if request["kind"] == "state":
        payload = {{
            "playback": "paused",
            "track": "Hombre Lobo",
            "artist": "Los Abuelos De La Nada",
            "album": "Himno De Mi Corazon",
            "item_ref": f"qobuz:{{os.getpid()}}",
        }}
    else:
        payload = {{"status": "applied", "code": "qobuz.applied"}}
    print(json.dumps(payload), flush=True)
""",
        encoding="utf-8",
    )
    helper.chmod(0o755)

    port = OsaScriptQobuzPort(helper)
    first = _run(port.current_state(OperationContext.with_timeout(2)))
    second = _run(port.current_state(OperationContext.with_timeout(2)))
    _run(
        port.execute(
            MediaAction.PLAY,
            OperationContext.with_timeout(2),
            known_playback="paused",
        )
    )
    assert first.item_ref == second.item_ref
    assert port._agent_process is not None
    process = port._agent_process
    _run(port.close_helper())
    assert port._agent_process is None
    assert process.poll() is not None



def test_discovery_y_limites_quedan_documentados():
    root = Path(__file__).parents[1]
    rfc = (root / "docs" / "RFC_COMMAND_CENTER.md").read_text(
        encoding="utf-8"
    )
    log = (root / "docs" / "VALIDATION_LOG.md").read_text(
        encoding="utf-8"
    )
    assert "adaptador Qobuz conserva la limitación oficial" in rfc
    assert "VAL-0015 — Qobuz Adapter capability-limited" in log
    assert "aplicaciones de terceros no están soportadas" in log
    assert "VAL-0026 — Puente multimedia accesible Qobuz/TIDAL" in log
