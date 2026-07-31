import asyncio

import pytest

from modules.command_center import TidalAdapter as PublicAdapter
from modules.command_center.media_controller import (
    MediaAction,
    MediaCapability,
    MediaCapabilityError,
    MediaCommand,
    MediaLifecycle,
)
from modules.command_center.operations import OperationContext
from modules.command_center.tidal_adapter import TidalAdapter

NOW = 1_800_000_000_000


def _run(coro):
    return asyncio.run(coro)


class RecordingPort:
    def __init__(self):
        self.running = False
        self.open_calls = 0

    async def is_running(self, context):
        return self.running

    async def probe_app(self, context):
        return "2.43.0"

    async def open_app(self, context):
        self.open_calls += 1
        self.running = True


def test_tidal_declara_solo_apertura_y_salud() -> None:
    async def scenario():
        port = RecordingPort()
        adapter = TidalAdapter(port, clock_ms=lambda: NOW)

        assert PublicAdapter is TidalAdapter
        assert adapter.capabilities() == frozenset({MediaCapability.OPEN_APP})
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


def test_tidal_no_inventa_playback_ni_metadatos() -> None:
    async def scenario():
        adapter = TidalAdapter(RecordingPort(), clock_ms=lambda: NOW)
        with pytest.raises(MediaCapabilityError):
            await adapter.current_state(OperationContext())
        with pytest.raises(MediaCapabilityError):
            await adapter.execute(
                MediaCommand("tidal-play", MediaAction.PLAY, NOW),
                OperationContext(),
            )

    _run(scenario())
