"""Observador Bot3.v13 — transporte aislado con deadline ejecutable (§20.4).

Todo el I/O de red vive en un **proceso trabajador** sin estado propio: no
escribe almacenes, ni libro, ni sidecars. El padre lo mata con `SIGKILL` al
vencer `REQUEST_DEADLINE` y lo respawnea.

Matar es el único mecanismo que realmente acota una petición. «Abortar el
socket» no sirve: durante una resolución DNS bloqueada el socket todavía no
existe, y `getaddrinfo` no es cancelable desde el proceso que la llamó. Y
matar es SEGURO precisamente porque el trabajador no tiene estado: la página se
descarta entera, que es lo que §10 ya exige de cualquier página inválida.

Seis decisiones que «devuelve el cuerpo por una tubería» dejaba abiertas
(§20.4.1), y que acá quedan congeladas:

1. **identificadores**: `generacion` por respawn, `pedido` por petición, en
   todo mensaje;
2. **sobres CERRADOS** con el enmarcado de §5, para que uno a medio escribir
   sea DETECTABLE y no un JSON plausible;
3. **`status` y `retry_after` como campos propios**: el cuerpo solo no permite
   distinguir un `429` de un `200`, y el backoff decide con los dos;
4. **el deadline arranca ANTES del primer byte** del pedido. Escribir en una
   tubería BLOQUEA cuando el buffer del kernel se llena, así que arrancarlo
   después dejaba al padre detenido con el reloj parado;
5. **I/O incremental y NO BLOQUEANTE en los dos sentidos**. `poll` marca
   escribible cuando cabe AL MENOS UN BYTE, no el bloque entero, así que un
   `write` bloqueante mayor al espacio libre detiene al padre dentro de la
   syscall. Y sin drenar mientras el trabajador escribe hay abrazo mortal
   real: una respuesta de Binance supera el buffer de la tubería, los dos
   quedan detenidos, y el deadline termina matando una respuesta VÁLIDA;
6. **canal NUEVO por generación**, cerrando los extremos viejos ANTES de crear
   los nuevos: los bytes que el trabajador muerto alcanzó a escribir viven en
   un buffer de kernel que se destruye con el canal.

Y una distinción que no es de matiz: el `SIGKILL` DELIBERADO del padre es un
fallo de transporte y consume intento; una muerte espontánea del trabajador es
**fallo cerrado**. Un proceso que se cae solo no es una falla de red sino del
observador, y reintentarlo cinco veces lo taparía.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import random
import select
import signal
import time

from . import contrato as C
from . import proceso as P
from .estado import canon

# §20.4, enum CERRADO de resultados. Solo estos consumen intento.
ERR_DNS = "dns"
ERR_CONEXION = "conexion"
ERR_TLS = "tls"
ERR_LECTURA = "lectura"
ERR_429 = "http_429"
ERR_5XX = "http_5xx"
ERR_4XX = "http_4xx"
ERR_INTERNO = "interno"
ERRORES_REINTENTABLES = (ERR_DNS, ERR_CONEXION, ERR_TLS, ERR_LECTURA,
                         ERR_429, ERR_5XX)
# `http_4xx` falla cerrado porque los parámetros están congelados (§15): un
# `400` significa que el contrato del exchange cambió y un `403`/`418` que
# estamos bloqueados. Ninguno se arregla reintentando, y reintentar un baneo lo
# empeora.
ERRORES_CERRADOS = (ERR_4XX, ERR_INTERNO)
ERRORES = ERRORES_REINTENTABLES + ERRORES_CERRADOS

CAMPOS_PEDIDO = ("generacion", "pedido", "url", "params", "connect_timeout",
                 "read_timeout")
CAMPOS_RESPUESTA = ("generacion", "pedido", "ok", "status", "retry_after",
                    "body", "error")


class TransporteCerrado(RuntimeError):
    """El observador está roto, no la red. `codigo: 1`, y NO consume intento."""


class FalloDeRed(RuntimeError):
    """Reintentable: consume intento y entra al backoff (§20.4)."""

    def __init__(self, clase: str, detalle: str = "",
                 retry_after: float | None = None):
        super().__init__(f"{clase}: {detalle}" if detalle else clase)
        self.clase = clase
        self.retry_after = retry_after


# --------------------------------------------------------------------------
# sobres: enmarcado de §5 sobre la tubería
# --------------------------------------------------------------------------
def enmarcar(cuerpo: dict) -> bytes:
    payload = canon(cuerpo).encode("utf-8")
    cabeza = f"{len(payload)}\t{hashlib.sha256(payload).hexdigest()}\t"
    return cabeza.encode("ascii") + payload + b"\n"


def desenmarcar(crudo: bytes) -> dict:
    """Un sobre a medio escribir es DETECTABLE, no un JSON plausible.

    El criterio de truncación es la ausencia del `\\n` final, igual que en §5.
    Una trama cerrada cuyo encabezado, longitud o hash fallen es CORRUPCIÓN:
    el encabezado no puede ser juez de su propia integridad."""
    if not crudo.endswith(b"\n"):
        raise TransporteCerrado(
            "sobre TRUNCADO: el trabajador murió a mitad de la escritura")
    cuerpo = crudo[:-1]
    try:
        largo_txt, sha_txt, payload = cuerpo.split(b"\t", 2)
        largo = int(largo_txt)
    except ValueError as exc:
        raise TransporteCerrado(f"encabezado de sobre ilegible: {exc}")
    if largo > C.MAX_SOBRE:
        raise TransporteCerrado(
            f"sobre de {largo} bytes sobre el techo {C.MAX_SOBRE}: no se "
            f"reserva memoria por un campo de longitud que ya no es confiable")
    if len(payload) != largo:
        raise TransporteCerrado(
            f"longitud declarada {largo} != {len(payload)} reales")
    if hashlib.sha256(payload).hexdigest() != sha_txt.decode("ascii", "replace"):
        raise TransporteCerrado("checksum del sobre no cuadra: canal corrupto")
    try:
        return json.loads(payload.decode("utf-8"))
    except ValueError as exc:
        raise TransporteCerrado(f"payload del sobre no es JSON: {exc}")


def validar_respuesta(cuerpo, generacion: int, pedido: int) -> dict:
    if not isinstance(cuerpo, dict):
        raise TransporteCerrado(f"respuesta no es un objeto: {cuerpo!r}")
    sobran = sorted(set(cuerpo) - set(CAMPOS_RESPUESTA))
    faltan = sorted(set(CAMPOS_RESPUESTA) - set(cuerpo))
    if sobran or faltan:
        raise TransporteCerrado(
            f"respuesta fuera del schema: sobran {sobran}, faltan {faltan}")
    # Con UNA petición en vuelo y un canal nuevo por generación, un ID que no
    # coincide es IMPOSIBLE en operación válida: solo puede venir de un
    # protocolo corrupto. Descartarlo lo convertía en una espera que terminaba
    # venciendo el deadline —que sí es reintentable—, así que una corrupción
    # del observador se habría reintentado cinco veces y seguido como si nada.
    if (cuerpo["generacion"], cuerpo["pedido"]) != (generacion, pedido):
        raise TransporteCerrado(
            f"respuesta ajena: esperaba ({generacion}, {pedido}) y llegó "
            f"({cuerpo['generacion']!r}, {cuerpo['pedido']!r})")
    if cuerpo["ok"] is True:
        if cuerpo["error"] is not None:
            raise TransporteCerrado("respuesta `ok` con `error` presente")
        if type(cuerpo["status"]) is not int:
            raise TransporteCerrado(f"`status` no entero: {cuerpo['status']!r}")
    else:
        if cuerpo["error"] not in ERRORES:
            # Un valor desconocido no describe nada, así que no puede decidir
            # si se reintenta.
            raise TransporteCerrado(
                f"`error` fuera del enum cerrado: {cuerpo['error']!r}")
    return cuerpo


# --------------------------------------------------------------------------
# I/O no bloqueante contra el deadline
# --------------------------------------------------------------------------
def _no_bloqueante(fd: int) -> None:
    import fcntl as _f
    _f.fcntl(fd, _f.F_SETFL, _f.fcntl(fd, _f.F_GETFL) | os.O_NONBLOCK)


def _resto(deadline: float, reloj=time.monotonic) -> float:
    return deadline - reloj()


class DeadlineVencido(FalloDeRed):
    """La cota real. Consume intento, como cualquier fallo de transporte."""

    def __init__(self, detalle: str = ""):
        super().__init__("deadline", detalle)


def escribir_todo(fd: int, datos: bytes, deadline: float) -> None:
    """Bucle PARCIAL: avanza por lo que la syscall efectivamente movió.

    `poll` garantiza que cabe AL MENOS UN BYTE, no el bloque: asumir que
    escribió todo detenía al padre dentro de la syscall y el deadline dejaba
    de gobernar."""
    puesto = 0
    while puesto < len(datos):
        resto = _resto(deadline)
        if resto <= 0:
            raise DeadlineVencido(f"escribiendo el pedido ({puesto} bytes)")
        listos = select.select([], [fd], [], resto)[1]
        if not listos:
            continue                        # vuelve a medir el remanente
        try:
            puesto += os.write(fd, datos[puesto:])
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                continue
            if exc.errno == errno.EINTR:
                # Una señal NO es un fallo de transporte: se reintenta la
                # syscall sin consumir nada ni alterar el deadline.
                continue
            if exc.errno == errno.EPIPE:
                raise TransporteCerrado(
                    "el trabajador cerró su entrada a mitad del pedido: "
                    "murió por su cuenta")
            raise


def leer_sobre(fd: int, deadline: float, reloj=time.monotonic) -> bytes:
    """Drena INCREMENTALMENTE mientras el trabajador escribe.

    Sin esto hay abrazo mortal real: una respuesta de Binance supera el buffer
    de la tubería, el trabajador se bloquea escribiendo, el padre espera sin
    drenar, y el deadline termina matando una respuesta VÁLIDA."""
    buf = bytearray()
    while True:
        resto = _resto(deadline, reloj)
        if resto <= 0:
            raise DeadlineVencido(f"leyendo la respuesta ({len(buf)} bytes)")
        listos = select.select([fd], [], [], resto)[0]
        if not listos:
            continue
        try:
            trozo = os.read(fd, 65536)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                continue
            raise
        if not trozo:                       # EOF
            raise TransporteCerrado(
                f"EOF con la trama a medias ({len(buf)} bytes): el trabajador "
                f"murió sin que el padre lo matara")
        buf += trozo
        if len(buf) > C.MAX_SOBRE + 1024:
            raise TransporteCerrado(
                f"la respuesta supera {C.MAX_SOBRE} bytes")
        if buf.endswith(b"\n"):
            # ACEPTACIÓN POR EL BORDE: el reloj se muestrea DESPUÉS de la trama
            # completa. Mirarlo antes del último `read` haría que una trama
            # completa pareciera tardía, y al entrar al `poll`, lo contrario.
            if reloj() > deadline:
                raise DeadlineVencido("la trama llegó completa fuera de plazo")
            return bytes(buf)


# --------------------------------------------------------------------------
# el trabajador
# --------------------------------------------------------------------------
class Trabajador:
    """Una generación: un subproceso y su canal.

    El canal es NUEVO en cada generación, y los extremos viejos se cierran
    ANTES de crear los nuevos: los bytes que el trabajador muerto alcanzó a
    escribir viven en un buffer de kernel que se destruye con el canal, así
    que reusar la tubería habría dejado media respuesta de la generación
    anterior esperando al principio del flujo."""

    def __init__(self, generacion: int, pid: int, escribir_fd: int,
                 leer_fd: int):
        self.generacion = generacion
        self.pid = pid
        self.escribir_fd = escribir_fd
        self.leer_fd = leer_fd
        self.pedido = 0

    def cerrar_canal(self) -> None:
        for fd in (self.escribir_fd, self.leer_fd):
            try:
                os.close(fd)
            except OSError:
                pass


def _cerrar_ajenos(conservar) -> None:
    """El trabajador cierra TODO descriptor heredado que no le corresponde.

    Sin esto se lleva copias del `supervisor.lock`, de los almacenes y del
    libro: sostendría locks que no son suyos y mantendría vivos archivos que
    el padre cree cerrados."""
    from . import supervision as SUP
    SUP.cerrar_locks_heredados()
    conservar = set(conservar) | {0, 1, 2}
    try:
        maximo = os.sysconf("SC_OPEN_MAX")
    except (ValueError, OSError):
        maximo = 1024
    maximo = min(int(maximo), 4096)
    for fd in range(3, maximo):
        if fd in conservar:
            continue
        try:
            os.close(fd)
        except OSError:
            pass


def lanzar_trabajador(generacion: int, servir) -> Trabajador:
    """`servir(leer_fd, escribir_fd)` corre en el HIJO."""
    pedido_r, pedido_w = os.pipe()
    resp_r, resp_w = os.pipe()
    pid = os.fork()
    if pid == 0:                                        # ---- TRABAJADOR ----
        codigo = 1
        try:
            os.close(pedido_w)
            os.close(resp_r)
            _cerrar_ajenos((pedido_r, resp_w))
            codigo = servir(pedido_r, resp_w) or 0
        except BaseException:
            codigo = 1
        finally:
            os._exit(codigo if isinstance(codigo, int) else 1)
    os.close(pedido_r)
    os.close(resp_w)
    _no_bloqueante(pedido_w)
    _no_bloqueante(resp_r)
    return Trabajador(generacion, pid, pedido_w, resp_r)


class Canal:
    """El lado PADRE: una petición en vuelo a la vez, deadline por petición."""

    def __init__(self, servir, deadline_ms: int | None = None,
                 al_respawnear=None):
        self.servir = servir
        self.deadline_ms = (C.REQUEST_DEADLINE_MS if deadline_ms is None
                            else deadline_ms)
        self.al_respawnear = al_respawnear
        self.generacion = 0
        self.trabajador: Trabajador | None = None

    # -- ciclo de generación -------------------------------------------------
    def asegurar(self) -> Trabajador:
        if self.trabajador is None:
            self.generacion += 1
            self.trabajador = lanzar_trabajador(self.generacion, self.servir)
            if self.al_respawnear is not None:
                # DURABLE antes del primer pedido a la generación nueva: si no,
                # el sidecar apuntaría a la generación muerta y el barrido
                # diferido dejaría vivo justamente al trabajador colgado.
                self.al_respawnear(self.trabajador)
        return self.trabajador

    def respawnear(self) -> None:
        """`kill → waitpid → cerrar extremos viejos → crear canal nuevo`."""
        viejo = self.trabajador
        self.trabajador = None
        if viejo is None:
            return
        try:
            os.kill(viejo.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        P.recolectar(viejo.pid)
        viejo.cerrar_canal()

    def cerrar(self, plazo_s: float | None = None) -> str:
        """Clausura cooperativa del nivel 1: EOF primero."""
        from . import supervision as SUP
        viejo = self.trabajador
        self.trabajador = None
        if viejo is None:
            return "sin trabajador"
        def cerrar_entrada():
            try:
                os.close(viejo.escribir_fd)
            except OSError:
                pass
        salida = SUP.clausurar_hijo(viejo.pid, cerrar_entrada, plazo_s)
        try:
            os.close(viejo.leer_fd)
        except OSError:
            pass
        return salida

    # -- una petición --------------------------------------------------------
    def pedir(self, url: str, params: dict) -> dict:
        """Una petición acotada por `REQUEST_DEADLINE`.

        El deadline arranca ANTES del primer byte, no después de escribir el
        pedido: escribir en una tubería bloquea cuando el buffer del kernel se
        llena, y arrancarlo después dejaba al padre detenido con el reloj
        parado."""
        trabajador = self.asegurar()
        trabajador.pedido += 1
        sobre = {"generacion": trabajador.generacion,
                 "pedido": trabajador.pedido, "url": url, "params": params,
                 "connect_timeout": C.CONNECT_TIMEOUT_MS / 1000.0,
                 "read_timeout": C.READ_TIMEOUT_MS / 1000.0}
        deadline = time.monotonic() + self.deadline_ms / 1000.0
        try:
            escribir_todo(trabajador.escribir_fd, enmarcar(sobre), deadline)
            crudo = leer_sobre(trabajador.leer_fd, deadline)
        except DeadlineVencido:
            # Matar cubre DNS, TLS y cuerpo por igual, porque no depende de que
            # la operación colgada sea cancelable.
            self.respawnear()
            raise
        except TransporteCerrado:
            # Muerte espontánea o canal corrupto: el observador está roto. Se
            # respawnea igual para no dejar el proceso vivo, pero NO se
            # reintenta.
            self.respawnear()
            raise
        cuerpo = validar_respuesta(desenmarcar(crudo), trabajador.generacion,
                                   trabajador.pedido)
        if cuerpo["ok"]:
            return cuerpo
        clase = cuerpo["error"]
        if clase in ERRORES_CERRADOS:
            raise TransporteCerrado(
                f"{clase}: no se reintenta — los parámetros están congelados "
                f"(§15), así que esto no se arregla pidiendo de nuevo")
        raise FalloDeRed(clase, f"status={cuerpo['status']}",
                         cuerpo.get("retry_after"))


# --------------------------------------------------------------------------
# backoff
# --------------------------------------------------------------------------
def espera_de(intento: int, retry_after: float | None = None,
              azar=random.uniform) -> float:
    """`min(BACKOFF_MAX, BASE * 2**(n-1))` con full jitter.

    El jitter completo es la ÚNICA fuente de aleatoriedad del observador:
    vive en la capa de transporte, no entra en ningún hash, ningún evento ni
    ninguna decisión, así que no afecta la reproducibilidad del libro. Y es
    deliberado — los 14 streams de un ciclo reintentando en fase sincronizada
    son una ráfaga contra el mismo endpoint."""
    techo = min(C.BACKOFF_MAX_MS, C.BACKOFF_BASE_MS * 2 ** (intento - 1))
    if retry_after is not None:
        # Acotado: sin la cota, un `Retry-After` hostil o mal configurado
        # dormiría el ciclo por horas.
        return max(0.0, min(float(retry_after), C.BACKOFF_MAX_MS / 1000.0))
    return azar(0, techo / 1000.0)


def interpretar_retry_after(valor, ahora=None) -> float | None:
    """Segundos enteros o HTTP-date. Un valor malformado se IGNORA y se usa el
    jitter: una cabecera rota no debe poder detener ni acelerar el ciclo."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return max(0.0, float(valor))
    if not isinstance(valor, str) or not valor.strip():
        return None
    texto = valor.strip()
    try:
        return max(0.0, float(int(texto)))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        fecha = parsedate_to_datetime(texto)
    except (TypeError, ValueError, IndexError):
        return None
    if fecha is None:
        return None
    referencia = time.time() if ahora is None else ahora
    import datetime
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=datetime.timezone.utc)
    return max(0.0, fecha.timestamp() - referencia)


