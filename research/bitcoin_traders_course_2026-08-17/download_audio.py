#!/usr/bin/env python3
"""Download authorized course audio from expiring Drive URLs by byte ranges."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)


def _download_part(url: str, start: int, end: int, path: Path, retries: int = 4) -> int:
    expected = end - start + 1
    for attempt in range(retries):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": "https://drive.google.com/",
                "Range": f"bytes={start}-{end}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response, path.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            size = path.stat().st_size
            if size != expected:
                raise OSError(f"range {start}-{end}: expected {expected}, got {size}")
            return size
        except Exception:
            if attempt + 1 == retries:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise AssertionError("unreachable")


def download_session(cache: Path, number: int, total: int, workers: int, chunk_mb: int) -> Path:
    url_path = cache / f"session_{number:02d}_url.txt"
    if not url_path.exists():
        raise FileNotFoundError(f"missing ephemeral URL: {url_path}")
    url = url_path.read_text(encoding="utf-8").strip()
    output = cache / "audio" / f"session_{number:02d}.m4a"
    parts_dir = cache / ".parts" / f"session_{number:02d}"
    parts_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)

    chunk = chunk_mb * 1024 * 1024
    ranges = []
    for index, start in enumerate(range(0, total, chunk)):
        end = min(total - 1, start + chunk - 1)
        ranges.append((index, start, end, parts_dir / f"{index:05d}.part"))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_download_part, url, start, end, path): (index, path)
            for index, start, end, path in ranges
            if not path.exists() or path.stat().st_size != end - start + 1
        }
        for future in as_completed(futures):
            future.result()

    temporary = output.with_suffix(".m4a.partial")
    with temporary.open("wb") as merged:
        for _, _, _, path in ranges:
            with path.open("rb") as source:
                shutil.copyfileobj(source, merged, length=1024 * 1024)
    if temporary.stat().st_size != total:
        raise OSError(f"merged size mismatch: expected {total}, got {temporary.stat().st_size}")
    os.replace(temporary, output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session", type=int)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--chunk-mb", type=int, default=4)
    args = parser.parse_args()

    manifest = json.loads((args.cache / "course_manifest.json").read_text(encoding="utf-8"))
    entry = next(item for item in manifest["sessions"] if item["n"] == args.session)
    path = download_session(args.cache, args.session, int(entry["audioBytes"]), args.workers, args.chunk_mb)
    print(json.dumps({"session": args.session, "path": str(path), "bytes": path.stat().st_size}))


if __name__ == "__main__":
    main()
