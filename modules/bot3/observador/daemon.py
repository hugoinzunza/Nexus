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


def avanzar_lotes(motor, m15: dict, verificacion, desde_T: int | None,
                  reloj: int | None = None) -> dict:
    """Procesa los lotes pendientes en orden, deteniéndose en el primero que
    no avance —por no ser finalizable o por la zona de corte."""
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
    verificacion.pendiente(ahora, digest, firma)
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
def transicion_terminal(barrera: BarreraCiclo, estado_dir: str, motivo: str,
                        identidad: dict, evidencia: dict, ahora: int,
                        motor, m15: dict, h4: dict, libro,
                        estado_final: str = C.BLOQUEADO) -> dict:
    """`terminal.request` → barrera → PROHIBIR ciclos → fsync → heads y firma
    → publicar → salir.

    `BLOCKED_INTEGRITY` **no ejecuta el cierre científico**: no llama al corte
    del motor, no emite `abierta_al_corte` ni `orden_al_corte` y no toca el
    libro. Solo hace durable lo que ya existe."""
    ruta_req = os.path.join(estado_dir, C.ARCHIVO_SOLICITUD_TERMINAL)
    with barrera:
        # La solicitud se escribe DENTRO de la barrera: si no, dos anexiones
        # concurrentes no estarían serializadas y un ciclo en espera podría
        # colarse entre la solicitud y la publicación.
        barrera.cerrar_para_siempre(motivo)
        E.solicitar_terminal(
            ruta_req, motivo, identidad, evidencia, ahora,
            {"heads": E.estado_almacenes(m15, h4), "firma": libro.firma()})
        for mapa in (m15, h4):
            for alm in mapa.values():
                alm.sincronizar()
        libro.sincronizar()
        cuerpo = {
            "cohorte": identidad.get("cohorte"),
            "contrato": identidad.get("contrato"),
            "commit": identidad.get("commit"),
            "motivo": motivo,
            "evidencia": evidencia,
            "cerrado_en": int(ahora),
            "heads": E.estado_almacenes(m15, h4),
            "firma": libro.firma(),
        }
        ruta = E.publicar_terminal(estado_dir, estado_final, cuerpo)
        os.remove(ruta_req)
    return {"estado": estado_final, "ruta": ruta, "cuerpo": cuerpo}


def reanudar(barrera: BarreraCiclo, estado_dir: str, identidad: dict,
             motor, m15: dict, h4: dict, libro, ahora: int) -> dict | None:
    """Al arrancar, ANTES de abrir ningún ciclo.

    Un terminal publicado prohíbe ciclos. Un `terminal.request` sin terminal
    significa caída a mitad: se VALIDA identidad y se REANUDA la transición
    desde la barrera, nunca se ingiere."""
    leido = E.leer_terminal(estado_dir)
    if leido is None:
        return None
    if leido["estado"] in (C.COMPLETADO, C.BLOQUEADO):
        barrera.cerrar_para_siempre(leido["cuerpo"].get("motivo", "terminal"))
        return leido
    cuerpo = leido["cuerpo"]
    for campo in ("cohorte", "contrato", "commit"):
        if cuerpo.get(campo) != identidad.get(campo):
            raise ValueError(
                f"terminal.request de otra cohorte: {campo} no coincide")
    hecho = transicion_terminal(
        barrera, estado_dir, cuerpo["motivo"], identidad,
        cuerpo.get("evidencia", {}), ahora, motor, m15, h4, libro)
    return {"estado": hecho["estado"], "cuerpo": hecho["cuerpo"],
            "reanudado": True}


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
        elif h4[p["mercado"]].cubre(p["esperada"]) == "vela":
            silencio.resolver(p["mercado"], "4h", p["esperada"])
    silencio.verificar_contra_almacen(h4)


def ciclo(fetch, barrera: BarreraCiclo, motor, m15: dict, h4: dict, libro,
          verificacion, reloj_local, silencio=None, estado_dir=None,
          identidad=None, ultimo_T=None) -> dict:
    """Un pull = un ciclo = un reloj observado.

    `eligibility_time` se muestrea UNA vez y ANTES de tomar la barrera: si no
    está, el ciclo termina sin ingerir. El motor recibe el reloj LOCAL como
    `processed_at` (CF-34); el de Binance solo filtra velas."""
    parte = {"ingirio": False, "procesados": [], "incidencias": [],
             "ultimo_T": ultimo_T}
    if barrera.terminal:
        parte["motivo"] = f"terminal: {barrera.terminal}"
        return parte                                # no se abren ciclos nuevos
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
        if barrera.terminal:                        # se cerró mientras esperaba
            parte["motivo"] = f"terminal: {barrera.terminal}"
            return parte
        partes = I.ingerir_ciclo(fetch, m15, h4, elegibilidad)
        parte["ingirio"] = True
        parte["streams"] = partes
        if silencio is not None:
            _actualizar_silencio(silencio, partes, elegibilidad, h4)
        emitir_huecos_locales(motor, m15, h4, local)
        for mapa in (m15, h4):
            for alm in mapa.values():
                alm.sincronizar()
        decision = I.puede_procesar(m15, h4, elegibilidad, elegibilidad)
        parte["decision"] = decision
        if decision["procesar"]:
            avance = avanzar_lotes(motor, m15, verificacion, ultimo_T,
                                   local)
            parte["procesados"] = avance["procesados"]
            parte["ultimo_T"] = avance["ultimo_T"]
            if avance["bloqueo"]:
                parte["bloqueado_por"] = avance["bloqueo"]
        libro.sincronizar()
        if silencio is not None and estado_dir:
            # La memoria no basta: sin persistir, un reinicio pierde las
            # observaciones y las 72 h nunca producirían un terminal.
            silencio.guardar(os.path.join(estado_dir, C.ARCHIVO_SILENCIO))
    if silencio is not None and estado_dir and identidad is not None:
        ganadora = silencio.ganadora()
        if ganadora is not None:
            parte["terminal"] = transicion_terminal(
                barrera, estado_dir, C.MOTIVO_SILENCIO, identidad,
                ganadora, local, motor, m15, h4, libro)
    return parte
