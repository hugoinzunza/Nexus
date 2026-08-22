#!/usr/bin/env python3
"""Actualiza dólar BCCh: API autenticada preferida, tabla BDE pública de respaldo."""
from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.paths import persist_dir  # noqa: E402
from modules.acciones_chile.fx import (  # noqa: E402
    TOKEN_ENV, build_fx_dataset, build_public_fx_dataset, download_observed_dollar,
    download_public_observed_dollar, write_fx_dataset,
)


def main() -> int:
    token = os.environ.get(TOKEN_ENV, "")
    end = date.today()
    start = end - timedelta(days=35)
    try:
        if token:
            data = build_fx_dataset(download_observed_dollar(start, end, token))
        else:
            data = build_public_fx_dataset(download_public_observed_dollar())
        path = pathlib.Path(persist_dir(str(ROOT))) / "acciones_chile_fx.json"
        write_fx_dataset(str(path), data)
    except ValueError as exc:
        print(f"actualización BCCh bloqueada: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "ok": True, "path": str(path), "latest": data["latest"],
        "observations": len(data["observations"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
