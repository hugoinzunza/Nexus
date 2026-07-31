import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from modules.command_center.contracts import CONTRACT_V1_FINGERPRINT
from modules.command_center.apple_music_adapter import (
    AppleMusicAdapter,
    AppleMusicSnapshot,
)
from modules.command_center.fake_adapters import FakeMediaController
from modules.command_center.media_controller import (
    MediaAckStatus,
    MediaAction,
    MediaCapability,
)
from modules.command_center.media_surface import (
    MediaCommandsDisabled,
    MediaSurfaceService,
)
from modules.command_center.module import CommandCenterModule
from modules.command_center.module_registry import command_center_module_registry


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "modules" / "command_center" / "public"
NOW = 1_800_000_000_000


def _run(coro):
    return asyncio.run(coro)


def test_snapshot_expone_estado_y_metadata_sin_ampliar_media_controller() -> None:
    async def scenario():
        controller = FakeMediaController(
            controller_id="apple-music",
            clock_ms=lambda: NOW,
        )
        surface = MediaSurfaceService(
            controller,
            clock_ms=lambda: NOW,
            metadata_resolver=lambda ref: {
                "track": "Midnight City",
                "artist": "M83",
                "album": "Hurry Up, We're Dreaming",
                "ignored": "no se publica",
            },
        )
        result = await surface.snapshot()
        assert result["provider"] == "apple-music"
        assert result["lifecycle"] == "ready"
        assert result["playback"] == "paused"
        assert result["freshness"] == "live"
        assert result["track"] == "Midnight City"
        assert result["artist"] == "M83"
        assert result["album"] == "Hurry Up, We're Dreaming"
        assert "ignored" not in result
        assert result["commands_enabled"] is False
        assert result["read_only"] is True

    _run(scenario())


def test_comandos_estan_bloqueados_por_defecto_sin_efectos() -> None:
    async def scenario():
        controller = FakeMediaController(clock_ms=lambda: NOW)
        surface = MediaSurfaceService(controller, clock_ms=lambda: NOW)
        with pytest.raises(MediaCommandsDisabled):
            await surface.execute(
                command_id="b7-play",
                action=MediaAction.PLAY,
            )
        assert controller.effects == []

    _run(scenario())


def test_comandos_fake_preservan_idempotencia_y_ack() -> None:
    async def scenario():
        controller = FakeMediaController(clock_ms=lambda: NOW)
        surface = MediaSurfaceService(
            controller,
            commands_enabled=True,
            clock_ms=lambda: NOW,
        )
        first, second = await asyncio.gather(
            surface.execute(command_id="b7-play", action=MediaAction.PLAY),
            surface.execute(command_id="b7-play", action=MediaAction.PLAY),
        )
        assert first["status"] == "applied"
        assert second == first
        assert controller.effects == [("b7-play", MediaAction.PLAY)]

    _run(scenario())


def test_play_abre_music_cerrada_y_reproduce_con_un_solo_gesto() -> None:
    class Port:
        def __init__(self):
            self.running = False
            self.open_calls = 0
            self.actions = []

        async def is_running(self, context):
            return self.running

        async def probe_playback_access(self, context):
            return None

        async def current_state(self, context):
            return AppleMusicSnapshot("paused", 0.5, 0, "TRACK")

        async def execute(self, action, arguments, context):
            self.actions.append(action)

        async def open_app(self, context):
            self.open_calls += 1
            self.running = True

    async def scenario():
        port = Port()
        controller = AppleMusicAdapter(port, clock_ms=lambda: NOW)
        surface = MediaSurfaceService(
            controller,
            commands_enabled=True,
            clock_ms=lambda: NOW,
        )

        first = await surface.execute(
            command_id="start-music",
            action=MediaAction.PLAY,
        )
        second = await surface.execute(
            command_id="start-music",
            action=MediaAction.PLAY,
        )

        assert first["status"] == "applied"
        assert second == first
        assert port.open_calls == 1
        assert port.actions == [MediaAction.PLAY]

    _run(scenario())


