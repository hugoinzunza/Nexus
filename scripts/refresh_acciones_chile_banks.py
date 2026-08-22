#!/usr/bin/env python3
"""Actualiza el cache separado de resultados para bancos listados chilenos."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.paths import persist_dir  # noqa: E402
from modules.acciones_chile.banks import (  # noqa: E402
    API_KEY_ENV, LISTED_BANKS, build_bank_dataset, download_results, write_bank_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Actualizar cache oficial CMF Bancos")
    parser.add_argument("--year", action="append", type=int,
                        help="año a descargar; se puede repetir (default: año UTC actual)")
    parser.add_argument("--ticker", action="append", choices=sorted(LISTED_BANKS),
                        help="banco a descargar; se puede repetir (default: los cuatro)")
    parser.add_argument("--output", type=pathlib.Path,
                        default=pathlib.Path(persist_dir(str(ROOT))) /
                        "acciones_chile_banks.json")
    args = parser.parse_args()
    api_key = os.environ.get(API_KEY_ENV, "")
    if not api_key:
        print(json.dumps({"ok": False, "error": f"falta {API_KEY_ENV}"}, ensure_ascii=False))
        return 3
    years = sorted(set(args.year or [datetime.now(timezone.utc).year]))
    tickers = sorted(set(args.ticker or LISTED_BANKS))
    downloads = [
        download_results(year, LISTED_BANKS[ticker]["institution_code"], api_key)
        for year in years for ticker in tickers
    ]
    data = build_bank_dataset(downloads)
    write_bank_dataset(str(args.output), data)
    print(json.dumps({
        "ok": True, "output": str(args.output), "years": years, "tickers": tickers,
        "observations": len(data["observations"]), "periods": data["periods"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
