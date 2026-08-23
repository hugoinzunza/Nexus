"""Observador Bot3.v13 — ciclo, barrera, verificación y terminales.

Checkpoint 3 del bloque 2. Cubre §9, §9.0, §9.1, §9.1.1, §12 y §13 del diseño
rev.8.

Todo lo de acá corre contra el `Motor` y el `Ledger` REALES. La versión
anterior usaba un motor sustituto y por eso sus gates no detectaban que
`cierres_pendientes()` no existe en `engine.py`: el primer ciclo real habría
muerto con `AttributeError`.

Las cuatro propiedades que este módulo garantiza:

1. **ningún ciclo ingiere sin reloj**: `eligibility_time` se muestrea UNA vez,
   antes de tomar la barrera, y si no está no se ingiere nada;
2. **`pending` o `deferred` impiden el corte científico**: dentro de la ZONA DE
   CORTE no se procesa ningún lote hasta que la verificación sea `ok` y
   posterior a toda deferencia. Demorar `completed.json` no alcanzaba — el
   motor emite `abierta_al_corte` y `orden_al_corte` DENTRO del corte;
3. **ningún terminal parcial se publica**: la transición va serializada tras
   una solicitud persistente, prohíbe ciclos nuevos y se reanuda tras caída;
4. **la barrera se RETIENE**, no se readquiere.
"""
from __future__ import annotations

import os
import shutil
import contextlib
import threading

from ..v9 import store as S
from ..v9.contract import (CORTE_ADMIN_GRACIA_MS, CORTE_N_CIERRES, T_CORTE,
                           TF_MS)
from ..v9.engine import DUR_M15, Motor
from ..v9.ledger import Ledger
from . import binance as B
from . import contrato as C
from . import estado as E
from . import ingesta as I
from . import silencio as SIL


class CicloProhibido(RuntimeError):
    """Hay una transición terminal en curso o publicada."""


class BarreraCiclo:
    """Mutex interno del proceso, y la bandera que prohíbe abrir ciclos.

    Distinta del `singleton_lock`, que es un `flock` de vida completa y NUNCA
    se libera para auditar."""

    def __init__(self):
        self._lock = threading.Lock()
        self.retenida = False
        self.terminal = False               # nadie abre un ciclo nuevo
        # DISTINTO de `terminal`: hay una causa registrada y la ventana de
        # recolección está abierta. Prohíbe ciclos —una captura nueva podría
        # producir la deferencia que §13.5.0 declara inalcanzable— pero NO
        # prohíbe la fase B ni la comparación fría, que no ingieren (§13.5.1).
        self.cierre_en_curso = False

    def __enter__(self):
        self._lock.acquire()
        self.retenida = True
        return self

    def __exit__(self, *_):
        self.retenida = False
        self._lock.release()
        return False

    def cerrar_para_siempre(self, motivo: str) -> None:
        self.terminal = motivo


# --------------------------------------------------------------------------
# §9.0 — zona de corte
# --------------------------------------------------------------------------
def mercados_vivos(motor) -> int:
    """Cota de cuántos cierres puede producir el lote siguiente.

    Es una COTA a demostrar, no una afirmación: exige un gate contra el orden
    completo de fases del motor, `fill+STOP` en el mismo lote incluido."""
    return sum(1 for m in motor.mercados
               if motor.estados[m].posicion is not None
               or motor.estados[m].orden is not None)


def en_zona_de_corte(motor, T: int) -> bool:
    """Conservadora a propósito: cubre todo lote en el que el corte PODRÍA
    ocurrir, sin predecir si ocurrirá. La condición temporal resta la gracia
    administrativa, que en realidad ocurre DESPUÉS del corte."""
    if CORTE_N_CIERRES - len(motor.cierres) <= mercados_vivos(motor):
        return True
    return int(T) >= T_CORTE - CORTE_ADMIN_GRACIA_MS


def puede_procesar_lote(motor, T: int, verificacion) -> dict:
    zona = en_zona_de_corte(motor, T)
    if not zona:
        return {"procesar": True, "zona_de_corte": False, "motivo": None}
    if verificacion.habilita_cierre():
        return {"procesar": True, "zona_de_corte": True, "motivo": None}
    return {"procesar": False, "zona_de_corte": True,
            "motivo": f"verificacion={verificacion.estado}"}


# --------------------------------------------------------------------------
# §12 — secuencia causal canónica, la misma de `runner.correr`
# --------------------------------------------------------------------------
def emitir_huecos_locales(motor, m15: dict, h4: dict,
                          reloj: int | None = None) -> None:
    """CF-31/CF-34. La fuente son los marcadores SELLADOS en el almacén, no
    los declarados en esta corrida: si el proceso murió entre el sellado y el
    append, al reiniciar el marcador ya está y no vuelve a declararse.
    `event_id` hace la reemisión idempotente."""
    motor.iniciar_ciclo(reloj)
    try:
        for tf_h, mapa in (("15m", m15), ("4h", h4)):
            for mercado in motor.mercados:
                for r in mapa[mercado].registros:
                    if r["tipo"] != "gap" or r.get("motivo") != "local":
                        continue
                    motor._emit("hueco_detectado", r["detected_at"], mercado,
                                finalized_at=r["detected_at"],
                                efectivo=r["desde"], tf=tf_h,
                                desde=r["desde"], hasta=r["hasta"],
                                motivo="local", detected_at=r["detected_at"])
    finally:
        motor.finalizar_ciclo()


