import asyncio
import ast
from pathlib import Path

import pytest

from modules.command_center import AppleMusicAdapter as PublicAdapter
from modules.command_center.apple_music_adapter import (
    AppleMusicAdapter,
    AppleMusicPortError,
    AppleMusicSnapshot,
    OsaScriptAppleMusicPort,
)
from modules.command_center.conformance import (
    HeadlessIntegrationHarness,
    verify_media_controller,
)
from modules.command_center.media_controller import (
    MediaAckStatus,
    MediaAction,
    MediaCapability,
    MediaCommand,
    MediaCommandConflict,
    MediaLifecycle,
    MediaLifecycleError,
)
from modules.command_center.module_registry import ModuleLifecycle
from modules.command_center.operations import OperationContext

NOW = 1_785_430_000_000


def _run(coro):
    return asyncio.run(coro)


class RecordingPort:
    def __init__(self):
        self.running = True
        self.snapshot = AppleMusicSnapshot(
            "playing",
            0.42,
            12.5,
            "ABC123",
        )
        self.actions = []
        self.open_calls = 0
        self.error = None
        self.probe_error = None
        self.probe_calls = 0
        self.execute_delay = 0
        self.artwork = (b"\xff\xd8\xffcover", "image/jpeg")

    async def is_running(self, context):
        if self.error:
            raise self.error
        return self.running

    async def probe_playback_access(self, context):
        self.probe_calls += 1
        if self.probe_error:
            raise self.probe_error

    async def current_state(self, context):
        if self.error:
            raise self.error
        return self.snapshot

    async def execute(self, action, arguments, context):
        if self.error:
            raise self.error
        if self.execute_delay:
            await asyncio.sleep(self.execute_delay)
        self.actions.append((action, dict(arguments)))

    async def open_app(self, context):
        if self.error:
            raise self.error
        self.open_calls += 1
        self.running = True

    async def current_artwork(self, persistent_id, context):
        assert persistent_id == "ABC123"
        return self.artwork


def _command(
    command_id="cmd-1",
    action=MediaAction.PLAY,
    *,
    arguments=None,
    issued_at_ms=NOW,
):
    return MediaCommand(command_id, action, issued_at_ms, arguments)


def test_adapter_publico_declara_capacidades_reales():
    adapter = AppleMusicAdapter(RecordingPort(), clock_ms=lambda: NOW)
    assert PublicAdapter is AppleMusicAdapter
    assert adapter.capabilities() == frozenset(MediaCapability)


def test_metadata_y_caratula_se_exponen_fuera_de_media_controller():
    async def scenario():
        port = RecordingPort()
        port.snapshot = AppleMusicSnapshot(
            "playing",
            0.42,
            12.5,
            "ABC123",
            "Song",
            "Artist",
            "Album",
            True,
        )
        adapter = AppleMusicAdapter(port, clock_ms=lambda: NOW)

        state = await adapter.current_state(OperationContext())
        metadata = adapter.metadata(state.item_ref)
        artwork = await adapter.artwork(OperationContext())

        assert metadata == {
            "item_ref": "music:ABC123",
            "track": "Song",
            "artist": "Artist",
            "album": "Album",
            "has_artwork": True,
        }
        assert artwork == (b"\xff\xd8\xffcover", "image/jpeg")

    _run(scenario())


def test_health_distingue_ready_unavailable_revoked_y_closed():
    async def scenario():
        port = RecordingPort()
        adapter = AppleMusicAdapter(port, clock_ms=lambda: NOW)
        assert (await adapter.health(OperationContext())).lifecycle is (
            MediaLifecycle.READY
        )
        port.running = False
        unavailable = await adapter.health(OperationContext())
        assert unavailable.lifecycle is MediaLifecycle.UNAVAILABLE
        assert unavailable.code == "apple-music.not-running"
        port.error = AppleMusicPortError(
            "apple-music.permission-denied",
            "denegado",
            retryable=False,
        )
        revoked = await adapter.health(OperationContext())
        assert revoked.lifecycle is MediaLifecycle.REVOKED
        await adapter.close(OperationContext())
        assert (await adapter.health(OperationContext())).lifecycle is (
            MediaLifecycle.CLOSED
        )
        assert port.probe_calls == 1

    _run(scenario())


