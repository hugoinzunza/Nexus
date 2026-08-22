import asyncio
import hashlib
import json
import subprocess
import threading
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
    MediaCommand,
)
from modules.command_center.media_surface import (
    MediaCommandsDisabled,
    MediaSurfaceService,
)
from modules.command_center.module import CommandCenterModule
from modules.command_center.module_registry import command_center_module_registry
from modules.command_center.operations import OperationContext


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
                "position_seconds": 92,
                "duration_seconds": 267,
                "progress": 92 / 267,
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
        assert result["position_seconds"] == 92.0
        assert result["duration_seconds"] == 267.0
        assert result["progress"] == pytest.approx(92 / 267)
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
            selected_provider: "qobuz",
            available_providers: ["apple-music", "qobuz", "tidal"],
            artwork_url: "/m/command-center/api/media-artwork?v=abc",
            position_seconds: 92,
            duration_seconds: 267,
            progress: 0.344,
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
    assert payload["qobuz"]["selectedProvider"] == "qobuz"
    assert payload["qobuz"]["availableProviders"] == [
        "apple-music", "qobuz", "tidal"
    ]
    assert payload["qobuz"]["artworkUrl"].endswith("?v=abc")
    assert payload["qobuz"]["positionSeconds"] == 92
    assert payload["qobuz"]["durationSeconds"] == 267
    assert payload["qobuz"]["progress"] == 0.344


def test_b7_expone_solo_el_post_multimedia_acotado() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert page.count('class="music-panel"') == 1
    assert 'class="telemetry-panel"' not in page
    assert page.count('class="music-control"') == 2
    assert page.count('class="music-control music-toggle"') == 1
    assert page.count('data-media-provider=') == 3
    music_panel = page.split('<section class="music-panel"', 1)[1].split(
        "</section>", 1
    )[0]
    music_header = music_panel.split('<header class="panel-header">', 1)[1].split(
        "</header>", 1
    )[0]
    assert 'class="media-provider-selector"' in music_header
    assert 'id="music-open"' in page
    assert 'id="music-artwork-image"' in page
    assert 'id="music-progress"' in page
    assert 'id="music-provider-label"' in page
    assert "/m/command-center/api/media-context" in script
    assert "/m/command-center/api/media-command" in script
    assert script.count('method: "POST"') == 1
    assert "Fixture sin efectos" in script
    assert "Sin pista cargada" in script
    assert "reproductor local" in script
    assert 'controls.toggle.hidden = !hasPlaybackControls' in script


def test_comando_http_usa_surface_y_rechaza_acciones_fuera_del_alcance() -> None:
    async def scenario():
        controller = FakeMediaController(clock_ms=lambda: NOW)
        module = object.__new__(CommandCenterModule)
        module.media_surface = MediaSurfaceService(
            controller,
            commands_enabled=True,
            clock_ms=lambda: NOW,
        )
        qobuz = FakeMediaController(
            controller_id="qobuz",
            capabilities={MediaCapability.OPEN_APP},
            clock_ms=lambda: NOW,
        )
        module.media_surfaces = {
            "apple-music": module.media_surface,
            "qobuz": MediaSurfaceService(
                qobuz,
                commands_enabled=True,
                clock_ms=lambda: NOW,
            ),
        }
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
        opened = await module.api_post(
            "media-command",
            {
                "command_id": "web-open-qobuz",
                "action": "open_app",
                "provider": "qobuz",
            },
            {},
            user={"uid": 1},
        )

        assert applied[0] == 200
        assert json.loads(applied[2])["status"] == "applied"
        assert forbidden[0] == 400
        assert opened[0] == 200
        assert controller.effects == [("web-play", MediaAction.PLAY)]
        assert qobuz.effects == [("web-open-qobuz", MediaAction.OPEN_APP)]

    _run(scenario())