def cierres_de(m15: dict, mercados) -> list[int]:
    return sorted({int(v["t"]) + DUR_M15
                   for m in mercados for v in m15[m].velas})


def procesar_lote_canonico(motor, T: int, reloj: int | None = None) -> bool:
    """`recuperar_exchange → lote_finalizable → watermark_exchange →
    reevaluar → procesar_lote`, exactamente el orden de `runner.correr`.

    Devuelve True si el lote se procesó. A diferencia del runner —que recorre
    datos COMPLETOS y puede saltarse un lote con `continue`—, acá el lote no
    finalizable BLOQUEA: en vivo llegan velas después, y saltárselo haría que
    la reconstrucción en frío, que ve el almacén final, procesara un lote que
    el vivo descartó. Esa es justamente la divergencia que se persigue.

    El reloj se INYECTA: si el motor muestreara el suyo, `processed_at` no
    sería el reloj local del ciclo que el observador observó (CF-34)."""
    motor.iniciar_ciclo(reloj)
    try:
        motor.recuperar_exchange(T)
        if not motor.lote_finalizable(T):
            motor.watermark_exchange(T)
            if not motor.lote_finalizable(T):
                return False
        motor.procesar_lote(T)
        return True
    finally:
        motor.finalizar_ciclo()


def watermark_lotes(motor) -> int | None:
    """El último lote FINALIZADO, derivado del motor.

    No se recibe de afuera: si el llamador lo omitiera o lo perdiera en un
    reinicio, `avanzar_lotes` recorrería otra vez toda la historia sobre el
    mismo motor vivo. La única fuente es `motor.lotes_finalizados`."""
    return max(motor.lotes_finalizados) if motor.lotes_finalizados else None


def avanzar_lotes(motor, m15: dict, verificacion,
                  reloj: int | None = None) -> dict:
    """Procesa los lotes pendientes en orden, deteniéndose en el primero que
    no avance —por no ser finalizable o por la zona de corte."""
    desde_T = watermark_lotes(motor)
    procesados, bloqueo = [], None
    for T in cierres_de(m15, motor.mercados):
        if desde_T is not None and T <= desde_T:
            continue
        permiso = puede_procesar_lote(motor, T, verificacion)
        if not permiso["procesar"]:
            bloqueo = {"T": T, **permiso}
            break
        if not procesar_lote_canonico(motor, T, reloj):
            bloqueo = {"T": T, "procesar": False, "motivo": "no finalizable"}
            break
        procesados.append(T)
        if motor.cortado:
            break
    return {"procesados": procesados, "bloqueo": bloqueo,
            "ultimo_T": procesados[-1] if procesados else desde_T}


# --------------------------------------------------------------------------
# §9 — captura y verificación vivo ↔ frío
# --------------------------------------------------------------------------
def buffers_no_vacios(m15: dict, h4: dict) -> dict:
    """`_buffer` NO es caché derivada: ante un hueco contiene las velas que
    determinan `prueba_local`, el `detected_at` y el rango del marcador."""
    pendientes = {}
    for tf, mapa in (("15m", m15), ("4h", h4)):
        for mercado in sorted(mapa):
            n = len(getattr(mapa[mercado], "_buffer", {}) or {})
            if n:
                pendientes[f"{mercado}_{tf}"] = n
    return pendientes


def capturar(barrera: BarreraCiclo, motor, m15: dict, h4: dict, libro,
             silencio, destino: str, ahora: int, verificacion) -> dict | None:
    """Captura consistente DENTRO de la barrera ya retenida. No la readquiere:
    con un mutex no reentrante sería un deadlock."""
    if not barrera.retenida:
        raise RuntimeError(
            "la captura exige la barrera del ciclo RETENIDA, no readquirida")
    pendientes = buffers_no_vacios(m15, h4)
    if pendientes:
        verificacion.diferir(ahora, pendientes)
        return None
    for mapa in (m15, h4):
        for alm in mapa.values():
            alm.sincronizar()
    libro.sincronizar()
    doc = silencio.documento() if silencio is not None else None
    digest = E.observer_state_digest(motor, m15, h4, doc)
    firma = libro.firma()
    os.makedirs(destino, exist_ok=True)
    copias = {}
    for tf, mapa in (("15m", m15), ("4h", h4)):
        for mercado, alm in mapa.items():
            if alm.ruta and os.path.exists(alm.ruta):
                dst = os.path.join(destino, f"{mercado}_{tf}.jsonl")
                shutil.copy(alm.ruta, dst)
                copias[(mercado, tf)] = dst
    ruta_libro = os.path.join(destino, "libro.jsonl")
    if libro.ruta and os.path.exists(libro.ruta):
        shutil.copy(libro.ruta, ruta_libro)
    # El sidecar de silencio VIAJA: decide un terminal futuro y el clon frío
    # no puede reconstruirlo — una ausencia H4 permanente todavía no es un
    # marcador sellado.
    ruta_silencio = None
    if silencio is not None:
        ruta_silencio = os.path.join(destino, C.ARCHIVO_SILENCIO)
        silencio.guardar(ruta_silencio)
    verificacion.pendiente(ahora, digest, firma, destino)
    return {"digest": digest, "firma": firma, "destino": destino,
            "instante": int(ahora), "copias": copias,
            "libro": ruta_libro, "silencio": ruta_silencio,
            "bootstrap_hasta": motor.bootstrap_hasta,
            "mercados": list(motor.mercados)}


