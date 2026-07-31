import threading
import time
import urllib.parse

from modules.command_center.external_artwork import ExternalArtworkResolver
from modules.command_center.module import CommandCenterModule


MBID_A = "734dbef9-fc99-397d-bab0-24b9773d5afc"
MBID_B = "7af8e4d1-1a6b-4cb4-892f-4a003065bcbe"


def _recording(*releases):
    return {
        "score": 100,
        "title": "De onda",
        "artist-credit": [{"name": "Bersuit Vergarabat"}],
        "releases": [
            {
                "title": title,
                "release-group": {"id": mbid, "title": title},
            }
            for title, mbid in releases
        ],
    }


def test_resuelve_album_exacto_y_cachea_imagen_validada() -> None:
    calls = []

    def fetch_json(url):
        calls.append(("json", url))
        return {
            "recordings": [
                _recording(
                    ("Libertinaje 25 Años", MBID_B),
                    ("Libertinaje", MBID_A),
                )
            ]
        }

    def fetch_image(url):
        calls.append(("image", url))
        return b"\xff\xd8\xffcover", "image/jpeg"

    resolver = ExternalArtworkResolver(
        fetch_json=fetch_json,
        fetch_image=fetch_image,
    )
    arguments = {
        "provider": "qobuz",
        "item_ref": "qobuz:TRACK",
        "track": "De Onda",
        "artist": "Bersuit Vergarabat",
        "album": "Libertinaje",
    }
    first = resolver.resolve(**arguments)
    second = resolver.resolve(**arguments)

    assert first == second
    assert first.startswith(
        "/m/command-center/api/media-artwork?provider=qobuz&v="
    )
    parsed = urllib.parse.parse_qs(urllib.parse.urlsplit(first).query)
    assert resolver.artwork("qobuz", parsed["v"][0]) == (
        b"\xff\xd8\xffcover",
        "image/jpeg",
    )
    assert [kind for kind, _url in calls] == ["json", "image"]
    assert calls[1][1].endswith(f"/{MBID_A}/front-500")


def test_rechaza_resultado_ambiguo_si_album_no_coincide() -> None:
    image_calls = []
    resolver = ExternalArtworkResolver(
        fetch_json=lambda _url: {
            "recordings": [
                _recording(("Album A", MBID_A), ("Album B", MBID_B))
            ]
        },
        fetch_image=lambda url: image_calls.append(url),
    )

    result = resolver.resolve(
        provider="tidal",
        item_ref="tidal:TRACK",
        track="De Onda",
        artist="Bersuit Vergarabat",
        album="Playlist ajena",
    )

    assert result is None
    assert image_calls == []


def test_acepta_solo_fallback_univoco_para_playlist_de_tidal() -> None:
    resolver = ExternalArtworkResolver(
        fetch_json=lambda _url: {
            "recordings": [_recording(("Libertinaje", MBID_A))]
        },
        fetch_image=lambda _url: (b"\x89PNG\r\n\x1a\ncover", "image/png"),
    )

    result = resolver.resolve(
        provider="tidal",
        item_ref="tidal:TRACK",
        track="De Onda",
        artist="Bersuit Vergarabat",
        album="Mi playlist",
    )

    assert "provider=tidal" in result


def test_playlist_tidal_prefiere_album_publicado_por_el_artista() -> None:
    payload = {
        "recordings": [
            {
                "score": 100,
                "title": "Lovin' You",
                "artist-credit": [{"name": "Minnie Riperton"}],
                "releases": [
                    {
                        "title": "Love Compilation",
                        "date": "1975",
                        "artist-credit": [{"name": "Various Artists"}],
                        "release-group": {
                            "id": MBID_B,
                            "title": "Love Compilation",
                            "primary-type": "Album",
                        },
                    },
                    {
                        "title": "Perfect Angel",
                        "date": "1988",
                        "artist-credit": [{"name": "Minnie Riperton"}],
                        "release-group": {
                            "id": MBID_A,
                            "title": "Perfect Angel",
                            "primary-type": "Album",
                        },
                    },
                ],
            }
        ]
    }
    urls = []
    resolver = ExternalArtworkResolver(
        fetch_json=lambda _url: payload,
        fetch_image=lambda url: (
            urls.append(url) or b"\xff\xd8\xffcover",
            "image/jpeg",
        ),
    )

    result = resolver.resolve(
        provider="tidal",
        item_ref="tidal:LOVIN",
        track="Lovin' You",
        artist="Minnie Riperton",
        album="Playlist personal",
    )

    assert "provider=tidal" in result
    assert urls[0].endswith(f"/{MBID_A}/front-500")


def test_fallo_externo_se_cachea_como_placeholder() -> None:
    calls = []

    def unavailable(_url):
        calls.append(1)
        raise TimeoutError("offline")

    resolver = ExternalArtworkResolver(fetch_json=unavailable)
    arguments = {
        "provider": "qobuz",
        "item_ref": "qobuz:OFFLINE",
        "track": "Track",
        "artist": "Artist",
        "album": "Album",
    }

    assert resolver.resolve(**arguments) is None
    assert resolver.resolve(**arguments) is None
    assert calls == [1]


def test_endpoint_sirve_solo_version_cacheada_y_proveedor_correcto() -> None:
    resolver = ExternalArtworkResolver(
        fetch_json=lambda _url: {
            "recordings": [_recording(("Libertinaje", MBID_A))]
        },
        fetch_image=lambda _url: (b"\xff\xd8\xffcover", "image/jpeg"),
    )
    url = resolver.resolve(
        provider="qobuz",
        item_ref="qobuz:TRACK",
        track="De Onda",
        artist="Bersuit Vergarabat",
        album="Libertinaje",
    )
    version = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["v"][0]
    module = object.__new__(CommandCenterModule)
    module._external_artwork = resolver
    module.context = type("Context", (), {"log": lambda *_args: None})()

    response = module.api(
        "media-artwork",
        {"provider": "qobuz", "v": version},
        user={"id": 1},
    )
    wrong_provider = module.api(
        "media-artwork",
        {"provider": "tidal", "v": version},
        user={"id": 1},
    )

    assert response == (200, "image/jpeg", b"\xff\xd8\xffcover")
    assert wrong_provider[0] == 404


def test_resolucion_en_background_no_bloquea_controles() -> None:
    started = threading.Event()
    release = threading.Event()

    def fetch_json(_url):
        started.set()
        assert release.wait(timeout=1)
        return {"recordings": [_recording(("Libertinaje", MBID_A))]}

    resolver = ExternalArtworkResolver(
        fetch_json=fetch_json,
        fetch_image=lambda _url: (b"\xff\xd8\xffcover", "image/jpeg"),
    )
    arguments = {
        "provider": "qobuz",
        "item_ref": "qobuz:BACKGROUND",
        "track": "De Onda",
        "artist": "Bersuit Vergarabat",
        "album": "Libertinaje",
    }

    assert resolver.resolve_cached_or_schedule(**arguments) is None
    assert started.wait(timeout=1)
    release.set()
    result = None
    for _attempt in range(50):
        result = resolver.resolve_cached_or_schedule(**arguments)
        if result:
            break
        time.sleep(0.01)

    assert result and "provider=qobuz" in result
