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
TFS_SERVIBLES = ("15m", "1h", "4h", "1d")


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


def edad_segundos(root: str) -> float | None:
    datos = leer_todo(root)
    if not datos:
        return None
    try:
        return time.time() - float(datos.get("empujado_ts") or 0)
    except (TypeError, ValueError):
        return None


def serie(root: str, symbol: str, tf: str, limit: int = 500) -> list[dict]:
    """Las velas de `symbol`/`tf` si el push está fresco. Lista vacía si no.

    `symbol` en formato Binance (BTCUSDT) y `tf` en el del colector (15m/1h/4h/1d).
    """
    if tf not in TFS_SERVIBLES:
        return []
    datos = leer_todo(root)
    if not datos:
        return []
    edad = edad_segundos(root)
    if edad is None or edad > MAX_EDAD_S:
        return []
    filas = (datos.get("series") or {}).get(f"{symbol}:{tf}")
    if not isinstance(filas, list) or not filas:
        return []
    return filas[-limit:]