def test_health_no_declara_ready_si_acceso_playback_esta_bloqueado():
    async def scenario():
        port = RecordingPort()
        port.probe_error = AppleMusicPortError(
            "apple-music.timeout",
            "permiso pendiente",
            retryable=True,
            ambiguous=True,
        )
        adapter = AppleMusicAdapter(port, clock_ms=lambda: NOW)
        health = await adapter.health(OperationContext())
        assert health.lifecycle is MediaLifecycle.DEGRADED
        assert health.code == "apple-music.timeout"
        assert health.retryable is True
        assert adapter.stats()["permission_probes"] == 1

    _run(scenario())


def test_current_state_no_abre_app_y_normaliza_item_ref():
    async def scenario():
        port = RecordingPort()
        adapter = AppleMusicAdapter(port, clock_ms=lambda: NOW)
        state = await adapter.current_state(OperationContext())
        assert state.lifecycle is MediaLifecycle.READY
        assert state.playback == "playing"
        assert state.volume == 0.42
        assert state.item_ref == "music:ABC123"
        assert port.open_calls == 0
        port.running = False
        stopped = await adapter.current_state(OperationContext())
        assert stopped.lifecycle is MediaLifecycle.UNAVAILABLE
        assert stopped.playback == "stopped"
        assert port.open_calls == 0

    _run(scenario())


@pytest.mark.parametrize(
    ("action", "arguments"),
    [
        (MediaAction.PLAY, None),
        (MediaAction.PAUSE, None),
        (MediaAction.NEXT, None),
        (MediaAction.PREVIOUS, None),
        (MediaAction.SET_VOLUME, {"volume": 0.25}),
    ],
)
def test_comandos_se_delegan_y_son_idempotentes(action, arguments):
    async def scenario():
        port = RecordingPort()
        adapter = AppleMusicAdapter(port, clock_ms=lambda: NOW)
        command = _command(action=action, arguments=arguments)
        first = await adapter.execute(command, OperationContext())
        second = await adapter.execute(command, OperationContext())
        assert first.status is MediaAckStatus.APPLIED
        assert second is first
        assert port.actions == [(action, dict(arguments or {}))]
        assert adapter.stats()["cache_hits"] == 1

    _run(scenario())


def test_open_app_es_explicito_y_no_ocurre_al_construir():
    async def scenario():
        port = RecordingPort()
        port.running = False
        adapter = AppleMusicAdapter(port, clock_ms=lambda: NOW)
        assert port.open_calls == 0
        ack = await adapter.execute(
            _command(action=MediaAction.OPEN_APP),
            OperationContext(),
        )
        assert ack.status is MediaAckStatus.APPLIED
        assert port.open_calls == 1

    _run(scenario())


def test_app_cerrada_rechaza_control_sin_arrancarla():
    async def scenario():
        port = RecordingPort()
        port.running = False
        adapter = AppleMusicAdapter(port, clock_ms=lambda: NOW)
        ack = await adapter.execute(_command(), OperationContext())
        assert ack.status is MediaAckStatus.REJECTED
        assert ack.code == "apple-music.not-running"
        assert ack.retryable is True
        assert port.actions == []
        assert port.open_calls == 0

    _run(scenario())


def test_timeout_ambiguo_no_repite_un_comando_con_efecto():
    async def scenario():
        port = RecordingPort()
        port.error = AppleMusicPortError(
            "apple-music.timeout",
            "timeout",
            retryable=True,
            ambiguous=True,
        )
        adapter = AppleMusicAdapter(port, clock_ms=lambda: NOW)
        command = _command(action=MediaAction.NEXT)
        first = await adapter.execute(command, OperationContext())
        port.error = None
        second = await adapter.execute(command, OperationContext())
        assert first.status is MediaAckStatus.UNKNOWN
        assert second is first
        assert port.actions == []
        assert adapter.stats()["unknown_results"] == 1

    _run(scenario())


def test_reintentos_concurrentes_ejecutan_un_solo_efecto():
    async def scenario():
        port = RecordingPort()
        port.execute_delay = 0.01
        adapter = AppleMusicAdapter(port, clock_ms=lambda: NOW)
        command = _command()
        first, second = await asyncio.gather(
            adapter.execute(command, OperationContext()),
            adapter.execute(command, OperationContext()),
        )
        assert first is second
        assert port.actions == [(MediaAction.PLAY, {})]
        assert adapter.stats()["commands"] == 1
        assert adapter.stats()["cache_hits"] == 1

    _run(scenario())


def test_reutilizar_command_id_con_otro_payload_falla_cerrado():
    async def scenario():
        adapter = AppleMusicAdapter(
            RecordingPort(),
            clock_ms=lambda: NOW,
        )
        await adapter.execute(_command(), OperationContext())
        with pytest.raises(MediaCommandConflict):
            await adapter.execute(
                _command(action=MediaAction.PAUSE),
                OperationContext(),
            )

    _run(scenario())