def test_ack_unknown_se_reconcilia_con_lectura_sin_repetir_efecto() -> None:
    async def scenario():
        controller = FakeMediaController(clock_ms=lambda: NOW)
        controller.return_next(MediaAckStatus.UNKNOWN)
        surface = MediaSurfaceService(
            controller,
            commands_enabled=True,
            clock_ms=lambda: NOW,
        )
        result = await surface.execute(
            command_id="b7-next",
            action=MediaAction.NEXT,
        )
        assert result["status"] == "unknown"
        assert result["reconciled_state"]["playback"] == "paused"
        assert controller.effects == []
        assert [call[0] for call in controller.calls].count("execute") == 1
        assert [call[0] for call in controller.calls].count("current_state") == 1

    _run(scenario())


def test_proveedor_parcial_no_inventa_estado_ni_controles() -> None:
    async def scenario():
        controller = FakeMediaController(
            controller_id="qobuz",
            capabilities={MediaCapability.OPEN_APP},
            clock_ms=lambda: NOW,
        )
        result = await MediaSurfaceService(
            controller,
            clock_ms=lambda: NOW,
        ).snapshot()
        assert result["provider"] == "qobuz"
        assert result["playback"] == "unknown"
        assert result["track"] is None
        assert result["capabilities"] == ["open_app"]

    _run(scenario())


def test_endpoint_real_permanece_inactivo_sin_factory() -> None:
    module = object.__new__(CommandCenterModule)
    module.media_surface = MediaSurfaceService(clock_ms=lambda: NOW)
    module.context = type("Context", (), {"log": lambda *_args: None})()

    response = module.api("media-context", {}, user={"id": 1})
    payload = json.loads(response[2])

    assert response[0] == 200
    assert payload["code"] == "media.factory-inactive"
    assert payload["commands_enabled"] is False
    assert payload["read_only"] is True
    assert command_center_module_registry().stats()["attached_factories"] == 0
    assert CONTRACT_V1_FINGERPRINT == (
        "b0a8a7efa623a1aae4b681c3cfc42790d36a6a14fbc689688026c523f2e49b46"
    )


def test_frontend_normaliza_capacidades_y_no_habilita_comandos_por_defecto() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        process.stdout.write(JSON.stringify({{
          empty: module.normalizeMediaContext(null),
          qobuz: module.normalizeMediaContext({{
            provider: "qobuz", lifecycle: "ready",
            capabilities: ["open_app", "invented"],
            commands_enabled: false
          }})
        }}));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["empty"]["commandsEnabled"] is False
    assert payload["empty"]["lifecycle"] == "unknown"
    assert payload["qobuz"]["capabilities"] == ["open_app"]


def test_b7_expone_solo_el_post_multimedia_acotado() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert page.count('class="music-panel"') == 1
    assert 'class="telemetry-panel"' not in page
    assert page.count('class="music-control"') == 3
    assert "/m/command-center/api/media-context" in script
    assert "/m/command-center/api/media-command" in script
    assert script.count('method: "POST"') == 1
    assert "Fixture sin efectos" in script
    assert "Sin pista cargada" in script


def test_comando_http_usa_surface_y_rechaza_acciones_fuera_del_alcance() -> None:
    async def scenario():
        controller = FakeMediaController(clock_ms=lambda: NOW)
        module = object.__new__(CommandCenterModule)
        module.media_surface = MediaSurfaceService(
            controller,
            commands_enabled=True,
            clock_ms=lambda: NOW,
        )
        module.context = type("Context", (), {"log": lambda *_args: None})()

        applied = await module.api_post(
            "media-command",
            {"command_id": "web-play", "action": "play"},
            {},
            user={"uid": 1},
        )
        forbidden = await module.api_post(
            "media-command",
            {"command_id": "web-volume", "action": "set_volume"},
            {},
            user={"uid": 1},
        )

        assert applied[0] == 200
        assert json.loads(applied[2])["status"] == "applied"
        assert forbidden[0] == 400
        assert controller.effects == [("web-play", MediaAction.PLAY)]

    _run(scenario())


def test_fixture_antiguo_no_congela_el_carrusel_live() -> None:
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert 'parameters.get("fixture_mode") === "1"' in script
    assert "}, 30_000);" in script