def test_play_pausa_otro_proveedor_activo() -> None:
    async def scenario():
        apple = FakeMediaController(
            controller_id="apple-music",
            clock_ms=lambda: NOW,
        )
        tidal = FakeMediaController(
            controller_id="tidal",
            clock_ms=lambda: NOW,
        )
        await apple.execute(
            MediaCommand("start-apple", MediaAction.PLAY, NOW),
            OperationContext(),
        )
        module = object.__new__(CommandCenterModule)
        module.media_surfaces = {
            "apple-music": MediaSurfaceService(
                apple, commands_enabled=True, clock_ms=lambda: NOW
            ),
            "tidal": MediaSurfaceService(
                tidal, commands_enabled=True, clock_ms=lambda: NOW
            ),
        }
        module.context = type("Context", (), {"log": lambda *_args: None})()

        response = await module.api_post(
            "media-command",
            {
                "command_id": "switch-to-tidal",
                "action": "play",
                "provider": "tidal",
            },
            {},
            user={"uid": 1},
        )

        assert response[0] == 200
        assert apple.effects[-1] == (
            "switch-to-tidal.pause-apple-music",
            MediaAction.PAUSE,
        )
        assert tidal.effects == [("switch-to-tidal", MediaAction.PLAY)]

    _run(scenario())


def test_selector_lee_cada_proveedor_sin_cambiar_estado_global() -> None:
    module = object.__new__(CommandCenterModule)
    module.context = type("Context", (), {"log": lambda *_args: None})()
    module.media_surfaces = {
        provider: MediaSurfaceService(
            FakeMediaController(
                controller_id=provider,
                capabilities={MediaCapability.OPEN_APP},
                clock_ms=lambda: NOW,
            ),
            commands_enabled=True,
            clock_ms=lambda: NOW,
        )
        for provider in ("apple-music", "qobuz", "tidal")
    }

    qobuz = module.api(
        "media-context", {"provider": "qobuz"}, user={"id": 1}
    )
    tidal = module.api(
        "media-context", {"provider": "tidal"}, user={"id": 1}
    )

    assert json.loads(qobuz[2])["selected_provider"] == "qobuz"
    assert json.loads(tidal[2])["selected_provider"] == "tidal"


def test_selector_automatico_sigue_nueva_reproduccion_y_su_caratula() -> None:
    class Surface:
        def __init__(self, provider, playback, artwork_url=None):
            self.provider = provider
            self.playback = playback
            self.artwork_url = artwork_url

        async def snapshot(self):
            return {
                "provider": self.provider,
                "lifecycle": "ready",
                "playback": self.playback,
                "track": f"track-{self.provider}",
                "artist": f"artist-{self.provider}",
                "artwork_url": self.artwork_url,
            }

    module = object.__new__(CommandCenterModule)
    module.context = type("Context", (), {"log": lambda *_args: None})()
    module._media_selection_lock = threading.Lock()
    module._media_last_playback = {
        "apple-music": "unknown",
        "qobuz": "unknown",
        "tidal": "unknown",
    }
    module._active_media_provider = None
    module.media_surfaces = {
        "apple-music": Surface("apple-music", "paused"),
        "qobuz": Surface("qobuz", "paused", "/artwork-qobuz"),
        "tidal": Surface("tidal", "playing", "/artwork-tidal"),
    }

    first = module.api(
        "media-context",
        {"provider": "auto", "preferred": "tidal"},
        user={"id": 1},
    )
    module.media_surfaces["qobuz"].playback = "playing"
    module._invalidate_media_snapshot("qobuz")
    second = module.api(
        "media-context",
        {"provider": "auto", "preferred": "tidal"},
        user={"id": 1},
    )
    first_payload = json.loads(first[2])
    second_payload = json.loads(second[2])

    assert first_payload["selected_provider"] == "tidal"
    assert second_payload["selected_provider"] == "qobuz"
    assert second_payload["track"] == "track-qobuz"
    assert second_payload["artwork_url"] == "/artwork-qobuz"
    assert second_payload["selection_mode"] == "automatic"


def test_lecturas_concurrentes_comparten_un_snapshot_y_se_invalidan() -> None:
    class SlowSurface:
        def __init__(self):
            self.calls = 0
            self.lock = threading.Lock()

        async def snapshot(self):
            with self.lock:
                self.calls += 1
            await asyncio.sleep(0.05)
            return {
                "provider": "qobuz",
                "lifecycle": "ready",
                "playback": "paused",
            }

    module = object.__new__(CommandCenterModule)
    surface = SlowSurface()
    module.media_surfaces = {"qobuz": surface}
    module._media_snapshot_locks = {"qobuz": threading.Lock()}
    module._media_snapshot_cache = {}
    module._media_snapshot_ttl_seconds = 2.5
    barrier = threading.Barrier(6)
    results = []

    def read_snapshot():
        barrier.wait()
        results.append(module._cached_media_snapshot_sync("qobuz"))

    workers = [threading.Thread(target=read_snapshot) for _ in range(5)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=1)

    assert len(results) == 5
    assert surface.calls == 1
    module._invalidate_media_snapshot("qobuz")
    module._cached_media_snapshot_sync("qobuz")
    assert surface.calls == 2


