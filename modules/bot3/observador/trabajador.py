"""Observador Bot3.v13 — el proceso TRABAJADOR de transporte (§20.4.1).

Sin estado propio: no escribe almacenes, ni libro, ni sidecars. Lee sobres de
pedido de una tubería, hace la petición HTTP y devuelve sobres de respuesta.
Por eso el padre puede matarlo en cualquier momento sin dejar nada a medias.

Clasifica cada falla en el enum CERRADO de §20.4 y la devuelve como campo del
sobre. `status` y `retry_after` viajan aparte del cuerpo: el cuerpo solo no
permite distinguir un `429` de un `200`, y el backoff decide con los dos.

Sale por EOF cuando el padre cierra su extremo de escritura. Ese es el camino
normal de la clausura cooperativa (§20.4.1, nivel 1); el `SIGKILL` es el
respaldo para cuando está colgado y no mira la tubería.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

from . import contrato as C
from . import transporte as T


def clasificar(exc: BaseException) -> tuple[str, int | None, object]:
    """Excepción → `(error, status, retry_after)` del enum cerrado."""
    if isinstance(exc, urllib.error.HTTPError):
        status = exc.code
        retry = exc.headers.get("Retry-After") if exc.headers else None
        if status == 429:
            return T.ERR_429, status, retry
        if 500 <= status <= 599:
            return T.ERR_5XX, status, retry
        if 400 <= status <= 499:
            # No se reintenta: los parámetros están congelados (§15), así que
            # un `400` significa que el contrato del exchange cambió y un
            # `403`/`418` que estamos bloqueados.
            return T.ERR_4XX, status, None
        return T.ERR_INTERNO, status, None
    if isinstance(exc, ssl.SSLError):
        return T.ERR_TLS, None, None
    if isinstance(exc, socket.timeout):
        return T.ERR_LECTURA, None, None
    if isinstance(exc, socket.gaierror):
        return T.ERR_DNS, None, None
    if isinstance(exc, urllib.error.URLError):
        razon = getattr(exc, "reason", None)
        if isinstance(razon, socket.gaierror):
            return T.ERR_DNS, None, None
        if isinstance(razon, ssl.SSLError):
            return T.ERR_TLS, None, None
        if isinstance(razon, socket.timeout):
            return T.ERR_LECTURA, None, None
        return T.ERR_CONEXION, None, None
    if isinstance(exc, (ConnectionError, http.client.HTTPException)):
        return T.ERR_CONEXION, None, None
    if isinstance(exc, OSError):
        return T.ERR_CONEXION, None, None
    # Cualquier otra cosa es una falla NUESTRA, no de la red: `interno` falla
    # cerrado y no consume intento.
    return T.ERR_INTERNO, None, None


def obtener(url: str, params: dict, connect_timeout: float,
            read_timeout: float, abrir=None) -> tuple[int, object]:
    """GET público, sin credenciales. La falla máxima posible es no obtener
    datos."""
    consulta = urllib.parse.urlencode(params or {})
    completa = f"{url}?{consulta}" if consulta else url
    abrir = abrir or urllib.request.urlopen
    # `urllib` toma un solo timeout para conexión y lectura; se usa el mayor y
    # la cota real la pone el `REQUEST_DEADLINE` del padre (§20.4).
    respuesta = abrir(completa, timeout=max(connect_timeout, read_timeout))
    with respuesta:
        crudo = respuesta.read(C.MAX_SOBRE + 1)
        if len(crudo) > C.MAX_SOBRE:
            raise ValueError(f"respuesta sobre el techo {C.MAX_SOBRE}")
        return respuesta.status, json.loads(crudo.decode("utf-8"))


def atender(pedido: dict, hacer=obtener) -> dict:
    """Un sobre de pedido → un sobre de respuesta, siempre bien formado."""
    base = {"generacion": pedido.get("generacion"),
            "pedido": pedido.get("pedido")}
    try:
        status, cuerpo = hacer(pedido["url"], pedido.get("params") or {},
                               float(pedido.get("connect_timeout", 5.0)),
                               float(pedido.get("read_timeout", 20.0)))
    except BaseException as exc:                        # noqa: BLE001
        clase, status, retry = clasificar(exc)
        return dict(base, ok=False, status=status, retry_after=retry,
                    body=None, error=clase)
    return dict(base, ok=True, status=status, retry_after=None, body=cuerpo,
                error=None)


def servir(leer_fd: int, escribir_fd: int, hacer=obtener) -> int:
    """Bucle del trabajador. Sale `0` por EOF, que es el camino normal."""
    buf = bytearray()
    while True:
        try:
            trozo = os.read(leer_fd, 65536)
        except OSError:
            return 1
        if not trozo:
            return 0                                    # EOF: salida limpia
        buf += trozo
        while b"\n" in buf:
            linea, _, resto = bytes(buf).partition(b"\n")
            buf = bytearray(resto)
            try:
                sobre = T.desenmarcar(linea + b"\n")
            except T.TransporteCerrado:
                # Un pedido corrupto no se contesta: el padre lo detectará por
                # el deadline o por el EOF, y contestar «algo» sería inventar
                # una correlación que no existe.
                return 1
            respuesta = atender(sobre, hacer)
            try:
                os.write(escribir_fd, T.enmarcar(respuesta))
            except OSError:
                return 1
