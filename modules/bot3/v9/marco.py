"""Encuadre de registros para los archivos append-only de Bot3.v13.

Diseño del observador rev.8 §5.1 (SHA-256 del diseño
`660c25d6f9151dfcde5db06abf31158f58e5ad3d65a370897299d080561aa781`).

`fsync` ordena la durabilidad pero NO hace atómico un registro: una caída puede
dejar la última escritura a medias. Sin un marco, `Almacen.cargar()` y
`Ledger._releer()` no pueden distinguir esa cola truncada de una corrupción, y
la recuperación exacta que exige el gate de durabilidad es indemostrable.

Formato, idéntico para almacén y libro::

    <longitud_bytes>\\t<sha256(payload)>\\t<payload>\\n

`longitud_bytes` es el tamaño EXACTO del payload en bytes UTF-8.

**El único criterio de truncación es la ausencia del `\\n` final**, y solo el
último segmento del archivo puede sufrirla. Una trama cerrada con `\\n` cuyo
encabezado, longitud, UTF-8 o hash fallen es CORRUPCIÓN y falla cerrado: el
encabezado no puede ser juez de su propia integridad —el hash cubre el
payload—, así que `bytes < longitud` no sirve para clasificar.

El marco es contenedor, no contenido: no entra en ninguna identidad.
`hash_acum` encadena el `payload` y `Ledger.firma()` hashea eventos canónicos.
"""
from __future__ import annotations

import os
import re

from .contract import sha256_hex

CABECERA = re.compile(rb"([0-9]{1,9})\t([0-9a-f]{64})\t")

LONGITUD_MAX = 10 ** 9 - 1


class MarcoCorrupto(ValueError):
    """Una trama cerrada que no valida. Nunca se descarta en silencio."""


def enmarcar(payload: str) -> bytes:
    """Serializa un payload en una trama."""
    crudo = payload.encode("utf-8")
    if len(crudo) > LONGITUD_MAX:
        raise ValueError(f"payload de {len(crudo)} bytes excede el marco")
    cabecera = f"{len(crudo)}\t{sha256_hex(payload)}\t".encode("utf-8")
    return cabecera + crudo + b"\n"


def escribir(ruta: str, payload: str, durable: bool = False) -> None:
    """Appendea una trama. Con `durable`, la baja a disco antes de volver."""
    carpeta = os.path.dirname(ruta)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    with open(ruta, "ab") as fh:
        fh.write(enmarcar(payload))
        if durable:
            fh.flush()
            os.fsync(fh.fileno())


def sincronizar(ruta: str) -> None:
    """`fsync` explícito del archivo (cierre de ciclo)."""
    if not os.path.exists(ruta):
        return
    fd = os.open(ruta, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def leer(ruta: str) -> tuple[list[str], bool]:
    """Lee las tramas de `ruta`.

    Devuelve `(payloads, cola_truncada)`. `cola_truncada` es True cuando se
    descartó una última trama incompleta —el archivo no termina en `\\n` y no
    hay ninguna frontera de trama posterior—, que es el único descarte
    permitido. Cualquier otro defecto levanta `MarcoCorrupto`.
    """
    with open(ruta, "rb") as fh:
        datos = fh.read()
    payloads: list[str] = []
    pos, n = 0, 0
    while pos < len(datos):
        n += 1
        # ¿Es este el ÚLTIMO segmento? Lo es sii no queda ninguna frontera de
        # trama por delante. El payload es JSON canónico y nunca contiene un
        # `\n` crudo, así que un `\n` posterior implica otra trama. Un archivo
        # que termina en `\n` NUNCA tiene un segmento final truncable.
        final = datos.find(b"\n", pos) == -1
        motivo = None

        m = CABECERA.match(datos, pos)
        if m is None:
            motivo = "encabezado fuera de gramática"
        else:
            largo = int(m.group(1))
            ini, fin = m.end(), m.end() + largo
            if fin >= len(datos) or datos[fin:fin + 1] != b"\n":
                motivo = "la longitud no cierra en `\\n`"
            else:
                try:
                    payload = datos[ini:fin].decode("utf-8")
                except UnicodeDecodeError:
                    motivo = "payload no es UTF-8 válido"
                else:
                    if sha256_hex(payload) != m.group(2).decode("ascii"):
                        motivo = "hash del payload no coincide"

        if motivo is not None:
            if final:
                return payloads, True         # truncación: único descarte
            raise MarcoCorrupto(f"trama {n} corrupta en {ruta}: {motivo}")

        payloads.append(payload)
        pos = fin + 1
    return payloads, False


def truncar_cola(ruta: str) -> bool:
    """Deja el archivo con solo las tramas íntegras.

    Se usa tras detectar una cola truncada: el reproceso volverá a escribir lo
    que falte, y dejar el resto pegado impediría que la próxima trama empezara
    en una frontera válida. Devuelve True si hubo algo que truncar."""
    payloads, cola = leer(ruta)
    if not cola:
        return False
    bueno = b"".join(enmarcar(p) for p in payloads)
    tmp = ruta + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(bueno)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, ruta)
    carpeta = os.path.dirname(ruta) or "."
    fd = os.open(carpeta, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return True