def con_reintentos(hacer, dormir=None, azar=random.uniform,
                   intentos: int | None = None):
    """`BACKOFF_INTENTOS` es el número de INTENTOS totales, no de reintentos.

    Solo se DUERME después de los fallos 1 a 4; el quinto levanta de inmediato.
    Dormir tras el último sería retrasar el fracaso sin cambiarlo, y la espera
    se la comería el `ExitTimeOut` de §20.6."""
    total = C.BACKOFF_INTENTOS if intentos is None else intentos
    for intento in range(1, total + 1):
        try:
            return hacer()
        except FalloDeRed as exc:
            if intento >= total:
                raise
            espera = espera_de(intento, interpretar_retry_after(
                exc.retry_after), azar)
            if dormir is not None:
                dormir(espera)
    raise AssertionError("inalcanzable")


class SuenoInterrumpible:
    """El sueño del backoff se espera sobre un EVENTO que el manejador de
    señal levanta, no con un `sleep` ciego: sin eso, un `SIGTERM` durante la
    última espera costaba `BACKOFF_MAX` completo."""

    def __init__(self):
        import threading
        self.parar = threading.Event()

    def __call__(self, segundos: float) -> None:
        if self.parar.wait(max(0.0, segundos)):
            raise TransporteCerrado("apagado solicitado durante el backoff")
