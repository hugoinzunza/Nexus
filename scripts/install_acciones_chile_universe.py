#!/usr/bin/env python3
"""Instala localmente un universo normalizado autorizado; nunca lo versiona."""
import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.paths import persist_dir  # noqa: E402
from modules.acciones_chile.universe import validate_universe  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("universe", type=pathlib.Path,
                        help="JSON normalizado adquirido o autorizado")
    parser.add_argument(
        "--output", type=pathlib.Path,
        default=pathlib.Path(persist_dir(str(ROOT))) / "acciones_chile_universe.json",
    )
    args = parser.parse_args()
    data = validate_universe(json.loads(args.universe.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temp, args.output)
    print(json.dumps({
        "ok": True, "output": str(args.output), "snapshots": len(data["snapshots"]),
        "latest_members": len(data["snapshots"][-1]["members"]),
        "membership_history_complete": data["membership_history_complete"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