def reconstruir_en_frio(captura: dict, commit: str = "dev") -> tuple:
    """Arranque EN FRÍO desde la copia: almacenes recargados con
    `Almacen.cargar` —que revalida la cadena entera—, libro releído desde el
    archivo y motor reconstruido con la MISMA secuencia canónica."""
    m15, h4 = {}, {}
    for (mercado, tf), ruta in captura["copias"].items():
        alm = S.Almacen.cargar(mercado, tf, ruta, requerido=True)
        (m15 if tf == "15m" else h4)[mercado] = alm
    libro = Ledger(captura["libro"], commit=commit)
    motor = Motor(m15, h4, tuple(captura["mercados"]), libro,
                  bootstrap_hasta=captura["bootstrap_hasta"])
    emitir_huecos_locales(motor, m15, h4)
    for T in cierres_de(m15, motor.mercados):
        # `processed_at` es telemetría volátil y queda fuera de la comparación
        # de payload, así que el clon frío puede usar su propio reloj.
        if not procesar_lote_canonico(motor, T):
            break
        if motor.cortado:
            break
    silencio = (_cargar_silencio_frio(captura["silencio"])
                if captura.get("silencio") else None)
    doc = silencio.documento() if silencio is not None else None
    return motor, m15, h4, libro, doc


def captura_desde_copia(verificacion, motor) -> dict:
    """§13.5.1: rearma el manifiesto de la captura desde la copia en disco.

    Tras un reinicio, el `dict` que devolvió `capturar()` se perdió con el
    proceso; lo único que sobrevive es la RUTA guardada en el sidecar. Sin
    esta reconstrucción, el arranque con `pending` no tenía cómo reanudar la
    comparación y la cohorte quedaba detenida para siempre: los ciclos —los
    únicos que capturan— están prohibidos durante la ventana.

    Falla CERRADO si la copia no está o está incompleta: un `pending` que no
    se puede ni certificar ni descartar no autoriza ningún terminal."""
    d = verificacion.detalle
    destino = d.get("copia")
    if not destino or not os.path.isdir(destino):
        raise ValueError(
            f"verificación `pending` cuya copia no existe: {destino!r}. No se "
            f"puede certificar ni descartar el determinismo")
    copias = {}
    for tf in ("15m", "4h"):
        for mercado in motor.mercados:
            ruta = os.path.join(destino, f"{mercado}_{tf}.jsonl")
            if not os.path.exists(ruta):
                raise ValueError(
                    f"copia incompleta: falta {mercado} {tf} en {destino}")
            copias[(mercado, tf)] = ruta
    ruta_libro = os.path.join(destino, "libro.jsonl")
    if not os.path.exists(ruta_libro):
        raise ValueError(f"copia incompleta: falta el libro en {destino}")
    ruta_silencio = os.path.join(destino, C.ARCHIVO_SILENCIO)
    return {"digest": d["digest"], "firma": d["firma"], "destino": destino,
            "instante": int(d["desde"]), "copias": copias,
            "libro": ruta_libro,
            "silencio": ruta_silencio if os.path.exists(ruta_silencio)
            else None,
            "bootstrap_hasta": motor.bootstrap_hasta,
            "mercados": list(motor.mercados)}


def _cargar_silencio_frio(ruta: str):
    """El sidecar copiado se relee con su propia validación, pero la identidad
    se toma del propio archivo: el clon frío no tiene otra fuente."""
    import json
    with open(ruta, encoding="utf-8") as fh:
        crudo = json.load(fh)
    return SIL.Silencio.cargar(ruta, crudo.get("cohorte"),
                               crudo.get("contrato"), crudo.get("commit"))


def verificar_en_frio(captura: dict, verificacion, ahora: int,
                      commit: str = "dev") -> dict:
    """Reconstruye y compara. Se ejecuta FUERA de la barrera."""
    motor, m15, h4, libro, doc = reconstruir_en_frio(captura, commit)
    digest = E.observer_state_digest(motor, m15, h4, doc)
    firma = libro.firma()
    igual = digest == captura["digest"] and firma == captura["firma"]
    if igual:
        verificacion.conforme(ahora, captura["digest"], captura["firma"])
    else:
        verificacion.divergente(
            ahora, {"digest": captura["digest"], "firma": captura["firma"]},
            {"digest": digest, "firma": firma})
    return {"igual": igual, "digest": digest, "firma": firma}


