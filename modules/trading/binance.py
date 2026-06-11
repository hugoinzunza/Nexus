"""Descarga de klines (velas) históricas de Binance — API pública, sin clave.

Endpoint: https://api.binance.com/api/v3/klines  (solo lectura, datos públicos)

Se usa para el BACKTEST (no para el panel en vivo, que sigue con Crypto.com).
Binance entrega mucho más histórico que Crypto.com, ideal para testear estrategias.

Las velas se cachean en disco (carpeta `data/`, ya en .gitignore) para no volver
a bajar lo mismo cada vez. Cada vela queda como dict {t,o,h,l,c,v} con t en ms.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

BASE_URL = "https://api.binance.com/api/v3/klines"
FUTURES_URL = "https://fapi.binance.com/fapi/v1/klines"  # perpetuo USDⓈ-M (BTCUSDT.P)
TIMEOUT = 20
MAX_LIMIT = 1000  # tope de Binance por petición

# Mapeo de la temporalidad de la UI al intervalo de Binance (Binance usa "1d").
UI_TO_BINANCE = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
                 "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "12h": "12h",
                 "1D": "1d", "1d": "1d", "1W": "1w", "1M": "1M"}


def recent_klines(symbol: str, ui_timeframe: str, limit: int = 300, market: str = "futures") -> list:
    """Velas recientes de Binance (sin caché, para el gráfico/estructura en vivo).

    market="futures" usa el perpetuo USDⓈ-M (fapi, lo que Hugo ve como BTCUSDT.P);
    "spot" usa api/v3. Devuelve [{t,o,h,l,c,v}] (t en ms, más antigua → más reciente).

    Una sola petición, SIN reintentos: si falla (p.ej. HTTP 451 geo-block desde
    Railway), levanta enseguida para caer rápido a otra fuente.
    """
    interval = UI_TO_BINANCE.get(ui_timeframe, ui_timeframe)
    base = FUTURES_URL if market == "futures" else BASE_URL
    url = f"{base}?symbol={symbol}&interval={interval}&limit={min(limit, MAX_LIMIT)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Nexus-live/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        rows = json.load(resp)
    out = []
    for r in rows:
        out.append({"t": int(r[0]), "o": float(r[1]), "h": float(r[2]),
                    "l": float(r[3]), "c": float(r[4]), "v": float(r[5])})
    return out

# Milisegundos por vela según el intervalo (para paginar y validar).
INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000,
    "12h": 43_200_000, "1d": 86_400_000,
}


def _http_get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Nexus-backtest/1.0"})
    last_err = None
    for intento in range(4):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.load(resp)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_err = exc
            time.sleep(1.5 * (intento + 1))
    raise RuntimeError(f"Binance no respondió tras varios intentos: {last_err}")


def _cache_path(data_dir: str, symbol: str, interval: str) -> str:
    return os.path.join(data_dir, f"klines_{symbol}_{interval}.json")


def fetch_klines(symbol: str, interval: str, years: float = 3.0,
                 data_dir: str = "data", log=print, force: bool = False) -> list:
    """Devuelve la lista de velas {t,o,h,l,c,v} de los últimos `years` años.

    Usa caché en disco: si ya hay un archivo y cubre el rango pedido, lo lee;
    si el archivo está incompleto o `force`, completa lo que falte desde Binance.
    """
    os.makedirs(data_dir, exist_ok=True)
    path = _cache_path(data_dir, symbol, interval)
    step = INTERVAL_MS[interval]
    now_ms = int(time.time() * 1000)
    want_start = now_ms - int(years * 365 * 86_400_000)

    cached: list = []
    if os.path.isfile(path) and not force:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                cached = json.load(fh)
        except Exception:  # noqa: BLE001
            cached = []

    # Si la caché ya cubre desde antes del inicio pedido y está fresca, la usamos.
    if cached:
        first_t = cached[0]["t"]
        last_t = cached[-1]["t"]
        fresh = (now_ms - last_t) < 2 * step
        if first_t <= want_start and fresh and not force:
            return [v for v in cached if v["t"] >= want_start]

    # Punto de arranque: si la caché es fresca Y ya llega hasta atrás de lo pedido,
    # solo completamos lo nuevo. Si pedimos MÁS historia de la cacheada, rebajamos
    # todo desde el inicio pedido (backfill).
    if (cached and (now_ms - cached[-1]["t"]) < 30 * 86_400_000
            and cached[0]["t"] <= want_start and not force):
        start = cached[-1]["t"] + step
        out = list(cached)
        seen = {v["t"] for v in cached}
    else:
        start = want_start
        out = []
        seen = set()

    log(f"binance: descargando {symbol} {interval} desde "
        f"{time.strftime('%Y-%m-%d', time.gmtime(start/1000))}…")

    fetched_batches = 0
    while start < now_ms:
        url = (f"{BASE_URL}?symbol={symbol}&interval={interval}"
               f"&startTime={start}&limit={MAX_LIMIT}")
        rows = _http_get_json(url)
        if not rows:
            break
        for r in rows:
            t = int(r[0])
            if t in seen:
                continue
            seen.add(t)
            out.append({
                "t": t,
                "o": float(r[1]), "h": float(r[2]), "l": float(r[3]),
                "c": float(r[4]), "v": float(r[5]),
            })
        fetched_batches += 1
        last = int(rows[-1][0])
        if last <= start:
            break
        start = last + step
        if len(rows) < MAX_LIMIT:
            break
        time.sleep(0.25)  # cortesía con la API pública

    out.sort(key=lambda v: v["t"])
    # Persistimos todo (histórico completo) para próximas corridas.
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    log(f"binance: {symbol} {interval} → {len(out)} velas en caché "
        f"({fetched_batches} lotes nuevos)")
    return [v for v in out if v["t"] >= want_start]