def test_cliente_cambia_selector_pista_y_caratula_del_proveedor_activo() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      globalThis.location = {{ origin: "http://localhost" }};
      import({json.dumps(script_uri)}).then(async (module) => {{
        const responses = [
          {{
            selected_provider: "tidal", provider: "tidal",
            lifecycle: "ready", playback: "playing",
            track: "Lovin' You", artist: "Minnie Riperton",
            artwork_url: "/artwork-tidal"
          }},
          {{
            selected_provider: "qobuz", provider: "qobuz",
            lifecycle: "ready", playback: "playing",
            track: "Hombre Lobo", artist: "Los Abuelos De La Nada",
            artwork_url: "/artwork-qobuz"
          }}
        ];
        const urls = [];
        const client = new module.MediaContextClient({{
          fetcher: async (url) => {{
            urls.push(String(url));
            return {{ ok: true, json: async () => responses.shift() }};
          }}
        }});
        await client.refresh({{ detectActive: true }});
        const first = {{ provider: client.provider, ...client.context }};
        await client.refresh({{ detectActive: true }});
        process.stdout.write(JSON.stringify({{
          first,
          second: {{ provider: client.provider, ...client.context }},
          urls
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

    assert payload["first"]["provider"] == "tidal"
    assert payload["second"]["provider"] == "qobuz"
    assert payload["second"]["track"] == "Hombre Lobo"
    assert payload["second"]["artworkUrl"] == "/artwork-qobuz"
    assert all("provider=auto" in url for url in payload["urls"])


def test_cliente_espera_lectura_en_curso_antes_de_enviar_comando() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      globalThis.location = {{ origin: "http://localhost" }};
      import({json.dumps(script_uri)}).then(async (module) => {{
        let releaseRead;
        const calls = [];
        const context = {{
          selected_provider: "qobuz", provider: "qobuz",
          lifecycle: "ready", playback: "paused",
          commands_enabled: true, capabilities: ["current_state", "pause"]
        }};
        const client = new module.MediaContextClient({{
          fetcher: async (_url, options = {{}}) => {{
            const method = options.method || "GET";
            calls.push(method);
            if (calls.length === 1) {{
              return await new Promise((resolve) => {{ releaseRead = resolve; }});
            }}
            if (method === "POST") {{
              return {{
                ok: true,
                json: async () => ({{
                  status: "applied",
                  reconciled_state: context
                }})
              }};
            }}
            return {{ ok: true, json: async () => context }};
          }}
        }});
        const reading = client.refresh();
        await Promise.resolve();
        const command = client.execute("pause");
        await new Promise((resolve) => setTimeout(resolve, 0));
        const beforeRelease = [...calls];
        releaseRead({{ ok: true, json: async () => context }});
        await Promise.all([reading, command]);
        process.stdout.write(JSON.stringify({{ beforeRelease, calls }}));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["beforeRelease"] == ["GET"]
    assert payload["calls"] == ["GET", "POST", "GET"]


def test_endpoint_de_caratula_entrega_solo_imagen_local_acotada() -> None:
    class Apple:
        current_item_ref = "music:TRACK"

        async def artwork(self, context, expected_item_ref=None):
            assert expected_item_ref == self.current_item_ref
            return b"\x89PNG\r\n\x1a\ncover", "image/png"

    module = object.__new__(CommandCenterModule)
    module._apple_music = Apple()
    module.context = type("Context", (), {"log": lambda *_args: None})()

    version = hashlib.sha256(b"music:TRACK").hexdigest()[:16]
    response = module.api(
        "media-artwork", {"v": version}, user={"id": 1}
    )
    stale = module.api(
        "media-artwork", {"v": "0000000000000000"}, user={"id": 1}
    )

    assert response == (200, "image/png", b"\x89PNG\r\n\x1a\ncover")
    assert stale[0] == 404


def test_fixture_antiguo_no_congela_el_carrusel_live() -> None:
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert 'parameters.get("fixture_mode") === "1"' in script
    assert "}, 30_000);" in script