# --------------------------------------------------------------------------
# §9.1.1 — transición terminal serializada
# --------------------------------------------------------------------------
def estado_esperado(estado_dir: str, m15: dict, h4: dict, libro) -> dict:
    """Lo que el request AUTORIZA a publicar: heads, firma del libro y hash de
    los sidecars que DECIDEN el terminal. Sin esto, una caída podía publicar el
    terminal sobre un estado distinto del que se autorizó.

    `verificacion.json` queda FUERA, y no es una relajación: §13.4 pide «el
    hash de CADA sidecar», pero §9.1.3 hace que la comparación fría reescriba
    justamente ese archivo al pasar de `pending` a `ok` — y ese es el
    disparador normal de la fase B. Con el sidecar adentro, la ruta principal
    del diseño falla cerrado SIEMPRE: el request autoriza el hash de `pending`
    y la publicación encuentra el de `ok`. La cohorte no cerraría nunca.

    Lo que el estado autorizado protege es el CONTENIDO del terminal —heads,
    firma y la evidencia de silencio—; la verificación no es contenido sino
    COMPUERTA, y su evolución la gobierna `ventana_cerrada` (§9.1.2), que la
    lee en el momento de publicar y no contra una foto vieja. Ver el gate
    `test_g40_el_sidecar_de_verificacion_no_puede_estar_en_el_estado`."""
    sidecars = {}
    for nombre in (C.ARCHIVO_SILENCIO,):
        ruta = os.path.join(estado_dir, nombre)
        if os.path.exists(ruta):
            with open(ruta, "rb") as fh:
                sidecars[nombre] = E.sha(fh.read().decode("utf-8"))
    return {"heads": E.estado_almacenes(m15, h4), "firma": libro.firma(),
            "sidecars": sidecars}


def registrar_causa(barrera: BarreraCiclo, estado_dir: str, motivo: str,
                    identidad: dict, evidencia: dict, ahora: int,
                    m15: dict, h4: dict, libro,
                    ya_retenida: bool = False,
                    verificacion=None) -> dict | None:
    """FASE A (§9.1.1): marca `cierre_en_curso` y ANEXA la causa. No publica.

    Separar anotar de publicar es lo que hace real la precedencia: con una sola
    fase, dos causas de la misma corrida quedaban serializadas por la barrera y
    la primera publicaba de inmediato — ganaba el reloj, no la tabla.

    `ya_retenida` existe porque el CICLO registra su causa científica sin
    soltar la barrera (§12, orden congelado): reintentar el `acquire` sobre un
    `threading.Lock` no reentrante era un deadlock del proceso entero."""
    ctx = contextlib.nullcontext() if ya_retenida else barrera
    with ctx:
        ya = E.leer_terminal(estado_dir)
        if ya is not None and ya["estado"] in (C.COMPLETADO, C.BLOQUEADO):
            barrera.cerrar_para_siempre(ya["cuerpo"].get("motivo", "terminal"))
            return None                             # publicado = inmutable
        # La marca va ANTES del append: si se cayera entre ambos, el arranque
        # encuentra el estado previo y nada quedó a medio autorizar.
        barrera.cierre_en_curso = True
        return E.solicitar_terminal(
            os.path.join(estado_dir, C.ARCHIVO_SOLICITUD_TERMINAL), motivo,
            identidad, evidencia, ahora,
            estado_esperado(estado_dir, m15, h4, libro),
            E.captura_de(verificacion))


def estado_final_de(motivo: str) -> str:
    """El terminal se DERIVA del motivo ganador; no lo elige el llamador.

    Registro CERRADO (§13.2): un motivo desconocido FALLA CERRADO. El default
    anterior publicaba `COMPLETED` para cualquier cosa que no fuera integridad,
    así que un motivo mal escrito cerraba la cohorte como evaluable."""
    if motivo in C.MOTIVOS_INTEGRIDAD:
        return C.BLOQUEADO
    if motivo in C.MOTIVOS_CIENTIFICOS:
        return C.COMPLETADO
    raise ValueError(
        f"motivo terminal fuera del registro cerrado: {motivo!r}. No se "
        f"deriva un terminal de una causa que nadie definió")


def ventana_cerrada(ganador: str, verificacion) -> bool:
    """§9.1.2: si la ventana de recolección puede cerrarse con este ganador.

    Se decide por el GANADOR ACTUAL, no por el estado de la comparación a
    secas: rev.12 esperaba con cualquier `pending`, incluso cuando el request
    ya contenía el motivo de máxima precedencia — esperar algo que no podía
    cambiar el resultado."""
    estado = getattr(verificacion, "estado", C.VERIF_OK)
    if ganador == C.MOTIVO_DIVERGENCIA:
        return True                     # nada lo supera
    if ganador == C.MOTIVO_SILENCIO:
        # Solo una comparación REALMENTE activa lo retiene. `deferred` no:
        # resolverla exigiría una captura nueva, que vive en un ciclo, y los
        # ciclos están prohibidos durante la ventana — esperar ahí era esperar
        # a un productor inexistente y el bloqueo no salía nunca (rev.13).
        return estado != C.VERIF_PENDIENTE
    if ganador in C.MOTIVOS_CIENTIFICOS:
        if estado == C.VERIF_PENDIENTE:
            return False
        if estado == C.VERIF_DIFERIDA:
            raise ValueError(
                "verificación `deferred` con un corte científico registrado: "
                "estado inalcanzable (§13.5.0). Falla cerrado en vez de "
                "resolverse con una operación que el diseño no contempla")
        return bool(verificacion.habilita_cierre())
    raise ValueError(f"ganador fuera del registro cerrado: {ganador!r}")


