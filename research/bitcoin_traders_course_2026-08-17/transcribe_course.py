#!/usr/bin/env python3
"""Create timestamped local transcripts for authorized course audio."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import mlx_whisper


# Fast first pass for the complete corpus. Critical rules are verified later
# against the source and, when needed, retranscribed with a larger model.
MODEL = "mlx-community/whisper-small-mlx"


def stamp(seconds: float) -> str:
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session", type=int)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args()

    audio = args.cache / "audio" / f"session_{args.session:02d}.m4a"
    output_dir = args.cache / "transcripts"
    output_dir.mkdir(parents=True, exist_ok=True)
    result = mlx_whisper.transcribe(
        str(audio),
        path_or_hf_repo=args.model,
        language="es",
        verbose=False,
        word_timestamps=True,
    )

    payload = {
        "session": args.session,
        "audio_sha256": sha256(audio),
        "model": args.model,
        "language": result.get("language", "es"),
        "segments": result.get("segments", []),
        "text": result.get("text", ""),
    }
    json_path = output_dir / f"session_{args.session:02d}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# Transcripcion - Sesion {args.session:02d}", ""]
    for segment in payload["segments"]:
        text = str(segment.get("text", "")).strip()
        if text:
            lines.append(f"[{stamp(float(segment['start']))} - {stamp(float(segment['end']))}] {text}")
    markdown_path = output_dir / f"session_{args.session:02d}.md"
    markdown_path.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"session": args.session, "json": str(json_path), "markdown": str(markdown_path)}))


if __name__ == "__main__":
    main()
