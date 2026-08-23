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
import re

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
class VerificacionInvalida(ValueError):
    """El sidecar no cumple §13.4.2. Se falla cerrado en vez de asumir `ok`."""


_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


def _exigir_campos(mapa, campos, que: str) -> None:
    if not isinstance(mapa, dict):
        raise VerificacionInvalida(f"{que} no es un objeto: {mapa!r}")
    faltan = [c for c in campos if c not in mapa]
    if faltan:
        raise VerificacionInvalida(f"{que} sin {sorted(faltan)}")


def _exigir_entero(valor, que: str) -> None:
    """`type(...) is int` excluye `bool`, que es subclase de `int`: sin eso
    `True` pasaba como instante y comparaba igual a 1."""
    if type(valor) is not int:
        raise VerificacionInvalida(
            f"{que} no es entero: {valor!r} ({type(valor).__name__})")


def _exigir_sha(valor, que: str) -> None:
    """SHA-256 hexadecimal canónico. Comprobar solo la PRESENCIA del campo era
    fail-open: `digest: null` y `firma: []` pasaban la validación y llegaban a
    `exigir_captura_autorizada`, donde comparaban por igualdad contra otro
    valor basura — o habilitaban el cierre sin acreditar nada."""
    if not isinstance(valor, str) or not _HEX64.match(valor):
        raise VerificacionInvalida(
            f"{que} no es un SHA-256 hexadecimal: {valor!r}")


