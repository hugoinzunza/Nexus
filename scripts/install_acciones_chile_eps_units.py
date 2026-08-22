#!/usr/bin/env python3
"""Instala verificaciones de unidad EPS obtenidas de documentos auditados."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.paths import persist_dir  # noqa: E402
from modules.acciones_chile.fx import validate_eps_unit_dataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Instala unidades EPS verificadas")
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        data = validate_eps_unit_dataset(json.loads(args.input.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"unidades EPS rechazadas: {exc}", file=sys.stderr)
        return 2
    if args.check_only:
        print(json.dumps({"ok": True, "entries": len(data["entries"]), "written": False}))
        return 0
    destination = pathlib.Path(persist_dir(str(ROOT))) / "acciones_chile_eps_units.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, destination)
    print(json.dumps({"ok": True, "entries": len(data["entries"]),
                      "path": str(destination)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
