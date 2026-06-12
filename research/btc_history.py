"""Histórico máximo de BTC (diario) y resampleo a semanal / quincenal, para el motor
de análogos macro.

Fuente: API pública de Yahoo Finance (BTC-USD), con period1/period2 explícitos para
forzar resolución DIARIA (range=max devuelve mensual). Cobertura: 2014-09 → hoy
(~4280 días, ~610 semanas, ~3 ciclos de BTC). Cacheado en research/data_macro/.

Cada barra: {t (ms, cierre), c (cierre USD)}. Para análogos macro usamos el cierre
(log-precio). El resampleo semanal toma el ÚLTIMO cierre de cada semana ISO; el
quincenal agrupa de a 2 semanas. t = timestamp del último día del bucket.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_macro")
DAILY_PATH = os.path.join(DATA_DIR, "btc_daily_full.json")
DAY_MS = 86_400_000


def _fetch_daily():
    p1 = int(time.mktime(time.strptime("2014-09-01", "%Y-%m-%d")))
    p2 = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD"
           f"?period1={p1}&period2={p2}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    cl = res["indicators"]["quote"][0]["close"]
    vol = res["indicators"]["quote"][0].get("volume", [None] * len(ts))
    out = []
    for t, c, v in zip(ts, cl, vol):
        if c is None:
            continue
        out.append({"t": int(t) * 1000, "c": float(c), "v": float(v) if v else 0.0})
    out.sort(key=lambda x: x["t"])
    return out


def load_daily(force: bool = False) -> list:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.isfile(DAILY_PATH) and not force:
        with open(DAILY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Refrescar si está viejo (> 2 días).
        if (int(time.time() * 1000) - data[-1]["t"]) < 2 * DAY_MS:
            return data
    data = _fetch_daily()
    with open(DAILY_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return data


def resample(daily: list, weeks_per_bar: int = 1) -> list:
    """Agrupa el diario en barras de `weeks_per_bar` semanas. Devuelve [{t, c, v}]
    con el cierre del último día del bucket. Semana ISO = (días desde epoch)//7,
    alineada a lunes (epoch jueves → ajustamos +3 para que el corte caiga lunes)."""
    buckets = {}
    for d in daily:
        day = d["t"] // DAY_MS
        wk = (day + 3) // 7                 # +3: epoch (1970-01-01) fue jueves → lunes
        bar = wk // weeks_per_bar
        # nos quedamos con el último día (mayor t) de cada bar
        prev = buckets.get(bar)
        if prev is None or d["t"] > prev["t"]:
            buckets[bar] = {"t": d["t"], "c": d["c"], "v": d["v"]}
    return [buckets[k] for k in sorted(buckets)]


def get_series(scale: str = "weekly", force: bool = False):
    """Devuelve (timestamps_ms, closes) para la escala pedida: 'daily' | 'weekly' |
    'biweekly'."""
    daily = load_daily(force=force)
    if scale == "daily":
        bars = daily
    elif scale == "weekly":
        bars = resample(daily, 1)
    elif scale == "biweekly":
        bars = resample(daily, 2)
    else:
        raise ValueError(scale)
    return [b["t"] for b in bars], [b["c"] for b in bars]


if __name__ == "__main__":
    daily = load_daily(force=True)
    print(f"BTC diario: {len(daily)} barras "
          f"{time.strftime('%Y-%m-%d', time.gmtime(daily[0]['t']/1000))} → "
          f"{time.strftime('%Y-%m-%d', time.gmtime(daily[-1]['t']/1000))}")
    for scale in ("weekly", "biweekly"):
        ts, cl = get_series(scale)
        print(f"  {scale:9}: {len(cl)} barras · primer/último cierre "
              f"{cl[0]:.0f} / {cl[-1]:.0f}")