def test_close_no_cierra_music_y_bloquea_operaciones_nuevas():
    async def scenario():
        port = RecordingPort()
        adapter = AppleMusicAdapter(port, clock_ms=lambda: NOW)
        await adapter.close(OperationContext())
        assert port.running is True
        with pytest.raises(MediaLifecycleError):
            await adapter.current_state(OperationContext())
        with pytest.raises(MediaLifecycleError):
            await adapter.execute(_command(), OperationContext())

    _run(scenario())


def test_adapter_supera_harness_read_only_y_con_comandos_falsos():
    async def scenario():
        read_port = RecordingPort()
        read_report = await verify_media_controller(
            AppleMusicAdapter(read_port, clock_ms=lambda: NOW)
        )
        assert read_report.operations == ("health", "current_state")
        assert read_port.actions == []
        assert read_port.open_calls == 0

        command_port = RecordingPort()
        command_report = await verify_media_controller(
            AppleMusicAdapter(command_port, clock_ms=lambda: NOW),
            include_commands=True,
        )
        assert set(command_report.operations) == {
            "health",
            "current_state",
            "play",
            "pause",
            "next",
            "previous",
            "set_volume",
            "open_app",
        }

    _run(scenario())


def test_registro_conserva_runtime_degradado_y_observa_recuperacion():
    async def scenario():
        port = RecordingPort()
        port.running = False
        adapter = AppleMusicAdapter(port, clock_ms=lambda: NOW)
        harness = HeadlessIntegrationHarness(
            media_factory=lambda: adapter,
            media_capabilities=adapter.capabilities(),
        )
        await harness.start()
        degraded = harness.registry.status("media.controller")
        assert degraded.lifecycle is ModuleLifecycle.DEGRADED
        assert degraded.code == "apple-music.not-running"

        port.running = True
        await harness.registry.refresh_health()
        recovered = harness.registry.status("media.controller")
        assert recovered.lifecycle is ModuleLifecycle.READY
        assert recovered.code == "media.available"
        await harness.shutdown()

    _run(scenario())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "playing\x1f42\x1f12.5\x1fABC123\x1fSong\x1fArtist\x1fAlbum\x1f1\n",
            AppleMusicSnapshot(
                "playing", 0.42, 12.5, "ABC123",
                "Song", "Artist", "Album", True,
            ),
        ),
        (
            "fast forwarding\x1f100\x1f0\x1f\x1f\x1f\x1f\x1f0\n",
            AppleMusicSnapshot("fast_forwarding", 1.0, 0.0, None),
        ),
        (
            "stopped\x1f70\x1fmissing value\x1f\x1f\x1f\x1f\x1f0\n",
            AppleMusicSnapshot("stopped", 0.7, None, None),
        ),
        (
            "paused\x1f70\x1f12,5\x1fID\x1fSong\x1fArtist\x1fAlbum\x1f0\n",
            AppleMusicSnapshot(
                "paused", 0.7, 12.5, "ID", "Song", "Artist", "Album",
            ),
        ),
    ],
)
def test_parser_del_snapshot_real_es_determinista(raw, expected):
    assert OsaScriptAppleMusicPort._parse_snapshot(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "playing\x1f42\x1f12.5\n",
        "unknown\x1f42\x1f12.5\x1fABC\x1fS\x1fA\x1fL\x1f1\n",
        "playing\x1f101\x1f12.5\x1fABC\x1fS\x1fA\x1fL\x1f1\n",
        "playing\x1f42\x1f-1\x1fABC\x1fS\x1fA\x1fL\x1f1\n",
    ],
)
def test_parser_rechaza_snapshots_incompletos_o_fuera_de_rango(raw):
    with pytest.raises(AppleMusicPortError) as raised:
        OsaScriptAppleMusicPort._parse_snapshot(raw)
    assert raised.value.code == "apple-music.invalid-snapshot"


def test_puerto_real_no_usa_shell_ni_entrada_libre():
    root = Path(__file__).parents[1]
    path = (
        root
        / "modules"
        / "command_center"
        / "apple_music_adapter.py"
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


def test_fase_a5_queda_headless_y_sin_autorizar_factory():
    root = Path(__file__).parents[1]
    rfc = (root / "docs" / "RFC_COMMAND_CENTER.md").read_text(
        encoding="utf-8"
    )
    assert "Fase A.5 activa" in rfc
    assert "El primer incremento seleccionado es Apple Music" in rfc
    assert "factories productivas y despliegues" in rfc
