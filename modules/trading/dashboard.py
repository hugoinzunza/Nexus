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

import email.utils
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import regime
from . import news

_UA = {"User-Agent": "NexUX/1.0 (dashboard)"}
_CG = "https://api.coingecko.com/api/v3"
# CoinGecko id → símbolo para la tabla de mercado.
_COINS = [("bitcoin", "BTC"), ("ethereum", "ETH"), ("solana", "SOL"),
          ("ripple", "XRP"), ("dogecoin", "DOGE"), ("cardano", "ADA")]

_CACHE = {}   # key -> (ts, value)

# Feeds RSS de noticias cripto (gratis, sin clave, alcanzables desde Railway).
# (url, fuente, idioma). Los "es" salen ya en español; los "en" se traducen con
# Claude en la capa de endpoint (cacheado, tolerante).
_FEEDS = [("https://decrypt.co/es/feed", "Decrypt", "es"),
          ("https://es.beincrypto.com/feed/", "BeInCrypto", "es"),
          ("https://cointelegraph.com/rss", "Cointelegraph", "en")]
# Palabras que marcan una noticia como de impacto ALTO (heurística simple).
_HOT = ("sec", "etf", "fomc", "fed", "rate", "cpi", "inflation", "hack", "lawsuit",
        "ban", "regulation", "genius", "treasury", "powell", "crash", "liquidat")


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


def _fetch_text(url: str, timeout: float = 10.0):
    """GET texto crudo (para RSS/XML). None si falla."""
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None


def _safe_news_url(value: str | None) -> str | None:
    """Acepta solo enlaces web absolutos provenientes del RSS."""
    candidate = (value or "").strip()
    try:
        parsed = urllib.parse.urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return candidate


def _news_feed(max_keep: int = 6):
    """Titulares cripto recientes de los feeds RSS, ordenados por fecha. Cacheado
    20 min en memoria; tolerante (si un feed cae, sigue con los demás)."""
    ck = "_news_feed"
    item = _CACHE.get(ck)
    if item and (time.time() - item[0]) < 1200:
        return item[1]
    out = []
    now = time.time()
    for url, source, lang in _FEEDS:
        raw = _fetch_text(url)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
        except Exception:  # noqa: BLE001
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            if not title:
                continue
            link = _safe_news_url(it.findtext("link"))
            ts = None
            pub = it.findtext("pubDate")
            if pub:
                try:
                    ts = email.utils.parsedate_to_datetime(pub).timestamp()
                except Exception:  # noqa: BLE001
                    ts = None
            low = title.lower()
            impact = "high" if any(w in low for w in _HOT) else "med"
            age_min = int((now - ts) / 60) if ts else None
            out.append({"title": title, "source": source, "lang": lang,
                        "url": link, "ts": ts, "age_min": age_min,
                        "impact": impact})
    # Más recientes primero (los sin fecha al final).
    out.sort(key=lambda x: x["ts"] or 0, reverse=True)
    out = out[:max_keep]
    if out:
        _CACHE[ck] = (now, out)
        return out
    return item[1] if item else []


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


def _macro_band(score: float) -> str:
    if score < 25:
        return "Risk-off fuerte"
    if score < 42:
        return "Risk-off"
    if score <= 58:
        return "Neutral"
    if score <= 75:
        return "Risk-on"
    return "Risk-on fuerte"


def _macro_thermometer(ind: dict) -> dict | None:
    """Sintetiza los indicadores en UNA sola lectura risk-off ↔ risk-on
    (0 = aversión total, 100 = apetito total). Snapshot honesto: solo entran al
    promedio los datos que llegaron en vivo; cada driver aporta un sub-puntaje
    0–100 y un peso. Es contexto público (anzuelo), no una señal accionable.
    """
    drivers = []   # (nombre, sub-puntaje 0–100, peso, etiqueta corta)

    fg = ind.get("fear_greed")
    if fg and fg.get("value") is not None:
        v = max(0.0, min(100.0, float(fg["value"])))
        tag = "codicia" if v >= 55 else "miedo" if v < 45 else "neutral"
        drivers.append(("Fear & Greed", v, 1.0, tag))

    vix = ind.get("vix")
    if vix is not None:
        # VIX bajo = calma = risk-on. 12 → 100, 35 → 0 (lineal, recortado).
        s = max(0.0, min(100.0, (35.0 - vix) / (35.0 - 12.0) * 100.0))
        tag = "calma" if vix < 20 else "estrés" if vix > 25 else "precaución"
        drivers.append(("VIX", s, 1.0, tag))

    mc = ind.get("market_cap_24h_pct")
    if mc is not None:
        # ±5% en 24h satura la escala.
        s = max(0.0, min(100.0, 50.0 + mc * 10.0))
        tag = "entra" if mc > 0.3 else "sale" if mc < -0.3 else "plano"
        drivers.append(("Capital 24h", s, 0.8, tag))

    fund = ind.get("funding")
    if fund is not None:
        # ±0.05%/8h satura. Positivo = longs pagan = sesgo alcista.
        s = max(0.0, min(100.0, 50.0 + fund * 100000.0))
        tag = "alcista" if fund > 0 else "bajista" if fund < 0 else "plano"
        drivers.append(("Funding", s, 0.6, tag))

    if not drivers:
        return None
    total_w = sum(w for _, _, w, _ in drivers)
    score = round(sum(s * w for _, s, w, _ in drivers) / total_w)
    return {
        "score": score,
        "label": _macro_band(score),
        "drivers": [{"name": n, "score": round(s), "tag": t}
                    for n, s, _, t in drivers],
    }


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
        # El Command Center selecciona el próximo evento futuro. Un límite de
        # ocho podía agotarse con eventos recientes y ocultar los que venían.
        cal = news.week_key_events(max_keep=24)
    except Exception:  # noqa: BLE001
        cal = []
    indicators = {
        "fear_greed": _fear_greed(),
        "btc_dominance": g.get("btc_dominance"),
        "market_cap_usd": g.get("market_cap_usd"),
        "market_cap_24h_pct": g.get("market_cap_24h_pct"),
        "vix": round(vix, 1) if vix is not None else None,
        "eth_btc": eth_btc,
        "funding": None,   # pendiente (Binance vía VPS)
    }
    indicators["macro"] = _macro_thermometer(indicators)
    return {
        "generated_at_ms": int(time.time() * 1000),
        "indicators": indicators,
        "market": mk,
        "calendar": cal,
        "news": _news_feed(),
    }
