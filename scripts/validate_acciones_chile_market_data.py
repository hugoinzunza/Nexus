#!/usr/bin/env python3
"""Valida un CSV normalizado adquirido/autorizado; no persiste ni descarga."""
import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.acciones_chile.market_data import parse_market_csv  # noqa: E402
from core.paths import persist_dir  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=pathlib.Path)
    parser.add_argument("manifest", type=pathlib.Path)
    parser.add_argument(
        "--status-output", type=pathlib.Path,
        default=pathlib.Path(persist_dir(str(ROOT))) / "acciones_chile_market_data_status.json",
        help="persiste sólo procedencia/resumen; nunca copia el dataset licenciado",
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    _, summary = parse_market_csv(args.csv.read_bytes(), manifest)
    args.status_output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.status_output.with_suffix(args.status_output.suffix + ".tmp")
    temp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, args.status_output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["label_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