def publicar_pendiente(barrera: BarreraCiclo, estado_dir: str, ahora: int,
                       motor, m15: dict, h4: dict, libro,
                       verificacion=None, identidad: dict | None = None,
                       ) -> dict | None:
    """FASE B (§9.1.1): publica el GANADOR del request, con SU evidencia.

    `BLOCKED_INTEGRITY` no ejecuta el cierre científico: no llama al corte del
    motor, no emite `abierta_al_corte` ni `orden_al_corte` y no toca el libro.
    Solo hace durable lo que ya existe."""
    ruta_req = os.path.join(estado_dir, C.ARCHIVO_SOLICITUD_TERMINAL)
    with barrera:
        leido = E.leer_terminal(estado_dir)
        if leido is not None and leido["estado"] in (C.COMPLETADO, C.BLOQUEADO):
            return _cerrar_con_publicado(barrera, leido, estado_dir, ruta_req,
                                         identidad, m15, h4, libro)
        req = E.leer_solicitud(ruta_req)
        if req is None:
            return None
        barrera.cierre_en_curso = True
        # REGLA PREVIA E INCONDICIONAL (§9.1.2): quien entra en la fase B y ve
        # `divergent` anexa la causa ANTES de calcular el ganador. Si no, la
        # condición era inobservable — entre que la comparación fría escribe el
        # sidecar y pide la barrera, la fase B veía `divergent`, daba la
        # ventana por cerrada y publicaba el `silencio_h4` anterior.
        if (verificacion is not None
                and verificacion.estado == C.VERIF_DIVERGENTE
                and C.MOTIVO_DIVERGENCIA not in req.get("evidencias", {})):
            req = E.solicitar_terminal(
                ruta_req, C.MOTIVO_DIVERGENCIA,
                identidad or req, dict(verificacion.detalle), ahora,
                estado_esperado(estado_dir, m15, h4, libro))
            # `captura_autorizada` no se refresca: ya viene congelada del
            # primer registro y es lo que liga esta divergencia a SU captura.
        # §13.4.1: la transición desde la captura congelada se acredita ANTES
        # de decidir nada. Un `ok` de otra comparación no habilita este cierre.
        E.exigir_captura_autorizada(req, verificacion)
        ganador = req["motivo"]
        estado_final = estado_final_de(ganador)     # registro cerrado
        if not ventana_cerrada(ganador, verificacion):
            return {"estado": "espera", "motivo": ganador,
                    "verificacion": getattr(verificacion, "estado", None)}
        # El request AUTORIZA un estado concreto (§13.4). Publicar sobre otro
        # sería cerrar la cohorte con heads o firma distintos de los
        # autorizados.
        _exigir_estado_autorizado(req, estado_dir, m15, h4, libro)
        # La barrera se cierra con el motivo GANADOR, no con el entrante: si
        # no, `barrera.terminal` y el terminal publicado podían discrepar.
        barrera.cerrar_para_siempre(ganador)
        for mapa in (m15, h4):
            for alm in mapa.values():
                alm.sincronizar()
        libro.sincronizar()
        cuerpo = {
            "cohorte": req.get("cohorte"),
            "contrato": req.get("contrato"),
            "commit": req.get("commit"),
            "motivo": ganador,
            "motivos_adicionales": req.get("motivos_adicionales", []),
            "evidencia": req["evidencia"],          # la del GANADOR
            "evidencias": req.get("evidencias", {}),
            "cerrado_en": int(ahora),
            "heads": E.estado_almacenes(m15, h4),
            "firma": libro.firma(),
        }
        ruta = E.publicar_terminal(estado_dir, estado_final, cuerpo)
        # El terminal es la autoridad; el request ya no autoriza nada. Una
        # caída ENTRE publicar y borrar deja los dos, y §13.6 resuelve ese caso
        # comparándolos en vez de declararlo contradicción.
        os.remove(ruta_req)
        E.archivar(os.path.join(estado_dir, C.ARCHIVO_PEDIDO_VERIFICACION))
    return {"estado": estado_final, "ruta": ruta, "cuerpo": cuerpo}


def _exigir_estado_autorizado(req: dict, estado_dir: str, m15: dict, h4: dict,
                              libro) -> None:
    esperado = req.get("estado_esperado") or {}
    real = estado_esperado(estado_dir, m15, h4, libro)
    difs = [k for k in ("heads", "firma", "sidecars")
            if esperado.get(k) != real.get(k)]
    if difs:
        raise ValueError(
            f"terminal.request autoriza otro estado: difieren {sorted(difs)}")


def _cerrar_con_publicado(barrera, leido, estado_dir, ruta_req, identidad,
                          m15, h4, libro) -> dict:
    """§13.6: un terminal publicado con un request residual al lado NO es una
    contradicción — es el estado normal de una caída entre publicar y borrar.

    Se acredita que el residual DERIVA el mismo terminal; si no, falla
    cerrado."""
    barrera.cerrar_para_siempre(leido["cuerpo"].get("motivo", "terminal"))
    barrera.cierre_en_curso = False
    residual = leido.get("residual")
    if residual is not None:
        if identidad is None:
            raise ValueError(
                f"{estado_dir} tiene terminal publicado y terminal.request, y "
                f"no se recibió identidad para acreditar que coinciden")
        E.coincide_residual(residual, leido["cuerpo"], identidad,
                            estado_esperado(estado_dir, m15, h4, libro))
        E.archivar(ruta_req)
    return {"estado": leido["estado"], "ruta": None,
            "cuerpo": leido["cuerpo"], "ya_existia": True}


