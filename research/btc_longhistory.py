"""Histórico LARGO de BTC/USD diario desde 2013 (Bitstamp), para la anatomía de ciclos
bajistas. Bitstamp es de las series USD continuas más antiguas (parte 2011) y captura
el ATH de nov-2013 que Yahoo (parte 2014-09) se pierde.

Endpoint público: https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=86400 (diario),
paginado de a 1000 barras con `start`. Cacheado en research/data_macro/btc_bitstamp_1d.json.
Cada barra: {t (ms, cierre del día UTC), c (cierre USD)}.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_macro")
PATH = os.path.join(DATA_DIR, "btc_bitstamp_1d.json")
DAY = 86_400


def _fetch_chunk(start_s: int):
    url = (f"https://www.bitstamp.net/api/v2/ohlc/btcusd/?step={DAY}&limit=1000&start={start_s}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    return d["data"]["ohlc"]


def load(force: bool = False) -> list:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.isfile(PATH) and not force:
        with open(PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if (int(time.time() * 1000) - data[-1]["t"]) < 2 * DAY * 1000:
            return data
    start = int(time.mktime(time.strptime("2013-01-01", "%Y-%m-%d")))
    now = int(time.time())
    seen = {}
    while start < now:
        rows = _fetch_chunk(start)
        if not rows:
            break
        for o in rows:
            t = int(o["timestamp"])
            c = float(o["close"])
            if c > 0:
                seen[t] = c
        last = max(int(o["timestamp"]) for o in rows)
        if last <= start:
            break
        start = last + DAY
        time.sleep(0.3)
    out = [{"t": t * 1000, "c": c} for t, c in sorted(seen.items())]
    with open(PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    return out


def series():
    data = load()
    return [b["t"] for b in data], [b["c"] for b in data]


if __name__ == "__main__":
    data = load(force=True)
    ts = [b["t"] for b in data]
    cl = [b["c"] for b in data]
    print(f"Bitstamp BTC diario: {len(data)} barras "
          f"{time.strftime('%Y-%m-%d', time.gmtime(ts[0]/1000))} → "
          f"{time.strftime('%Y-%m-%d', time.gmtime(ts[-1]/1000))}")
    mx = max(cl)
    print(f"  ATH histórico en serie: ${mx:,.0f} "
          f"({time.strftime('%Y-%m-%d', time.gmtime(ts[cl.index(mx)]/1000))})")
    print(f"  último cierre: ${cl[-1]:,.0f}")
