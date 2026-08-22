#!/usr/bin/env python3
"""Actualiza manualmente el cache oficial CMF + índice @inversorchileno."""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.paths import persist_dir  # noqa: E402
from modules.acciones_chile.banks import availability as bank_availability  # noqa: E402
from modules.acciones_chile.dataset import build_audit_snapshot, refresh_dataset  # noqa: E402
from modules.acciones_chile.fx import availability as fx_availability  # noqa: E402
from modules.acciones_chile.predictor import feature_join_report, readiness  # noqa: E402
from modules.acciones_chile.universe import load_universe, universe_status  # noqa: E402


def main() -> int:
    path = pathlib.Path(persist_dir(str(ROOT))) / "acciones_chile_dataset.json"
    data = refresh_dataset(str(path))
    audit_snapshot = build_audit_snapshot(data)
    audit_snapshot["cmf_banks"] = bank_availability(
        str(path.with_name("acciones_chile_banks.json")))
    audit_snapshot["fx"] = fx_availability(str(path.with_name("acciones_chile_fx.json")))
    telegram_path = path.with_name("acciones_chile_telegram_events.json")
    telegram = None
    try:
        telegram = json.loads(telegram_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    local_universe = path.with_name("acciones_chile_universe.json")
    universe_path = (local_universe if local_universe.is_file()
                     else ROOT / "config" / "acciones_chile_universe_v0.1.json")
    universe = universe_status(load_universe(universe_path), date.today())
    universe["storage"] = "local_licensed" if universe_path == local_universe else "packaged_public"
    market_path = path.with_name("acciones_chile_market_data_status.json")
    market = None
    try:
        market = json.loads(market_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    price_ready = bool(
        (market or {}).get("label_ready") and universe["survivorship_free_backtest_allowed"])
    audit_snapshot["predictor"] = readiness(telegram, price_history_ready=price_ready)
    audit_snapshot["predictor"]["cmf_telegram_join"] = feature_join_report(data, telegram)
    audit_snapshot["predictor"]["universe"] = universe
    audit_snapshot["predictor"]["market_data"] = market or {"label_ready": False}
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
