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


def construir_almacenes(root: str, mercados=MERCADOS, tf: str = "15m",
                        limite: int | None = None,
                        extra: dict | None = None) -> dict:
    """Construye los almacenes ingiriendo el snapshot versionado (CF-28) y,
    opcionalmente, velas adicionales (push) por mercado.

    `limite` recorta las velas OFRECIDAS (no el ancla): sirve para el gate de
    determinismo de génesis — distintas profundidades de carga deben producir
    el mismo libro sobre el tramo común."""
    almacenes = {}
    dur = TF_MS[tf]
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
    return almacenes


def correr(root: str = ROOT, mercados=MERCADOS, hasta: int | None = None,
           desde: int | None = None, limite: int | None = None,
           ledger_ruta: str | None = None, commit: str = "dev",
           bootstrap_hasta: int | None = None,
           reloj_ms: int | None = None) -> tuple[Motor, Ledger]:
    """Corre el motor por lotes globales de `close_time` M15."""
    m15 = construir_almacenes(root, mercados, "15m", limite)
    h4 = construir_almacenes(root, mercados, "4h", limite)
    mercados_ok = tuple(sorted(set(m15) & set(h4)))
    led = Ledger(ledger_ruta, commit=commit)
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
        if not motor.lote_finalizable(T):
            # CF-29/CF-23: un mercado silencioso no bloquea para siempre —
            # se intenta el watermark global de exchange y se reevalúa.
            motor.watermark_exchange(T)
            if not motor.lote_finalizable(T):
                motor.finalizar_ciclo()
                continue
        motor.procesar_lote(T)
        motor.finalizar_ciclo()
        if motor.cortado:
            break
    # CF-35: sin lote global finalizado posterior a T_corte y con el reloj
    # pasado la gracia, el experimento se cierra administrativamente.
    if not motor.cortado and reloj_ms is not None:
        motor.cerrar_administrativo(reloj_ms)
    return motor, led
