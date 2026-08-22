"""Observador Bot3.v13 — ciclo, barrera, verificación y terminales.

Checkpoint 3 del bloque 2. Cubre §9, §9.0, §9.1, §9.1.1, §12 y §13 del diseño
rev.8.

Las cuatro propiedades que este módulo tiene que garantizar:

1. **ningún ciclo ingiere sin reloj**: `eligibility_time` se muestrea UNA vez,
   antes de tomar la barrera, y si no está no se ingiere nada;
2. **`pending` o `deferred` impiden el corte científico**: dentro de la ZONA DE
   CORTE no se procesa ningún lote hasta que la verificación sea `ok` y
   posterior a toda deferencia. Demorar `completed.json` no alcanzaba — el
   motor emite `abierta_al_corte` y `orden_al_corte` DENTRO del corte, así que
   había que impedir que llegara a cortar;
3. **ningún terminal parcial se publica**: la transición va serializada tras
   una solicitud persistente, y una caída a mitad se reanuda desde la barrera;
4. **la barrera se RETIENE**, no se readquiere: el ciclo la toma al abrir y la
   suelta al cerrar; la captura ocurre adentro. Con un mutex no reentrante,
   readquirirla sería un deadlock.
"""
from __future__ import annotations

import os
import shutil
import threading

from ..v9.contract import (CORTE_ADMIN_GRACIA_MS, CORTE_N_CIERRES, T_CORTE)
from . import binance as B
from . import contrato as C
from . import estado as E
from . import ingesta as I


class BarreraCiclo:
    """Mutex interno del proceso. Distinto del `singleton_lock`, que es un
    `flock` de vida completa y NUNCA se libera para auditar."""

    def __init__(self):
        self._lock = threading.Lock()
        self.retenida = False

    def __enter__(self):
        self._lock.acquire()
        self.retenida = True
        return self

    def __exit__(self, *_):
        self.retenida = False
        self._lock.release()
        return False


# --------------------------------------------------------------------------
# §9.0 — zona de corte
# --------------------------------------------------------------------------
def mercados_vivos(motor) -> int:
    """Mercados con posición u orden viva: cota de cuántos cierres puede
    producir el lote siguiente.

    Es una COTA a demostrar, no una afirmación: exige un gate contra el orden
    completo de fases del motor, `fill+STOP` en el mismo lote incluido."""
    return sum(1 for m in motor.mercados
               if motor.estados[m].posicion is not None
               or motor.estados[m].orden is not None)


def en_zona_de_corte(motor, T: int) -> bool:
    """Deliberadamente conservadora: cubre todo lote en el que el corte
    PODRÍA ocurrir, sin predecir si ocurrirá.

    La condición temporal resta la gracia administrativa, que en realidad
    ocurre DESPUÉS del corte: restarla no representa el instante real de
    cierre, solo garantiza entrar en la zona antes de tiempo."""
    faltan = CORTE_N_CIERRES - len(motor.cierres)
    if faltan <= mercados_vivos(motor):
        return True
    return int(T) >= T_CORTE - CORTE_ADMIN_GRACIA_MS


def puede_procesar_lote(motor, T: int, verificacion) -> dict:
    """Fuera de la zona se procesa aunque la verificación esté `pending`.
    Dentro, no se procesa NADA hasta que sea `ok` y posterior a toda
    deferencia."""
    zona = en_zona_de_corte(motor, T)
    if not zona:
        return {"procesar": True, "zona_de_corte": False, "motivo": None}
    if verificacion.habilita_cierre():
        return {"procesar": True, "zona_de_corte": True, "motivo": None}
    return {"procesar": False, "zona_de_corte": True,
            "motivo": f"verificacion={verificacion.estado}"}


# --------------------------------------------------------------------------
# §9 — captura y verificación
# --------------------------------------------------------------------------
def buffers_no_vacios(m15: dict, h4: dict) -> dict:
    """`_buffer` NO es caché derivada: ante un hueco contiene las velas que
    determinan `prueba_local`, el `detected_at` y el rango del marcador. Una
    barrera con buffers llenos no se puede certificar."""
    pendientes = {}
    for tf, mapa in (("15m", m15), ("4h", h4)):
        for mercado in sorted(mapa):
            n = len(getattr(mapa[mercado], "_buffer", {}) or {})
            if n:
                pendientes[f"{mercado}_{tf}"] = n
    return pendientes