def _exigir_par(mapa, que: str) -> None:
    _exigir_campos(mapa, ("digest", "firma"), que)
    _exigir_sha(mapa["digest"], f"{que}.digest")
    _exigir_sha(mapa["firma"], f"{que}.firma")


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
        v.estado = crudo.get("estado")
        v.ultima_ok = crudo.get("ultima_ok")
        v.ultima_deferencia = crudo.get("ultima_deferencia")
        v.detalle = crudo.get("detalle", {})
        v.validar(ruta)
        return v

    def validar(self, ruta: str = "") -> None:
        """§13.4.2: registro CERRADO de estados y estructura por estado.

        El default `ok` de `crudo.get("estado", C.VERIF_OK)` era fail-open: un
        sidecar sin `estado`, o con uno desconocido, se leía como habilitante
        y dejaba publicar `silencio_h4` sin comprobar si había una comparación
        `pending` que debiera retenerlo."""
        donde = f" en {ruta}" if ruta else ""
        if self.estado not in C.ESTADOS_VERIFICACION:
            raise VerificacionInvalida(
                f"estado de verificación fuera del registro cerrado{donde}: "
                f"{self.estado!r}")
        if self.ultima_deferencia is not None:
            _exigir_entero(self.ultima_deferencia,
                           f"`ultima_deferencia`{donde}")
        if self.ultima_ok is not None:
            _exigir_par(self.ultima_ok, f"`ultima_ok`{donde}")
            _exigir_campos(self.ultima_ok, ("instante",),
                           f"`ultima_ok`{donde}")
            _exigir_entero(self.ultima_ok["instante"],
                           f"`ultima_ok.instante`{donde}")
        if self.estado == C.VERIF_OK and not self.ultima_ok:
            raise VerificacionInvalida(
                f"estado `ok` sin `ultima_ok`{donde}: nada acredita qué "
                f"comparación lo produjo")
        if self.estado == C.VERIF_PENDIENTE:
            que = f"`detalle` de `pending`{donde}"
            _exigir_par(self.detalle, que)
            _exigir_campos(self.detalle, ("desde", "copia"), que)
            _exigir_entero(self.detalle["desde"], f"{que}.desde")
            # §13.5.1: sin la copia, la comparación no se puede reanudar tras
            # un reinicio y la cohorte queda trabada.
            if not isinstance(self.detalle["copia"], str) \
                    or not self.detalle["copia"].strip():
                raise VerificacionInvalida(
                    f"{que}.copia no es una ruta: {self.detalle['copia']!r}")
        if self.estado == C.VERIF_DIVERGENTE:
            que = f"`detalle` de `divergent`{donde}"
            _exigir_campos(self.detalle, ("instante", "esperado", "obtenido"),
                           que)
            _exigir_entero(self.detalle["instante"], f"{que}.instante")
            _exigir_par(self.detalle["esperado"], f"{que}.esperado")
            _exigir_par(self.detalle["obtenido"], f"{que}.obtenido")
        if self.estado == C.VERIF_DIFERIDA:
            if self.ultima_deferencia is None:
                raise VerificacionInvalida(
                    f"`deferred` sin `ultima_deferencia`{donde}")
            # Estructura CERRADA: `{"buffers_no_vacios": {stream: n}}`, con
            # `n` entero positivo. Es lo que produce `buffers_no_vacios`.
            que = f"`detalle` de `deferred`{donde}"
            _exigir_campos(self.detalle, ("buffers_no_vacios",), que)
            buffers = self.detalle["buffers_no_vacios"]
            if not isinstance(buffers, dict):
                raise VerificacionInvalida(
                    f"{que}.buffers_no_vacios no es un objeto: {buffers!r}")
            if not buffers:
                # Un `deferred` VACÍO es contradictorio: el estado solo nace
                # porque hay buffers pendientes. Y con ganador de integridad
                # `deferred` PUBLICA (§9.1.2), así que aceptar un documento
                # imposible es aceptar que publique.
                raise VerificacionInvalida(
                    f"{que}.buffers_no_vacios vacío: `deferred` solo existe "
                    f"porque hay buffers pendientes")
            for stream, n in buffers.items():
                if not isinstance(stream, str) or not stream:
                    raise VerificacionInvalida(
                        f"{que}: nombre de stream inválido {stream!r}")
                _exigir_entero(n, f"{que}[{stream!r}]")
                if n <= 0:
                    raise VerificacionInvalida(
                        f"{que}[{stream!r}] no es positivo: {n}")

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

    def pendiente(self, instante: int, digest: str, firma: str,
                  copia: str | None = None) -> None:
        """§13.5.1: se guarda la RUTA de la copia scratch para que la
        comparación fría sobreviva a un reinicio. Sin ella no se puede
        certificar ni descartar el determinismo, y eso es fallo cerrado."""
        self.estado = C.VERIF_PENDIENTE
        self.detalle = {"desde": int(instante), "digest": digest,
                        "firma": firma, "copia": copia}
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


class RequestInvalido(ValueError):
    """El request no cumple el contrato de §13.2/§13.7."""


def _ganador(evidencias: dict) -> str:
    """Ganador por precedencia TOTAL. Valida el registro cerrado ANTES de
    elegir: un motivo desconocido no puede aportar un ganador, y dos motivos
    científicos significan que algo ya está mal (§13.2.1)."""
    for m in evidencias:
        if m not in C.PRECEDENCIA_TERMINAL:
            raise RequestInvalido(
                f"motivo fuera del registro cerrado: {m!r}")
    cientificos = [m for m in evidencias if m in C.MOTIVOS_CIENTIFICOS]
    if len(cientificos) > 1:
        raise RequestInvalido(
            f"dos motivos científicos a la vez: {sorted(cientificos)}. El "
            f"motor corta una sola vez")
    return min(evidencias, key=lambda m: C.PRECEDENCIA_TERMINAL.index(m))


def captura_de(verificacion) -> dict | None:
    """§13.4.1: identidad ESTABLE de la comparación en curso, o `None`.

    No son los bytes del sidecar —que la propia comparación reescribe al
    terminar— sino de qué captura salió: `desde`, `digest`, `firma` y la ruta
    de la copia."""
    if verificacion is None or verificacion.estado != C.VERIF_PENDIENTE:
        return None
    d = verificacion.detalle
    return {"desde": d["desde"], "digest": d["digest"], "firma": d["firma"],
            "copia": d["copia"]}


