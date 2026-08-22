"""Observador Bot3.v13 — ingesta, lag y precondición H4 (§6, §11 y §12).

Lo que hace un ciclo con los almacenes: pedir las velas elegibles, ofrecerlas
como `push`, drenar, declarar los huecos locales que el watermark permita, y
decidir si el lote global puede procesarse.

Tres reglas gobiernan esa decisión:

1. **`LAG_MAX` se evalúa por mercado Y por timeframe**: 14 evaluaciones, no
   una. Un fallo en H4 no puede quedar oculto por un M15 fresco;
2. **precondición H4**: no se procesa ningún lote hasta que la grilla H4 esté
   RESUELTA hasta `T` en los siete mercados. `lote_finalizable` solo mira M15
   (`engine.py:293`), así que sin esto el motor decidiría con un rector
   congelado — la divergencia que todo el diseño quiere impedir;
3. **`catch-up`**: con cualquier stream stale se ingiere y se sella, pero NO se
   procesa. No se saltan lotes, no se redefine la frontera y no se reescribe
   nada sellado.

El reloj de elegibilidad se RECIBE: este módulo nunca lo muestrea. Es lo que
garantiza que haya un solo `serverTime` por ciclo.
"""
from __future__ import annotations

from ..v9.contract import GENESIS_H4, TF_MS
from . import binance as B
from . import contrato as C

DUR_H4 = TF_MS["4h"]


def lag(alm, tf: str, elegibilidad: int) -> int:
    """Milisegundos entre el último instante RESUELTO y el reloj del exchange.

    «Resuelto» es vela sellada o marcador de hueco: el almacén avanza
    `ultimo_t` en los dos casos, así que la región `[ancla, ultimo_t]` no tiene
    agujeros pendientes."""
    if alm.ultimo_t is None:
        return 0
    return max(0, int(elegibilidad) - (int(alm.ultimo_t) + TF_MS[tf]))


def streams_stale(m15: dict, h4: dict, elegibilidad: int) -> list[tuple]:
    """Los 14 streams evaluados por separado, en orden canónico.

    Un almacén SIN NACER no es «fresco»: el manifiesto garantiza el
    nacimiento, así que encontrarlo sin ancla significa que algo anterior
    falló. Se marca stale en vez de dejarlo pasar en silencio."""
    stale = []
    for tf, mapa in (("15m", m15), ("4h", h4)):
        for mercado in sorted(mapa):
            alm = mapa[mercado]
            if alm.ultimo_t is None:
                stale.append((mercado, tf, None))
                continue
            atraso = lag(alm, tf, elegibilidad)
            if atraso > C.LAG_MAX_MS[tf]:
                stale.append((mercado, tf, atraso))
    return stale


def grilla_h4_resuelta(alm_h4, T: int) -> int | None:
    """`None` si la grilla H4 está resuelta hasta `T`; si no, el primer cierre
    H4 esperado que falta.

    La comprobación es O(1) y no un barrido de la grilla: el almacén solo
    avanza contiguamente —`drenar` appendea el prefijo continuo y un marcador
    de hueco mueve `ultimo_t` hasta `hasta`—, así que todo `t ≤ ultimo_t` está
    resuelto y nada más allá lo está."""
    ultimo_esperado = ((int(T) - DUR_H4) // DUR_H4) * DUR_H4
    if ultimo_esperado < GENESIS_H4:
        return None                                # aún no hay grilla que exigir
    if alm_h4.ultimo_t is None:
        return GENESIS_H4
    if int(alm_h4.ultimo_t) >= ultimo_esperado:
        return None
    return int(alm_h4.ultimo_t) + DUR_H4


def precondicion_h4(h4: dict, T: int) -> list[tuple]:
    """Mercados cuya grilla H4 NO está resuelta hasta `T`.

    Vacío significa que se puede procesar el lote. Es una precondición sobre
    CUÁNDO llamar a `procesar_lote`, no sobre qué decide el motor: en frío se
    satisface trivialmente y se procesan los mismos lotes."""
    faltan = []
    for mercado in sorted(h4):
        falta = grilla_h4_resuelta(h4[mercado], T)
        if falta is not None:
            faltan.append((mercado, falta))
    return faltan


def puede_procesar(m15: dict, h4: dict, T: int, elegibilidad: int) -> dict:
    """Decisión completa del ciclo para el lote `T`."""
    stale = streams_stale(m15, h4, elegibilidad)
    faltan = precondicion_h4(h4, T)
    return {
        "procesar": not stale and not faltan,
        "catch_up": bool(stale),
        "streams_stale": stale,
        "h4_sin_resolver": faltan,
    }


def ingerir(fetch, mercado: str, tf: str, alm, elegibilidad: int) -> dict:
    """Un mercado y una TF: paginar, ofrecer, drenar y declarar huecos.

    Devuelve el parte del stream, incluida la señal de OBSERVACIÓN PROBATORIA
    para la máquina de silencio: una paginación válida y COMPLETA que no trajo
    la vela esperada. Si la paginación falla, NO hay observación probatoria —
    un error de red no es evidencia de que el mercado enmudeció."""
    ultimo_antes = alm.ultimo_t
    esperada = None if ultimo_antes is None else int(ultimo_antes) + TF_MS[tf]
    velas = B.paginar(fetch, mercado, tf, int(ultimo_antes or 0), elegibilidad)
    alm.ofrecer(velas, "push")
    alm.drenar()
    huecos = []
    while True:
        reg = alm.declarar_hueco_local()
        if reg is None:
            break
        huecos.append(reg)
    # ¿La vela que se esperaba llegó? La paginación fue válida y completa —si
    # no, `paginar` habría fallado cerrado antes de llegar acá.
    #
    # Pero la ausencia solo prueba algo si la vela YA DEBERÍA EXISTIR: una H4
    # todavía abierta falta por definición, y contarla como evidencia iniciaba
    # el silencio antes de `closeTime + 1 + MARGEN_CIERRE`.
    dur = TF_MS[tf]
    exigible = esperada is not None and B.es_elegible(
        esperada, esperada + dur - 1, elegibilidad)
    trajo_esperada = any(v["t"] == esperada for v in velas)
    return {
        "mercado": mercado, "tf": tf,
        "velas": len(velas),
        "huecos": huecos,
        "esperada": esperada,
        "esperada_exigible": exigible,
        "trajo_esperada": bool(esperada is not None and trajo_esperada),
        "observacion_probatoria": bool(exigible and not trajo_esperada),
        "ultimo_t": alm.ultimo_t,
    }


def ingerir_ciclo(fetch, m15: dict, h4: dict, elegibilidad: int) -> list[dict]:
    """Los 14 streams de un ciclo, en orden canónico.

    `elegibilidad` se RECIBE: este módulo no muestrea el reloj, y por eso un
    ciclo no puede terminar usando dos `serverTime` distintos."""
    partes = []
    for tf, mapa in (("15m", m15), ("4h", h4)):
        for mercado in sorted(mapa):
            partes.append(
                ingerir(fetch, mercado, tf, mapa[mercado], elegibilidad))
    return partes