def capturar(barrera: BarreraCiclo, motor, m15: dict, h4: dict,
             doc_silencio, libro, destino: str, ahora: int,
             verificacion) -> dict | None:
    """Captura consistente DENTRO de la barrera ya retenida.

    No la readquiere: el ciclo la tomó al abrir y la sigue reteniendo durante
    fsync, digest y copia. Con un mutex no reentrante, readquirirla sería un
    deadlock."""
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
    digest = E.observer_state_digest(motor, m15, h4, doc_silencio)
    firma = libro.firma()
    os.makedirs(destino, exist_ok=True)
    for mapa in (m15, h4):
        for alm in mapa.values():
            if alm.ruta and os.path.exists(alm.ruta):
                shutil.copy(alm.ruta, os.path.join(
                    destino, os.path.basename(alm.ruta)))
    if libro.ruta and os.path.exists(libro.ruta):
        shutil.copy(libro.ruta, os.path.join(destino, "libro.jsonl"))
    verificacion.pendiente(ahora, digest, firma)
    return {"digest": digest, "firma": firma, "destino": destino,
            "instante": int(ahora)}


def comparar_en_frio(captura: dict, digest_frio: str, firma_fria: str,
                     verificacion, ahora: int) -> bool:
    """Se ejecuta FUERA de la barrera. Divergencia → la cohorte termina en
    `BLOCKED_INTEGRITY(determinism_divergence)`, aunque el motor ya hubiera
    cortado; ningún ciclo posterior la rehabilita."""
    igual = (digest_frio == captura["digest"]
             and firma_fria == captura["firma"])
    if igual:
        verificacion.conforme(ahora, captura["digest"], captura["firma"])
    else:
        verificacion.divergente(
            ahora,
            {"digest": captura["digest"], "firma": captura["firma"]},
            {"digest": digest_frio, "firma": firma_fria})
    return igual


# --------------------------------------------------------------------------
# §9.1.1 — transición terminal serializada
# --------------------------------------------------------------------------
def transicion_terminal(barrera: BarreraCiclo, estado_dir: str, motivo: str,
                        identidad: dict, evidencia: dict, ahora: int,
                        motor, m15: dict, h4: dict, libro,
                        estado_final: str = C.BLOQUEADO) -> dict:
    """`terminal.request` → barrera → prohibir ciclos → fsync → heads y firma
    → publicar → salir.

    `BLOCKED_INTEGRITY` **no ejecuta el cierre científico**: no llama al corte
    del motor, no emite `abierta_al_corte` ni `orden_al_corte` y no toca el
    libro. Solo hace durable lo que ya existe y publica el marcador."""
    ruta_req = os.path.join(estado_dir, C.ARCHIVO_SOLICITUD_TERMINAL)
    heads = E.estado_almacenes(m15, h4)
    E.solicitar_terminal(ruta_req, motivo, identidad, evidencia, ahora,
                         {"heads": heads, "firma": libro.firma()})
    with barrera:
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


def reanudar_si_hace_falta(estado_dir: str) -> dict | None:
    """Al arrancar, ANTES de abrir ningún ciclo. Un `terminal.request` sin
    terminal significa caída a mitad: se reanuda, nunca se ingiere."""
    return E.leer_terminal(estado_dir)


# --------------------------------------------------------------------------
# §12 — el ciclo
# --------------------------------------------------------------------------
def ciclo(fetch, barrera: BarreraCiclo, motor, m15: dict, h4: dict, libro,
          verificacion, reloj_local, silencio=None) -> dict:
    """Un pull = un ciclo = un reloj observado.

    `eligibility_time` se muestrea UNA vez y ANTES de tomar la barrera: si no
    está, el ciclo termina sin ingerir. El motor recibe el reloj LOCAL como
    `processed_at` (CF-34); el de Binance solo filtra velas."""
    parte = {"ingirio": False, "procesados": [], "incidencias": []}
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
        motor.iniciar_ciclo(local)                  # processed_at = reloj LOCAL
        try:
            partes = I.ingerir_ciclo(fetch, m15, h4, elegibilidad)
            parte["ingirio"] = True
            parte["streams"] = partes
            if silencio is not None:
                for p in partes:
                    if p["tf"] != "4h":
                        continue
                    if p["observacion_probatoria"]:
                        silencio.observar(p["mercado"], "4h", p["esperada"],
                                          p["ultimo_t"], elegibilidad)
                    elif p["esperada"] is not None:
                        silencio.resolver(p["mercado"], "4h", p["esperada"])
            for mapa in (m15, h4):
                for alm in mapa.values():
                    alm.sincronizar()
            decision = I.puede_procesar(m15, h4, elegibilidad, elegibilidad)
            parte["decision"] = decision
            if decision["procesar"]:
                for T in motor.cierres_pendientes():
                    permiso = puede_procesar_lote(motor, T, verificacion)
                    if not permiso["procesar"]:
                        parte["bloqueado_por"] = permiso
                        break
                    motor.procesar_lote(T)
                    parte["procesados"].append(T)
            libro.sincronizar()
        finally:
            motor.finalizar_ciclo()
    return parte
