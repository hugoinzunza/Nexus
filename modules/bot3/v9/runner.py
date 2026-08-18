"""Bot3.v9 — ensamblado: fuentes → almacenes → motor → ledger.

Único punto donde se leen datos. Sin credenciales ni ejecutor: solo klines
públicas versionadas y el push del VPS (CF-22: prioridad versionado > push).
"""
from __future__ import annotations

import json
import os

from . import store as S
from .contract import GENESIS_H4, MERCADOS, TF_MS
from .engine import DUR_M15, Motor
from .ledger import Ledger

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
TF_ARCHIVO = {"15m": "15m", "4h": "4h"}


def leer_versionado(root: str, mercado: str, tf: str) -> list[dict]:
    ruta = os.path.join(root, "data", f"klines_{mercado}_{TF_ARCHIVO[tf]}.json")
    try:
        with open(ruta, encoding="utf-8") as fh:
            filas = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    return filas if isinstance(filas, list) else []


MANIFIESTO = "MANIFIESTO.json"


def ruta_estado(estado_dir: str, mercado: str, tf: str) -> str:
    return os.path.join(estado_dir, f"{mercado}_{tf}.jsonl")


def leer_manifiesto(estado_dir: str) -> set:
    """Almacenes que este estado_dir DECLARA tener sellados. Distingue las
    tres situaciones operacionales (B-6):
      - directorio nuevo (sin manifiesto)  → creación completa;
      - recuperación (declarado y presente) → obligatorio, se rehidrata;
      - directorio parcial (declarado y ausente) → FALLO CERRADO."""
    ruta = os.path.join(estado_dir, MANIFIESTO)
    if not os.path.exists(ruta):
        return set()
    with open(ruta, encoding="utf-8") as fh:
        return set(json.load(fh).get("almacenes", []))


def escribir_manifiesto(estado_dir: str, nombres: set) -> None:
    os.makedirs(estado_dir, exist_ok=True)
    with open(os.path.join(estado_dir, MANIFIESTO), "w", encoding="utf-8") as fh:
        json.dump({"almacenes": sorted(nombres)}, fh,
                  sort_keys=True, separators=(",", ":"))


def construir_almacenes(root: str, mercados=MERCADOS, tf: str = "15m",
                        limite: int | None = None,
                        extra: dict | None = None,
                        estado_dir: str | None = None,
                        ledger=None) -> dict:
    """Construye los almacenes ingiriendo el snapshot versionado (CF-28) y,
    opcionalmente, velas adicionales (push) por mercado.

    `limite` recorta las velas OFRECIDAS (no el ancla): sirve para el gate de
    determinismo de génesis — distintas profundidades de carga deben producir
    el mismo libro sobre el tramo común."""
    almacenes = {}
    dur = TF_MS[tf]
    declarados = leer_manifiesto(estado_dir) if estado_dir else set()
    nuevos: set = set()
    nacidos: list = []
    for mercado in mercados:
        filas = leer_versionado(root, mercado, tf)
        if not filas:
            continue
        filas = sorted(filas, key=lambda r: int(r["t"]))
        if tf == "4h":
            filas = [r for r in filas if int(r["t"]) >= GENESIS_H4]
            ancla = GENESIS_H4
        else:
            ancla = int(filas[0]["t"])
        if estado_dir:
            # RECUPERACIÓN (B-6): si el manifiesto DECLARA este almacén, su
            # archivo es obligatorio (fallo cerrado si desapareció); si no
            # está declarado, es primer arranque y se crea.
            ruta = ruta_estado(estado_dir, mercado, tf)
            nombre = f"{mercado}_{tf}"
            alm = S.Almacen.cargar(mercado, tf, ruta,
                                   requerido=nombre in declarados)
            nuevos.add(nombre)
            if not alm.registros:
                alm.nacer_en(ancla)
                nacidos.append((alm, ancla))
        else:
            alm = S.Almacen(mercado, tf)
            alm.nacer_en(ancla)
        ofrecidas = filas if limite is None else filas[-limite:]
        # El ancla manda: nada anterior puede entrar (CF-22/CF-28).
        alm.ofrecer(ofrecidas, "versionado")
        if extra and mercado in extra:
            alm.ofrecer(extra[mercado], "push")
        alm.drenar()
        while alm.declarar_hueco_local():
            pass
        almacenes[mercado] = alm
    if estado_dir:
        escribir_manifiesto(estado_dir, declarados | nuevos)
    if ledger is not None:
        for alm, ancla in nacidos:           # CF-28: nacimiento del almacén
            ledger.append("nacimiento", mercado=alm.mercado, tf=tf,
                          effective_at=ancla, ruta=alm.ruta)
        for alm in almacenes.values():       # CF-26: incidencias de ingestión
            for inc in alm.incidencias:
                ledger.append(inc["tipo"], mercado=inc["mercado"],
                              tf=inc["tf"], effective_at=inc["t"],
                              id=inc["contenido_sha"])
            alm.incidencias.clear()
    return almacenes


def correr(root: str = ROOT, mercados=MERCADOS, hasta: int | None = None,
           desde: int | None = None, limite: int | None = None,
           ledger_ruta: str | None = None, commit: str = "dev",
           bootstrap_hasta: int | None = None,
           reloj_ms: int | None = None,
           estado_dir: str | None = None) -> tuple[Motor, Ledger]:
    """Corre el motor por lotes globales de `close_time` M15.

    Con `estado_dir`, los almacenes se PERSISTEN y se rehidratan en el
    siguiente arranque (B-6): un reinicio real reutiliza el push ya sellado
    en vez de reconstruirlo."""
    led = Ledger(ledger_ruta, commit=commit)
    m15 = construir_almacenes(root, mercados, "15m", limite,
                              estado_dir=estado_dir, ledger=led)
    h4 = construir_almacenes(root, mercados, "4h", limite,
                             estado_dir=estado_dir, ledger=led)
    mercados_ok = tuple(sorted(set(m15) & set(h4)))
    motor = Motor(m15, h4, mercados_ok, led, bootstrap_hasta=bootstrap_hasta)
    cierres = sorted({int(v["t"]) + DUR_M15
                      for m in mercados_ok for v in m15[m].velas})
    for T in cierres:
        if desde is not None and T < desde:
            continue
        if hasta is not None and T > hasta:
            break
        # CF-34: un ciclo/pull = un reloj observado, compartido por el
        # watermark y por el lote que libera.
        motor.iniciar_ciclo()
        try:
            if not motor.lote_finalizable(T):
                # CF-29/CF-23: un mercado silencioso no bloquea para siempre
                # — se intenta el watermark global y se reevalúa.
                motor.watermark_exchange(T)
                if not motor.lote_finalizable(T):
                    continue
            motor.procesar_lote(T)
        finally:
            # Una excepción no puede dejar el ciclo abierto con el reloj
            # retenido (se propagaría a eventos de ciclos posteriores).
            motor.finalizar_ciclo()
        if motor.cortado:
            break
    # CF-35: sin lote global finalizado posterior a T_corte y con el reloj
    # pasado la gracia, el experimento se cierra administrativamente.
    if not motor.cortado and reloj_ms is not None:
        motor.cerrar_administrativo(reloj_ms)
    return motor, led
