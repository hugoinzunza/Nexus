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

import sys

SIMBOLO = "ADAUSDT"  # el de menor valor por contrato del universo del bot


def main() -> int:
    from modules.trading.binance_account import BinanceError, BinanceFutures

    cli = BinanceFutures()
    print(f"desfase de reloj: {cli.sync_clock()} ms")

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
    # Stop MUY lejos del precio y del lado que no se cruza: aunque por algún motivo
    # la orden se aceptara, no puede dispararse cerca del mercado.
    stop = round(px * 0.5, 4)
    print(f"\n{SIMBOLO} marca {px} → probando STOP_MARKET SELL en {stop} (sin posición)")

    try:
        r = cli.stop_market(SIMBOLO, "SELL", stop,
                            position_side="LONG" if hedge else None,
                            client_id="diag-stop-nativo")
    except BinanceError as exc:
        msg = str(exc)
        print(f"\nrechazada: {msg}\n")
        if "-4120" in msg:
            print("VEREDICTO: -4120 SIGUE VIGENTE.")
            print("  La subcuenta no admite STOP_MARKET por API. El stop nativo no es")
            print("  una opción; hay que construir el watchdog externo.")
        else:
            print("VEREDICTO: STOP_MARKET NO está bloqueado.")
            print("  El rechazo es por otra causa (probablemente la falta de posición).")
            print("  El bot PUEDE poner el stop nativo al abrir. Es el mejor arreglo:")
            print("  lo hace cumplir Binance, no el polling del bot.")
        return 0

    # Si llegó acá la orden quedó VIVA. Se cancela de inmediato: este script
    # diagnostica, no deja órdenes puestas.
    print(f"\nACEPTADA: {r.get('orderId')} — cancelando de inmediato…")
    try:
        cli.cancel_all_orders(SIMBOLO)
        print("cancelada.")
    except BinanceError as exc:
        print(f"NO SE PUDO CANCELAR: {exc}")
        print(f"CANCÉLALA A MANO EN LA UI DE BINANCE ({SIMBOLO}).")
        return 2
    print("\nVEREDICTO: STOP_MARKET FUNCIONA. El bot puede poner el stop nativo al abrir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
