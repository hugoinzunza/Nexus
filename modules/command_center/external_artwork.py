"""Resolución conservadora de carátulas mediante catálogos públicos."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


_MUSICBRAINZ_SEARCH = "https://musicbrainz.org/ws/2/recording"
_COVER_ART = "https://coverartarchive.org/release-group/{mbid}/front-500"
_ITUNES_SEARCH = "https://itunes.apple.com/search"
_MBID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_MAX_IMAGE_BYTES = 5_000_000
_MAX_JSON_BYTES = 1_000_000
@dataclass(frozen=True)
class ArtworkEntry:
    provider: str
    item_ref: str
    version: str
    data: bytes
    content_type: str
    release_group_mbid: str


@dataclass(frozen=True)
class ArtworkMiss:
    retry_at: float


def _fetch_json(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "NexUX/1.0 (https://nexux.cl)",
        },
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        data = response.read(_MAX_JSON_BYTES + 1)
    if len(data) > _MAX_JSON_BYTES:
        raise ValueError("respuesta MusicBrainz demasiado grande")
    return json.loads(data)


def _fetch_image(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "image/jpeg,image/png,image/webp",
            "User-Agent": "NexUX/1.0 (https://nexux.cl)",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        final_url = urllib.parse.urlsplit(response.geturl())
        host = (final_url.hostname or "").lower()
        if final_url.scheme != "https" or not (
            host == "coverartarchive.org"
            or host == "archive.org"
            or host.endswith(".archive.org")
            or host == "mzstatic.com"
            or host.endswith(".mzstatic.com")
        ):
            raise ValueError("redirección de carátula no autorizada")
        data = response.read(_MAX_IMAGE_BYTES + 1)
        content_type = response.headers.get_content_type().lower()
    if len(data) > _MAX_IMAGE_BYTES:
        raise ValueError("carátula demasiado grande")
    detected = _image_type(data)
    if detected is None or content_type not in {
        "image/jpeg",
        "image/png",
        "image/webp",
    }:
        raise ValueError("carátula inválida")
    return data, detected


def _image_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _canonical(value: object) -> str:
    if not isinstance(value, str):
        return ""
    folded = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text.lower()))


def _lucene_phrase(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _qobuz_local_artwork(
    album: str | None,
    artist: str,
) -> tuple[bytes, str, str] | None:
    """Lee únicamente la carátula oficial que Qobuz ya cacheó en el Mac."""
    if not album:
        return None
    support = Path.home() / "Library/Application Support/Qobuz"
    database = support / "qobuz.db"
    assets = (support / "tmp/Assets").resolve()
    if not database.is_file():
        return None
    album_candidates = [album.strip()]
    if "," in album:
        without_credit = album.split(",", 1)[1].strip()
        if without_credit:
            album_candidates.append(without_credit)
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT id, title, data FROM L_Album "
            "WHERE title = ? COLLATE NOCASE OR title = ? COLLATE NOCASE "
            "LIMIT 12",
            (album_candidates[0], album_candidates[-1]),
        ).fetchall()
    finally:
        connection.close()
    wanted_albums = {_canonical(candidate) for candidate in album_candidates}
    wanted_artist = _canonical(artist)
    for album_id, title, raw in rows:
        if _canonical(title) not in wanted_albums:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        credited = _canonical((payload.get("artist") or {}).get("name"))
        if wanted_artist and credited and credited != wanted_artist:
            continue
        images = payload.get("image") or {}
        for size in ("large", "small", "thumbnail"):
            candidate = images.get(size)
            if not isinstance(candidate, str):
                continue
            path = Path(candidate).expanduser().resolve()
            if not path.is_relative_to(assets) or not path.is_file():
                continue
            data = path.read_bytes()
            if len(data) > _MAX_IMAGE_BYTES:
                continue
            content_type = _image_type(data)
            if content_type:
                return data, content_type, f"qobuz-local:{album_id}"
    return None


def _track_variants(track: str) -> list[str]:
    variants = [track.strip()]
    shortened = re.sub(
        r"\s*(?:\([^()]*\)|\[[^\[\]]*\])\s*$", "", track
    ).strip()
    if shortened and _canonical(shortened) != _canonical(track):
        variants.append(shortened)
    return variants


def _transient(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 429 or 500 <= error.code < 600
    return isinstance(error, (TimeoutError, urllib.error.URLError))


class ExternalArtworkResolver:
    """Busca una carátula solo cuando la identidad musical es inequívoca."""

    def __init__(
        self,
        *,
        fetch_json: Callable[[str], object] = _fetch_json,
        fetch_image: Callable[[str], tuple[bytes, str]] = _fetch_image,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        qobuz_local: Callable[
            [str | None, str], tuple[bytes, str, str] | None
        ] = _qobuz_local_artwork,
        max_entries: int = 128,
    ):
        if max_entries <= 0:
            raise ValueError("max_entries debe ser positivo")
        self._fetch_json = fetch_json
        self._fetch_image = fetch_image
        self._monotonic = monotonic
        self._sleep = sleep
        self._qobuz_local = qobuz_local
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._lookup_lock = threading.Lock()
        self._pending: set[tuple[str, str]] = set()
        self._last_musicbrainz_request = float("-inf")
        self._cache: OrderedDict[tuple[str, str], ArtworkEntry | ArtworkMiss] = (
            OrderedDict()
        )
        self._by_version: dict[tuple[str, str], ArtworkEntry] = {}

    def resolve(
        self,
        *,
        provider: str,
        item_ref: str,
        track: str,
        artist: str,
        album: str | None,
    ) -> str | None:
        if provider not in {"qobuz", "tidal"}:
            return None
        if not item_ref or not _canonical(track) or not _canonical(artist):
            return None
        key = (provider, item_ref)
        with self._lock:
            found, url = self._cached_url(key)
            if found:
                return url
        entry = self._lookup_safely(provider, item_ref, track, artist, album)
        with self._lock:
            self._remember(key, entry)
            return self._url(entry) if entry else None

    def resolve_cached_or_schedule(
        self,
        *,
        provider: str,
        item_ref: str,
        track: str,
        artist: str,
        album: str | None,
    ) -> str | None:
        """Devuelve caché inmediata y resuelve misses fuera del request."""
        if provider not in {"qobuz", "tidal"}:
            return None
        if not item_ref or not _canonical(track) or not _canonical(artist):
            return None
        key = (provider, item_ref)
        with self._lock:
            found, url = self._cached_url(key)
            if found or key in self._pending:
                return url
            self._pending.add(key)
        threading.Thread(
            target=self._resolve_background,
            args=(key, provider, item_ref, track, artist, album),
            name=f"artwork-{provider}",
            daemon=True,
        ).start()
        return None

    def artwork(self, provider: str, version: str) -> tuple[bytes, str] | None:
        if provider not in {"qobuz", "tidal"}:
            return None
        with self._lock:
            entry = self._by_version.get((provider, version))
            return (entry.data, entry.content_type) if entry else None

    def _lookup(
        self,
        provider: str,
        item_ref: str,
        track: str,
        artist: str,
        album: str | None,
    ) -> ArtworkEntry | None:
        if provider == "qobuz":
            local = self._qobuz_local(album, artist)
            if local:
                data, content_type, provenance = local
                return self._entry(
                    provider, item_ref, data, content_type, provenance
                )
        for candidate in _track_variants(track):
            entry = self._lookup_catalog(
                provider, item_ref, candidate, artist, album
            )
            if entry:
                return entry
        if provider == "tidal":
            return self._lookup_itunes(item_ref, track, artist, album)
        return None

    def _lookup_itunes(
        self,
        item_ref: str,
        track: str,
        artist: str,
        album: str | None,
    ) -> ArtworkEntry | None:
        """Fallback exacto para playlists que no exponen el álbum real."""
        url = _ITUNES_SEARCH + "?" + urllib.parse.urlencode(
            {
                "term": f"{track} {artist}",
                "entity": "song",
                "limit": 25,
            }
        )
        payload = self._retry(self._fetch_json, url)
        if not isinstance(payload, dict) or not isinstance(
            payload.get("results"), list
        ):
            return None
        wanted_track = _canonical(track)
        wanted_artist = _canonical(artist)
        wanted_album = _canonical(album)
        candidates: list[tuple[tuple[int, str], dict]] = []
        for result in payload["results"]:
            if not isinstance(result, dict):
                continue
            if _canonical(result.get("trackName")) != wanted_track:
                continue
            credited = _canonical(result.get("artistName"))
            if credited != wanted_artist:
                continue
            artwork = result.get("artworkUrl100")
            if not isinstance(artwork, str):
                continue
            album_match = int(
                not wanted_album
                or _canonical(result.get("collectionName")) != wanted_album
            )
            released = str(result.get("releaseDate") or "9999")
            candidates.append(((album_match, released), result))
        if not candidates:
            return None
        _rank, selected = min(candidates, key=lambda candidate: candidate[0])
        artwork_url = str(selected["artworkUrl100"])
        artwork_url = re.sub(
            r"/\d+x\d+bb\.(jpg|png)$",
            r"/600x600bb.\1",
            artwork_url,
            flags=re.IGNORECASE,
        )
        data, content_type = self._retry(self._fetch_image, artwork_url)
        provenance = "itunes:" + str(
            selected.get("collectionId") or selected.get("trackId") or "exact"
        )
        return self._entry("tidal", item_ref, data, content_type, provenance)

    def _lookup_catalog(
        self,
        provider: str,
        item_ref: str,
        track: str,
        artist: str,
        album: str | None,
    ) -> ArtworkEntry | None:
        elapsed = self._monotonic() - self._last_musicbrainz_request
        if elapsed < 1.0:
            self._sleep(1.0 - elapsed)
        query = (
            f'recording:"{_lucene_phrase(track)}" '
            f'AND artist:"{_lucene_phrase(artist)}"'
        )
        url = _MUSICBRAINZ_SEARCH + "?" + urllib.parse.urlencode(
            {"query": query, "fmt": "json", "limit": 25}
        )
        self._last_musicbrainz_request = self._monotonic()
        payload = self._retry(self._fetch_json, url)
        mbid = self._select_release_group(payload, track, artist, album)
        if mbid is None:
            return None
        try:
            data, content_type = self._retry(
                self._fetch_image, _COVER_ART.format(mbid=mbid)
            )
        except (
            TimeoutError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            ValueError,
        ):
            return None
        return self._entry(provider, item_ref, data, content_type, mbid)

    def _retry(self, operation: Callable, argument: str):
        try:
            return operation(argument)
        except Exception as error:
            if not _transient(error):
                raise
            self._sleep(0.25)
            return operation(argument)

    @staticmethod
    def _entry(
        provider: str,
        item_ref: str,
        data: bytes,
        content_type: str,
        provenance: str,
    ) -> ArtworkEntry:
        digest = hashlib.sha256(
            provider.encode("utf-8") + b"\0" + item_ref.encode("utf-8") + data
        ).hexdigest()[:16]
        return ArtworkEntry(
            provider,
            item_ref,
            digest,
            data,
            content_type,
            provenance,
        )

    def _lookup_safely(
        self,
        provider: str,
        item_ref: str,
        track: str,
        artist: str,
        album: str | None,
    ) -> ArtworkEntry | None:
        try:
            with self._lookup_lock:
                return self._lookup(provider, item_ref, track, artist, album)
        except Exception:  # La carátula nunca debe romper el reproductor.
            return None

    def _resolve_background(
        self,
        key: tuple[str, str],
        provider: str,
        item_ref: str,
        track: str,
        artist: str,
        album: str | None,
    ) -> None:
        entry = self._lookup_safely(provider, item_ref, track, artist, album)
        with self._lock:
            self._pending.discard(key)
            self._remember(key, entry)

    def _cached_url(
        self,
        key: tuple[str, str],
    ) -> tuple[bool, str | None]:
        if key not in self._cache:
            return False, None
        cached = self._cache[key]
        self._cache.move_to_end(key)
        if isinstance(cached, ArtworkEntry):
            return True, self._url(cached)
        if self._monotonic() < cached.retry_at:
            return True, None
        self._cache.pop(key, None)
        return False, None

    @staticmethod
    def _select_release_group(
        payload: object,
        track: str,
        artist: str,
        album: str | None,
    ) -> str | None:
        if not isinstance(payload, dict):
            return None
        recordings = payload.get("recordings")
        if not isinstance(recordings, list):
            return None
        wanted_track = _canonical(track)
        wanted_artist = _canonical(artist)
        wanted_album = _canonical(album)
        exact_album: list[str] = []
        fallback: list[str] = []
        artist_owned: dict[str, tuple[int, str]] = {}
        for recording in recordings:
            if not isinstance(recording, dict):
                continue
            score = recording.get("score")
            if not isinstance(score, (int, float)) or score < 90:
                continue
            if _canonical(recording.get("title")) != wanted_track:
                continue
            credits = recording.get("artist-credit")
            names = [
                _canonical(credit.get("name"))
                for credit in credits or []
                if isinstance(credit, dict)
            ]
            if wanted_artist not in names:
                continue
            for release in recording.get("releases") or []:
                if not isinstance(release, dict):
                    continue
                group = release.get("release-group")
                if not isinstance(group, dict):
                    continue
                mbid = str(group.get("id") or "").lower()
                if not _MBID.fullmatch(mbid):
                    continue
                fallback.append(mbid)
                release_artists = {
                    _canonical(credit.get("name"))
                    for credit in release.get("artist-credit") or []
                    if isinstance(credit, dict)
                }
                if wanted_artist in release_artists:
                    primary_type = _canonical(group.get("primary-type"))
                    type_rank = {
                        "album": 0,
                        "ep": 1,
                        "single": 2,
                    }.get(primary_type, 3)
                    date = str(release.get("date") or "9999")
                    rank = (type_rank, date)
                    if mbid not in artist_owned or rank < artist_owned[mbid]:
                        artist_owned[mbid] = rank
                titles = {
                    _canonical(release.get("title")),
                    _canonical(group.get("title")),
                }
                if wanted_album and wanted_album in titles:
                    exact_album.append(mbid)
        exact_unique = list(dict.fromkeys(exact_album))
        if len(exact_unique) == 1:
            return exact_unique[0]
        if artist_owned:
            best_rank = min(artist_owned.values())
            best = [
                mbid for mbid, rank in artist_owned.items() if rank == best_rank
            ]
            if len(best) == 1:
                return best[0]
        fallback_unique = list(dict.fromkeys(fallback))
        return fallback_unique[0] if len(fallback_unique) == 1 else None

    def _remember(
        self,
        key: tuple[str, str],
        entry: ArtworkEntry | None,
    ) -> None:
        stored: ArtworkEntry | ArtworkMiss = (
            entry if entry else ArtworkMiss(self._monotonic() + 300.0)
        )
        self._cache[key] = stored
        if entry:
            self._by_version[(entry.provider, entry.version)] = entry
        while len(self._cache) > self._max_entries:
            _old_key, old = self._cache.popitem(last=False)
            if isinstance(old, ArtworkEntry):
                self._by_version.pop((old.provider, old.version), None)

    @staticmethod
    def _url(entry: ArtworkEntry) -> str:
        return (
            "/m/command-center/api/media-artwork?provider="
            f"{entry.provider}&v={entry.version}"
        )
