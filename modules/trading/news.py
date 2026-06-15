"""Calendario económico (eventos de alto impacto: CPI, FOMC, NFP, tasas…).

Fuente: feed semanal GRATIS de Forex Factory (sin API key). Solo lectura. Se usa
para el motor RISK-OFF: cuando falta poco para un evento de alto impacto, el bot
pausa entradas y protege lo abierto (igual que la guardia de volatilidad).

No es asesoría: es gestión de riesgo de contexto (cuándo NO operar).
"""
from __future__ import annotations

import datetime
import json
import time
import urllib.request

_FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_CACHE = {"ts": 0.0, "events": []}
_CACHE_TTL = 1800  # 30 min


def _parse_ts(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s).timestamp()   # ISO con offset
    except Exception:  # noqa: BLE001
        return None


def _fetch():
    req = urllib.request.Request(_FEED, headers={"User-Agent": "NexusBot/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def all_events(impact=("High",), countries=("USD",)):
    """Eventos del feed filtrados por impacto/país. Cacheado 30 min; ante error
    devuelve el último bueno (o vacío)."""
    now = time.time()
    if now - _CACHE["ts"] < _CACHE_TTL and _CACHE["events"]:
        return _CACHE["events"]
    try:
        raw = _fetch()
    except Exception:  # noqa: BLE001
        return _CACHE["events"]
    evs = []
    for e in raw or []:
        if impact and e.get("impact") not in impact:
            continue
        if countries and e.get("country") not in countries:
            continue
        ts = _parse_ts(e.get("date"))
        if ts is None:
            continue
        evs.append({"title": e.get("title"), "country": e.get("country"),
                    "impact": e.get("impact"), "ts": int(ts),
                    "forecast": e.get("forecast"), "previous": e.get("previous")})
    evs.sort(key=lambda x: x["ts"])
    _CACHE.update(ts=now, events=evs)
    return evs


def upcoming(max_keep=12):
    """Próximos eventos de alto impacto (y los de la última hora) para el panel."""
    now = time.time()
    out = [dict(e, in_min=round((e["ts"] - now) / 60)) for e in all_events() if e["ts"] > now - 3600]
    return out[:max_keep]


def danger_window(before_min=20, after_min=10):
    """Devuelve el evento de alto impacto si AHORA estamos en su ventana de peligro
    (desde `before_min` antes hasta `after_min` después), o None."""
    now = time.time()
    for e in all_events():
        if (e["ts"] - before_min * 60) <= now <= (e["ts"] + after_min * 60):
            return e
    return None
