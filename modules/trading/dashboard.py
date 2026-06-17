"""Agregador de datos EN VIVO para el centro de mando (Home de NexUX).

Reúne indicadores, mercado y calendario de fuentes reales y los cachea en memoria
(cambian lento). Fuentes públicas (no geo-bloqueadas como Binance, así que sirven
desde Railway):
  - Fear & Greed  → alternative.me (público, sin clave)
  - Dominancia BTC + market cap total → CoinGecko /global
  - Precios + 24h de los pares → CoinGecko /coins/markets
  - VIX → regime.vix_now() (lo que ya teníamos)
  - Calendario económico → news.upcoming() (CPI/FOMC/NFP)
  - ETH/BTC → derivado de los precios

Tolerante a fallos: si una fuente cae, ese campo va None y el resto sigue. Funding
(depende de Binance, geo-bloqueado en Railway) queda pendiente: lo empuja el VPS.
"""
from __future__ import annotations

import json
import time
import urllib.request

from . import regime
from . import news

_UA = {"User-Agent": "NexUX/1.0 (dashboard)"}
_CG = "https://api.coingecko.com/api/v3"
# CoinGecko id → símbolo para la tabla de mercado.
_COINS = [("bitcoin", "BTC"), ("ethereum", "ETH"), ("solana", "SOL"),
          ("ripple", "XRP"), ("dogecoin", "DOGE"), ("cardano", "ADA")]

_CACHE = {}   # key -> (ts, value)


def _get(url: str, ttl: float, timeout: float = 8.0):
    """GET JSON con caché en memoria por TTL. None si falla (tolerante)."""
    item = _CACHE.get(url)
    if item and (time.time() - item[0]) < ttl:
        return item[1]
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        _CACHE[url] = (time.time(), data)
        return data
    except Exception:  # noqa: BLE001
        return item[1] if item else None   # sirve lo último bueno si lo hay


def _fear_greed():
    d = _get("https://api.alternative.me/fng/?limit=1", ttl=600)
    try:
        row = d["data"][0]
        return {"value": int(row["value"]), "label": row.get("value_classification")}
    except Exception:  # noqa: BLE001
        return None


def _global():
    d = _get(f"{_CG}/global", ttl=300)
    try:
        g = d["data"]
        return {"btc_dominance": round(g["market_cap_percentage"]["btc"], 1),
                "market_cap_usd": g["total_market_cap"]["usd"],
                "market_cap_24h_pct": round(g["market_cap_change_percentage_24h_usd"], 2)}
    except Exception:  # noqa: BLE001
        return None


def _markets():
    ids = ",".join(c[0] for c in _COINS)
    d = _get(f"{_CG}/coins/markets?vs_currency=usd&ids={ids}&price_change_percentage=24h", ttl=120)
    if not isinstance(d, list):
        return None
    by_id = {row.get("id"): row for row in d}
    out = []
    for cid, sym in _COINS:
        row = by_id.get(cid)
        if not row:
            continue
        out.append({"symbol": sym, "price": row.get("current_price"),
                    "change_24h": round(row.get("price_change_percentage_24h") or 0.0, 1),
                    "market_cap": row.get("market_cap")})
    return out or None


def get_dashboard() -> dict:
    """Snapshot completo del centro de mando con datos reales."""
    g = _global() or {}
    mk = _markets() or []
    px = {m["symbol"]: m["price"] for m in mk}
    eth_btc = None
    if px.get("ETH") and px.get("BTC"):
        eth_btc = round(px["ETH"] / px["BTC"], 4)
    try:
        vix = regime.vix_now()
    except Exception:  # noqa: BLE001
        vix = None
    try:
        cal = news.upcoming(max_keep=8)
    except Exception:  # noqa: BLE001
        cal = []
    return {
        "generated_at_ms": int(time.time() * 1000),
        "indicators": {
            "fear_greed": _fear_greed(),
            "btc_dominance": g.get("btc_dominance"),
            "market_cap_usd": g.get("market_cap_usd"),
            "market_cap_24h_pct": g.get("market_cap_24h_pct"),
            "vix": round(vix, 1) if vix is not None else None,
            "eth_btc": eth_btc,
            "funding": None,   # pendiente (Binance vía VPS)
        },
        "market": mk,
        "calendar": cal,
    }
