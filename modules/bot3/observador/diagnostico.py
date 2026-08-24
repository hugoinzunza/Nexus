"""Observador Bot3.v13 — capa registral de §20: diagnósticos e incidencias.

Tres artefactos gobiernan el arranque del servicio, y ninguno es opcional:

- **`fallo_cerrado.json`** (§20.6.3): por qué terminó la corrida anterior. Con
  `codigo: 1` BLOQUEA el arranque siguiente; con `codigo: 2` lo deja continuar
  reanudando la serie transitoria (§20.6.4). Confundir presencia con bloqueo
  hacía que `MAX_TRANSITORIOS` fuera inalcanzable;
- **la INCIDENCIA de interrupción** (§20.4.2.3): cuando el barrido diferido
  encuentra un diagnóstico previo que NO puede sobrescribir, es lo único que
  acredita que el supervisor fue interrumpido;
- **la ACREDITACIÓN** (§20.6.5.1): el acto humano que levanta un bloqueo.

Los tres comparten dos primitivas que el diseño congela por separado porque
cada una tapa un agujero distinto:

1. `enlazar_exclusivo` (§20.6.4). `os.rename` sobrescribe en silencio y no
   admite `O_EXCL`, así que archivar siempre al mismo nombre era archivar y
   perder la historia a la vez. `link` es atómico y falla con `EEXIST`, que es
   la exclusión real —no una comprobación previa que otro proceso podría
   ganar—;
2. `comparar_deterministas` (§20.4.2.4). La reanudación tras una caída
   recalcula la misma ruta y vuelve a publicar; si comparara el documento
   ENTERO, el instante muestreado por el segundo proceso nunca coincidiría y
   el éxito idempotente que el diseño exige sería imposible. Se comparan los
   campos deterministas y se CONSERVA el instante de la primera publicación.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from . import contrato as C
from .estado import canon, escribir_atomico, sha

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")

SCHEMA_DIAGNOSTICO = 1
SCHEMA_INCIDENCIA = 1
SCHEMA_ACREDITACION = 1

CARPETA_DIAGNOSTICOS = "diagnosticos"

# §20.6.3 — registro CERRADO de motivos. Uno desconocido no describe nada, así
# que no puede gobernar un arranque.
MOTIVO_EXCEPCION = "excepcion"
MOTIVO_TRANSITORIOS = "transitorios_agotados"
MOTIVO_SENAL = "senal"
MOTIVO_SIN_DIAGNOSTICO = "sin_diagnostico"
MOTIVO_WRAPPER = "wrapper"
MOTIVO_SUPERVISOR = "supervisor_interrumpido"
MOTIVOS_DIAGNOSTICO = (MOTIVO_EXCEPCION, MOTIVO_TRANSITORIOS, MOTIVO_SENAL,
                       MOTIVO_SIN_DIAGNOSTICO, MOTIVO_WRAPPER,
                       MOTIVO_SUPERVISOR)

# §20.4.2.3 — clasificación CERRADA de la incidencia.
CLAS_PRESERVADO = "codigo_1_preservado"
CLAS_CORRUPTO = "corrupto"
CLAS_AJENA = "identidad_ajena"
CLASIFICACIONES = (CLAS_PRESERVADO, CLAS_CORRUPTO, CLAS_AJENA)

CODIGOS = (1, 2)

# §20.4.2.4 — qué se compara al reencontrar un documento ya publicado. El
# instante NO está acá a propósito.
DETERMINISTAS_INCIDENCIA = ("schema_version", "cohorte", "contrato", "commit",
                            "supervision_checksum", "diagnostico_sha256",
                            "clasificacion")
DETERMINISTAS_ACREDITACION = ("schema_version", "cohorte", "contrato",
                              "commit", "diagnostico_checksum",
                              "acreditado_por", "motivo_humano")

SHA_VACIO = hashlib.sha256(b"").hexdigest()

# Conjuntos CERRADOS de campos. Un campo desconocido con el checksum
# recalculado se aceptaba: el checksum acredita que nadie lo alteró DESPUÉS,
# no que el documento sea el que el schema define.
CAMPOS_DIAGNOSTICO = {
    "obligatorios": ("schema_version", "cohorte", "contrato", "commit",
                     "motivo", "codigo", "ocurrido_en", "transitorios",
                     "checksum"),
    "opcionales": ("excepcion", "traceback", "estado_crudo", "senal",
                   "supervision_checksum"),
}
# Tabla CONGELADA que RELACIONA motivo, código y campos (§20.6.3). Validar
# cada campo por separado dejaba pasar documentos coherentes campo a campo y
# absurdos como conjunto: `senal` con `codigo: 2` validaba, y con
# `transitorios: 1` el arranque lo dejaba CONTINUAR — una muerte por `SIGKILL`
# reiniciándose como transitoria, que es exactamente lo que §20.6.3 prohíbe.
#
# `codigos`: los únicos admisibles. `exige`: campos obligatorios de ese motivo.
# Todo campo opcional que no esté en `admite` queda PROHIBIDO para el motivo.
POR_MOTIVO = {
    # el daemon puede fallar por una excepción camino a salir 1 o a salir 2
    MOTIVO_EXCEPCION: {"codigos": (1, 2), "exige": ("excepcion",),
                       "admite": ("excepcion", "traceback")},
    # la cota de la serie: escala a 1 y nunca vuelve a ser transitoria
    MOTIVO_TRANSITORIOS: {"codigos": (1,), "exige": ("excepcion",),
                          "admite": ("excepcion", "traceback")},
    # un SIGKILL es el ExitTimeOut vencido o un OOM: reintentarlo repite la
    # misma muerte
    MOTIVO_SENAL: {"codigos": (1,), "exige": ("senal",),
                   "admite": ("senal", "estado_crudo")},
    # lo escribe el wrapper cuando el daemon no dejó diagnóstico; conserva el
    # estado crudo que observó, y el código que clasificó
    MOTIVO_SIN_DIAGNOSTICO: {"codigos": (1, 2), "exige": ("estado_crudo",),
                             "admite": ("estado_crudo",)},
    # un bug del wrapper no se arregla reintentando
    MOTIVO_WRAPPER: {"codigos": (1,), "exige": (), "admite": ("traceback",)},
    # §20.4.2.1: la muerte del supervisor no es un reinicio
    MOTIVO_SUPERVISOR: {"codigos": (1,), "exige": ("supervision_checksum",),
                        "admite": ("supervision_checksum",)},
}

CAMPOS_INCIDENCIA = {
    "obligatorios": ("schema_version", "cohorte", "contrato", "commit",
                     "supervision_checksum", "diagnostico_sha256",
                     "clasificacion", "ocurrido_en", "checksum"),
    "opcionales": (),
}
CAMPOS_ACREDITACION = {
    "obligatorios": ("schema_version", "cohorte", "contrato", "commit",
                     "diagnostico_checksum", "acreditado_por",
                     "motivo_humano", "acreditado_en", "checksum"),
    "opcionales": (),
}


class DocumentoInvalido(ValueError):
    """No cumple su schema. Se falla cerrado en vez de interpretarlo."""


class Conflicto(ValueError):
    """Ya existe un documento distinto en esa ruta: dos actos incompatibles."""


# --------------------------------------------------------------------------
# primitivas
# --------------------------------------------------------------------------
def _fsync_dir(carpeta: str) -> None:
    fd = os.open(carpeta, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def enlazar_exclusivo(origen: str, destino: str) -> bool:
    """§20.6.4: `link` → `fsync` del directorio → `unlink` → `fsync`.

    Devuelve `True` si el enlace se creó, `False` si el destino YA existía —el
    llamador decide entonces si es éxito idempotente o conflicto—.

    `os.replace` no sirve: sobrescribe en silencio. Y comprobar
    `os.path.exists` antes de renombrar tampoco: entre la comprobación y el
    rename otro proceso puede crear el destino. `link` resuelve las dos cosas
    en una sola operación atómica del kernel.
    """
    carpeta = os.path.dirname(destino) or "."
    try:
        os.link(origen, destino)
    except FileExistsError:
        # El origen se CONSERVA. Consumirlo acá borraba `fallo_cerrado.json`
        # antes de que nadie hubiera comprobado la colisión: bastaba que otro
        # proceso creara el destino entre el `exists()` del llamador y este
        # `link()`. Quien recibe `False` decide si es idempotencia o conflicto,
        # y hasta entonces el origen sigue siendo la autoridad.
        return False
    except OSError as exc:
        if getattr(exc, "errno", None) == 18:        # EXDEV
            raise DocumentoInvalido(
                f"{origen} y {destino} están en filesystems distintos: `link` "
                f"no cruza montajes y degradar a copiar+borrar perdería la "
                f"exclusión atómica, que es el único motivo para usarlo")
        raise
    _fsync_dir(carpeta)
    os.unlink(origen)                               # solo tras enlazar
    _fsync_dir(os.path.dirname(origen) or ".")
    return True


def completar_enlace_a_medias(origen: str, destino: str) -> bool:
    """§20.6.4: caída ENTRE `link` y `unlink`.

    Las dos rutas quedan sobre el MISMO archivo. Se comparan por
    `(st_dev, st_ino)` —el inodo solo no identifica un archivo: el mismo número
    existe en cada filesystem montado— y, si coinciden, se completa el
    `unlink`. Si difieren, son dos documentos distintos con el mismo nombre de
    destino: fallo cerrado.
    """
    if not (os.path.exists(origen) and os.path.exists(destino)):
        return False
    a, b = os.stat(origen), os.stat(destino)
    if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
        raise Conflicto(
            f"{origen} y {destino} son archivos DISTINTOS con el mismo "
            f"destino: no es media operación, es una colisión")
    os.unlink(origen)
    _fsync_dir(os.path.dirname(origen) or ".")
    return True


def comparar_deterministas(existente: dict, propuesto: dict,
                           campos) -> None:
    """§20.4.2.4: éxito idempotente o fallo cerrado, sin mirar el instante.

    Comparar el documento entero hacía imposible la recuperación que el propio
    diseño exige: el proceso que retoma muestrea su reloj, el instante difiere,
    y el reencuentro terminaba SIEMPRE en fallo cerrado."""
    difs = [c for c in campos if existente.get(c) != propuesto.get(c)]
    if difs:
        raise Conflicto(
            f"documento ya publicado con campos deterministas distintos: "
            f"{sorted(difs)}")


def publicar_unico(destino: str, cuerpo: dict, campos) -> dict:
    """`tmp` → `fsync` → `link` exclusivo → `fsync` → `unlink` → `fsync`.

    Ante `EEXIST` valida el documento existente ANTES de compararlo: uno
    corrupto ocupando esa ruta no es un éxito idempotente, es fallo cerrado —si
    no, la recuperación aceptaría cualquier basura que ocupara el nombre—.
    Devuelve el documento VIGENTE, que ante reencuentro es el ya publicado
    (conserva su instante de primera publicación).
    """
    carpeta = os.path.dirname(destino) or "."
    os.makedirs(carpeta, exist_ok=True)
    tmp = destino + ".tmp"
    escribir_atomico(tmp, canon(cuerpo))
    if enlazar_exclusivo(tmp, destino):
        return cuerpo
    # `enlazar_exclusivo` ya no consume el origen ante `EEXIST`; el `.tmp` es
    # nuestro, así que lo retiramos acá — pero DESPUÉS de comparar, para no
    # perderlo si la comparación falla cerrado.
    try:
        existente = _leer_json(destino)
        validar_por_schema(existente, destino)
        comparar_deterministas(existente, cuerpo, campos)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
            _fsync_dir(carpeta)
    return existente


def _leer_json(ruta: str) -> dict:
    with open(ruta, encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except ValueError as exc:
            raise DocumentoInvalido(f"{ruta} no es JSON: {exc}")


def sha_de_bytes(ruta: str) -> str:
    """§20.4.2.3: el documento previo se identifica por sus BYTES CRUDOS.

    No por su campo `checksum`: en un documento corrupto ese campo puede estar
    roto, ausente o mentir, y aun así hay que poder decir sin ambigüedad cuál
    era."""
    if not os.path.exists(ruta):
        return SHA_VACIO
    with open(ruta, "rb") as fh:
        # Sobre los BYTES, sin decodificar: `surrogateescape` producía
        # sustitutos que `str.encode` no puede recodificar, así que un
        # diagnóstico REALMENTE ilegible —`b"\xff\xfe\x80"`— hacía estallar
        # justo la publicación de la incidencia que debe identificarlo.
        return hashlib.sha256(fh.read()).hexdigest()


# --------------------------------------------------------------------------
# validación común
# --------------------------------------------------------------------------
def _exigir(cond, mensaje: str) -> None:
    if not cond:
        raise DocumentoInvalido(mensaje)


def _exigir_entero(valor, que: str) -> None:
    # `type(...) is int` excluye `bool`, que es subclase de `int`: sin eso
    # `True` pasaba como instante y comparaba igual a 1.
    _exigir(type(valor) is int, f"{que} no es entero: {valor!r}")


def _exigir_campos_cerrados(cuerpo: dict, campos: dict, donde: str) -> None:
    permitidos = set(campos["obligatorios"]) | set(campos["opcionales"])
    sobran = sorted(set(cuerpo) - permitidos)
    _exigir(not sobran, f"campos fuera del schema{donde}: {sobran}")
    faltan = sorted(set(campos["obligatorios"]) - set(cuerpo))
    _exigir(not faltan, f"campos obligatorios ausentes{donde}: {faltan}")


def _exigir_valor(valor, permitidos, que: str) -> None:
    """Compara por TIPO además de por valor: `True == 1`, así que
    `codigo in (1, 2)` aceptaba `True` y `schema_version == 1` aceptaba
    `True` por lo mismo."""
    _exigir(any(v == valor and type(v) is type(valor) for v in permitidos),
            f"{que} fuera del registro cerrado: {valor!r} "
            f"({type(valor).__name__})")


def _exigir_texto(valor, que: str) -> None:
    _exigir(isinstance(valor, str) and valor.strip(),
            f"{que} vacío o no textual: {valor!r}")


def _exigir_sha(valor, que: str) -> None:
    _exigir(isinstance(valor, str) and _HEX64.match(valor),
            f"{que} no es un SHA-256 hexadecimal: {valor!r}")


def _exigir_identidad(cuerpo: dict, donde: str) -> None:
    _exigir_texto(cuerpo.get("cohorte"), f"`cohorte`{donde}")
    _exigir_sha(cuerpo.get("contrato"), f"`contrato`{donde}")
    _exigir_texto(cuerpo.get("commit"), f"`commit`{donde}")


def _exigir_checksum(cuerpo: dict, donde: str) -> None:
    esperado = cuerpo.get("checksum")
    _exigir_sha(esperado, f"`checksum`{donde}")
    sin = {k: v for k, v in cuerpo.items() if k != "checksum"}
    _exigir(sha(canon(sin)) == esperado,
            f"checksum no corresponde{donde}: el documento fue alterado")


def _sellar(cuerpo: dict) -> dict:
    cuerpo = {k: v for k, v in cuerpo.items() if k != "checksum"}
    cuerpo["checksum"] = sha(canon(cuerpo))
    return cuerpo


# --------------------------------------------------------------------------
# fallo_cerrado.json — §20.6.3
# --------------------------------------------------------------------------
def validar_diagnostico(cuerpo, ruta: str = "") -> dict:
    donde = f" en {ruta}" if ruta else ""
    _exigir(isinstance(cuerpo, dict), f"diagnóstico no es un objeto{donde}")
    _exigir_campos_cerrados(cuerpo, CAMPOS_DIAGNOSTICO, donde)
    _exigir_valor(cuerpo.get("schema_version"), (SCHEMA_DIAGNOSTICO,),
                  f"`schema_version`{donde}")
    _exigir_identidad(cuerpo, donde)
    motivo = cuerpo.get("motivo")
    _exigir(motivo in MOTIVOS_DIAGNOSTICO,
            f"motivo fuera del registro cerrado{donde}: {motivo!r}")
    regla = POR_MOTIVO[motivo]
    # `codigo` es CLASIFICADO, no crudo: un proceso muerto por señal no
    # devuelve 1, el shell entrega `128 + N`. Ese valor viaja en
    # `estado_crudo`, y `senal` lleva además el número.
    _exigir_valor(cuerpo.get("codigo"), CODIGOS, f"`codigo`{donde}")
    _exigir_valor(cuerpo["codigo"], regla["codigos"],
                  f"`codigo`{donde} para `motivo: {motivo}`")
    _exigir_entero(cuerpo.get("ocurrido_en"), f"`ocurrido_en`{donde}")
    _exigir_entero(cuerpo.get("transitorios"), f"`transitorios`{donde}")
    _exigir(cuerpo["transitorios"] >= 0,
            f"`transitorios`{donde} negativo: {cuerpo['transitorios']}")
    # Solo `codigo: 2` lleva serie: un fallo cerrado no se reintenta, así que
    # un contador ahí no significaría nada y podría leerse como que sí.
    if cuerpo["codigo"] == 1:
        _exigir(cuerpo["transitorios"] == 0,
                f"`transitorios`{donde} no nulo con `codigo: 1`: un fallo "
                f"cerrado no tiene serie que continuar")
    faltan = sorted(c for c in regla["exige"] if c not in cuerpo)
    _exigir(not faltan,
            f"`motivo: {motivo}`{donde} exige {faltan}")
    sobran = sorted(c for c in CAMPOS_DIAGNOSTICO["opcionales"]
                    if c in cuerpo and c not in regla["admite"])
    _exigir(not sobran,
            f"`motivo: {motivo}`{donde} no admite {sobran}")
    if "senal" in cuerpo:
        _exigir_entero(cuerpo["senal"], f"`senal`{donde}")
        _exigir(cuerpo["senal"] > 0, f"`senal`{donde} no positiva")
    if "excepcion" in cuerpo:
        _exigir_texto(cuerpo["excepcion"], f"`excepcion`{donde}")
    if "traceback" in cuerpo:
        _exigir_texto(cuerpo["traceback"], f"`traceback`{donde}")
    if "supervision_checksum" in cuerpo:
        # §20.4.2.1: CITA el sidecar que lo motivó. Es lo que permite al
        # wrapper siguiente distinguir «ya diagnosticado, falta retirar» de
        # «hay que diagnosticar», sin heurística ni estado en memoria.
        _exigir_sha(cuerpo["supervision_checksum"],
                    f"`supervision_checksum`{donde}")
    if "estado_crudo" in cuerpo:
        _exigir_entero(cuerpo["estado_crudo"], f"`estado_crudo`{donde}")
    _exigir_checksum(cuerpo, donde)
    return cuerpo


def diagnostico(identidad: dict, motivo: str, codigo: int, ocurrido_en: int,
                transitorios: int = 0, **extra) -> dict:
    cuerpo = {
        "schema_version": SCHEMA_DIAGNOSTICO,
        "cohorte": identidad.get("cohorte"),
        "contrato": identidad.get("contrato"),
        "commit": identidad.get("commit"),
        "motivo": motivo,
        "codigo": codigo,
        # NADA de `int(...)`: convertía `True`, `"10"` y `10.7` en enteros
        # legítimos ANTES de validar, así que la validación nunca veía el
        # valor que el llamador realmente pasó.
        "ocurrido_en": ocurrido_en,
        "transitorios": transitorios,
    }
    cuerpo.update({k: v for k, v in extra.items() if v is not None})
    cuerpo = _sellar(cuerpo)
    return validar_diagnostico(cuerpo)


def publicar_diagnostico(estado_dir: str, cuerpo: dict) -> str:
    """El diagnóstico VIGENTE se sobrescribe atómicamente: es un puntero al
    estado actual, no un registro histórico. Lo histórico son los archivados
    de `diagnosticos/`, que sí son append-only."""
    validar_diagnostico(cuerpo)
    ruta = os.path.join(estado_dir, C.ARCHIVO_FALLO_CERRADO)
    escribir_atomico(ruta, canon(cuerpo))
    return ruta


def leer_diagnostico(estado_dir: str) -> dict | None:
    ruta = os.path.join(estado_dir, C.ARCHIVO_FALLO_CERRADO)
    if not os.path.exists(ruta):
        return None
    return validar_diagnostico(_leer_json(ruta), ruta)


def bloquea_arranque(estado_dir: str, identidad: dict) -> dict | None:
    """§20.6.4: el arranque distingue por CÓDIGO, no por presencia.

    rev.20 rechazaba cualquier presencia, y el daemon escribía un diagnóstico
    también antes de salir `2`: `EBUSY → codigo=2 → reinicio → sale 1`. Nunca
    se llegaba al segundo intento y `MAX_TRANSITORIOS` era inoperante.

    Devuelve el diagnóstico que BLOQUEA, o `None` si se puede continuar.
    """
    ruta = os.path.join(estado_dir, C.ARCHIVO_FALLO_CERRADO)
    if not os.path.exists(ruta):
        return None
    d = validar_diagnostico(_leer_json(ruta), ruta)   # corrupto → fallo cerrado
    for campo in ("cohorte", "contrato", "commit"):
        if d.get(campo) != identidad.get(campo):
            raise DocumentoInvalido(
                f"{ruta} es de otra identidad ({campo}): un diagnóstico ajeno "
                f"acá significa que algo mezcló dos estados")
    if d["codigo"] == 1:
        return d
    if d["transitorios"] >= C.MAX_TRANSITORIOS:
        return d                        # el llamador lo escala (§20.6.4)
    return None


def archivar_diagnostico(estado_dir: str, cuerpo: dict) -> str:
    """§20.6.4: ruta ÚNICA y append-only.

    Renombrar siempre al mismo `.archivado` hacía que una segunda serie
    transitoria pisara la primera: archivar y perder la historia a la vez."""
    validar_diagnostico(cuerpo)
    carpeta = os.path.join(estado_dir, CARPETA_DIAGNOSTICOS)
    os.makedirs(carpeta, exist_ok=True)
    destino = os.path.join(
        carpeta,
        f"fallo_cerrado.{cuerpo['ocurrido_en']}.{cuerpo['checksum'][:8]}.json")
    origen = os.path.join(estado_dir, C.ARCHIVO_FALLO_CERRADO)
    if not os.path.exists(origen):
        raise DocumentoInvalido(f"no hay {origen} que archivar")
    # El `cuerpo` declarado tiene que SER el archivo activo. Sin esto, archivar
    # A mientras el activo era B creaba una ruta nombrada con el checksum de A,
    # guardaba B adentro y borraba el diagnóstico vigente: el nombre mentía
    # sobre su contenido y se perdía el documento que gobernaba el arranque.
    activo = validar_diagnostico(_leer_json(origen), origen)
    if activo != cuerpo:
        raise Conflicto(
            f"el cuerpo a archivar no es el contenido de {origen}: "
            f"{activo.get('checksum')} vigente contra "
            f"{cuerpo.get('checksum')} declarado")
    if os.path.exists(destino):
        # Dos lecturas posibles, y hay que distinguirlas: MISMO archivo es una
        # caída entre `link` y `unlink` que se completa; archivos DISTINTOS es
        # una colisión de nombre, y archivar encima sería archivar y perder la
        # historia a la vez.
        try:
            if completar_enlace_a_medias(origen, destino):
                return destino
        except Conflicto:
            raise Conflicto(
                f"{destino} ya existe con otro contenido: no se pisa historia")
    if not enlazar_exclusivo(origen, destino):
        raise Conflicto(f"{destino} ya existe: no se pisa historia")
    return destino


# --------------------------------------------------------------------------
# incidencia de interrupción — §20.4.2.3
# --------------------------------------------------------------------------
def validar_incidencia(cuerpo, ruta: str = "") -> dict:
    donde = f" en {ruta}" if ruta else ""
    _exigir(isinstance(cuerpo, dict), f"incidencia no es un objeto{donde}")
    _exigir_campos_cerrados(cuerpo, CAMPOS_INCIDENCIA, donde)
    _exigir_valor(cuerpo.get("schema_version"), (SCHEMA_INCIDENCIA,),
                  f"`schema_version`{donde}")
    _exigir_identidad(cuerpo, donde)
    _exigir_sha(cuerpo.get("supervision_checksum"),
                f"`supervision_checksum`{donde}")
    _exigir_sha(cuerpo.get("diagnostico_sha256"),
                f"`diagnostico_sha256`{donde}")
    _exigir(cuerpo.get("clasificacion") in CLASIFICACIONES,
            f"`clasificacion`{donde} fuera del registro cerrado: "
            f"{cuerpo.get('clasificacion')!r}")
    _exigir_entero(cuerpo.get("ocurrido_en"), f"`ocurrido_en`{donde}")
    _exigir_checksum(cuerpo, donde)
    return cuerpo


def ruta_incidencia(estado_dir: str, supervision_checksum: str,
                    diagnostico_sha256: str) -> str:
    """DETERMINISTA, derivada de los dos hashes. Es lo que hace la reanudación
    idempotente SIN llevar estado: el proceso que retoma tras una caída
    recalcula exactamente el mismo nombre."""
    return os.path.join(
        estado_dir, CARPETA_DIAGNOSTICOS,
        f"incidencia.{supervision_checksum[:8]}.{diagnostico_sha256[:8]}.json")


def publicar_incidencia(estado_dir: str, supervision: dict,
                        diagnostico_sha256: str, clasificacion: str,
                        ocurrido_en: int) -> tuple[str, dict]:
    """La identidad sale de `supervision`, NO del diagnóstico previo: en el
    caso corrupto y en el de identidad ajena sus campos internos no son
    confiables, mientras el sidecar de supervisión ya validó antes del
    barrido."""
    cuerpo = _sellar({
        "schema_version": SCHEMA_INCIDENCIA,
        "cohorte": supervision.get("cohorte"),
        "contrato": supervision.get("contrato"),
        "commit": supervision.get("commit"),
        "supervision_checksum": supervision.get("checksum"),
        "diagnostico_sha256": diagnostico_sha256,
        "clasificacion": clasificacion,
        "ocurrido_en": ocurrido_en,
    })
    validar_incidencia(cuerpo)
    destino = ruta_incidencia(estado_dir, cuerpo["supervision_checksum"],
                              diagnostico_sha256)
    vigente = publicar_unico(destino, cuerpo, DETERMINISTAS_INCIDENCIA)
    return destino, vigente


# --------------------------------------------------------------------------
# acreditación — §20.6.5.1
# --------------------------------------------------------------------------
def validar_acreditacion(cuerpo, ruta: str = "") -> dict:
    donde = f" en {ruta}" if ruta else ""
    _exigir(isinstance(cuerpo, dict), f"acreditación no es un objeto{donde}")
    _exigir_campos_cerrados(cuerpo, CAMPOS_ACREDITACION, donde)
    _exigir_valor(cuerpo.get("schema_version"), (SCHEMA_ACREDITACION,),
                  f"`schema_version`{donde}")
    _exigir_identidad(cuerpo, donde)
    _exigir_sha(cuerpo.get("diagnostico_checksum"),
                f"`diagnostico_checksum`{donde}")
    _exigir_texto(cuerpo.get("acreditado_por"), f"`acreditado_por`{donde}")
    # Sin motivo, la acreditación no registra por qué se decidió continuar, que
    # es lo único que la distingue de borrar el archivo.
    _exigir_texto(cuerpo.get("motivo_humano"), f"`motivo_humano`{donde}")
    _exigir_entero(cuerpo.get("acreditado_en"), f"`acreditado_en`{donde}")
    _exigir_checksum(cuerpo, donde)
    return cuerpo


def ruta_acreditacion(estado_dir: str, diagnostico_checksum: str) -> str:
    """Deriva del checksum del diagnóstico: por eso siempre se puede demostrar
    que la acreditación corresponde al documento que se retiró."""
    return os.path.join(
        estado_dir, CARPETA_DIAGNOSTICOS,
        f"acreditacion.{diagnostico_checksum[:8]}.json")


def publicar_acreditacion(estado_dir: str, identidad: dict,
                          diagnostico_checksum: str, acreditado_por: str,
                          motivo_humano: str,
                          acreditado_en: int) -> tuple[str, dict]:
    cuerpo = _sellar({
        "schema_version": SCHEMA_ACREDITACION,
        "cohorte": identidad.get("cohorte"),
        "contrato": identidad.get("contrato"),
        "commit": identidad.get("commit"),
        "diagnostico_checksum": diagnostico_checksum,
        "acreditado_por": acreditado_por,
        "motivo_humano": motivo_humano,
        "acreditado_en": acreditado_en,
    })
    validar_acreditacion(cuerpo)
    destino = ruta_acreditacion(estado_dir, diagnostico_checksum)
    vigente = publicar_unico(destino, cuerpo, DETERMINISTAS_ACREDITACION)
    return destino, vigente


# --------------------------------------------------------------------------
def validar_por_schema(cuerpo, ruta: str) -> dict:
    """Valida por el TIPO de documento que la ruta declara. `publicar_unico`
    lo necesita para no aceptar basura que ocupe el nombre."""
    base = os.path.basename(ruta)
    if base.startswith("incidencia."):
        return validar_incidencia(cuerpo, ruta)
    if base.startswith("acreditacion."):
        return validar_acreditacion(cuerpo, ruta)
    return validar_diagnostico(cuerpo, ruta)
