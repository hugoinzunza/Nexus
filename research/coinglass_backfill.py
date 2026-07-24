#!/usr/bin/env python3
"""Backfill the read-only CoinGlass 4h history available to Hobbyist."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.coinsignals.coinglass import backfill_market_history


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--store",
        type=Path,
        default=ROOT / "data/coinsignals_coinglass.json",
    )
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--pause-seconds", type=float, default=0)
    args = parser.parse_args()
    api_key = os.environ.get("COINGLASS_API_KEY", "")
    if not api_key:
        raise SystemExit("COINGLASS_API_KEY is required")

    latest, history = backfill_market_history(
        api_key,
        args.store,
        days=args.days,
        window_days=args.window_days,
        interval="4h",
        pause_seconds=args.pause_seconds,
    )
    backfilled = sum(row.get("history_origin") == "backfill" for row in history)
    print(
        f"CoinGlass backfill: {backfilled} historical bars, "
        f"{len(history) - backfilled} forward bars, latest={bool(latest)}"
    )


if __name__ == "__main__":
    main()
