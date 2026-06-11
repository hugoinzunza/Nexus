"""Cliente Binance — SOLO LECTURA.

REGLA DE ORO: este cliente solo hace consultas GET firmadas de LECTURA. No
existe ni existirá ninguna función para crear/cancelar órdenes, transferir ni
retirar. Si alguna vez hace falta operar, NO se hace acá.

Seguridad:
  - Las credenciales se leen de las variables de entorno BINANCE_API_KEY y
    BINANCE_API_SECRET en cada request. Nunca se hardcodean, ni se loguean, ni
    se incluyen en mensajes de error o URLs registradas.
  - Firmado HMAC-SHA256 sobre el query string, con timestamp y recvWindow.

Endpoints (todos de lectura):
  Futuros USDⓈ-M (fapi.binance.com):
    /fapi/v1/income          PnL realizado, comisiones y funding (paginado)
    /fapi/v2/positionRisk    posiciones abiertas
    /fapi/v2/balance         balances de futuros
  Spot (api.binance.com):
    /api/v3/account          balances spot
    /api/v3/ticker/price     precios públicos (sin firma) para valorizar
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

FAPI = "https://fapi.binance.com"
SAPI = "https://api.binance.com"
RECV_WINDOW = 5000
TIMEOUT = 15

# Caché en memoria con TTL (para no golpear la API en cada carga del panel).
_CACHE = {}


def have_keys() -> bool:
    return bool(os.environ.get("BINANCE_API_KEY") and os.environ.get("BINANCE_API_SECRET"))


def _keys():
    return os.environ.get("BINANCE_API_KEY", ""), os.environ.get("BINANCE_API_SECRET", "")


def _cache_get(key, ttl):
    item = _CACHE.get(key)
    if item and (time.time() - item[0]) < ttl:
        return item[1]
    return None


def _cache_set(key, value):
    _CACHE[key] = (time.time(), value)


class BinanceError(RuntimeError):
    """Error de la API de Binance, ya saneado (sin credenciales)."""


def _request(url: str, headers: dict):
    """GET crudo con reintentos ante rate limit. Nunca registra la URL firmada."""
    last = None
    for intento in range(4):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8")[:300]
            except Exception:  # noqa: BLE001
                pass
            if exc.code in (418, 429):  # rate limit / ban temporal → backoff
                time.sleep(1.5 * (intento + 1))
                last = BinanceError(f"rate limit (HTTP {exc.code})")
                continue
            # Mensaje de Binance saneado (no incluye claves ni firma).
            raise BinanceError(f"HTTP {exc.code}: {body}")
        except (urllib.error.URLError, TimeoutError) as exc:
            last = BinanceError(f"red: {exc}")
            time.sleep(1.0 * (intento + 1))
    raise last or BinanceError("fallo de red")


def public_get(base: str, path: str, params: dict = None):
    qs = urllib.parse.urlencode(params or {})
    url = f"{base}{path}" + (f"?{qs}" if qs else "")
    return _request(url, {})


def signed_get(base: str, path: str, params: dict = None):
    """GET firmado de lectura. Lee las credenciales del entorno en cada llamada."""
    key, secret = _keys()
    if not key or not secret:
        raise BinanceError("sin credenciales (BINANCE_API_KEY / BINANCE_API_SECRET)")
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = RECV_WINDOW
    qs = urllib.parse.urlencode(p)
    sig = hmac.new(secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{base}{path}?{qs}&signature={sig}"
    return _request(url, {"X-MBX-APIKEY": key})


# --- Futuros USDⓈ-M -----------------------------------------------------
def futures_income(start_ms: int, end_ms: int) -> list:
    """Trae el income de futuros (todos los tipos: REALIZED_PNL, COMMISSION,
    FUNDING_FEE, etc.) entre start y end, paginando en ventanas de 7 días."""
    out = []
    seven = 7 * 86_400_000
    start = start_ms
    while start < end_ms:
        wend = min(start + seven, end_ms)
        rows = signed_get(FAPI, "/fapi/v1/income",
                          {"startTime": start, "endTime": wend, "limit": 1000})
        out.extend(rows)
        if len(rows) == 1000:
            # Ventana saturada: avanzamos justo después del último registro.
            start = int(rows[-1]["time"]) + 1
        else:
            start = wend + 1
        time.sleep(0.15)
    return out


def futures_positions() -> list:
    return signed_get(FAPI, "/fapi/v2/positionRisk", {})


def futures_balances() -> list:
    return signed_get(FAPI, "/fapi/v2/balance", {})


# --- Spot ----------------------------------------------------------------
def spot_account() -> dict:
    return signed_get(SAPI, "/api/v3/account", {})


def all_prices() -> dict:
    """Precios públicos (sin firma). Devuelve {symbol: price}. Cacheado 60s."""
    cached = _cache_get("prices", 60)
    if cached is not None:
        return cached
    rows = public_get(SAPI, "/api/v3/ticker/price")
    prices = {r["symbol"]: float(r["price"]) for r in rows}
    _cache_set("prices", prices)
    return prices
