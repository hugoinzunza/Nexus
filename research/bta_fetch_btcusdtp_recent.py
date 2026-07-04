"""Descarga reciente BTCUSDT.P 15m desde Binance Futures para estudio BTA.

No toca `data/klines_BTCUSDT_15m.json` porque esa cache histórica puede estar
usada por otros estudios. Esta salida es sólo de research.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "bta_btcusdtp_15m_recent.json")

URL = "https://fapi.binance.com/fapi/v1/klines"
STEP = 900_000
LIMIT = 1000


def ts(s: str) -> int:
    return int(time.mktime(time.strptime(s + " UTC", "%Y-%m-%d %H:%M %Z")) * 1000)


def fetch(start: int, end: int):
    out = []
    seen = set()
    cur = start
    while cur < end:
        url = f"{URL}?symbol=BTCUSDT&interval=15m&startTime={cur}&endTime={end}&limit={LIMIT}"
        req = urllib.request.Request(url, headers={"User-Agent": "Nexux-BTA-research/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            rows = json.load(resp)
        if not rows:
            break
        for r in rows:
            t = int(r[0])
            if t in seen:
                continue
            seen.add(t)
            out.append({"t": t, "o": float(r[1]), "h": float(r[2]),
                        "l": float(r[3]), "c": float(r[4]), "v": float(r[5])})
        last = int(rows[-1][0])
        if last <= cur:
            break
        cur = last + STEP
        time.sleep(0.15)
    out.sort(key=lambda c: c["t"])
    return out


def main():
    # Cubrir las zonas visibles recientes del profe y algo de contexto.
    start = ts("2026-05-01 00:00")
    end = int(time.time() * 1000)
    data = fetch(start, end)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    print(f"{OUT} {len(data)} velas")


if __name__ == "__main__":
    main()
