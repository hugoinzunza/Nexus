"""Observador Bot3.v13 — supervisión del árbol de procesos (§20.4).

El wrapper es dueño del árbol; el daemon no. Esa propiedad se materializa en
tres cosas que hay que sostener juntas:

1. **el daemon corre en su PROPIO grupo de procesos** (`setpgid`, `PGID == PID`
   del daemon) y el trabajador lo hereda. El wrapper queda FUERA del grupo, que
   es lo que le permite barrerlo sin matarse a sí mismo;
2. **`supervision.json` registra la identidad de NACIMIENTO** de los tres, y es
   el ÚNICO puntero de liveness. Un wrapper que sale limpio lo BORRA: por eso
   encontrarlo presente tras adquirir el lock significa exactamente que el
   anterior no llegó a clausurar, sin heurística ni códigos de salida —que en
   un `SIGKILL` no existen—;
3. **`supervisor.lock`** es la única prueba de que hay un supervisor vivo. Un
   `pgid` vivo NO lo es: es también lo que se ve cuando la corrida anterior
   está sana, y barrer por eso mataba a la instancia que la red de seguridad
   debía proteger.

La clausura tiene tres niveles porque ninguno cubre lo que cubren los otros: el
cooperativo no corre si al daemon lo matan con `SIGKILL`; el barrido del
wrapper no ocurre si al wrapper lo matan; y la red diferida no puede ejercerse
sin un supervisor nuevo.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import time

from . import contrato as C
from . import diagnostico as G
from . import proceso as P
from .estado import canon, escribir_atomico, sha

SCHEMA_SUPERVISION = 1

CAMPOS_SUPERVISION = {
    "obligatorios": ("schema_version", "cohorte", "contrato", "commit",
                     "wrapper", "daemon", "trabajador", "publicado_en",
                     "checksum"),
    "opcionales": (),
}


class SupervisionInvalida(ValueError):
    """El sidecar no describe un árbol. Fallo cerrado, y NINGUNA señal."""


# --------------------------------------------------------------------------
# el sidecar
# --------------------------------------------------------------------------
def _exigir(cond, mensaje: str) -> None:
    if not cond:
        raise SupervisionInvalida(mensaje)


def _validar_rama(rama, que: str, opcional: bool = False) -> None:
    if rama is None:
        _exigir(opcional, f"{que} ausente")
        return
    _exigir(isinstance(rama, dict), f"{que} no es un objeto: {rama!r}")
    sobran = sorted(set(rama) - set(P.CAMPOS_IDENTIDAD) - {"generacion"})
    _exigir(not sobran, f"{que} con campos fuera del schema: {sobran}")
    for campo in P.CAMPOS_IDENTIDAD:
        _exigir(campo in rama, f"{que} sin `{campo}`")
    for campo in ("pid", "pgid", "inicio"):
        _exigir(type(rama[campo]) is int and rama[campo] > 0,
                f"{que}.{campo} no es entero positivo: {rama[campo]!r}")
    _exigir(isinstance(rama["ejecutable"], str)
            and rama["ejecutable"].startswith("/"),
            f"{que}.ejecutable no es una ruta absoluta: "
            f"{rama['ejecutable']!r}")
    if "generacion" in rama:
        _exigir(type(rama["generacion"]) is int and rama["generacion"] >= 0,
                f"{que}.generacion inválida: {rama['generacion']!r}")


def validar_supervision(cuerpo, ruta: str = "") -> dict:
    donde = f" en {ruta}" if ruta else ""
    _exigir(isinstance(cuerpo, dict), f"supervisión no es un objeto{donde}")
    sobran = sorted(set(cuerpo) - set(CAMPOS_SUPERVISION["obligatorios"]))
    _exigir(not sobran, f"campos fuera del schema{donde}: {sobran}")
    faltan = sorted(set(CAMPOS_SUPERVISION["obligatorios"]) - set(cuerpo))
    _exigir(not faltan, f"campos obligatorios ausentes{donde}: {faltan}")
    _exigir(cuerpo["schema_version"] == SCHEMA_SUPERVISION
            and type(cuerpo["schema_version"]) is int,
            f"schema de supervisión desconocido{donde}")
    _exigir(isinstance(cuerpo["cohorte"], str) and cuerpo["cohorte"].strip(),
            f"`cohorte` vacía{donde}")
    _exigir(isinstance(cuerpo["contrato"], str)
            and len(cuerpo["contrato"]) == 64,
            f"`contrato` no es un SHA-256{donde}")
    _exigir(isinstance(cuerpo["commit"], str) and cuerpo["commit"].strip(),
            f"`commit` vacío{donde}")
    _validar_rama(cuerpo["wrapper"], f"`wrapper`{donde}")
    _validar_rama(cuerpo["daemon"], f"`daemon`{donde}")
    # El trabajador puede no existir todavía: se registra al primer spawn.
    _validar_rama(cuerpo["trabajador"], f"`trabajador`{donde}", opcional=True)
    _exigir(type(cuerpo["publicado_en"]) is int,
            f"`publicado_en` no es entero{donde}")
    esperado = cuerpo["checksum"]
    sin = {k: v for k, v in cuerpo.items() if k != "checksum"}
    _exigir(sha(canon(sin)) == esperado,
            f"checksum no corresponde{donde}: el documento fue alterado")
    return cuerpo


def _sellar(cuerpo: dict) -> dict:
    cuerpo = {k: v for k, v in cuerpo.items() if k != "checksum"}
    cuerpo["checksum"] = sha(canon(cuerpo))
    return cuerpo


def ruta_supervision(estado_dir: str) -> str:
    return os.path.join(estado_dir, C.ARCHIVO_SUPERVISION)


def publicar_supervision(estado_dir: str, identidad: dict, wrapper: dict,
                         daemon: dict, publicado_en: int,
                         trabajador: dict | None = None) -> dict:
    cuerpo = _sellar({
        "schema_version": SCHEMA_SUPERVISION,
        "cohorte": identidad.get("cohorte"),
        "contrato": identidad.get("contrato"),
        "commit": identidad.get("commit"),
        "wrapper": wrapper, "daemon": daemon, "trabajador": trabajador,
        "publicado_en": publicado_en,
    })
    validar_supervision(cuerpo)
    escribir_atomico(ruta_supervision(estado_dir), canon(cuerpo))
    return cuerpo


def leer_supervision(estado_dir: str) -> dict | None:
    ruta = ruta_supervision(estado_dir)
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding="utf-8") as fh:
        try:
            crudo = json.load(fh)
        except ValueError as exc:
            raise SupervisionInvalida(f"{ruta} no es JSON: {exc}")
    return validar_supervision(crudo, ruta)


def retirar_supervision(estado_dir: str) -> None:
    """Al terminar limpiamente se BORRA, no se archiva: es un puntero de
    liveness, no evidencia. Conservarlo produciría barridos diferidos contra
    procesos que ya no existen."""
    ruta = ruta_supervision(estado_dir)
    if os.path.exists(ruta):
        os.unlink(ruta)
        G._fsync_dir(os.path.dirname(ruta) or ".")


def actualizar_trabajador(estado_dir: str, trabajador: dict | None) -> dict:
    """Se hace DURABLE en cada respawn, antes de escribir el primer pedido a
    la generación nueva. Sin esto el sidecar apuntaría a la generación muerta y
    el barrido diferido dejaría vivo justamente al trabajador colgado que
    motiva el nivel 2."""
    vigente = leer_supervision(estado_dir)
    if vigente is None:
        raise SupervisionInvalida(
            f"no hay {C.ARCHIVO_SUPERVISION} que actualizar: el árbol no está "
            f"registrado y su barrido sería imposible")
    cuerpo = _sellar(dict(vigente, trabajador=trabajador))
    validar_supervision(cuerpo)
    escribir_atomico(ruta_supervision(estado_dir), canon(cuerpo))
    return cuerpo


# --------------------------------------------------------------------------
# locks
# --------------------------------------------------------------------------
class LockOcupado(RuntimeError):
    """Lo tiene otro proceso. Para `supervisor.lock` eso significa que hay un
    supervisor VIVO, y este proceso no tiene nada que hacer."""


class Lock:
    """`flock` exclusivo no bloqueante, de vida completa.

    `os.open` con `O_CREAT` y RECIÉN DESPUÉS el `flock`: un `exists()` seguido
    de `open("x")` deja una ventana que otro proceso puede ganar, y truncar
    antes de tener el lock borra el contenido del que sí lo tiene."""

    def __init__(self, ruta: str):
        self.ruta = ruta
        self.fd = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.ruta) or ".", exist_ok=True)
        self.fd = os.open(self.ruta, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            self.fd = None
            raise LockOcupado(f"{self.ruta} lo tiene otro proceso")
        os.ftruncate(self.fd, 0)
        os.write(self.fd, f"{os.getpid()}\n".encode())
        os.fsync(self.fd)
        return self

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)               # el `flock` se libera al cerrar
            self.fd = None
        return False


# --------------------------------------------------------------------------
# §20.4.4 — handshake de publicación
# --------------------------------------------------------------------------
class HandshakeFallido(RuntimeError):
    """El daemon no llegó a quedar registrado. Fallo cerrado."""


def lanzar_daemon(estado_dir: str, identidad: dict, arrancar, ahora: int,
                  cierre_cooperativo_s: float | None = None) -> dict:
    """Lanza `arrancar()` en un hijo con GRUPO propio y publica el sidecar
    ANTES de que el hijo toque nada.

    `arrancar` corre en el HIJO, y solo después de que el padre haya hecho
    durable `supervision.json`. Publicar después dejaba una ventana en la que
    el daemon ya corría sin registro de su grupo — justo la ventana en la que
    una caída del wrapper produce el huérfano que el nivel 3 debe barrer.
    """
    plazo = (C.CIERRE_COOPERATIVO_MS / 1000.0
             if cierre_cooperativo_s is None else cierre_cooperativo_s)
    confirma_r, confirma_w = os.pipe()
    libera_r, libera_w = os.pipe()
    pid = os.fork()
    if pid == 0:                                        # ---- HIJO ----
        codigo = 1
        try:
            os.close(confirma_r)
            os.close(libera_w)
            os.setpgid(0, 0)                            # grupo PROPIO
            os.write(confirma_w, canon({"pid": os.getpid(),
                                        "pgid": os.getpgid(0)}).encode())
            os.close(confirma_w)
            # BLOQUEA sin haber tocado nada: ni un almacén, ni el libro, ni el
            # exchange. Si el padre no libera, este proceso muere sin efectos.
            if not os.read(libera_r, 1):
                os._exit(1)
            os.close(libera_r)
            codigo = arrancar()
        except BaseException:
            codigo = 1
        finally:
            os._exit(codigo if isinstance(codigo, int) else 1)
    # ---- PADRE ----
    os.close(confirma_w)
    os.close(libera_r)
    try:
        crudo = _leer_con_plazo(confirma_r, plazo)
        if not crudo:
            raise HandshakeFallido(
                f"el daemon pid={pid} no confirmó su grupo en {plazo}s: uno "
                f"que no confirma no puede supervisarse")
        informado = json.loads(crudo.decode())
        # Se verifica contra el SISTEMA, no contra lo que el hijo informó: un
        # hijo que reportara mal su grupo haría que el barrido futuro apuntara
        # al grupo equivocado.
        real = P.identidad_de(pid)
        if real is None:
            raise HandshakeFallido(f"el daemon pid={pid} murió al arrancar")
        if real["pgid"] != informado.get("pgid") or real["pgid"] != pid:
            raise HandshakeFallido(
                f"el daemon informó pgid={informado.get('pgid')} y el sistema "
                f"dice {real['pgid']} (se esperaba {pid})")
        cuerpo = publicar_supervision(
            estado_dir, identidad, P.identidad_de(os.getpid()), real, ahora)
        try:
            os.write(libera_w, b"\x01")
        except OSError as exc:
            # El sidecar YA es durable y apunta a un daemon que nunca va a
            # correr. Dejarlo haría que el wrapper siguiente registrara
            # `supervisor_interrumpido` por una corrida que jamás existió.
            retirar_supervision(estado_dir)
            raise HandshakeFallido(
                f"no se pudo liberar al daemon pid={pid}: {exc}")
        return cuerpo
    except BaseException:
        _matar_y_recolectar(pid)
        raise
    finally:
        for fd in (confirma_r, libera_w):
            try:
                os.close(fd)
            except OSError:
                pass


def _leer_con_plazo(fd: int, plazo: float) -> bytes:
    import select
    fin = time.monotonic() + plazo
    datos = b""
    while True:
        resto = fin - time.monotonic()
        if resto <= 0:
            return datos
        listos, _, _ = select.select([fd], [], [], resto)
        if not listos:
            return datos
        trozo = os.read(fd, 4096)
        if not trozo:
            return datos
        datos += trozo
        if datos.rstrip().endswith(b"}"):
            return datos


def _matar_y_recolectar(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    P.recolectar(pid)


# --------------------------------------------------------------------------
# §20.4.1 — clausura cooperativa (nivel 1)
# --------------------------------------------------------------------------
def clausurar_hijo(pid: int, cerrar_entrada, plazo_s: float | None = None,
                   dormir=time.sleep) -> str:
    """EOF → esperar → `SIGKILL` → `waitpid`.

    El EOF va primero para que el caso normal sea una salida limpia del hijo y
    no una señal. El plazo es corto porque el trabajador no tiene nada durable
    que cerrar, así que uno largo solo comería el `ExitTimeOut`. Y el
    `waitpid` va SIEMPRE, incluso tras el `SIGKILL`: si no, el zombi sobrevive
    al padre."""
    plazo = (C.CIERRE_COOPERATIVO_MS / 1000.0 if plazo_s is None else plazo_s)
    cerrar_entrada()
    fin = time.monotonic() + plazo
    while time.monotonic() < fin:
        if P.recolectar(pid, bloqueante=False) is not None:
            return "eof"
        if not P.vivo(pid):
            P.recolectar(pid)
            return "eof"
        dormir(0.01)
    _matar_y_recolectar(pid)
    return "sigkill"


# --------------------------------------------------------------------------
# §20.4.2 — barrido diferido bajo `supervisor.lock`
# --------------------------------------------------------------------------
def barrer_grupo(supervision: dict, plazo_s: float = 5.0,
                 dormir=time.sleep) -> dict:
    """Nivel 2/3: mata el grupo del daemon registrado, tras REVALIDAR.

    Se comparan los CUATRO campos inmediatamente antes de señalar. Si el
    proceso ya no existe no hay nada que barrer; si vive pero es OTRO, fallo
    cerrado y NINGUNA señal — nunca se barre por parecido.

    No se recolecta al trabajador: es NIETO del wrapper, así que al morir el
    daemon queda huérfano y lo recolecta `init`."""
    rama = supervision["daemon"]
    parte = {"pgid": rama["pgid"], "señalado": False, "vivia": False}
    if P.exigir_coincidencia(rama, "daemon"):
        parte["vivia"] = True
    trab = supervision.get("trabajador")
    if trab is not None:
        # Si el PID del trabajador fue reciclado, se falla cerrado igual: el
        # `killpg` alcanzaría a su grupo, y no sabemos cuál es.
        P.exigir_coincidencia(trab, "trabajador")
    if P.grupo_vivo(rama["pgid"]):
        P.matar_grupo(rama["pgid"], signal.SIGKILL)
        parte["señalado"] = True
    # `SIGKILL` es asíncrono: el kernel lo entrega, no lo completa en la
    # llamada. Y si el daemon es hijo NUESTRO —nivel 2— queda ZOMBI hasta que
    # lo recolectemos, y un zombi sigue teniendo entrada de PID, así que
    # `killpg(pgid, 0)` seguiría diciendo que el grupo vive.
    fin = time.monotonic() + plazo_s
    while time.monotonic() < fin:
        P.recolectar(rama["pid"], bloqueante=False)   # no-op si no es hijo
        if not P.grupo_vivo(rama["pgid"]):
            break
        dormir(0.01)
    parte["quedo_vivo"] = P.grupo_vivo(rama["pgid"])
    return parte


def arbitrar(estado_dir: str, supervision: dict, ahora: int) -> dict:
    """§20.4.2.2: qué se publica cuando ya hay un diagnóstico del daemon.

    Ninguna rama sobrescribe en silencio: la primera conserva, la segunda
    archiva antes de publicar, y la tercera no toca nada."""
    ruta = os.path.join(estado_dir, C.ARCHIVO_FALLO_CERRADO)
    identidad = {k: supervision[k] for k in ("cohorte", "contrato", "commit")}
    sha_previo = G.sha_de_bytes(ruta)
    previo = None
    clasificacion = None
    if os.path.exists(ruta):
        try:
            previo = G.validar_diagnostico(G._leer_json(ruta), ruta)
        except (G.DocumentoInvalido, ValueError):
            clasificacion = G.CLAS_CORRUPTO
        else:
            ajeno = any(previo.get(k) != identidad[k] for k in identidad)
            if ajeno:
                clasificacion = G.CLAS_AJENA
            elif previo["codigo"] == 1:
                clasificacion = G.CLAS_PRESERVADO

    parte = {"clasificacion": clasificacion, "incidencia": None,
             "diagnostico": None, "archivado": None}
    if clasificacion is not None:
        # `codigo: 1` de esta identidad, corrupto o ajeno: NO se sobrescribe.
        # El diagnóstico del daemon dice por qué murió, que es la causa raíz;
        # la interrupción del supervisor es consecuencia.
        parte["incidencia"], _ = G.publicar_incidencia(
            estado_dir, supervision, sha_previo, clasificacion, ahora)
        return parte
    if previo is not None:
        # `codigo: 2` de esta identidad: se ARCHIVA —la serie transitoria no se
        # pierde— y se publica la interrupción, porque la severidad no baja.
        parte["archivado"] = G.archivar_diagnostico(estado_dir, previo)
    cuerpo = G.diagnostico(
        identidad, G.MOTIVO_SUPERVISOR, 1, ahora,
        supervision_checksum=supervision["checksum"])
    G.publicar_diagnostico(estado_dir, cuerpo)
    parte["diagnostico"] = cuerpo
    return parte


def barrido_diferido(estado_dir: str, ahora: int) -> dict:
    """§20.4.2.1, orden CONGELADO y recuperable:

    ```
    1. barrer, y COMPROBAR que el grupo desapareció
    2. publicar el diagnóstico o la incidencia
    3. retirar supervision.json + fsync
    4. salir sin lanzar ningún daemon
    ```

    El paso 2 va antes del 3: invertidos queda una ventana sin sidecar y sin
    ningún registro de la interrupción, y un wrapper que entrara ahí arrancaría
    un daemon como si nada hubiera pasado.

    Se llama con `supervisor.lock` YA ADQUIRIDO. Que el lock se adquiera es la
    prueba de que el wrapper anterior murió; que el sidecar exista, la de que
    no llegó a clausurar."""
    supervision = leer_supervision(estado_dir)
    if supervision is None:
        return {"barrido": False, "motivo": "salida limpia anterior"}
    parte = {"barrido": True, "grupo": barrer_grupo(supervision)}
    if parte["grupo"]["quedo_vivo"]:
        raise SupervisionInvalida(
            f"el grupo {parte['grupo']['pgid']} sigue vivo tras el SIGKILL: "
            f"no se publica nada hasta que el árbol desaparezca")
    # ¿Ya se diagnosticó ESTA interrupción? El `supervisor_interrumpido` CITA
    # el sidecar que lo motivó, así que la reanudación no rediagnostica.
    vigente = None
    ruta = os.path.join(estado_dir, C.ARCHIVO_FALLO_CERRADO)
    if os.path.exists(ruta):
        try:
            vigente = G.validar_diagnostico(G._leer_json(ruta), ruta)
        except (G.DocumentoInvalido, ValueError):
            vigente = None
    ya = (vigente is not None
          and vigente.get("motivo") == G.MOTIVO_SUPERVISOR
          and vigente.get("supervision_checksum") == supervision["checksum"])
    if ya:
        parte["arbitraje"] = {"clasificacion": None, "ya_diagnosticado": True}
    else:
        parte["arbitraje"] = arbitrar(estado_dir, supervision, ahora)
    retirar_supervision(estado_dir)
    return parte
