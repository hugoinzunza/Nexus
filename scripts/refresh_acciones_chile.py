#!/usr/bin/env python3
"""Actualiza manualmente el cache oficial CMF + índice @inversorchileno."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.paths import persist_dir  # noqa: E402
from modules.acciones_chile.dataset import build_audit_snapshot, refresh_dataset  # noqa: E402
from modules.acciones_chile.predictor import feature_join_report, readiness  # noqa: E402


def main() -> int:
    path = pathlib.Path(persist_dir(str(ROOT))) / "acciones_chile_dataset.json"
    data = refresh_dataset(str(path))
    audit_snapshot = build_audit_snapshot(data)
    telegram_path = path.with_name("acciones_chile_telegram_events.json")
    telegram = None
    try:
        telegram = json.loads(telegram_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    audit_snapshot["predictor"] = readiness(telegram, price_history_ready=False)
    audit_snapshot["predictor"]["cmf_telegram_join"] = feature_join_report(data, telegram)
    audit_path = path.with_name("acciones_chile_audit_snapshot.json")
    audit_path.write_text(json.dumps(audit_snapshot, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(json.dumps({
        "ok": True, "path": str(path), "periods": data["cmf"]["periods"],
        "issuers": len(data["cmf"]["issuers"]),
        "videos": len(data["youtube"]["entries"]),
        "audit_snapshot": str(audit_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
