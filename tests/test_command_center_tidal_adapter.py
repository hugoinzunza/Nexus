import asyncio

from modules.command_center import TidalAdapter as PublicAdapter
from modules.command_center.media_controller import (
    MediaAckStatus,
    MediaAction,
    MediaCapability,
    MediaCommand,
    MediaLifecycle,
)
from modules.command_center.operations import OperationContext
from modules.command_center.qobuz_adapter import DesktopPlaybackSnapshot
from modules.command_center.tidal_adapter import TidalAdapter

NOW = 1_800_000_000_000


def _run(coro):
    return asyncio.run(coro)


class RecordingPort:
    def __init__(self):
        self.running = False
        self.open_calls = 0
        self.effects = []
        self.known_playbacks = []
        self.snapshot = DesktopPlaybackSnapshot(
            "playing",
            "The Sweetest Taboo",
            "Sade",
            "EMAXSA VARIOS 1",
            "tidal:TRACK",
        )

    def helper_available(self):
        return True

    async def is_running(self, context):
        return self.running

    async def probe_app(self, context):
        return "2.43.0"

    async def open_app(self, context):
        self.open_calls += 1
        self.running = True

    async def current_state(self, context):
        return self.snapshot

    async def execute(self, action, context, known_playback=None):
        self.effects.append(action)
        self.known_playbacks.append(known_playback)


def test_tidal_declara_lectura_controles_y_apertura() -> None:
    async def scenario():
        port = RecordingPort()
        adapter = TidalAdapter(port, clock_ms=lambda: NOW)

        assert PublicAdapter is TidalAdapter
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
        unavailable = await adapter.health(OperationContext())
        assert unavailable.lifecycle is MediaLifecycle.UNAVAILABLE
        assert unavailable.code == "tidal.not-running"

        ack = await adapter.execute(
            MediaCommand("open-tidal", MediaAction.OPEN_APP, NOW),
            OperationContext(),
        )
        assert ack.code == "tidal.applied"
        assert port.open_calls == 1
        assert (await adapter.health(OperationContext())).lifecycle is (
            MediaLifecycle.READY
        )

    _run(scenario())


def test_tidal_proyecta_playback_y_control_del_puente_accesible() -> None:
    async def scenario():
        port = RecordingPort()
        port.running = True
        adapter = TidalAdapter(port, clock_ms=lambda: NOW)
        state = await adapter.current_state(OperationContext())
        assert state.playback == "playing"
        assert adapter.metadata(state.item_ref) == {
            "item_ref": "tidal:TRACK",
            "track": "The Sweetest Taboo",
            "artist": "Sade",
            "album": "EMAXSA VARIOS 1",
        }
        ack = await adapter.execute(
            MediaCommand("tidal-pause", MediaAction.PAUSE, NOW),
            OperationContext(),
        )
        assert ack.status is MediaAckStatus.APPLIED
        assert port.effects == [MediaAction.PAUSE]
        assert port.known_playbacks == ["playing"]

    _run(scenario())
