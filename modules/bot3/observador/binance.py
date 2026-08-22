"""Observador Bot3.v13 — cliente PÚBLICO de Binance (§10 del diseño rev.8).

Solo lectura y sin credenciales: `klines` y `serverTime`. Sin llaves, la falla
máxima posible es no obtener datos.

Tres cosas se congelan acá porque, sueltas, permiten dos implementaciones
honestas con resultados distintos:

1. **el reloj de elegibilidad es el de Binance**, muestreado una vez por ciclo.
   Si no está disponible NO se ingiere nada en ese ciclo: nunca hay fallback
   silencioso al reloj del Mac. La deriva contra el reloj local se registra
   como incidencia operacional —un Mac con la hora rota tiene que verse—, pero
   no decide nada;
2. **la paginación**, alineada a la grilla y con progreso estricto. Una página
   llena que no avanza es fallo cerrado, nunca un loop;
3. **el mapeo OHLCV**, por la MISMA ruta que el cargador del snapshot. Si el
   push serializara distinto para la misma vela, el solape produciría una
   tormenta de `vela_revisada` sobre datos idénticos desde el primer ciclo.

El acceso a la red se INYECTA (`fetch`): este módulo no abre sockets por su
cuenta, y por eso se puede probar entero sin tocar Binance.
"""
from __future__ import annotations

import math

from ..v9.contract import TF_MS
from . import contrato as C

# Índices de la fila de klines de Binance. Explícitos a propósito: un mapeo
# posicional implícito es exactamente la clase de detalle que diverge.
I_OPEN_TIME = 0
I_OPEN = 1
I_HIGH = 2
I_LOW = 3
I_CLOSE = 4
I_VOLUME = 5
I_CLOSE_TIME = 6
CAMPOS_MINIMOS = 7


class RelojIndisponible(RuntimeError):
    """Sin `eligibility_time` no se ingiere: no hay fallback al reloj local."""


class PaginaInvalida(ValueError):
    """La página se descarta ENTERA; no se ofrece nada de ella."""


class SinProgreso(RuntimeError):
    """Una página llena que no avanza sería un loop infinito."""


def eligibility_time(fetch) -> int:
    """`serverTime` de Binance, muestreado UNA vez por ciclo.

    Es el único reloj que decide qué vela es elegible. El reloj local se usa
    para `processed_at` (telemetría CF-34) y para medir deriva, nunca para
    filtrar."""
    try:
        cuerpo = fetch(C.ENDPOINT_TIME, None)
    except Exception as exc:                       # noqa: BLE001
        raise RelojIndisponible(f"no se pudo obtener serverTime: {exc}")
    # Cualquier respuesta que no sea un objeto —lista, cadena, número— es
    # indisponibilidad, no un `AttributeError` a mitad del ciclo.
    if not isinstance(cuerpo, dict):
        raise RelojIndisponible(
            f"serverTime no vino en un objeto: {type(cuerpo).__name__}")
    valor = cuerpo.get("serverTime")
    if type(valor) is not int or valor <= 0:
        raise RelojIndisponible(f"serverTime inválido: {valor!r}")
    return valor


def deriva(elegibilidad: int, local: int) -> dict | None:
    """Incidencia operacional si el reloj del Mac se aparta. No decide nada:
    solo hace visible una hora rota en el host."""
    delta = abs(int(elegibilidad) - int(local))
    if delta <= C.DERIVA_MAX_MS:
        return None
    return {"tipo": "deriva_de_reloj", "delta_ms": delta,
            "eligibility_time": int(elegibilidad), "processed_at": int(local),
            "umbral_ms": C.DERIVA_MAX_MS}


def es_elegible(open_time: int, close_time: int, elegibilidad: int) -> bool:
    """`eligibility_time ≥ closeTime + 1 + MARGEN_CIERRE`.

    La vela en curso se descarta SIEMPRE: `closeTime` de Binance es el último
    milisegundo del intervalo, así que `+1` es el instante en que cerró."""
    return int(elegibilidad) >= int(close_time) + 1 + C.MARGEN_CIERRE_MS


def normalizar_fila(fila, tf: str) -> dict:
    """Mapeo EXPLÍCITO índice → campo, con `t = openTime`.

    Los numéricos se parsean con `float(...)` sobre la cadena de Binance, que
    es la misma ruta por la que el snapshot versionado obtuvo sus valores: el
    round-trip por `repr` más corto da el mismo float64, y por eso `ser_vela`
    produce los mismos bytes para la misma vela venga de donde venga."""
    if not isinstance(fila, (list, tuple)) or len(fila) < CAMPOS_MINIMOS:
        raise PaginaInvalida(f"fila incompleta: {fila!r}")
    dur = TF_MS[tf]
    try:
        t = int(fila[I_OPEN_TIME])
        cierre = int(fila[I_CLOSE_TIME])
        vela = {
            "t": t,
            "o": float(fila[I_OPEN]),
            "h": float(fila[I_HIGH]),
            "l": float(fila[I_LOW]),
            "c": float(fila[I_CLOSE]),
            "v": float(fila[I_VOLUME]),
        }
    except (TypeError, ValueError) as exc:
        raise PaginaInvalida(f"fila no numérica: {exc}")
    if t % dur:
        raise PaginaInvalida(f"`t` {t} desalineado de la grilla de {tf}")
    # `float("nan")` y `float("inf")` PARSEAN. Sin este control quedarían
    # sellados en la cadena de hashes del almacén, para siempre.
    for campo in ("o", "h", "l", "c", "v"):
        if not math.isfinite(vela[campo]):
            raise PaginaInvalida(
                f"valor no finito en {t}: {campo}={vela[campo]!r}")
    if vela["h"] < vela["l"]:
        raise PaginaInvalida(
            f"OHLC incoherente en {t}: high {vela['h']} < low {vela['l']}")
    for campo in ("o", "c"):
        if not (vela["l"] <= vela[campo] <= vela["h"]):
            raise PaginaInvalida(
                f"OHLC incoherente en {t}: {campo}={vela[campo]} fuera de "
                f"[{vela['l']}, {vela['h']}]")
    if vela["v"] < 0:
        raise PaginaInvalida(f"volumen negativo en {t}: {vela['v']}")
    if cierre - t + 1 != dur:
        # El intervalo de la fila NO es el pedido: pedir 15m y recibir 1h
        # pasaría inadvertido si solo se mirara `openTime`.
        raise PaginaInvalida(
            f"intervalo distinto del pedido en {t}: "
            f"{cierre - t + 1} ms != {dur} ms de {tf}")
    vela["close_time"] = cierre
    return vela