def exigir_captura_autorizada(req: dict, verificacion) -> None:
    """§13.4.1: el `ok` que habilita el cierre tiene que ser EL DE LA MISMA
    comparación que estaba `pending` cuando se registró la causa.

    `habilita_cierre()` no alcanza: mira estado y tiempos, no procedencia, así
    que un `ok` de OTRA captura habilitaba un `COMPLETED` que nadie autorizó.
    Solo dos transiciones son legítimas; cualquier otra es fallo cerrado."""
    cap = req.get("captura_autorizada")
    if cap is None:
        return                      # no había comparación de la cual derivar
    if verificacion is None:
        raise ValueError(
            "el request congeló una captura autorizada y no se recibió el "
            "sidecar para acreditar su transición")
    est = verificacion.estado
    if est == C.VERIF_PENDIENTE:
        actual = captura_de(verificacion)
        if actual != cap:
            raise ValueError(
                f"la comparación en curso no es la autorizada: {actual} != "
                f"{cap}")
        return                      # sigue corriendo: la ventana no cierra
    if est == C.VERIF_OK:
        ok = verificacion.ultima_ok or {}
        if (ok.get("digest"), ok.get("firma")) != (cap["digest"],
                                                   cap["firma"]):
            raise ValueError(
                f"el `ok` vigente no deriva de la captura autorizada: "
                f"{ok.get('digest')!r}/{ok.get('firma')!r} != "
                f"{cap['digest']!r}/{cap['firma']!r}")
        return
    if est == C.VERIF_DIVERGENTE:
        esp = verificacion.detalle.get("esperado") or {}
        if (esp.get("digest"), esp.get("firma")) != (cap["digest"],
                                                     cap["firma"]):
            raise ValueError(
                f"la divergencia vigente no es contra la captura autorizada: "
                f"{esp.get('digest')!r} != {cap['digest']!r}")
        return
    raise ValueError(
        f"transición no autorizada desde la captura congelada: `pending` → "
        f"{est!r}. Solo se admiten `ok` y `divergent` (§13.4.1)")


def solicitar_terminal(ruta: str, motivo: str, identidad: dict,
                       evidencia: dict, solicitado_en: int,
                       estado_esperado: dict,
                       captura_autorizada: dict | None = None) -> dict:
    """Fase A: anota (o anexa) la causa. NO publica.

    La evidencia viaja CON su motivo: guardar una sola dejaba que un terminal
    `determinism_divergence` se publicara con la evidencia del `silencio_h4`
    que había llegado antes."""
    previo = _leer(ruta)
    if previo is not None:
        verificar_solicitud(previo, ruta)
        cuerpo = dict(previo)
        evidencias = dict(cuerpo.get("evidencias", {}))
        evidencias.setdefault(motivo, evidencia)
        cuerpo["evidencias"] = evidencias
    else:
        cuerpo = {
            "schema_version": C.SCHEMA_TERMINAL,
            "cohorte": identidad.get("cohorte"),
            "contrato": identidad.get("contrato"),
            "commit": identidad.get("commit"),
            "evidencias": {motivo: evidencia},
        }
    # El estado AUTORIZADO se refresca en cada registro (§13.4): si la primera
    # causa lo fijara y una segunda moviera el libro, el request habría
    # autorizado un estado ya viejo y la reanudación lo rechazaría.
    cuerpo["estado_esperado"] = estado_esperado
    # La captura se congela UNA vez, en el primer registro, y NO se refresca:
    # es la ligadura causal con la comparación que estaba corriendo entonces.
    # Refrescarla la borraría justo cuando esa comparación termina —que es el
    # disparador de la publicación—, y no quedaría nada que acreditar.
    if "captura_autorizada" not in cuerpo:
        cuerpo["captura_autorizada"] = captura_autorizada
    cuerpo["solicitado_en"] = int(solicitado_en)
    cuerpo["motivo"] = _ganador(cuerpo["evidencias"])
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
        # §13.7: sin migración. El formato anterior nunca se desplegó, así que
        # aceptarlo solo agregaría una ruta sin probar.
        raise RequestInvalido(
            f"schema {cuerpo.get('schema_version')!r} en {ruta}: se exige "
            f"{C.SCHEMA_TERMINAL} y no hay migración")
    _ganador(cuerpo.get("evidencias", {}))          # registro cerrado


