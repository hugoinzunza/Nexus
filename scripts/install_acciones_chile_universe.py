#!/usr/bin/env python3
"""Valida e instala un universo IPSA autorizado; nunca lo versiona."""
import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.paths import persist_dir  # noqa: E402
from modules.acciones_chile.universe import load_universe, snapshot_as_of  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("universe", type=pathlib.Path,
                        help="JSON normalizado adquirido o autorizado")
    parser.add_argument("--as-of", required=True, help="fecha a validar, YYYY-MM-DD")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument(
        "--output", type=pathlib.Path,
        default=pathlib.Path(persist_dir(str(ROOT))) / "acciones_chile_universe.json",
    )
    args = parser.parse_args()
    try:
        data = load_universe(args.universe)
        snapshot = snapshot_as_of(data, args.as_of, require_complete=True)
    except (OSError, ValueError) as exc:
        print(f"universo rechazado: {exc}", file=sys.stderr)
        return 2
    if args.check_only:
        print(json.dumps({
            "ok": True, "as_of": args.as_of, "members": len(snapshot["members"]),
            "membership_history_complete": data["membership_history_complete"],
            "written": False,
        }, ensure_ascii=False))
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, args.output)
    print(json.dumps({
        "ok": True, "output": str(args.output), "snapshots": len(data["snapshots"]),
        "validated_as_of": args.as_of, "latest_members": len(data["snapshots"][-1]["members"]),
        "membership_history_complete": data["membership_history_complete"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
