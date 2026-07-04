"""Verify the BTA package manifest hashes and required sanity checks."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "bta_package_manifest_2026-07-01.json")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=os.path.dirname(HERE), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.strip()


def main() -> None:
    with open(MANIFEST, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    errors = []
    for entry in manifest["artifacts"]:
        path = entry["path"]
        if not os.path.isfile(path):
            errors.append(f"missing: {path}")
            continue
        size = os.path.getsize(path)
        if size != entry["size_bytes"]:
            errors.append(f"size changed: {path} expected {entry['size_bytes']} got {size}")
        digest = sha256(path)
        if digest != entry["sha256"]:
            errors.append(f"sha changed: {path}")

    checks = [
        ["python3", os.path.join(HERE, "test_bta_visual_model.py")],
        ["python3", os.path.join(HERE, "bta_visual_inventory_summary.py")],
        ["python3", os.path.join(HERE, "bta_morning_html.py")],
    ]
    for cmd in checks:
        code, out = run(cmd)
        if code != 0:
            errors.append(f"check failed: {' '.join(cmd)}\n{out}")

    html_path = os.path.join(HERE, "bta_morning_review_2026-07-01.html")
    if os.path.isfile(html_path):
        html = open(html_path, "r", encoding="utf-8").read()
        required_markers = [
            "BTA TradingView vs Nexux",
            "Backtest de filtros",
            "Capturas y zonas",
            "Pendientes para cerrar la misión",
        ]
        for marker in required_markers:
            if marker not in html:
                errors.append(f"html missing marker: {marker}")
    else:
        errors.append(f"missing html: {html_path}")

    zip_path = os.path.join(HERE, "bta_review_package_2026-07-01.zip")
    if os.path.isfile(zip_path):
        try:
            with zipfile.ZipFile(zip_path) as zf:
                bad = zf.testzip()
                names = zf.namelist()
            if bad:
                errors.append(f"zip corrupt member: {bad}")
            expected_names = {
                "bta_review_package_2026-07-01/" + os.path.relpath(e["path"], HERE)
                for e in manifest["artifacts"]
            }
            actual_names = set(names)
            missing_zip = sorted(expected_names - actual_names)
            extra_zip = sorted(actual_names - expected_names)
            if missing_zip:
                errors.append(f"zip missing entries: {missing_zip[:5]}")
            if extra_zip:
                errors.append(f"zip extra entries: {extra_zip[:5]}")
        except zipfile.BadZipFile as exc:
            errors.append(f"bad zip: {exc}")
    else:
        errors.append(f"missing zip: {zip_path}")

    print(f"manifest_artifacts={len(manifest['artifacts'])}")
    print(f"errors={len(errors)}")
    for err in errors:
        print(err)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
