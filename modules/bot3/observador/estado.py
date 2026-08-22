"""Observador Bot3.v13 — digest de estado, verificación y terminales.

Cubre §6-§9 y §13 del diseño rev.8:

- `observer_state_digest`: comparar solo los bytes del libro detecta una
  divergencia YA materializada, no una latente. Dos motores pueden tener libros
  idénticos y diferir en candidato vivo, posición, zonas consumidas o épocas
  anunciadas, y declarar un falso éxito. El digest cubre todo el estado que
  pueda afectar decisiones futuras, más el sidecar de silencio, que decide un
  terminal y que el clon frío no puede reconstruir.
- `verificacion.json`: `verification_deferred` NO es un tipo del registro
  cerrado CF-37 y no entra al libro científico. Vive acá, atómico y
  rehidratable: sin él, un reinicio olvidaría que la última verificación quedó
  diferida y el reporte tomaría por válida una anterior.
- terminales `completed.json` / `blocked.json` y la solicitud `terminal.request`
  que permite reanudar una transición interrumpida.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os

from . import contrato as C


def canon(objeto) -> str:
    return json.dumps(objeto, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def escribir_atomico(ruta: str, cuerpo: str) -> None:
    """`tmp` → `fsync` → `replace` → `fsync` del directorio. El rename no es
    durable por sí solo, y estas entradas son testigos de estados terminales."""
    carpeta = os.path.dirname(ruta) or "."
    os.makedirs(carpeta, exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(cuerpo)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, ruta)
    fd = os.open(carpeta, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# --------------------------------------------------------------------------
# §7 — dos primitivas de exclusión, no una
# --------------------------------------------------------------------------
class SingletonTomado(RuntimeError):
    """Ya hay un observador sobre este estado."""


class Singleton:
    """`flock` de vida completa. **Nunca** se libera para auditar: la captura
    la ejecuta el proceso propietario, no un verificador externo.

    Es una primitiva distinta de la barrera de ciclo (un mutex interno). rev.2
    las confundía y pedía adquirir para capturar un lock que el daemon
    conserva toda su vida."""

    def __init__(self, ruta: str):
        self.ruta = ruta
        self._fh = None

    def __enter__(self) -> "Singleton":
        os.makedirs(os.path.dirname(self.ruta) or ".", exist_ok=True)
        # `O_RDWR | O_CREAT` en UNA syscall: sin truncar y sin carrera.
        #   - abrir en "w" vaciaba el archivo ANTES de pedir el lock, así que
        #     un competidor rechazado borraba el PID del propietario;
        #   - `exists()` seguido de `open("x+")` es un TOCTOU: dos primeros
        #     arranques simultáneos daban `FileExistsError` al perdedor en vez
        #     de `SingletonTomado`.
        fd = os.open(self.ruta, os.O_RDWR | os.O_CREAT, 0o600)
        self._fh = os.fdopen(fd, "r+")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fh.close()
            self._fh = None
            raise SingletonTomado(
                f"otro observador ya tiene {self.ruta}: dos sobre el mismo "
                f"estado producirían dos historias bajo una identidad")
        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write(str(os.getpid()))
        self._fh.flush()
        return self

    def __exit__(self, *_):
        if self._fh is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None
        return False


# --------------------------------------------------------------------------
# §8 — digest completo
# --------------------------------------------------------------------------
# Derivados: se recomputan sin cambiar resultados, así que no entran.
DERIVADOS = ("_reloj_ciclo", "_ciclo_externo", "_cache_h4", "_swm15",
             "_epocas_cache", "_por_t", "_ts", "_prefix_max", "_vela_hashes",
             "_gap_por_desde", "_buffer")


def estado_motor(motor) -> dict:
    """Estado del motor que puede afectar decisiones futuras."""
    mercados = {}
    for m in motor.mercados:
        st = motor.estados[m]
        mercados[m] = {
            "estado": st.estado,
            "degradado": bool(st.degradado),
            "candidato": st.candidato,
            "orden": st.orden,
            "posicion": st.posicion,
            "salida": st.salida,
            # ordenado canónicamente: un `set` no tiene orden estable
            "zonas_tocadas": sorted(list(z) for z in st.zonas_tocadas),
        }
    return {
        "mercados": mercados,
        # `motivo_corte` ausente es `null` EXPLÍCITO, nunca una clave omitida
        "cortado": bool(motor.cortado),
        "motivo_corte": getattr(motor, "motivo_corte", None),
        "frontera_cruzada": bool(motor._frontera_cruzada),
        "bootstrap_hasta": motor.bootstrap_hasta,
        "epocas_anunciadas": sorted(list(e) for e in motor._epocas_anunciadas),
        # listas COMPLETAS: `cierres` participa del corte por semanas ISO, así
        # que su contenido afecta decisiones futuras. Cardinalidad y último
        # elemento dejaban pasar dos estados distintos con el mismo digest.
        "lotes_finalizados": list(motor.lotes_finalizados),
        "cierres": list(motor.cierres),
    }


def estado_almacenes(m15: dict, h4: dict) -> dict:
    salida = {}
    for tf, mapa in (("15m", m15), ("4h", h4)):
        for mercado in sorted(mapa):
            alm = mapa[mercado]
            salida[f"{mercado}_{tf}"] = {
                "head": alm.head, "registros": len(alm.registros)}
    return salida


def observer_state_digest(motor, m15: dict, h4: dict,
                          doc_silencio: dict | None) -> str:
    """Digest del motor + almacenes + silencio.

    El sidecar de silencio va adentro porque decide un terminal futuro y el
    clon frío NO puede reconstruirlo: una ausencia H4 permanente todavía no es
    un marcador sellado. `verificacion.json` queda FUERA a propósito — es el
    registro de la propia verificación y meterlo crearía una circularidad."""
    return sha(canon({
        "motor": sha(canon({"motor": estado_motor(motor),
                            "almacenes": estado_almacenes(m15, h4)})),
        "silencio": doc_silencio or {},
    }))


# --------------------------------------------------------------------------
# §9.2 — sidecar de verificación
# --------------------------------------------------------------------------
class Verificacion:
    """Estado vigente: `ok` | `deferred` | `pending` | `divergent`."""

    def __init__(self, ruta: str):
        self.ruta = ruta
        self.estado = C.VERIF_OK
        self.ultima_ok: dict | None = None
        self.ultima_deferencia: int | None = None
        self.detalle: dict = {}

    @classmethod
    def cargar(cls, ruta: str) -> "Verificacion":
        v = cls(ruta)
        if not os.path.exists(ruta):
            return v
        with open(ruta, encoding="utf-8") as fh:
            crudo = json.load(fh)
        if crudo.get("schema_version") != C.SCHEMA_VERIFICACION:
            raise ValueError(f"schema de verificación desconocido en {ruta}")
        v.estado = crudo.get("estado", C.VERIF_OK)
        v.ultima_ok = crudo.get("ultima_ok")
        v.ultima_deferencia = crudo.get("ultima_deferencia")
        v.detalle = crudo.get("detalle", {})
        return v

    def guardar(self) -> None:
        escribir_atomico(self.ruta, canon({
            "schema_version": C.SCHEMA_VERIFICACION,
            "estado": self.estado,
            "ultima_ok": self.ultima_ok,
            "ultima_deferencia": self.ultima_deferencia,
            "detalle": self.detalle,
        }))

    def diferir(self, instante: int, buffers: dict) -> None:
        """Solo se certifica una barrera con los 14 buffers vacíos: el buffer
        no es caché derivada — ante un hueco contiene las velas que determinan
        `prueba_local`, el `detected_at` y el rango del marcador."""
        self.estado = C.VERIF_DIFERIDA
        self.ultima_deferencia = int(instante)
        self.detalle = {"buffers_no_vacios": buffers}
        self.guardar()

    def pendiente(self, instante: int, digest: str, firma: str) -> None:
        self.estado = C.VERIF_PENDIENTE
        self.detalle = {"desde": int(instante), "digest": digest,
                        "firma": firma}
        self.guardar()

    def conforme(self, instante: int, digest: str, firma: str) -> None:
        self.estado = C.VERIF_OK
        self.ultima_ok = {"instante": int(instante), "digest": digest,
                          "firma": firma}
        self.detalle = {}
        self.guardar()

    def divergente(self, instante: int, esperado: dict, obtenido: dict) -> None:
        self.estado = C.VERIF_DIVERGENTE
        self.detalle = {"instante": int(instante), "esperado": esperado,
                        "obtenido": obtenido}
        self.guardar()

    def habilita_cierre(self) -> bool:
        """`COMPLETED` exige `ok` **y posterior a toda deferencia**. No basta
        con la ausencia de `pending`: un `deferred` sin verificación exitosa
        posterior tampoco habilita el cierre."""
        if self.estado != C.VERIF_OK or not self.ultima_ok:
            return False
        if self.ultima_deferencia is None:
            return True
        return self.ultima_ok["instante"] > self.ultima_deferencia


# --------------------------------------------------------------------------
# §13 y §9.1.1 — terminales y transición serializada
# --------------------------------------------------------------------------
def _leer(ruta: str) -> dict | None:
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding="utf-8") as fh:
        return json.load(fh)


def solicitar_terminal(ruta: str, motivo: str, identidad: dict,
                       evidencia: dict, solicitado_en: int,
                       estado_esperado: dict) -> dict:
    """Escribe (o ANEXA a) la solicitud persistente que permite reanudar la
    transición tras una caída. La anexión también es una escritura y va
    atómica; el motivo ganador se decide por PRECEDENCIA, no por orden de
    llegada."""
    previo = _leer(ruta)
    if previo is not None:
        verificar_solicitud(previo, ruta)
        cuerpo = dict(previo)
        # La evidencia viaja CON su motivo. Guardar una sola dejaba que un
        # terminal `determinism_divergence` se publicara con la evidencia del
        # `silencio_h4` que había llegado antes.
        evidencias = dict(cuerpo.get("evidencias", {}))
        evidencias.setdefault(motivo, evidencia)
        cuerpo["evidencias"] = evidencias
        cuerpo["motivos_adicionales"] = sorted(
            m for m in evidencias if m != previo["motivo"])
        # El estado AUTORIZADO se refresca en cada registro: si la primera
        # causa lo fijó y una segunda movió el libro —un cierre administrativo
        # emite eventos—, el request habría autorizado un estado ya viejo y la
        # reanudación lo habría rechazado por divergencia de heads/firma.
        cuerpo["estado_esperado"] = estado_esperado
        cuerpo["solicitado_en"] = int(solicitado_en)
    else:
        cuerpo = {
            "schema_version": C.SCHEMA_TERMINAL,
            "cohorte": identidad.get("cohorte"),
            "contrato": identidad.get("contrato"),
            "commit": identidad.get("commit"),
            "motivos_adicionales": [],
            "evidencias": {motivo: evidencia},
            "solicitado_en": int(solicitado_en),
            "estado_esperado": estado_esperado,
        }
    # El GANADOR y su evidencia se derivan juntos, siempre, de la misma tabla.
    cuerpo["motivo"] = min(
        cuerpo["evidencias"],
        key=lambda m: (C.PRECEDENCIA_MOTIVOS.index(m)
                       if m in C.PRECEDENCIA_MOTIVOS
                       else len(C.PRECEDENCIA_MOTIVOS), m))
    cuerpo["evidencia"] = cuerpo["evidencias"][cuerpo["motivo"]]
    cuerpo["motivos_adicionales"] = sorted(
        m for m in cuerpo["evidencias"] if m != cuerpo["motivo"])
    cuerpo.pop("checksum", None)
    cuerpo["checksum"] = sha(canon(cuerpo))
    escribir_atomico(ruta, canon(cuerpo))
    return cuerpo


def leer_solicitud(ruta: str) -> dict | None:
    """El request VALIDADO, o None si no existe."""
    cuerpo = _leer(ruta)
    if cuerpo is None:
        return None
    verificar_solicitud(cuerpo, ruta)
    return cuerpo


def verificar_solicitud(cuerpo: dict, ruta: str) -> None:
    esperado = cuerpo.get("checksum")
    cuerpo_sin = {k: v for k, v in cuerpo.items() if k != "checksum"}
    real = sha(canon(cuerpo_sin))
    if esperado != real:
        raise ValueError(
            f"terminal.request alterado en {ruta}: checksum no corresponde")
    if cuerpo.get("schema_version") != C.SCHEMA_TERMINAL:
        raise ValueError(f"schema de terminal.request desconocido en {ruta}")


def publicar_terminal(estado_dir: str, estado: str, cuerpo: dict) -> str:
    archivo = C.ARCHIVO_COMPLETADO if estado == C.COMPLETADO \
        else C.ARCHIVO_BLOQUEADO
    ruta = os.path.join(estado_dir, archivo)
    escribir_atomico(ruta, canon({**cuerpo, "estado": estado,
                                  "schema_version": C.SCHEMA_TERMINAL}))
    return ruta


def leer_terminal(estado_dir: str) -> dict | None:
    """Precedencia CONGELADA (§9.1.1):

    - `blocked.json` presente manda; el request se ignora y se archiva;
    - `completed.json` **y** `terminal.request` a la vez es fallo cerrado —
      una contradicción que exige intervención humana;
    - un request sin terminal significa caída a mitad: se reanuda.
    """
    bloqueado = _leer(os.path.join(estado_dir, C.ARCHIVO_BLOQUEADO))
    completado = _leer(os.path.join(estado_dir, C.ARCHIVO_COMPLETADO))
    ruta_req = os.path.join(estado_dir, C.ARCHIVO_SOLICITUD_TERMINAL)
    solicitud = _leer(ruta_req)
    if bloqueado is not None and completado is not None:
        raise ValueError(
            f"{estado_dir} tiene completed.json y blocked.json a la vez")
    if bloqueado is not None:
        return {"estado": C.BLOQUEADO, "cuerpo": bloqueado}
    if completado is not None:
        if solicitud is not None:
            raise ValueError(
                f"{estado_dir} tiene completed.json y terminal.request a la "
                f"vez: contradicción que exige intervención humana")
        return {"estado": C.COMPLETADO, "cuerpo": completado}
    if solicitud is not None:
        verificar_solicitud(solicitud, ruta_req)
        return {"estado": "reanudar", "cuerpo": solicitud}
    return None
