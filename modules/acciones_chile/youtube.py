"""Índice de metadatos del canal @inversorchileno.

Usa el feed RSS público: títulos, fechas, URLs, descripción y capítulos. No
descarga ni reproduce videos y no trata opiniones como evidencia financiera.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


CHANNEL_ID = "UC2VeEMIf-GX4FeKhA8q2FjA"
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
MAX_FEED_BYTES = 2_000_000
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
CHAPTER = re.compile(r"^(\d{2}:\d{2}(?::\d{2})?)\s+(.+)$")


def fetch_feed(timeout: float = 20.0) -> bytes:
    request = urllib.request.Request(FEED_URL, headers={"User-Agent": "NexUX-AccionesChile/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL constante
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != "www.youtube.com" or final.path != "/feeds/videos.xml":
            raise ValueError("YouTube redirigió fuera del feed autorizado")
        body = response.read(MAX_FEED_BYTES + 1)
    if len(body) > MAX_FEED_BYTES:
        raise ValueError("feed de YouTube excede el límite")
    return body


def parse_feed(payload: bytes | str) -> list[dict]:
    root = ET.fromstring(payload)
    videos = []
    for entry in root.findall("atom:entry", NS):
        description = entry.findtext("media:group/media:description", default="", namespaces=NS)
        chapters = []
        for line in description.splitlines():
            match = CHAPTER.match(line.strip())
            if match:
                chapters.append({"timestamp": match.group(1), "title": match.group(2).strip()})
        video_id = entry.findtext("yt:videoId", default="", namespaces=NS)
        videos.append({
            "video_id": video_id,
            "title": entry.findtext("atom:title", default="", namespaces=NS),
            "published": entry.findtext("atom:published", default="", namespaces=NS),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "chapters": chapters,
            "source_role": "secondary_thesis",
        })
    return videos
