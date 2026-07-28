"""Graduador SOMBRA de setups con Claude (modo observación, NO interviene).

Al crearse un setup, le pedimos a Claude una NOTA DE CALIDAD (0-100) + si lo
tomaría, a ciegas (solo contexto pre-entrada, cero look-ahead). Se guarda en el
setup y NO afecta ninguna decisión.

APAGADO POR DEFECTO desde el 2026-07-27, y esta es la razón. La validación que
motivó el modo sombra YA SE HIZO, con 254 setups graduados y con resultado:

    keep=True  : n=158  avgR +0,258  WR 59%
    keep=False : n= 96  avgR +0,506  WR 72%
    diferencia : -0,249 R   CI95 por bloques diarios [-0,546, +0,039]  CRUZA CERO

Y las notas no son monótonas: 38 -> +1,06R, 68 -> -0,11R, 88 -> +1,83R.

La lectura correcta NO es "keep=False es mejor" —el intervalo cruza cero— sino que
NO HAY EVIDENCIA de discriminación positiva, con la estimación puntual invertida.
No autoriza usarlo, ni normal ni al revés.

Se apaga por costo: era el grueso del gasto Opus (~US$12 en julio) para producir
metadata que ninguna decisión lee. El código queda porque una evidencia nueva
podría justificar retomarlo; lo que no queda es encendido por el solo hecho de que
exista una API key.

Diseño defensivo:
  - El SDK `anthropic` se importa PEREZOSAMENTE dentro de grade(): si no está
    instalado (p. ej. Railway), el módulo igual importa y el graduador queda
    deshabilitado — nunca rompe el módulo de trading.
  - La API key se lee del entorno o de deploy/collector.env (gitignored).
  - Cualquier error → devuelve None (el setup se registra igual, sin grado).
  - SOLO se activa si hay key Y el SDK está disponible (opt-in por presencia).
"""
from __future__ import annotations

import json
import os
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV = os.path.join(ROOT, "deploy", "collector.env")
CONFIG = os.path.join(ROOT, "config", "nexus.json")
MODEL = "claude-opus-4-8"

_client = None          # cache del cliente anthropic
_checked = False        # ya intentamos resolver key+SDK
_enabled = False

SYSTEM = """Eres un trader disciplinado de Smart Money Concepts (SMC). Califica la \
CALIDAD de un setup (0-100) usando SOLO el contexto previo a la entrada (no sabes \
qué pasó después). Califica en sus MÉRITOS — no repruebes por defecto; un buen \
setup merece nota alta aunque no sea perfecto. Factores:
- Premium/descuento (OTE): largo en descuento / corto en premium (disc_ok).
- Régimen: idealmente VIX < 25 y ADX > 25 (regime_ok); ADX bajo = rango, resta.
- R:R y zona bien definida; confirmación de cambio de carácter (CDC) si aplica.
- Coherencia con la estructura; entrar en la zona, no perseguir.
Devuelve nota 0-100 (calidad), keep (¿lo tomarías?), confianza y una razón breve, \
llamando a la herramienta `calificar`."""

TOOL = {
    "name": "calificar",
    "description": "Registra la nota de calidad del setup.",
    "input_schema": {
        "type": "object",
        "properties": {
            "grade": {"type": "integer", "description": "Calidad del setup, 0-100"},
            "keep": {"type": "boolean", "description": "¿Tomarías este setup?"},
            "confidence": {"type": "integer", "description": "0-100"},
            "rationale": {"type": "string", "description": "razón breve (1 frase)"},
        },
        "required": ["grade", "keep", "confidence", "rationale"],
    },
}


def _resolve_key() -> Optional[str]:
    k = os.environ.get("ANTHROPIC_API_KEY")
    if k:
        return k
    if os.path.isfile(ENV):
        try:
            for line in open(ENV, encoding="utf-8"):
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:  # noqa: BLE001
            return None
    return None


def habilitado() -> bool:
    """`trading.claude_grader_enabled` de la config. FALSO si falta.

    Opt-in explícito y versionado, en vez del opt-in por presencia de key que había
    antes. Esa era la falla que hizo el gasto invisible: la key vive en el entorno de
    Railway, así que el graduador se encendía solo ahí sin que nada en el repo lo
    dijera, y el `bot.live=false` no lo apagaba porque nunca lo miró.
    """
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            data = json.load(fh)
        return bool(((data.get("modules") or {}).get("trading") or {})
                    .get("claude_grader_enabled", False))
    except Exception:  # noqa: BLE001 - sin config legible se queda APAGADO
        return False


def available() -> bool:
    """True solo si está HABILITADO en config, hay key y el SDK es importable.

    La bandera se mira PRIMERO y en cada llamada: si se consultara después del caché
    de `_checked`, encenderla o apagarla exigiría reiniciar el proceso.
    """
    global _checked, _enabled, _client
    if not habilitado():
        return False
    if _checked:
        return _enabled
    _checked = True
    key = _resolve_key()
    if not key:
        return False
    try:
        import anthropic  # import perezoso: no romper si falta (Railway)
        _client = anthropic.Anthropic(api_key=key)
        _enabled = True
    except Exception:  # noqa: BLE001
        _enabled = False
    return _enabled


def _blind_context(s: dict) -> str:
    """Solo lo conocido al crearse — cero look-ahead (mismo formato que el test)."""
    reg = "n/d"
    if s.get("regime_ok") is not None:
        reg = "favorable" if s["regime_ok"] else "desfavorable"
        reg += f" (VIX={s.get('regime_vix')}, ADX={s.get('regime_adx')})"
    disc = {True: "sí (alineado)", False: "no (mal lado)", None: "n/d"}.get(s.get("disc_ok"), "n/d")
    return (
        f"Par: {s.get('pair')}\n"
        f"Dirección: {s.get('dir')}\n"
        f"TF del POI: {s.get('poi_tf')} (TF de planeación: {s.get('sel_tf')})\n"
        f"Zona de entrada (POI): {s.get('entry_lo')} – {s.get('entry_hi')} (ref {s.get('entry')})\n"
        f"Stop loss: {s.get('sl')}\n"
        f"Take profit: {s.get('tp')} ({s.get('tp_label','')})\n"
        f"R:R: {s.get('rr')}\n"
        f"Precio al detectarse: {s.get('price_at_create')}\n"
        f"Premium/descuento (OTE): {disc}\n"
        f"Régimen: {reg}\n"
        f"CDC al generarse: {s.get('cdc_status_init', 'n/d')}\n"
        f"Estado inicial: {s.get('state_init','pendiente')}"
    )


def grade(setup: dict) -> Optional[dict]:
    """Gradúa un setup a ciegas. Devuelve {grade, keep, confidence, rationale} o
    None ante cualquier fallo (la app sigue, el setup queda sin grado)."""
    if not available():
        return None
    try:
        resp = _client.messages.create(
            model=MODEL, max_tokens=1024, system=SYSTEM,
            tools=[TOOL], tool_choice={"type": "tool", "name": "calificar"},
            messages=[{"role": "user", "content":
                       "Califica este setup:\n\n" + _blind_context(setup)}],
        )
        for b in resp.content:
            if b.type == "tool_use":
                return b.input
    except Exception:  # noqa: BLE001
        return None
    return None
