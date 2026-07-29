"""Calendario económico (eventos de alto impacto: CPI, FOMC, NFP, tasas…).

Fuente: feed semanal GRATIS de Forex Factory (sin API key). Solo lectura. Se usa
para el motor RISK-OFF: cuando falta poco para un evento de alto impacto, el bot
pausa entradas y protege lo abierto (igual que la guardia de volatilidad).

No es asesoría: es gestión de riesgo de contexto (cuándo NO operar).
"""
from __future__ import annotations

import datetime
import json
import os
import time
import urllib.request

_FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_RAW_CACHE = {"ts": 0.0, "raw": None}   # feed crudo cacheado (se filtra por llamada)
_CACHE_TTL = 1800  # 30 min
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CACHE_FILE = os.path.join(_ROOT, "data", "news_calendar_cache.json")

# Economías mayores: para el panel "Fechas clave" del Home (no solo USD).
_MAJORS = ("USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "NZD")


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


def _load_disk_cache():
    try:
        with open(_CACHE_FILE, encoding="utf-8") as fh:
            payload = json.load(fh)
        raw = payload.get("raw")
        return raw if isinstance(raw, list) else None
    except (OSError, ValueError, TypeError):
        return None


def _save_disk_cache(raw):
    """Persiste el último calendario bueno para sobrevivir deploys y rate limits."""
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        tmp = _CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"saved_at": int(time.time()), "raw": raw}, fh)
        os.replace(tmp, _CACHE_FILE)
    except OSError:
        pass


def _raw():
    """Feed crudo cacheado 30 min (se filtra por llamada). Ante error, el último bueno."""
    now = time.time()
    if _RAW_CACHE["raw"] is None:
        _RAW_CACHE["raw"] = _load_disk_cache()
    if now - _RAW_CACHE["ts"] < _CACHE_TTL and _RAW_CACHE["raw"] is not None:
        return _RAW_CACHE["raw"]
    try:
        raw = _fetch()
    except Exception:  # noqa: BLE001
        # Backoff también en error: sin esto un 429 provoca otro request en cada
        # tick del poller y prolonga indefinidamente el rate limit.
        _RAW_CACHE["ts"] = now
        return _RAW_CACHE["raw"] or []
    _RAW_CACHE.update(ts=now, raw=raw)
    _save_disk_cache(raw)
    return raw


def all_events(impact=("High",), countries=("USD",)):
    """Eventos del feed filtrados por impacto/país (orden cronológico). Cachea el feed
    crudo, así distintos filtros no se pisan."""
    evs = []
    for e in _raw() or []:
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
    return evs


def upcoming(max_keep=12):
    """Próximos eventos de alto impacto USD (y los de la última hora) para el motor
    de riesgo y la barra de la página de Trading."""
    now = time.time()
    out = [dict(e, in_min=round((e["ts"] - now) / 60)) for e in all_events() if e["ts"] > now - 3600]
    return out[:max_keep]


def event_window_minutes(event):
    """Ventana de bloqueo según el tipo de evento.

    FOMC tiene dos hitos separados: comunicado/tasa y conferencia. Una ventana
    genérica corta puede quedar abierta justo entre ambos o terminar mientras
    sigue hablando el presidente de la Fed.
    """
    title = str((event or {}).get("title") or "").lower()
    if any(term in title for term in (
            "federal funds rate", "fomc statement", "interest rate decision")):
        return 45, 120
    if any(term in title for term in (
            "fomc press conference", "fed chair", "fomc member")):
        return 30, 90
    if any(term in title for term in (
            "non-farm", "nonfarm", "cpi", "pce price", "advance gdp")):
        return 20, 30
    return 20, 15


def _enrich_window(event, now):
    before_min, after_min = event_window_minutes(event)
    start = event["ts"] - before_min * 60
    end = event["ts"] + after_min * 60
    return dict(
        event,
        in_min=round((event["ts"] - now) / 60),
        window_before_min=before_min,
        window_after_min=after_min,
        active_from=int(start),
        active_until=int(end),
    )


def week_key_events(max_keep=8):
    """Fechas clave de la SEMANA para el panel del Home: alto impacto de economías
    mayores (no solo USD), recientes (últimas 24 h) + próximos, en orden cronológico.
    A diferencia de upcoming() (solo USD futuros, para el motor), esto da contexto
    macro aunque el gran evento de la semana ya haya pasado, así el panel no queda vacío."""
    evs = all_events(impact=("High",), countries=_MAJORS)
    if not evs:
        return []
    now = time.time()
    window = [e for e in evs if e["ts"] > now - 24 * 3600]
    if not window:
        # Ya pasó todo (fin de semana): muestra los últimos de la semana como contexto.
        window = evs[-3:]
    return [dict(e, in_min=round((e["ts"] - now) / 60)) for e in window][:max_keep]


def danger_window(before_min=None, after_min=None, now=None):
    """Devuelve el evento de alto impacto si AHORA estamos en su ventana de peligro
    o None. Por defecto usa ventanas específicas; los argumentos conservan la API
    anterior para pruebas o consumidores que necesiten una ventana uniforme."""
    now = time.time() if now is None else float(now)
    active = []
    for e in all_events():
        if before_min is None or after_min is None:
            enriched = _enrich_window(e, now)
        else:
            enriched = dict(
                e,
                in_min=round((e["ts"] - now) / 60),
                window_before_min=before_min,
                window_after_min=after_min,
                active_from=int(e["ts"] - before_min * 60),
                active_until=int(e["ts"] + after_min * 60),
            )
        if enriched["active_from"] <= now <= enriched["active_until"]:
            active.append(enriched)
    if not active:
        return None
    # Si hay eventos solapados (tasa + comunicado + conferencia), muestra el hito
    # más reciente y conserva el final más lejano de todo el episodio.
    selected = max(active, key=lambda e: e["ts"])
    selected["active_until"] = max(e["active_until"] for e in active)
    selected["episode_titles"] = list(dict.fromkeys(e["title"] for e in active))
    return selected


def fundamental_status(now=None):
    """Estado compacto para paneles y ejecutores; no modifica posiciones abiertas."""
    now = time.time() if now is None else float(now)
    active = danger_window(now=now)
    future = [
        _enrich_window(e, now) for e in all_events()
        if e["ts"] > now
    ]
    return {
        "active": active,
        "next": future[0] if future else None,
        "blocks_new_entries": bool(active),
    }