def publicar_terminal(estado_dir: str, estado: str, cuerpo: dict) -> str:
    archivo = C.ARCHIVO_COMPLETADO if estado == C.COMPLETADO \
        else C.ARCHIVO_BLOQUEADO
    ruta = os.path.join(estado_dir, archivo)
    escribir_atomico(ruta, canon({**cuerpo, "estado": estado,
                                  "schema_version": C.SCHEMA_TERMINAL}))
    return ruta


def coincide_residual(req: dict, terminal: dict, identidad: dict,
                     estado_actual: dict, verificacion=None) -> None:
    """§13.6: cuándo un terminal publicado domina un request residual.

    Secuencia NORMATIVA, en este orden. Un request malformado no puede aportar
    un ganador, así que la forma se valida antes que nada."""
    for campo in ("cohorte", "contrato", "commit"):
        if req.get(campo) != identidad.get(campo):
            raise ValueError(
                f"request residual de otra cohorte: {campo} no coincide")
    ganador = _ganador(req.get("evidencias", {}))    # registro cerrado
    if req.get("evidencia") != req["evidencias"][ganador]:
        raise ValueError(
            "request residual incoherente: la evidencia no es la del ganador")
    esperado = req.get("estado_esperado") or {}
    difs = [k for k in set(esperado) | set(estado_actual)
            if esperado.get(k) != estado_actual.get(k)]
    if difs:
        raise ValueError(
            f"request residual autoriza otro estado: difieren {sorted(difs)}")
    # §13.4.1 también acá: sin esto, una caída entre publicar y borrar
    # acreditaba motivo, familia, heads y firma, pero NO que el `ok` o la
    # divergencia vigentes derivaran de la captura que el request congeló.
    exigir_captura_autorizada(req, verificacion)
    familia = (C.BLOQUEADO if ganador in C.MOTIVOS_INTEGRIDAD
               else C.COMPLETADO)
    if terminal.get("estado") != familia or terminal.get("motivo") != ganador:
        raise ValueError(
            f"el terminal publicado ({terminal.get('estado')}, "
            f"{terminal.get('motivo')!r}) no deriva del ganador del request "
            f"({familia}, {ganador!r})")


def archivar(ruta: str) -> None:
    if os.path.exists(ruta):
        os.replace(ruta, ruta + ".archivado")


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
    if solicitud is not None:
        # §13.6, orden NORMATIVO: forma, schema y checksum ANTES de calcular
        # nada. Validar solo en la rama sin terminal dejaba pasar el residual
        # como JSON crudo: un request con el checksum alterado se acreditaba
        # contra el terminal y se ARCHIVABA como si fuera legítimo.
        verificar_solicitud(solicitud, ruta_req)
    if bloqueado is not None and completado is not None:
        raise ValueError(
            f"{estado_dir} tiene completed.json y blocked.json a la vez")
    if bloqueado is not None or completado is not None:
        estado = C.BLOQUEADO if bloqueado is not None else C.COMPLETADO
        cuerpo = bloqueado if bloqueado is not None else completado
        # §13.6 (rev.10+): terminal + request ya NO es contradicción — es el
        # estado normal de una caída entre publicar y borrar. La validación de
        # coincidencia la hace el llamador, que conoce identidad y estado.
        return {"estado": estado, "cuerpo": cuerpo, "residual": solicitud}
    if solicitud is not None:
        return {"estado": "reanudar", "cuerpo": solicitud}
    return None
