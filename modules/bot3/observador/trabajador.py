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

import errno
import fcntl
import http.client
import json
import os
import select
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

from . import contrato as C
from . import transporte as T


# Registro CERRADO de `errno` que sí son de red. Todo lo demás —`EMFILE`,
# `ENFILE`, `ENOMEM`, `EBADF`— es una falla del trabajador, no del exchange.
ERRNOS_DE_RED = frozenset({
    errno.ECONNREFUSED, errno.ECONNRESET, errno.ECONNABORTED,
    errno.EHOSTUNREACH, errno.EHOSTDOWN, errno.ENETUNREACH, errno.ENETDOWN,
    errno.ENETRESET, errno.ETIMEDOUT, errno.EPIPE, errno.ENOTCONN,
    errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT,
})


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
        # Un `OSError` NO es de red por defecto: `EMFILE` —descriptores
        # agotados— es una falla LOCAL del trabajador, y clasificarla como
        # `conexion` la hacía reintentable, así que el observador reintentaba
        # cinco veces un problema suyo y seguía como si nada.
        if exc.errno in ERRNOS_DE_RED:
            return T.ERR_CONEXION, None, None
        return T.ERR_INTERNO, None, None
    # Cualquier otra cosa es una falla NUESTRA, no de la red: `interno` falla
    # cerrado y no consume intento.
    return T.ERR_INTERNO, None, None


def obtener(url: str, params: dict, connect_timeout: float,
            read_timeout: float, abrir=None) -> tuple[int, object]:
    """GET público, sin credenciales. La falla máxima posible es no obtener
    datos."""
    if abrir is not None:
        return abrir(url, params, connect_timeout, read_timeout)
    partes = urllib.parse.urlsplit(url)
    consulta = urllib.parse.urlencode(params or {})
    camino = partes.path + (f"?{consulta}" if consulta else "")
    # `urllib.request.urlopen` toma UN solo timeout para conexión y lectura, y
    # §15 congela dos valores distintos. Se abre la conexión con
    # `CONNECT_TIMEOUT` y se cambia el socket a `READ_TIMEOUT` recién después
    # del `connect`, que es lo único que aplica los dos de verdad.
    clase = (http.client.HTTPSConnection if partes.scheme == "https"
             else http.client.HTTPConnection)
    conexion = clase(partes.netloc, timeout=connect_timeout)
    try:
        conexion.connect()
        if conexion.sock is not None:
            conexion.sock.settimeout(read_timeout)
        conexion.request("GET", camino or "/")
        respuesta = conexion.getresponse()
        crudo = respuesta.read(C.MAX_SOBRE + 1)
        if len(crudo) > C.MAX_SOBRE:
            raise ValueError(f"respuesta sobre el techo {C.MAX_SOBRE}")
        if respuesta.status >= 400:
            raise urllib.error.HTTPError(
                url, respuesta.status, respuesta.reason, respuesta.headers,
                None)
        return respuesta.status, json.loads(crudo.decode("utf-8"))
    finally:
        conexion.close()


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


def _escribir_todo(fd: int, datos: bytes) -> None:
    """Bucle PARCIAL, igual que en el padre.

    Un solo `os.write` ignorando lo que efectivamente escribió dejaba la
    respuesta a medias: el padre se quedaba esperando la trama, vencía el
    deadline, y una falla del TRANSPORTE se convertía en un reintento."""
    puesto = 0
    while puesto < len(datos):
        listos = select.select([], [fd], [])[1]
        if not listos:
            continue
        try:
            puesto += os.write(fd, datos[puesto:])
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                continue
            raise


def servir(leer_fd: int, escribir_fd: int, hacer=obtener) -> int:
    """Bucle del trabajador. Sale `0` por EOF, que es el camino normal."""
    # Los DOS descriptores en no bloqueante, igual que en el padre: `select`
    # marca escribible cuando cabe al menos un byte, no el bloque entero.
    for fd in (leer_fd, escribir_fd):
        fcntl.fcntl(fd, fcntl.F_SETFL,
                    fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)
    buf = bytearray()
    while True:
        try:
            listos = select.select([leer_fd], [], [])[0]
            if not listos:
                continue
            trozo = os.read(leer_fd, 65536)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                continue
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
                _escribir_todo(escribir_fd, T.enmarcar(respuesta))
            except OSError:
                return 1