def validar_simbolo(mercado: str) -> None:
    """Perpetuo USD-M del universo congelado. El endpoint es `fapi`, pero el
    símbolo también se verifica: pedir un par ajeno traería otra serie."""
    if mercado not in C.UNIVERSO:
        raise PaginaInvalida(f"{mercado} no pertenece al universo congelado")
    if not mercado.endswith("USDT"):
        raise PaginaInvalida(f"{mercado} no es un perpetuo USD-M")


def inicio_paginacion(ultimo_t: int, tf: str) -> int:
    """`ultimo_t − (RESOLAPE − 1)·dur`, ALINEADO a la grilla.

    Incluye exactamente `RESOLAPE` velas ya selladas, la última incluida. Se
    re-piden a propósito: si el exchange revisa una vela, tiene que aparecer
    como `vela_revisada` (CF-26) y no pasar inadvertida."""
    # El TIPO se valida ANTES de convertir: `int(...)` truncaba en silencio
    # (`900000.5` → `900000`), aceptaba cadenas y convertía `False` en `0`.
    # `type(...) is int` además excluye `bool`, que es subclase de `int`.
    if type(ultimo_t) is not int:
        raise PaginaInvalida(
            f"`ultimo_t` debe ser entero, no {type(ultimo_t).__name__}: "
            f"{ultimo_t!r}")
    dur = TF_MS[tf]
    if ultimo_t < 0:
        raise PaginaInvalida(f"`ultimo_t` negativo: {ultimo_t}")
    if ultimo_t % dur:
        # Un `ultimo_t` fuera de la grilla desplazaría TODA la paginación.
        raise PaginaInvalida(
            f"`ultimo_t` {ultimo_t} desalineado de la grilla de {tf}")
    return max(0, ultimo_t - (C.RESOLAPE - 1) * dur)


def paginar(fetch, mercado: str, tf: str, ultimo_t: int,
            elegibilidad: int, limite: int | None = None) -> list[dict]:
    """Recorre desde `inicio_paginacion` hasta la PÁGINA VACÍA final.

    Devuelve solo velas elegibles. Cualquier página inválida —orden, grilla,
    duplicado interno o intervalo distinto— se descarta ENTERA y falla cerrado:
    no se ofrece nada de ella.
    """
    validar_simbolo(mercado)
    dur = TF_MS[tf]
    limite = limite or C.LIMITE_PAGINA
    inicio = inicio_paginacion(ultimo_t, tf)
    velas: list[dict] = []
    vistos: set[int] = set()
    while True:
        pagina = fetch(C.ENDPOINT_KLINES, {
            "symbol": mercado, "interval": tf, "startTime": inicio,
            "limit": limite})
        # El TIPO se valida ANTES de la vacuidad: `None`, `{}`, `""`, `0` y
        # `False` son falsy y se leían como «página vacía válida y completa»,
        # que es justo lo que la máquina de silencio toma por evidencia. Solo
        # una LISTA o TUPLA vacía es un fin legítimo.
        if not isinstance(pagina, (list, tuple)):
            raise PaginaInvalida(
                f"respuesta que no es una lista: {type(pagina).__name__}")
        if not pagina:
            return velas                            # página vacía → fin
        normalizadas = []
        previo = None
        for fila in pagina:
            vela = normalizar_fila(fila, tf)
            if vela["t"] < inicio:
                # La respuesta no corresponde al pedido: devolver velas
                # anteriores al `startTime` es otra serie, no la nuestra.
                raise PaginaInvalida(
                    f"vela {vela['t']} anterior al `startTime` {inicio}")
            if previo is not None and vela["t"] <= previo:
                raise PaginaInvalida(
                    f"fuera de orden o duplicada dentro de la página: "
                    f"{vela['t']} tras {previo}")
            if vela["t"] in vistos:
                raise PaginaInvalida(
                    f"vela {vela['t']} repetida entre páginas")
            previo = vela["t"]
            normalizadas.append(vela)
        for vela in normalizadas:
            vistos.add(vela["t"])
            if es_elegible(vela["t"], vela.pop("close_time"), elegibilidad):
                velas.append(vela)
        if len(pagina) < limite:
            return velas                            # página incompleta → fin
        siguiente = normalizadas[-1]["t"] + dur
        if siguiente <= inicio:
            # BACKSTOP. Con el guardia de «anterior al startTime» esto es
            # inalcanzable —toda vela cumple `t >= inicio`, así que
            # `siguiente >= inicio + dur`—, pero se conserva: si alguien
            # relajara aquel guardia, sin esto la paginación entraría en un
            # loop infinito en silencio.
            raise SinProgreso(
                f"la paginación de {mercado} {tf} no avanza: "
                f"{siguiente} <= {inicio}")
        inicio = siguiente
