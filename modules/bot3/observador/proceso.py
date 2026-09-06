"""Observador Bot3.v13 — identidad de NACIMIENTO de un proceso (§20.4.3).

Un PID no identifica un proceso: el kernel los recicla. Barrer un grupo por
PID es enviarle `SIGKILL` a lo que sea que esté ocupando ese número ahora, y
eso es un daño que el observador no tiene derecho a causar.

La identidad es el par `(inicio, ejecutable)` junto al PID y al PGID:

- **`inicio`** sale de `sysctl(KERN_PROC_PID)` → `kinfo_proc.kp_proc.p_starttime`,
  un `struct timeval` que se canoniza a MICROsegundos. La resolución importa:
  `ps -o lstart=` da segundos, y dos procesos nacidos en el mismo segundo son
  indistinguibles ahí — un PID reciclado dentro de ese segundo pasaría la
  comprobación;
- **`ejecutable`** sale de `proc_pidpath` y se pasa por `realpath`. Sin
  normalizar, el mismo binario alcanzado por un symlink da rutas distintas y
  la comparación byte a byte produciría un falso negativo que **aborta el
  barrido** — dejando vivo justamente al proceso que había que matar.

Queda una ventana inevitable entre verificar y señalar: el kernel podría
reciclar el PID en ese intervalo. Se declara en vez de disimularse. Con
`inicio` en microsegundos, que esa carrera se materialice exige una
coincidencia que ningún mecanismo de espacio de usuario puede descartar del
todo; lo que sí se garantiza es que no se señala por parecido ni con datos
viejos.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import struct

CTL_KERN = 1
KERN_PROC = 14
KERN_PROC_PID = 1

# `struct timeval` en macOS de 64 bits: `int64 tv_sec` + `int32 tv_usec`. Está
# en el offset 0 de `kinfo_proc` porque `extern_proc` empieza por una unión que
# comparte espacio con `__p_starttime`.
_TIMEVAL = "<qi"

_MAX_RUTA = 4096

_lib = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib",
                   use_errno=True)


class ProcesoInvalido(ValueError):
    """La identidad registrada no describe al proceso vivo. Fallo cerrado, y
    NO se envía ninguna señal."""


class ConsultaFallida(RuntimeError):
    """No se pudo CONSULTAR la identidad. Distinto de «el proceso no existe»:
    ausencia confirmada significa que no hay nada que barrer, mientras que una
    identidad no verificable tiene que ABORTAR el barrido — tratarla como
    ausencia dejaría vivo al proceso que había que matar, y tratarla como
    presencia mataría a ciegas."""


# Un `errno` que significa AUSENCIA confirmada. Cualquier otro es una consulta
# que no se pudo hacer, y eso no es lo mismo.
_AUSENTE = (errno.ESRCH, errno.ENOENT)


def _sysctl_kinfo(pid: int) -> bytes | None:
    """Bytes del `kinfo_proc`, o `None` si el proceso NO EXISTE.

    Levanta `ConsultaFallida` si el kernel devolvió un error que no significa
    ausencia: devolver `None` ahí hacía que un `EIO` se leyera como «este
    proceso ya murió», y el barrido daba por limpio un árbol que seguía vivo.
    """
    mib = (ctypes.c_int * 4)(CTL_KERN, KERN_PROC, KERN_PROC_PID, int(pid))
    tam = ctypes.c_size_t(0)
    for intento in (1, 2):
        ctypes.set_errno(0)
        if intento == 1:
            r = _lib.sysctl(mib, 4, None, ctypes.byref(tam), None, 0)
            buf = None
        else:
            buf = ctypes.create_string_buffer(tam.value)
            r = _lib.sysctl(mib, 4, buf, ctypes.byref(tam), None, 0)
        if r != 0:
            err = ctypes.get_errno()
            if err in _AUSENTE:
                return None
            raise ConsultaFallida(
                f"sysctl(KERN_PROC_PID, {pid}) falló con errno {err} "
                f"({os.strerror(err)}): la identidad no es verificable")
        if intento == 1 and tam.value == 0:
            return None
    # Un PID que ya no existe devuelve 0 bytes ÚTILES aunque el dimensionado
    # haya reservado espacio: `sysctl` no falla, simplemente no escribe nada.
    if tam.value < struct.calcsize(_TIMEVAL):
        return None
    return buf.raw[:tam.value]


def inicio_de(pid: int) -> int | None:
    """Microsegundos desde epoch del NACIMIENTO del proceso, o `None` si no
    existe."""
    crudo = _sysctl_kinfo(pid)
    if crudo is None:
        return None
    seg, usec = struct.unpack_from(_TIMEVAL, crudo, 0)
    if seg <= 0:
        return None
    return seg * 1_000_000 + usec


def ejecutable_de(pid: int) -> str | None:
    """Ruta absoluta y CANÓNICA del ejecutable, o `None` si no existe."""
    buf = ctypes.create_string_buffer(_MAX_RUTA)
    ctypes.set_errno(0)
    n = _lib.proc_pidpath(int(pid), buf, _MAX_RUTA)
    if n <= 0:
        err = ctypes.get_errno()
        if err in _AUSENTE or err == 0:
            return None
        raise ConsultaFallida(
            f"proc_pidpath({pid}) falló con errno {err} "
            f"({os.strerror(err)}): la identidad no es verificable")
    return os.path.realpath(buf.value.decode("utf-8", "replace"))


def pgid_de(pid: int) -> int | None:
    try:
        return os.getpgid(int(pid))
    except ProcessLookupError:
        return None
    except PermissionError as exc:
        # Existe pero es de otro usuario. NO es ausencia: es un proceso vivo
        # que no podemos acreditar, y darlo por muerto dejaría el barrido
        # incompleto.
        raise ConsultaFallida(
            f"getpgid({pid}): existe pero es de otro usuario") from exc


def identidad_de(pid: int) -> dict | None:
    """Los CUATRO campos, o `None` si el proceso no existe.

    Se leen juntos y de una sola vez: leer el `inicio` y el `ejecutable` en
    momentos distintos permitiría que el PID se reciclara entre las dos
    lecturas y que la identidad resultante no describiera a ningún proceso
    real."""
    inicio = inicio_de(pid)
    if inicio is None:
        return None
    ejecutable = ejecutable_de(pid)
    pgid = pgid_de(pid)
    if ejecutable is None or pgid is None:
        # El proceso existía al leer el `inicio` y desapareció en el camino:
        # ausencia confirmada, no consulta fallida.
        return None
    return {"pid": int(pid), "pgid": int(pgid), "inicio": inicio,
            "ejecutable": ejecutable}


CAMPOS_IDENTIDAD = ("pid", "pgid", "inicio", "ejecutable")


def coincide(registrada: dict, actual: dict | None) -> bool:
    """Los CUATRO campos, no solo el PID."""
    if actual is None:
        return False
    return all(registrada.get(c) == actual.get(c) for c in CAMPOS_IDENTIDAD)


def exigir_coincidencia(registrada: dict, que: str = "proceso") -> bool:
    """`True` si vive y es el registrado; `False` si ya no existe —no hay nada
    que barrer—; levanta si vive pero es OTRO.

    Nunca se barre por parecido: un PID reciclado por un proceso ajeno del
    sistema recibiría `SIGKILL` sin haber hecho nada."""
    actual = identidad_de(registrada.get("pid"))
    if actual is None:
        return False
    if not coincide(registrada, actual):
        difs = sorted(c for c in CAMPOS_IDENTIDAD
                      if registrada.get(c) != actual.get(c))
        raise ProcesoInvalido(
            f"{que} pid={registrada.get('pid')} vive pero NO es el "
            f"registrado: difieren {difs}. El PID fue reciclado y señalarlo "
            f"mataría a un proceso ajeno")
    return True


def matar_grupo(pgid: int, senal: int) -> None:
    try:
        os.killpg(int(pgid), senal)
    except ProcessLookupError:
        pass                                    # ya no queda nadie
    except PermissionError as exc:
        raise ProcesoInvalido(
            f"sin permiso para señalar al grupo {pgid}: no es nuestro") \
            from exc


def vivo(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                             # existe, aunque sea ajeno
    except OSError as exc:
        raise ConsultaFallida(
            f"kill({pid}, 0) falló con errno {exc.errno}") from exc


def grupo_vivo(pgid: int) -> bool:
    try:
        os.killpg(int(pgid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def recolectar(pid: int, bloqueante: bool = True) -> int | None:
    """`waitpid` del propio hijo. Sin esto queda ZOMBI.

    Un NIETO no se puede recolectar —el sistema operativo no lo permite—: al
    morir su padre queda huérfano y lo recolecta `init`. Por eso el barrido
    por grupo solo tiene que MATAR, no esperar."""
    try:
        recogido, estado = os.waitpid(int(pid),
                                      0 if bloqueante else os.WNOHANG)
        # Con `WNOHANG`, un hijo que TODAVÍA VIVE devuelve `(0, 0)`. Leer solo
        # el estado hacía que un `0` significara «recolectado» y la clausura
        # cooperativa daba por muerto a un proceso vivo.
        if recogido == 0:
            return None
        return estado
    except ChildProcessError:
        return None
    except OSError as exc:
        if exc.errno == errno.ECHILD:
            return None
        raise