def transicion_terminal(barrera: BarreraCiclo, estado_dir: str, motivo: str,
                        identidad: dict, evidencia: dict, ahora: int,
                        motor, m15: dict, h4: dict, libro,
                        verificacion=None) -> dict:
    """Anota la causa y dispara la fase B. Para un solo causante."""
    registrar_causa(barrera, estado_dir, motivo, identidad, evidencia, ahora,
                    m15, h4, libro, verificacion=verificacion)
    hecho = publicar_pendiente(barrera, estado_dir, ahora, motor, m15, h4,
                               libro, verificacion, identidad)
    if hecho is None:                               # ya había terminal
        ya = E.leer_terminal(estado_dir)
        return {"estado": ya["estado"], "ruta": None, "cuerpo": ya["cuerpo"],
                "ya_existia": True}
    return hecho


def reanudar(barrera: BarreraCiclo, estado_dir: str, identidad: dict,
             motor, m15: dict, h4: dict, libro, ahora: int,
             verificacion=None) -> dict | None:
    """Al arrancar, ANTES de abrir ningún ciclo (§13.5).

    Un terminal publicado prohíbe ciclos. Un `terminal.request` sin terminal
    significa caída a mitad: se VALIDA identidad y estado autorizado, y el
    ARRANQUE dispara la fase B —el tercer disparador de §9.1.3—, nunca ingiere.

    La verificación se RECARGA DESDE DISCO: el objeto en memoria se perdió con
    la caída, y confiar en uno nuevo —que nace `ok`— dejaba que el arranque
    publicara el `COMPLETED` que antes se había rechazado."""
    leido = E.leer_terminal(estado_dir)
    if leido is None:
        return None
    ruta_req = os.path.join(estado_dir, C.ARCHIVO_SOLICITUD_TERMINAL)
    if leido["estado"] in (C.COMPLETADO, C.BLOQUEADO):
        return _cerrar_con_publicado(barrera, leido, estado_dir, ruta_req,
                                     identidad, m15, h4, libro)
    cuerpo = leido["cuerpo"]
    for campo in ("cohorte", "contrato", "commit"):
        if cuerpo.get(campo) != identidad.get(campo):
            raise ValueError(
                f"terminal.request de otra cohorte: {campo} no coincide")
    _exigir_estado_autorizado(cuerpo, estado_dir, m15, h4, libro)
    # Hay causa registrada: ni ciclos ni ingesta hasta que la ventana cierre.
    barrera.cierre_en_curso = True
    if verificacion is None:
        ruta_v = os.path.join(estado_dir, C.ARCHIVO_VERIFICACION)
        if not os.path.exists(ruta_v):
            # §13.4.2: fallo cerrado para CUALQUIER ganador, no solo los
            # científicos. Sin sidecar no se sabe si hay una comparación
            # `pending` que deba RETENER un `silencio_h4`, y un objeto recién
            # construido diría `ok` — justo la retención que se saltearía.
            raise ValueError(
                f"reanudación sin {ruta_v}: no se puede acreditar el estado "
                f"de la comparación fría")
        verificacion = E.Verificacion.cargar(ruta_v)     # valida §13.4.2
    hecho = publicar_pendiente(barrera, estado_dir, ahora, motor, m15, h4,
                               libro, verificacion, identidad)
    if hecho is not None and hecho["estado"] != "espera":
        return {"estado": hecho["estado"], "cuerpo": hecho["cuerpo"],
                "reanudado": True}
    if verificacion.estado != C.VERIF_PENDIENTE:
        # Espera sin comparación activa: no hay productor que la resuelva.
        raise ValueError(
            f"reanudación detenida sin comparación activa "
            f"(verificacion={verificacion.estado!r}): nadie despertaría la "
            f"fase B")
    # §13.5.1: el ARRANQUE **completa** la comparación, no la espera. Quedarse
    # esperando era detener la cohorte para siempre: la comparación fría no es
    # un ciclo y nadie más la iba a retomar.
    captura = captura_desde_copia(verificacion, motor)
    resultado = verificar_y_reaccionar(barrera, captura, verificacion, ahora,
                                       estado_dir, identidad, motor, m15, h4,
                                       libro, commit=identidad.get("commit",
                                                                   "dev"))
    terminal = resultado.get("terminal")
    if terminal is None or terminal.get("estado") == "espera":
        raise ValueError(
            f"la comparación fría terminó ({verificacion.estado}) y la fase B "
            f"no publicó: {terminal!r}")
    return {"estado": terminal["estado"], "cuerpo": terminal["cuerpo"],
            "reanudado": True, "verificacion": verificacion.estado,
            "comparacion": resultado}


# --------------------------------------------------------------------------
# §12 — el ciclo
# --------------------------------------------------------------------------
def _actualizar_silencio(silencio, partes, elegibilidad, h4):
    """Solo la ausencia EXIGIBLE es evidencia, y solo la llegada REAL de la
    vela resuelve. Resolver ante cualquier observación no probatoria dejaba
    que una regresión de `serverTime` —que vuelve la vela no exigible— marcara
    resuelto un silencio sin que la vela hubiera llegado."""
    for p in partes:
        if p["tf"] != "4h" or p["esperada"] is None:
            continue
        if p["observacion_probatoria"]:
            silencio.observar(p["mercado"], "4h", p["esperada"],
                              p["ultimo_t"], elegibilidad)
        elif p.get("trajo_esperada"):
            # Gobierna el HECHO de que la respuesta trajo la vela, no que el
            # almacén la tenga: un backfill posterior al sellado del hueco
            # queda como `vela_no_incorporada` y `cubre()` nunca diría "vela",
            # así que el silencio no se resolvería nunca.
            silencio.resolver(p["mercado"], "4h", p["esperada"])
    silencio.verificar_contra_almacen(h4)


