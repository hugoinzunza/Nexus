"""Klines de Binance que empuja el colector del VPS. Lectura y escritura compartidas.

POR QUÉ ESTÁ EN `core/`: lo escribe el módulo `inteligencia` (que recibe la ingesta) y
lo leen dos módulos (`inteligencia` y `trading`). Con el lector duplicado, el día que
cambie el formato o la ventana de frescura uno de los dos se queda atrás en silencio,
que es justo el tipo de desincronización que ya nos costó caro hoy.

CONTEXTO: Railway está geo-bloqueado por Binance (HTTP 451, verificado el 2026-07-26).
El VPS sí puede, así que recolecta y empuja. Este archivo es el punto de encuentro.

NO es un feed en vivo: llega cada 10 minutos. Cualquier consumidor que necesite el
tick del momento —el gráfico de 1m, por ejemplo— no puede usar esto.
"""
from __future__ import annotations

import json
import os
import time

from core.paths import persist_dir

# Cuánto vale un push antes de considerarse viejo. 25 min deja pasar un ciclo perdido
# del timer de 10 min sin gritar, y no tanto como para que un colector muerto pase
# desapercibido media hora larga.
#
# La regla que importa: klines empujadas hace horas son PEOR que no tener nada,
# porque parecen en vivo. Vencido el plazo se devuelve vacío y el consumidor decide.
MAX_EDAD_S = 25 * 60

# Temporalidades donde un dato de hasta 10 min de atraso es aceptable. En 1m y 5m NO
# lo es: una vela de 1m alimentada por un push de 10 minutos deja el gráfico atrasado
# más que la vela misma, y eso es peor que mostrar otro exchange declarado.
TFS_SERVIBLES = ("15m", "1h", "4h", "1d", "1w")
TF_MS = {
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


def _ruta(root: str) -> str:
    return os.path.join(persist_dir(root), "inteligencia_klines.json")


def leer_todo(root: str) -> dict:
    try:
        with open(_ruta(root), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def escribir(root: str, datos: dict) -> None:
    ruta = _ruta(root)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, separators=(",", ":"))
    os.replace(tmp, ruta)


def edad_segundos(root: str, datos: dict | None = None) -> float | None:
    datos = datos if datos is not None else leer_todo(root)
    if not datos:
        return None
    try:
        return time.time() - float(datos.get("empujado_ts") or 0)
    except (TypeError, ValueError):
        return None


def validar_serie(filas: list, tf: str, now: float | None = None,
                  exigir_frescura: bool = True) -> tuple[list[dict], str | None, float | None]:
    """Normaliza una serie y rechaza huecos, duplicados, futuro u OHLCV imposible."""
    if tf not in TF_MS or not isinstance(filas, list) or not filas:
        return [], "serie ausente", None
    ahora = time.time() if now is None else now
    paso = TF_MS[tf]
    prev_t = None
    limpias = []
    for fila in filas:
        try:
            t = int(fila["t"])
            o, h, l, c = (float(fila[k]) for k in ("o", "h", "l", "c"))
            v = float(fila.get("v") or 0)
        except (KeyError, TypeError, ValueError):
            return [], "vela inválida", None
        if h < max(o, c) or l > min(o, c) or h < l or v < 0:
            return [], "OHLCV incoherente", None
        if prev_t is not None and t - prev_t != paso:
            return [], "timestamps con huecos o duplicados", None
        if t / 1000 > ahora + 5:
            return [], "vela futura", None
        limpias.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v})
        prev_t = t
    lag = ahora - limpias[-1]["t"] / 1000
    if exigir_frescura and lag > paso / 1000 + MAX_EDAD_S:
        return [], "serie vencida", lag
    return limpias, None, lag


def serie_con_meta(root: str, symbol: str, tf: str, limit: int = 500,
                   now: float | None = None) -> tuple[list[dict], dict]:
    """Serie validada y metadatos de frescura propios de esa serie.

    `symbol` en formato Binance (BTCUSDT) y `tf` en el del colector
    (15m/1h/4h/1d/1w).
    """
    ahora = time.time() if now is None else now
    meta = {"fuente": "binance_vps", "tf": tf, "symbol": symbol, "valida": False}
    if tf not in TFS_SERVIBLES:
        return [], {**meta, "error": "temporalidad no servible"}
    datos = leer_todo(root)
    if not datos:
        return [], {**meta, "error": "sin push"}
    edad = edad_segundos(root, datos)
    if edad is None or edad > MAX_EDAD_S:
        return [], {**meta, "error": "push vencido", "push_age_seconds": edad}
    filas = (datos.get("series") or {}).get(f"{symbol}:{tf}")
    if not isinstance(filas, list) or not filas:
        return [], {**meta, "error": "serie ausente", "push_age_seconds": edad}

    limpias, error, lag = validar_serie(filas, tf, ahora)
    if error:
        return [], {**meta, "error": error, "push_age_seconds": edad,
                    "series_lag_seconds": lag}
    ultima_t = limpias[-1]["t"]
    return limpias[-limit:], {
        **meta,
        "valida": True,
        "push_age_seconds": round(edad, 3),
        "series_lag_seconds": round(lag, 3),
        "captured_at": datos.get("empujado_at"),
        "last_bar_open_t": ultima_t,
    }


def serie(root: str, symbol: str, tf: str, limit: int = 500) -> list[dict]:
    """Compatibilidad para consumidores que solo necesitan las velas."""
    filas, _ = serie_con_meta(root, symbol, tf, limit)
    return filas
