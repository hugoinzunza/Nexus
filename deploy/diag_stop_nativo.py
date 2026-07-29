"""¿La subcuenta acepta STOP_MARKET por API, o sigue el -4120?

POR QUÉ IMPORTA: en el libro real de junio-julio, 8 de 11 stops se pasaron del -1R
(peor -4.17R = -37.54 USD). La causa es que no hay stop nativo en el exchange: lo
gestiona el bot a ritmo de polling, y cuando el precio corre, el bot llega tarde.
El -1R no es hoy un piso, es una intención.

QUÉ HACE ESTE SCRIPT: manda UNA orden STOP_MARKET sobre un símbolo SIN posición
abierta. Esa orden no puede ejecutarse —no hay nada que cerrar— así que rebota
siempre. Lo que interesa es CON QUÉ CÓDIGO rebota:

  -4120  → la subcuenta sigue bloqueando STOP_MARKET; hay que ir por watchdog
  otro   → STOP_MARKET está permitido y el rechazo es solo por la falta de
           posición; entonces el bot puede poner el stop nativo al abrir

Antes de mandar nada verifica que no haya ninguna posición abierta y aborta si la
hay: no queremos que una orden de diagnóstico toque una posición viva.

    ssh hugo@49.13.85.184
    cd /home/hugo/Nexus
    set -a; . deploy/trade.env; set +a
    .venv/bin/python deploy/diag_stop_nativo.py
"""
from __future__ import annotations

import os
import sys

# Python pone en sys.path la carpeta del SCRIPT (deploy/), no la raíz del repo, así
# que `modules` no se ve. El colector se ejecuta con `-m` y no lo necesita; este se
# corre por ruta, para poder copiarlo suelto sin desplegar nada más.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SIMBOLO = "ADAUSDT"  # el de menor valor por contrato del universo del bot


def main() -> int:
    from modules.trading.binance_account import BinanceError, BinanceFutures

    cli = BinanceFutures()
    # sync_clock es nuevo; este script tiene que poder correr contra el código que YA
    # está en el VPS, sin obligar a desplegar nada solo para diagnosticar.
    if hasattr(cli, "sync_clock"):
        print(f"desfase de reloj: {cli.sync_clock()} ms")
    else:
        import time as _t
        print(f"desfase de reloj: {cli.server_time() - int(_t.time() * 1000)} ms")

    saldo = cli.balance_usdt()
    print(f"saldo: {saldo.get('balance')} USDT (disponible {saldo.get('available')})")

    abiertas = [p for p in cli.positions() if abs(float(p.get("qty") or 0)) > 0]
    if abiertas:
        print("\nHAY POSICIONES ABIERTAS. No se manda nada:")
        for p in abiertas:
            print(f"   {p['symbol']} {p.get('side')} qty={p.get('qty')}")
        print("Corre esto cuando el bot no tenga nada abierto.")
        return 1

    hedge = cli.position_mode()
    print(f"modo de posición: {'HEDGE' if hedge else 'ONE-WAY'}")

    px = cli.mark_price(SIMBOLO)
    filtros = cli.symbol_filters(SIMBOLO)
    # Cantidad mínima válida: por debajo del minNotional Binance rechaza por parámetros
    # y volveríamos a no saber nada de permisos.
    qty = cli.round_qty(SIMBOLO, max(float(filtros.get("min_qty") or 0),
                                     (float(filtros.get("min_notional") or 5) * 1.2) / px))
    # Stop MUY lejos del mercado: aunque la orden se acepte, no puede dispararse en
    # los segundos que vive antes de cancelarse.
    stop = round(px * 0.5, filtros["price_precision"])
    print(f"\n{SIMBOLO} marca {px} · qty de prueba {qty} · stop {stop} (sin posición)")

    # -1102/-1111/-4014 y familia son errores de PARÁMETROS: Binance los devuelve antes
    # de evaluar permisos, así que no dicen nada sobre si el stop está permitido. Solo
    # -4120 responde la pregunta.
    PARAMETRO = ("-1102", "-1111", "-1106", "-4014", "-4003", "-1013")

    def probar(etiqueta: str, **extra) -> str:
        """Arma la petición a mano en vez de usar `stop_market`.

        El VPS puede tener una versión distinta del wrapper —de hecho la tiene: le
        faltaba `closePosition` en HEDGE sin qty, y por eso salía -1102—. Acá se
        prueba a BINANCE, no a nuestro código.
        """
        print(f"\n--- {etiqueta} ---")
        p = {"symbol": SIMBOLO, "side": "SELL", "type": "STOP_MARKET",
             "stopPrice": stop, "workingType": "MARK_PRICE"}
        if hedge:
            p["positionSide"] = "LONG"
        p.update(extra)
        if not hedge and "quantity" in extra:
            p["reduceOnly"] = "true"
        print(f"params: {p}")
        try:
            r = cli._request("POST", "/fapi/v1/order", p, signed=True)
        except BinanceError as exc:
            msg = str(exc)
            print(f"rechazada: {msg[-140:]}")
            if "-4120" in msg:
                return "bloqueado"
            if any(c in msg for c in PARAMETRO):
                return "parametros"
            return "otro"
        print(f"ACEPTADA (orderId {r.get('orderId')}) — cancelando…")
        try:
            cli.cancel_all_orders(SIMBOLO)
            print("cancelada.")
        except BinanceError as exc:
            print(f"NO SE PUDO CANCELAR: {exc}")
            print(f"CANCÉLALA A MANO EN LA UI DE BINANCE ({SIMBOLO}).")
        return "aceptada"

    con_qty = probar("STOP_MARKET con quantity (lo que usa el bot en el stop BE)",
                     quantity=qty)
    cierra_todo = probar("STOP_MARKET con closePosition (lo que usaría al abrir)",
                         closePosition="true")

    print("\n" + "=" * 62)
    if "bloqueado" in (con_qty, cierra_todo):
        print("VEREDICTO: -4120 SIGUE VIGENTE en al menos una variante.")
        print(f"  con quantity: {con_qty} · closePosition: {cierra_todo}")
        print("  Hay que ir por el watchdog externo.")
    elif "aceptada" in (con_qty, cierra_todo):
        print("VEREDICTO: STOP_MARKET FUNCIONA.")
        print(f"  con quantity: {con_qty} · closePosition: {cierra_todo}")
        print("  El bot PUEDE poner el stop nativo al abrir, que es el arreglo bueno:")
        print("  lo hace cumplir Binance, no el polling del bot.")
    else:
        print("VEREDICTO: INDETERMINADO.")
        print(f"  con quantity: {con_qty} · closePosition: {cierra_todo}")
        print("  Ninguna variante llegó a la comprobación de permisos. Pásame la salida.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
