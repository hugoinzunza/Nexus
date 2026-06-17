"""Brief diario del centro de mando, sintetizado por Claude.

Toma el snapshot EN VIVO del dashboard (indicadores + calendario + titulares) y
le pide a Claude un resumen corto en español: qué está pasando hoy y qué vigilar.
Es CONTEXTO, no asesoría — no da señales de compra/venta.

Diseño defensivo (igual que claude_grader):
  - SDK `anthropic` perezoso; si falta o no hay key, queda deshabilitado.
  - Caché en memoria ~2h: NO llamamos a Claude en cada carga de página (costo).
  - Cualquier error → None; el Home muestra el brief estático de respaldo.
"""
from __future__ import annotations

import re
import time
from typing import Optional

from .claude_grader import _resolve_key  # mismo resolutor de key (entorno/env)

MODEL = "claude-opus-4-8"           # brief: cara visible, prosa pulida
TRANSLATE_MODEL = "claude-haiku-4-5"  # traducir titulares: tarea trivial, 5× más barato
_TTL = 7200  # 2h: el contexto macro cambia lento

_client = None
_checked = False
_enabled = False
_cache = {"ts": 0.0, "text": None}

SYSTEM = """Eres el analista de NexUX, un panel de contexto para traders de cripto. \
Con los datos EN VIVO que te paso (indicadores, calendario económico y titulares), \
escribe un BRIEF de 2-3 frases en español neutro y claro: qué define el día y qué \
vigilar. Es CONTEXTO, NO asesoría: no des señales de compra/venta ni precios objetivo, \
no inventes datos que no estén. Tono sobrio y profesional, sin emojis."""


def available() -> bool:
    global _checked, _enabled, _client
    if _checked:
        return _enabled
    _checked = True
    key = _resolve_key()
    if not key:
        return False
    try:
        import anthropic  # perezoso: no romper si falta (Railway sin SDK)
        _client = anthropic.Anthropic(api_key=key)
        _enabled = True
    except Exception:  # noqa: BLE001
        _enabled = False
    return _enabled


def _context(dash: dict) -> str:
    ind = dash.get("indicators", {}) or {}
    fg = ind.get("fear_greed") or {}
    lines = [
        f"Fear & Greed: {fg.get('value')} ({fg.get('label')})",
        f"Dominancia BTC: {ind.get('btc_dominance')}%",
        f"Market cap total: {ind.get('market_cap_usd')} (24h {ind.get('market_cap_24h_pct')}%)",
        f"VIX: {ind.get('vix')}",
        f"ETH/BTC: {ind.get('eth_btc')}",
    ]
    mk = dash.get("market") or []
    if mk:
        lines.append("Mercado 24h: " + ", ".join(
            f"{m['symbol']} {m.get('change_24h')}%" for m in mk))
    cal = dash.get("calendar") or []
    if cal:
        lines.append("Próximos eventos: " + "; ".join(
            f"{e.get('title')} ({e.get('country')})" for e in cal[:4]))
    nw = dash.get("news") or []
    if nw:
        lines.append("Titulares: " + " | ".join(n["title"] for n in nw[:5]))
    return "\n".join(lines)


_tr_cache: dict = {}  # título original -> traducción al español (persistente)


def translate_titles(titles: list) -> dict:
    """Traduce al español los títulos dados (los que ya estén en español se
    devuelven igual). Cacheado por título: solo llama a Claude por los nuevos.
    Tolerante: si Claude no está o falla, devuelve el original sin romper."""
    titles = [t for t in titles if t]
    if not titles:
        return {}
    todo = [t for t in titles if t not in _tr_cache]
    if todo and available():
        try:
            numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(todo))
            resp = _client.messages.create(
                model=TRANSLATE_MODEL, max_tokens=1200,
                system=("Traduce al español neutro CADA titular de noticia cripto. "
                        "Si ya está en español, devuélvelo igual. Mantén nombres "
                        "propios y tickers. Responde SOLO la lista numerada, un "
                        "título por línea, sin comentarios."),
                messages=[{"role": "user", "content": numbered}],
            )
            text = "".join(b.text for b in resp.content
                           if getattr(b, "type", "") == "text")
            for line in text.splitlines():
                m = re.match(r"^\s*(\d+)[.)]\s*(.+)$", line.strip())
                if not m:
                    continue
                idx = int(m.group(1)) - 1
                if 0 <= idx < len(todo):
                    _tr_cache[todo[idx]] = m.group(2).strip()
        except Exception:  # noqa: BLE001
            pass
    return {t: _tr_cache.get(t, t) for t in titles}


def get_brief(dash: dict) -> Optional[str]:
    """Brief cacheado (~2h). None si Claude no está disponible o falla."""
    now = time.time()
    if _cache["text"] and (now - _cache["ts"]) < _TTL:
        return _cache["text"]
    if not available():
        return None
    try:
        resp = _client.messages.create(
            model=MODEL, max_tokens=400, system=SYSTEM,
            messages=[{"role": "user", "content":
                       "Datos de hoy:\n\n" + _context(dash)}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        if text:
            _cache["ts"] = now
            _cache["text"] = text
            return text
    except Exception:  # noqa: BLE001
        return _cache["text"]  # si había uno bueno, sírvelo
    return None
