"""Cliente de la API pública (REST) de Crypto.com Exchange.

Documentación: https://exchange-docs.crypto.com

Solo usamos endpoints PÚBLICOS de lectura de datos de mercado. No hay claves,
no hay órdenes, no se mueve dinero. Este módulo es un "co-piloto": observa el
mercado y lo muestra; nunca opera.

Endpoints usados (API v1):
  - public/get-tickers       → precio, bid/ask, máx/mín 24h, cambio %, volumen
  - public/get-book          → libro de órdenes (bids/asks)
  - public/get-candlestick   → velas OHLCV para el gráfico
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error

BASE_URL = "https://api.crypto.com/exchange/v1"
TIMEOUT = 12


def _get(path: str) -> dict:
    """GET a un endpoint público y devuelve el JSON parseado.

    Lanza excepción si falla la red o la API responde con código de error.
    """
    req = urllib.request.Request(
        BASE_URL + path,
        headers={"User-Agent": "Nexus/0.1 (+local Mac mini)"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        payload = json.load(resp)
    if payload.get("code", 0) != 0:
        raise RuntimeError(f"API Crypto.com devolvió código {payload.get('code')}: {payload}")
    return payload.get("result", {})


def _f(value, default=0.0) -> float:
    """Convierte a float de forma segura (la API manda números como strings)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_ticker(instrument: str) -> dict:
    """Datos de precio en vivo para un instrumento (ej: BTC_USDT)."""
    result = _get(f"/public/get-tickers?instrument_name={instrument}")
    data = result.get("data", [])
    if not data:
        raise RuntimeError(f"sin datos de ticker para {instrument}")
    t = data[0]
    return {
        "instrument": t.get("i", instrument),
        "last": _f(t.get("a")),      # último precio negociado
        "bid": _f(t.get("b")),       # mejor compra
        "ask": _f(t.get("k")),       # mejor venta
        "high": _f(t.get("h")),      # máximo 24h
        "low": _f(t.get("l")),       # mínimo 24h
        "change": _f(t.get("c")),    # variación 24h (fracción: 0.003 = 0.3%)
        "volume": _f(t.get("v")),    # volumen 24h (en la cripto base)
        "value": _f(t.get("vv")),    # valor negociado 24h (en la moneda quote)
        "ts": int(t.get("t", 0)),
    }


def get_book(instrument: str, depth: int = 12) -> dict:
    """Libro de órdenes: niveles de compra (bids) y venta (asks).

    Cada nivel es [precio, cantidad, número_de_órdenes].
    """
    result = _get(f"/public/get-book?instrument_name={instrument}&depth={depth}")
    data = result.get("data", [])
    if not data:
        return {"bids": [], "asks": []}
    level = data[0]

    def norm(rows):
        out = []
        for row in rows:
            out.append({"price": _f(row[0]), "qty": _f(row[1]),
                        "orders": int(row[2]) if len(row) > 2 else 1})
        return out

    return {"bids": norm(level.get("bids", [])), "asks": norm(level.get("asks", []))}


def get_candles(instrument: str, timeframe: str = "1m", count: int = 200) -> list:
    """Velas OHLCV. Devuelve lista ordenada (más antigua → más reciente)."""
    result = _get(
        f"/public/get-candlestick?instrument_name={instrument}"
        f"&timeframe={timeframe}&count={count}"
    )
    out = []
    for c in result.get("data", []):
        out.append({
            "t": int(c.get("t", 0)),   # timestamp en ms (inicio de la vela)
            "o": _f(c.get("o")),
            "h": _f(c.get("h")),
            "l": _f(c.get("l")),
            "c": _f(c.get("c")),
            "v": _f(c.get("v")),
        })
    out.sort(key=lambda x: x["t"])
    return out
