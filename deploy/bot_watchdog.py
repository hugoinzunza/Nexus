"""Watchdog del stop — hace cumplir el -1R cuando el bot no llega.

POR QUÉ EXISTE — Y QUÉ NO ES
----------------------------
ES LA SEGUNDA LÍNEA DE DEFENSA, NO LA PRIMERA. La primera es el stop NATIVO que el
executor coloca en Binance vía `/fapi/v1/algoOrder` al abrir cada posición.

Corrección de una versión anterior de este archivo, que decía "no hay stop nativo
disponible": era FALSO. Binance movió las condicionales fuera de /fapi/v1/order el
2025-12-09 y el -4120 apuntaba justo al endpoint nuevo; se leyó el mensaje correcto y se
sacó la conclusión contraria. El stop nativo existe y estuvo disponible todo el tiempo.

Este proceso cubre lo que el stop nativo no puede: que el stop no se haya llegado a
colocar, que lo cancelen por error, o que la posición quede fuera del libro. Medido en el
libro real de junio-julio, cuando NO había stop nativo: de 11 setups donde el Diario marcó
stop limpio (-1.00R), 8 se pasaron; promedio -1.305R, peor -4.17R (-37.54 USD).

Corre APARTE del bot —su propio servicio, su propio cliente— para seguir en pie aunque el
bot se cuelgue, se caiga o se quede sin feed. No depende de un heartbeat: mira el precio
contra el SL, que es cierto esté el bot vivo o muerto.

QUÉ HACE Y QUÉ NO
-----------------
  • SOLO cierra. Nunca abre, nunca aumenta, nunca mueve un SL.
  • Cierra únicamente posiciones que ya pasaron su SL por más de la tolerancia. Dentro
    de la tolerancia no toca nada: ahí el bot es el que manda y no queremos carreras.
  • Si no puede leer el precio o las posiciones, NO hace nada. Un watchdog que actúa a
    ciegas es peor que no tenerlo.
  • Arranca APAGADO (`enabled: false` en la config).

Se ejecuta cada `INTERVALO_S`. Con 15 s y la tolerancia por defecto, un stop que hoy se
pasaba a -4.17R se habría cortado bastante antes.

    python3 deploy/bot_watchdog.py          # un ciclo y sale (para el timer)
    python3 deploy/bot_watchdog.py --loop   # bucle propio
    python3 deploy/bot_watchdog.py --dry    # dice qué haría, no manda nada
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "nexus.json")
ESTADO = os.path.join(ROOT, "data", "bot_watchdog.json")

INTERVALO_S = 15.0

# Cuánto se deja pasar del SL antes de intervenir, en fracción de la distancia
# entrada→SL (o sea, en R). 0.25 = se actúa al -1.25R.
#
# Empezó en 0.15, calibrado con que 6 de los 8 stops pasados lo hicieron por más de
# 0.13R. Eso era ajustar el umbral a la MISMA muestra que motivó construir esto, o sea
# circular. Y el rol cambió: con stop nativo puesto por el exchange, este proceso es
# emergencia, no ejecutor. Un umbral holgado es lo correcto para una emergencia — el
# costo de no disparar cuando el stop nativo sí funcionó es cero, y el de disparar de
# más es cerrar una posición que no correspondía.
TOLERANCIA_R = 0.25


def _cfg() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    bot = (data.get("modules") or {}).get("bot") or {}
    return bot.get("watchdog") or {}


def _trades_abiertos() -> list[dict]:
    """Trades vivos del libro, con su SL. Es de donde sale el nivel a hacer cumplir."""
    from core.paths import persist_dir
    ruta = os.path.join(persist_dir(ROOT), "bot_trades.json")
    try:
        with open(ruta, encoding="utf-8") as fh:
            datos = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    filas = datos if isinstance(datos, list) else (datos.get("trades") or [])
    return [t for t in filas if t.get("status") == "abierta" and t.get("mode") == "live"]


def _excedido(trade: dict, precio: float) -> float | None:
    """Cuántas R lleva el precio MÁS ALLÁ del SL. None si aún no lo cruzó."""
    try:
        entrada = float(trade["entry_price"])
        sl = float(trade["sl"])
    except (KeyError, TypeError, ValueError):
        return None
    riesgo = abs(entrada - sl)
    if riesgo <= 0:
        return None
    # El SL tiene que estar del lado que corresponde: por DEBAJO de la entrada en un
    # long, por ENCIMA en un short. Un registro con el SL invertido —o con dir mal
    # escrito— haría que `exceso` salga positivo con el precio a favor, y el watchdog
    # cerraría una posición ganadora. Ante un dato incoherente, no se toca nada.
    direccion = trade.get("dir")
    if direccion == "long":
        if sl >= entrada:
            return None
        exceso = sl - precio
    elif direccion == "short":
        if sl <= entrada:
            return None
        exceso = precio - sl
    else:
        return None
    return exceso / riesgo if exceso > 0 else None


def _latido(vigilados: int, posiciones: int, state_path: str | None = ESTADO) -> None:
    """Deja constancia de que el ciclo COMPLETÓ la lectura, aunque no hiciera nada.

    Sirve para poder mirar el archivo y saber si el watchdog está vivo y leyendo, en
    vez de suponerlo. Un watchdog que no reporta y uno que no tiene nada que hacer se
    ven idénticos desde afuera.
    """
    if not state_path:
        return
    try:
        with open(state_path, encoding="utf-8") as fh:
            datos = json.load(fh)
    except (OSError, json.JSONDecodeError):
        datos = {"eventos": []}
    datos["ultimo_ciclo"] = time.time()
    datos["ultimo_ciclo_iso"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    datos["vigilados"] = vigilados
    datos["posiciones_reales"] = posiciones
    datos["ciclos"] = int(datos.get("ciclos") or 0) + 1
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        tmp = state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, indent=1)
        os.replace(tmp, state_path)
    except OSError:
        pass


def _registrar(evento: dict, state_path: str | None = ESTADO) -> None:
    if not state_path:
        return
    try:
        with open(state_path, encoding="utf-8") as fh:
            datos = json.load(fh)
    except (OSError, json.JSONDecodeError):
        datos = {"eventos": []}
    datos["ultimo_ciclo"] = time.time()
    datos.setdefault("eventos", []).append(evento)
    datos["eventos"] = datos["eventos"][-200:]
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        tmp = state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, indent=1)
        os.replace(tmp, state_path)
    except OSError:
        pass


def ciclo(dry: bool = False, log=print, cli=None, abiertos=None, cfg=None) -> int:
    """Un barrido. Devuelve cuántas posiciones cerró.

    `cli` y `abiertos` se pueden inyectar para probar la ruta de disparo sin abrir
    una posición real: contra la API solo se puede verificar que NO actúa, porque
    solo toca posiciones que existen de verdad.
    """
    cfg = _cfg() if cfg is None else cfg
    # Los tests y simuladores pueden desactivar o redirigir explícitamente el estado.
    # Producción no declara esta clave y conserva la ruta operacional de siempre.
    state_path = cfg.get("_state_path", ESTADO)
    if not cfg.get("enabled") and not dry:
        return 0
    tolerancia = float(cfg.get("tolerancia_r", TOLERANCIA_R))

    from modules.bot.executor import BinanceOrdenAmbigua, ordenar_resuelto
    from modules.trading.binance_account import BinanceError, BinanceFutures
    if cli is None:
        try:
            cli = BinanceFutures()
        except BinanceError as exc:
            log(f"watchdog: sin cliente ({exc})")
            return 0

    abiertos = _trades_abiertos() if abiertos is None else abiertos
    # La lectura se hace SIEMPRE, aunque no haya nada que vigilar. Si solo se ejercitara
    # con posiciones vivas, la primera vez que el watchdog tocara la API sería el mismo
    # día que hay dinero en juego — y ahí no es donde uno quiere descubrir que la llave
    # no tiene permisos o que el endpoint cambió. Con el bot en dry esto no cierra nada
    # y aun así prueba todo el camino de lectura.
    # -1003 (cuota de la IP) es TRANSITORIO y no es culpa nuestra: el watchdog pide 4
    # veces por minuto. Medido en el VPS, la IP vivía en 1620 de 2400 por el colector,
    # y esto dejaba al watchdog ciego el 8% de los ciclos. La causa de fondo ya está
    # arreglada, pero lo único que sostiene el -1R no puede depender de que nadie más
    # se pase de cuota: ante -1003 se reintenta en vez de saltarse el ciclo.
    reales = None
    for intento in range(3):
        try:
            # Clave (símbolo, lado). Indexar solo por símbolo perdía la distinción en
            # HEDGE —que es el modo de esta subcuenta—: con BTC long y short abiertos a
            # la vez, uno pisaba al otro y el watchdog podía cerrar el lado equivocado.
            reales = {(p["symbol"], "long" if p["side"] == "LONG" else "short"): p
                      for p in cli.positions() if abs(float(p.get("qty") or 0)) > 0}
            break
        except BinanceError as exc:
            if "-1003" in str(exc) and intento < 2:
                time.sleep(2.0 * (intento + 1))
                continue
            # Sin lectura confiable no se cierra nada: actuar a ciegas es peor que no estar.
            log(f"watchdog: no se pudieron leer posiciones ({exc}); no se toca nada")
            _registrar({"ts": time.time(), "accion": "lectura_fallida",
                        "error": str(exc)[-200:], "intentos": intento + 1}, state_path)
            return 0
    if reales is None:
        return 0
    _latido(len(abiertos), len(reales), state_path)
    if not abiertos:
        return 0

    cerradas = 0
    for t in abiertos:
        symbol = t.get("symbol")
        pos = reales.get((symbol, t.get("dir")))
        if not pos:
            continue  # el bot ya cerró, o la reconciliación lo verá
        try:
            precio = cli.mark_price(symbol)
        except BinanceError as exc:
            log(f"watchdog: sin precio de {symbol} ({exc}); no se toca")
            continue
        exceso = _excedido(t, precio)
        if exceso is None or exceso < tolerancia:
            continue

        r_actual = -(1.0 + exceso)
        log(f"watchdog: {symbol} {t.get('dir')} pasó el SL {t.get('sl')} "
            f"(marca {precio}, {r_actual:+.2f}R) → CIERRA")
        if dry:
            cerradas += 1
            continue
        # La cantidad la manda BINANCE, no el libro. Si el libro está desincronizado
        # —que es justo el escenario en que el watchdog hace falta— cerrar por qty_open
        # deja un resto abierto o intenta cerrar de más.
        qty = abs(float(pos.get("qty") or 0))
        if qty <= 0:
            continue
        side = "SELL" if t.get("dir") == "long" else "BUY"
        pos_side = pos.get("position_side") if cfg.get("hedge", True) else None
        # id DETERMINISTA por trade: un timestamp generaba un id nuevo en cada ciclo, así
        # que un timeout podía terminar en dos órdenes de cierre. Y es newClientOrderId,
        # espacio distinto del clientAlgoId de los stops: confundirlos cancela lo que no era.
        cid = "wd" + hashlib.md5(str(t.get("setup_id")).encode()).hexdigest()[:16]
        try:
            resp = ordenar_resuelto(cli, symbol, side, cli.round_qty(symbol, qty), cid,
                                    reduce_only=not pos_side, position_side=pos_side,
                                    log=log)
        except BinanceOrdenAmbigua as exc:
            # No sabemos si cerró. NO se reintenta con otro id ni se da por hecho:
            # el próximo ciclo vuelve a mirar la posición real, que es la verdad.
            log(f"watchdog: cierre AMBIGUO en {symbol} ({exc}); se revisa el próximo ciclo")
            _registrar({"ts": time.time(), "symbol": symbol, "accion": "ambiguo",
                        "error": str(exc)[-200:], "r": r_actual}, state_path)
            continue
        if not resp:
            log(f"watchdog: el cierre de {symbol} no se ejecutó")
            _registrar({"ts": time.time(), "symbol": symbol, "accion": "no_ejecutada",
                        "r": r_actual}, state_path)
            continue
        cerradas += 1
        _registrar({"ts": time.time(), "symbol": symbol, "accion": "cerrada",
                    "precio": precio, "sl": t.get("sl"), "r": r_actual,
                    "exceso_r": exceso}, state_path)
        log(f"watchdog: {symbol} cerrada a mercado")
    return cerradas


def _sd_notify(mensaje: str) -> None:
    """Avisa a systemd. Sin dependencias: es un datagrama a un socket unix.

    Sirve para que `WatchdogSec` funcione de verdad. Con Type=simple systemd lo
    ignora, así que un proceso COLGADO se ve perfectamente sano — que es el peor
    estado posible para lo único que sostiene el -1R.
    """
    ruta = os.environ.get("NOTIFY_SOCKET")
    if not ruta:
        return
    import socket
    if ruta.startswith("@"):  # namespace abstracto
        ruta = "\0" + ruta[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(ruta)
            s.sendall(mensaje.encode())
    except OSError:
        pass


def main() -> int:
    dry = "--dry" in sys.argv
    if "--loop" not in sys.argv:
        ciclo(dry=dry)
        return 0
    _sd_notify("READY=1")
    while True:
        try:
            ciclo(dry=dry)
        except Exception as exc:  # noqa: BLE001
            # Un watchdog que se muere por una excepción no vigila nada.
            print(f"watchdog: error en el ciclo: {exc}", flush=True)
        else:
            # Solo se avisa "vivo" si el ciclo TERMINÓ. Si se cuelga leyendo Binance,
            # systemd deja de recibir el latido y lo reinicia, que es lo que queremos.
            _sd_notify("WATCHDOG=1")
        time.sleep(INTERVALO_S)


if __name__ == "__main__":
    sys.exit(main())
