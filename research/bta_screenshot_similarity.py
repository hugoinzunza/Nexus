"""Audit exact and perceptual similarity across BTA screenshots."""
from __future__ import annotations

import hashlib
import json
import os
from itertools import combinations
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SCREEN_DIR = HERE / "tradingview_bta_screenshots_2026-06-30"
OUT_JSON = HERE / "bta_screenshot_similarity_2026-07-01.json"
OUT_MD = HERE / "bta_screenshot_similarity_2026-07-01.md"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def average_hash(path: Path, size: int = 16) -> str:
    img = Image.open(path).convert("L").resize((size, size), Image.Resampling.LANCZOS)
    vals = list(img.getdata())
    avg = sum(vals) / len(vals)
    return "".join("1" if v > avg else "0" for v in vals)


def hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b))


def md_table(rows, headers):
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def main():
    files = sorted(SCREEN_DIR.glob("*.jpg"))
    captures = []
    for path in files:
        im = Image.open(path)
        captures.append({
            "file": path.name,
            "bytes": path.stat().st_size,
            "width": im.width,
            "height": im.height,
            "sha256": sha256(path),
            "ahash16": average_hash(path),
        })

    exact = []
    similar = []
    for a, b in combinations(captures, 2):
        same = a["sha256"] == b["sha256"]
        dist = hamming(a["ahash16"], b["ahash16"])
        if same:
            exact.append({"a": a["file"], "b": b["file"], "sha256": a["sha256"]})
        if dist <= 8:
            similar.append({"a": a["file"], "b": b["file"], "ahash_hamming": dist,
                            "exact": same})

    out = {
        "screen_dir": str(SCREEN_DIR),
        "captures": captures,
        "exact_duplicates": exact,
        "near_duplicates_ahash_hamming_le_8": similar,
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    exact_rows = [{"a": x["a"], "b": x["b"], "sha256": x["sha256"][:12]} for x in exact]
    sim_rows = [{"a": x["a"], "b": x["b"], "hamming": x["ahash_hamming"],
                 "exact": x["exact"]} for x in similar]
    cap_rows = [{
        "file": c["file"],
        "bytes": c["bytes"],
        "size": f"{c['width']}x{c['height']}",
        "sha256": c["sha256"][:12],
    } for c in captures]

    md = f"""# Auditoría similitud capturas BTA

Carpeta: `{SCREEN_DIR}`

Capturas: `{len(captures)}`
Duplicados exactos: `{len(exact)}`
Pares visualmente similares `(aHash16 hamming <= 8)`: `{len(similar)}`

## Capturas

{md_table(cap_rows, ["file", "bytes", "size", "sha256"])}

## Duplicados exactos

{md_table(exact_rows, ["a", "b", "sha256"]) if exact_rows else "Sin duplicados exactos."}

## Pares visualmente similares

{md_table(sim_rows, ["a", "b", "hamming", "exact"]) if sim_rows else "Sin pares bajo umbral."}

## Lectura

Los duplicados exactos prueban repetición de archivo. Los pares visualmente similares no prueban identidad por sí solos; sólo priorizan revisión manual. En esta auditoría, la repetición exacta de capturas antiguas refuerza que 2025 debe re-navegarse con chart limpio.
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"captures={len(captures)} exact={len(exact)} similar={len(similar)}")
    print(OUT_MD)


if __name__ == "__main__":
    main()