def cerrar_si_corresponde(barrera: BarreraCiclo, estado_dir: str,
                          identidad: dict, motor, m15: dict, h4: dict, libro,
                          verificacion, ahora: int) -> dict | None:
    """Conecta los terminales CIENTÍFICOS, que sin esto quedaban a cargo de un
    `main` inexistente:

    - la verificación gobierna ANTES de tocar el motor: `cerrar_administrativo`
      EMITE `abierta_al_corte`, `orden_al_corte`, `degradacion_de_cobertura` y
      `corte_administrativo`. Llamarlo con la verificación en `pending`,
      `deferred` o `divergent` reproducía exactamente el cierre científico que
      la zona de corte existe para impedir;
    - CF-35: con la verificación `ok`, se intenta en cada ciclo; es un no-op
      salvo que el reloj pase `T_corte + gracia` sin lote posterior;
    - si el motor CORTÓ, se publica `COMPLETED`. Si el corte ya había ocurrido
      antes y la verificación aún no habilita, se espera al ciclo siguiente:
      el corte no se pierde.
    """
    if not verificacion.habilita_cierre():
        return ({"estado": "espera",
                 "motivo": f"verificacion={verificacion.estado}"}
                if motor.cortado else None)
    # El corte administrativo va DENTRO de un ciclo con el reloj YA observado:
    # si no, `_asegurar_ciclo` muestrea `motor.reloj()` y sus eventos llevan
    # un `processed_at` distinto del ciclo que los produjo (CF-34).
    motor.iniciar_ciclo(int(ahora))
    try:
        motor.cerrar_administrativo(int(ahora))
    finally:
        motor.finalizar_ciclo()
    if not motor.cortado:
        return None
    # Devuelve la CAUSA; publicar es del ciclo, que junta todas las del turno.
    # El motivo sale del MOTOR (`muestra` | `tiempo` | `administrativo`); el
    # default `"corte"` anterior era fail-open — un motor cortado sin motivo
    # habría anotado una causa que el registro cerrado no define.
    motivo = getattr(motor, "motivo_corte", None)
    if motivo not in C.MOTIVOS_CIENTIFICOS:
        raise ValueError(
            f"el motor cortó con un motivo que no es científico: {motivo!r}")
    return {"estado": "causa", "motivo": motivo,
            "evidencia": {"cierres": len(motor.cierres),
                          "lotes_finalizados": len(motor.lotes_finalizados)}}


def verificar_y_reaccionar(barrera: BarreraCiclo, captura: dict,
                           verificacion, ahora: int, estado_dir: str,
                           identidad: dict, motor, m15: dict, h4: dict,
                           libro, commit: str = "dev") -> dict:
    """Verifica en frío y, si diverge, DISPARA el terminal. Antes se marcaba
    la divergencia en el sidecar y ahí quedaba."""
    resultado = verificar_en_frio(captura, verificacion, ahora, commit)
    if not resultado["igual"]:
        # Dos fases, igual que el ciclo: si otra causa del mismo turno ya está
        # anotada, la precedencia decide; y `verificacion` ya quedó en
        # `divergent`, así que un `COMPLETED` pendiente no puede publicarse.
        registrar_causa(
            barrera, estado_dir, C.MOTIVO_DIVERGENCIA, identidad,
            {"esperado": {"digest": captura["digest"],
                          "firma": captura["firma"]},
             "obtenido": {"digest": resultado["digest"],
                          "firma": resultado["firma"]}},
            ahora, m15, h4, libro)
        resultado["terminal"] = publicar_pendiente(
            barrera, estado_dir, ahora, motor, m15, h4, libro, verificacion,
            identidad)
    else:
        # §9.1.3, segundo disparador: la comparación fría intenta la fase B en
        # TODAS sus salidas, no solo al divergir. Al pasar de `pending` a `ok`
        # no hay causa nueva que registrar, así que sin esto nadie volvería a
        # publicar y la cohorte quedaba detenida con la ventana abierta.
        if os.path.exists(os.path.join(estado_dir,
                                       C.ARCHIVO_SOLICITUD_TERMINAL)):
            resultado["terminal"] = publicar_pendiente(
                barrera, estado_dir, ahora, motor, m15, h4, libro,
                verificacion, identidad)
    return resultado


def atender_pedido_verificacion(barrera: BarreraCiclo, estado_dir: str,
                                motor, m15: dict, h4: dict, libro, silencio,
                                verificacion, ahora: int) -> dict | None:
    """§12: se atiende con la barrera YA RETENIDA, y solo si el motor NO cortó.

    Capturar con un corte científico ya alcanzado podía encontrar buffers y
    dejar la verificación en `deferred` justo antes de registrar la causa — la
    combinación que §13.5.0 declara inalcanzable y que ahí traba la cohorte."""
    ruta = os.path.join(estado_dir, C.ARCHIVO_PEDIDO_VERIFICACION)
    if not os.path.exists(ruta):
        return None
    destino = os.path.join(estado_dir, "scratch", f"captura_{int(ahora)}")
    return capturar(barrera, motor, m15, h4, libro, silencio, destino, ahora,
                    verificacion)


