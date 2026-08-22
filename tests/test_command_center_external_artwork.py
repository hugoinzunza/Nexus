import threading
import time
import sqlite3
import urllib.parse

from modules.command_center.external_artwork import (
    ExternalArtworkResolver,
    _qobuz_local_artwork,
)
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
        qobuz_local=lambda *_args: None,
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
        qobuz_local=lambda *_args: None,
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
        qobuz_local=lambda *_args: None,
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
        qobuz_local=lambda *_args: None,
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

    resolver = ExternalArtworkResolver(
        fetch_json=unavailable,
        sleep=lambda _n: None,
        qobuz_local=lambda *_args: None,
    )
    arguments = {
        "provider": "qobuz",
        "item_ref": "qobuz:OFFLINE",
        "track": "Track",
        "artist": "Artist",
        "album": "Album",
    }

    assert resolver.resolve(**arguments) is None
    assert resolver.resolve(**arguments) is None
    assert calls == [1, 1]


def test_qobuz_prefiere_caratula_oficial_cacheada_localmente(
    tmp_path, monkeypatch
) -> None:
    support = tmp_path / "Library/Application Support/Qobuz"
    assets = support / "tmp/Assets/album-1"
    assets.mkdir(parents=True)
    database = support / "qobuz.db"
    artwork = assets / "large_cover.png"
    artwork.write_bytes(b"\x89PNG\r\n\x1a\ncover")
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE L_Album (id TEXT, title TEXT, data TEXT)")
    connection.execute(
        "INSERT INTO L_Album VALUES (?, ?, ?)",
        (
            "album-1",
            "El Amor Después del Amor",
            '{"artist":{"name":"Fito Páez"},"image":{"large":"'
            + str(artwork)
            + '"}}',
        ),
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("HOME", str(tmp_path))
    external_calls = []
    resolver = ExternalArtworkResolver(
        fetch_json=lambda url: external_calls.append(url),
        qobuz_local=_qobuz_local_artwork,
    )

    result = resolver.resolve(
        provider="qobuz",
        item_ref="qobuz:FITO",
        track="El amor después del amor",
        artist="Fito Páez",
        album="Fito, El Amor Después del Amor",
    )

    assert result and "provider=qobuz" in result
    assert external_calls == []


def test_tidal_reintenta_titulo_sin_sufijo_parentetico() -> None:
    queries = []

    def fetch_json(url):
        queries.append(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["query"][0])
        if len(queries) == 1:
            return {"recordings": []}
        return {
            "recordings": [
                {
                    "score": 100,
                    "title": "The Pink Panther Theme",
                    "artist-credit": [{"name": "Henry Mancini"}],
                    "releases": [
                        {
                            "title": "The Pink Panther",
                            "artist-credit": [{"name": "Henry Mancini"}],
                            "release-group": {
                                "id": MBID_A,
                                "title": "The Pink Panther",
                                "primary-type": "Album",
                            },
                        }
                    ],
                }
            ]
        }

    resolver = ExternalArtworkResolver(
        fetch_json=fetch_json,
        fetch_image=lambda _url: (b"\xff\xd8\xffcover", "image/jpeg"),
        monotonic=lambda: 100.0,
        sleep=lambda _n: None,
        qobuz_local=lambda *_args: None,
    )
    result = resolver.resolve(
        provider="tidal",
        item_ref="tidal:PINK",
        track='The Pink Panther Theme (From "The Pink Panther")',
        artist="Henry Mancini",
        album="The Pink Panther",
    )

    assert result and "provider=tidal" in result
    assert len(queries) == 2
    assert 'recording:"The Pink Panther Theme"' in queries[1]


def test_tidal_usa_itunes_solo_para_coincidencia_exacta() -> None:
    urls = []

    def fetch_json(url):
        if "musicbrainz.org" in url:
            return {"recordings": []}
        return {
            "results": [
                {
                    "trackName": "Fever",
                    "artistName": "Elvis Presley",
                    "collectionName": "Elvis Is Back!",
                    "releaseDate": "1960-04-08T12:00:00Z",
                    "collectionId": 123,
                    "artworkUrl100": (
                        "https://is1-ssl.mzstatic.com/image/thumb/cover/"
                        "100x100bb.jpg"
                    ),
                }
            ]
        }

    resolver = ExternalArtworkResolver(
        fetch_json=fetch_json,
        fetch_image=lambda url: (
            urls.append(url) or b"\xff\xd8\xffcover",
            "image/jpeg",
        ),
        monotonic=lambda: 100.0,
        sleep=lambda _n: None,
        qobuz_local=lambda *_args: None,
    )

    result = resolver.resolve(
        provider="tidal",
        item_ref="tidal:FEVER",
        track="Fever",
        artist="Elvis Presley",
        album="Hugh HI",
    )

    assert result and "provider=tidal" in result
    assert urls == [
        "https://is1-ssl.mzstatic.com/image/thumb/cover/600x600bb.jpg"
    ]


def test_tidal_no_acepta_caratula_itunes_de_otra_version() -> None:
    resolver = ExternalArtworkResolver(
        fetch_json=lambda url: (
            {"recordings": []}
            if "musicbrainz.org" in url
            else {
                "results": [
                    {
                        "trackName": "Fever (Live)",
                        "artistName": "Elvis Presley",
                        "collectionName": "Aloha from Hawaii",
                        "artworkUrl100": (
                            "https://is1-ssl.mzstatic.com/image/thumb/cover/"
                            "100x100bb.jpg"
                        ),
                    }
                ]
            }
        ),
        fetch_image=lambda _url: (_ for _ in ()).throw(
            AssertionError("no debe descargar una coincidencia aproximada")
        ),
        monotonic=lambda: 100.0,
        sleep=lambda _n: None,
        qobuz_local=lambda *_args: None,
    )

    assert resolver.resolve(
        provider="tidal",
        item_ref="tidal:FEVER-LIVE",
        track="Fever",
        artist="Elvis Presley",
        album="Hugh HI",
    ) is None


def test_endpoint_sirve_solo_version_cacheada_y_proveedor_correcto() -> None:
    resolver = ExternalArtworkResolver(
        fetch_json=lambda _url: {
            "recordings": [_recording(("Libertinaje", MBID_A))]
        },
        fetch_image=lambda _url: (b"\xff\xd8\xffcover", "image/jpeg"),
        qobuz_local=lambda *_args: None,
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
        qobuz_local=lambda *_args: None,
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
