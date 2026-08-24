"""Contrato uniforme de procedencia y frescura para cada fuente del módulo.

Una cifra sin fecha ni origen es una afirmación sin respaldo. Cada tarjeta de
la interfaz tiene que poder decir de dónde salió el dato, cuándo se trajo, si
es tiempo real, diferido, un snapshot o una publicación oficial, y cuánto ha
envejecido. Cuando una conexión se cae, el estado degradado se muestra en vez
de servir el último valor como si fuera de ahora.

Aquí sólo vive la lógica pura: no lee archivos ni red. Quien tiene los datos
los pasa; esto los describe.
"""
from __future__ import annotations

from datetime import datetime, timezone


# Cómo se relaciona el dato con el momento presente. No es decoración: separa
# un precio de bolsa en vivo de una foto que sacaste hace tres horas.
MODES = {
    "realtime": "tiempo real",
    "delayed": "diferido",
    "snapshot": "snapshot manual",
    "official_publication": "publicación oficial",
    "derived": "derivado de otras fuentes",
}

# "unknown" existe a propósito: si no se sabe cuándo se trajo un dato, decirlo
# es más honesto que asumir que está fresco.
STATES = ("fresh", "aging", "stale", "unknown", "missing")


def _instante(valor) -> datetime | None:
    """Acepta ISO-8601, epoch en milisegundos o None. Devuelve UTC o None."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        try:
            return datetime.fromtimestamp(float(valor) / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        momento = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def describe(source: str, mode: str, *, retrieved_at=None, observed_at=None,
             stale_after_seconds: int | None = None, now=None,
             available: bool = True, detail: str | None = None) -> dict:
    """Describe una fuente: qué es, de cuándo es y en qué estado está.

    `observed_at` es la fecha del dato en sí —el cierre contable, la rueda
    bursátil— y `retrieved_at` es cuándo NexUX lo trajo. Son distintos a
    propósito: un TXT de la CMF de junio descargado hoy es reciente en
    recuperación y viejo en contenido, y la interfaz debe poder decir ambas.
    """
    if mode not in MODES:
        raise ValueError(f"modo de frescura desconocido: {mode}")
    ahora = _instante(now) or datetime.now(timezone.utc)
    traido = _instante(retrieved_at)
    edad = round((ahora - traido).total_seconds()) if traido else None

    if not available:
        estado = "missing"
    elif edad is None:
        estado = "unknown"
    elif stale_after_seconds is None:
        estado = "fresh"
    elif edad >= stale_after_seconds:
        estado = "stale"
    elif edad >= stale_after_seconds * 0.75:
        estado = "aging"
    else:
        estado = "fresh"

    return {
        "source": source,
        "mode": mode,
        "mode_label": MODES[mode],
        "observed_at": _iso(_instante(observed_at)),
        "retrieved_at": _iso(traido),
        "age_seconds": edad,
        "age_label": humanizar(edad),
        "stale_after_seconds": stale_after_seconds,
        "state": estado,
        "available": bool(available),
        "detail": detail,
    }


def _iso(momento: datetime | None) -> str | None:
    return momento.isoformat() if momento else None


def humanizar(segundos: int | None) -> str | None:
    """Edad en palabras. `None` cuando no se sabe: no se inventa un 'ahora'."""
    if segundos is None:
        return None
    if segundos < 0:
        return "con fecha futura"
    if segundos < 90:
        return "hace instantes"
    minutos = segundos // 60
    if minutos < 60:
        return f"hace {minutos} min"
    horas = minutos // 60
    if horas < 48:
        return f"hace {horas} h"
    return f"hace {horas // 24} días"


def overall(items) -> dict:
    """Estado agregado: manda el peor. Una fuente caída degrada el conjunto."""
    entradas = [item for item in items if isinstance(item, dict)]
    if not entradas:
        return {"state": "missing", "worst": None, "counts": {}, "total": 0}
    orden = {"fresh": 0, "aging": 1, "unknown": 2, "stale": 3, "missing": 4}
    peor = max(entradas, key=lambda item: orden.get(item.get("state"), 3))
    conteo = {estado: sum(1 for item in entradas if item.get("state") == estado)
              for estado in STATES}
    return {
        "state": peor.get("state", "missing"),
        "worst": peor.get("source"),
        "counts": {estado: total for estado, total in conteo.items() if total},
        "total": len(entradas),
    }