def ciclo(fetch, barrera: BarreraCiclo, motor, m15: dict, h4: dict, libro,
          verificacion, reloj_local, silencio=None, estado_dir=None,
          identidad=None) -> dict:
    """Un pull = un ciclo = un reloj observado.

    `eligibility_time` se muestrea UNA vez y ANTES de tomar la barrera: si no
    está, el ciclo termina sin ingerir. El motor recibe el reloj LOCAL como
    `processed_at` (CF-34); el de Binance solo filtra velas."""
    parte = {"ingirio": False, "procesados": [], "incidencias": [],
             "ultimo_T": watermark_lotes(motor)}
    if barrera.terminal:
        parte["motivo"] = f"terminal: {barrera.terminal}"
        return parte                                # no se abren ciclos nuevos
    if barrera.cierre_en_curso:
        # Ventana de recolección abierta: la fase B y la comparación fría
        # siguen —no ingieren—, pero un ciclo sí, y una captura suya podría
        # producir la deferencia que §13.5.0 declara inalcanzable.
        parte["motivo"] = "cierre en curso: ventana de recolección abierta"
        return parte
    try:
        elegibilidad = B.eligibility_time(fetch)
    except B.RelojIndisponible as exc:
        parte["motivo"] = f"sin reloj: {exc}"
        return parte                                # NO se ingiere nada
    parte["eligibility_time"] = elegibilidad
    local = reloj_local()
    inc = B.deriva(elegibilidad, local)
    if inc:
        parte["incidencias"].append(inc)
    with barrera:
        # LAS DOS banderas se REVUELVEN adentro del mutex. Comprobar solo
        # `terminal` dejaba una carrera real: si la fase A marcaba
        # `cierre_en_curso` mientras este ciclo esperaba el lock, el ciclo
        # entraba igual y movía almacenes y libro DESPUÉS del estado que el
        # request ya había autorizado.
        if barrera.terminal:                        # se cerró mientras esperaba
            parte["motivo"] = f"terminal: {barrera.terminal}"
            return parte
        if barrera.cierre_en_curso:
            parte["motivo"] = "cierre en curso: ventana de recolección abierta"
            return parte
        partes = I.ingerir_ciclo(fetch, m15, h4, elegibilidad)
        parte["ingirio"] = True
        parte["streams"] = partes
        if silencio is not None:
            _actualizar_silencio(silencio, partes, elegibilidad, h4)
        # §5: el marcador tiene que ser DURABLE antes de que exista el evento
        # que lo cita. El `fsync` va ANTES de emitir, no después.
        for mapa in (m15, h4):
            for alm in mapa.values():
                alm.sincronizar()
        emitir_huecos_locales(motor, m15, h4, local)
        decision = I.puede_procesar(m15, h4, elegibilidad, elegibilidad)
        parte["decision"] = decision
        if decision["procesar"]:
            avance = avanzar_lotes(motor, m15, verificacion, local)
            parte["procesados"] = avance["procesados"]
            parte["ultimo_T"] = avance["ultimo_T"]
            if avance["bloqueo"]:
                parte["bloqueado_por"] = avance["bloqueo"]
        libro.sincronizar()
        if silencio is not None and estado_dir:
            # La memoria no basta: sin persistir, un reinicio pierde las
            # observaciones y las 72 h nunca producirían un terminal.
            silencio.guardar(os.path.join(estado_dir, C.ARCHIVO_SILENCIO))
        # ORDEN CONGELADO del final del ciclo (§12, rev.14/15), con la barrera
        # YA RETENIDA y sin readquirirla —el mutex no es reentrante—:
        #
        #   si el motor cortó → marcar, anexar la causa, y NO atender ningún
        #   verify.request nuevo; si no cortó → atender el verify.request.
        #
        # Al revés, esta secuencia era legítima y trababa la cohorte: se
        # atendía el pedido, la captura encontraba buffers, la verificación
        # pasaba a `deferred`, y recién ahí se registraba la causa científica.
        causas = []
        if estado_dir and identidad is not None:
            if silencio is not None:
                ganadora = silencio.ganadora()
                if ganadora is not None:
                    causas.append(C.MOTIVO_SILENCIO)
                    registrar_causa(barrera, estado_dir, C.MOTIVO_SILENCIO,
                                    identidad, ganadora, local, m15, h4,
                                    libro, ya_retenida=True,
                                    verificacion=verificacion)
            cierre = cerrar_si_corresponde(
                barrera, estado_dir, identidad, motor, m15, h4, libro,
                verificacion, local)
            if cierre is not None and cierre.get("estado") == "espera":
                parte["terminal"] = cierre
            elif cierre is not None:
                causas.append(cierre["motivo"])
                registrar_causa(barrera, estado_dir, cierre["motivo"],
                                identidad, cierre["evidencia"], local, m15,
                                h4, libro, ya_retenida=True,
                                verificacion=verificacion)
            if not motor.cortado:
                parte["captura"] = atender_pedido_verificacion(
                    barrera, estado_dir, motor, m15, h4, libro, silencio,
                    verificacion, local)
    # FUERA de la barrera: primer disparador de §9.1.3 — el ciclo que registra
    # una causa intenta la fase B apenas la suelta.
    if causas:
        parte["causas"] = causas
        parte["terminal"] = publicar_pendiente(
            barrera, estado_dir, local, motor, m15, h4, libro, verificacion,
            identidad) or parte.get("terminal")
    return parte
