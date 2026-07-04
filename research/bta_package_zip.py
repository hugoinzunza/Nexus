"""Create a portable ZIP from the verified BTA package manifest."""
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "bta_package_manifest_2026-07-01.json"
OUT_ZIP = HERE / "bta_review_package_2026-07-01.zip"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    root = Path(manifest["root"])
    written = 0
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry in manifest["artifacts"]:
            path = Path(entry["path"])
            if not path.is_file():
                raise FileNotFoundError(path)
            arcname = Path("bta_review_package_2026-07-01") / path.relative_to(root)
            zf.write(path, arcname.as_posix())
            written += 1
    print(f"zip={OUT_ZIP}")
    print(f"files={written}")
    print(f"bytes={OUT_ZIP.stat().st_size}")


if __name__ == "__main__":
    main()
