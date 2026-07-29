#!/usr/bin/env python3
"""Prueba integral de ejecución de NexUX contra Binance Demo Futures.

Abre posiciones LONG y SHORT pequeñas con fondos virtuales, confirma stops
nativos, prueba un parcial y deja la cuenta plana aun si algo falla.
"""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.bot.executor import ordenar_resuelto  # noqa: E402
from modules.trading.binance_account import BinanceFutures  # noqa: E402


DEMO_URL = "https://demo-fapi.binance.com"
SYMBOL = os.environ.get("NEXUS_TESTNET_SYMBOL", "ADAUSDT")


def _require_demo() -> None:
    base = os.environ.get("BINANCE_FAPI_BASE_URL", "").rstrip("/")
    if os.environ.get("NEXUS_TESTNET") != "1" or base != DEMO_URL:
        raise SystemExit(
            "ABORTADO: exige NEXUS_TESTNET=1 y "
            f"BINANCE_FAPI_BASE_URL={DEMO_URL}"
        )


def _qty_for_notional(cli: BinanceFutures, symbol: str, notional: float = 15.0) -> float:
    price = cli.mark_price(symbol)
    filters = cli.symbol_filters(symbol)
    step = filters["qty_step"] or (10 ** -filters["qty_precision"])
    minimum = max(filters["min_qty"], filters["min_notional"] / price)
    raw = max(minimum, notional / price)
    qty = math.ceil(raw / step) * step
    return round(qty, filters["qty_precision"])


def _wait_qty(cli: BinanceFutures, side: str, expected: float, timeout: float = 8.0) -> float:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for position in cli.positions([SYMBOL]):
            if position["position_side"] == side:
                qty = float(position["qty"])
                if abs(qty - expected) < max(expected * 0.01, 1e-10):
                    return qty
        if expected == 0 and not cli.positions([SYMBOL]):
            return 0.0
        time.sleep(0.4)
    actual = [
        (p["position_side"], p["qty"]) for p in cli.positions([SYMBOL])
    ]
    raise RuntimeError(f"cantidad esperada {side}={expected}; real={actual}")


def _cleanup(cli: BinanceFutures, algo_ids: list[str]) -> None:
    for algo_id in algo_ids:
        try:
            cli.cancel_algo_order(client_algo_id=algo_id)
        except Exception:
            pass
    for position in cli.positions([SYMBOL]):
        qty = float(position["qty"])
        if qty <= 0:
            continue
        side = "SELL" if position["position_side"] == "LONG" else "BUY"
        cli.market_order(
            SYMBOL,
            side,
            qty,
            client_id=f"nxtclean{int(time.time() * 1000) % 10**12}",
            position_side=position["position_side"],
        )


def _exercise_side(cli: BinanceFutures, position_side: str, qty: float) -> None:
    stamp = str(int(time.time() * 1000))[-10:]
    prefix = f"nxt{position_side[0].lower()}{stamp}"
    open_side = "BUY" if position_side == "LONG" else "SELL"
    close_side = "SELL" if position_side == "LONG" else "BUY"
    algo_ids = [f"{prefix}s0", f"{prefix}s1"]

    try:
        opened = ordenar_resuelto(
            cli,
            SYMBOL,
            open_side,
            qty,
            f"{prefix}open",
            position_side=position_side,
            log=lambda message: print(f"  {message}"),
        )
        if not opened or float(opened["executed_qty"]) <= 0:
            raise RuntimeError(f"apertura {position_side} no confirmada")
        real_qty = _wait_qty(cli, position_side, float(opened["executed_qty"]))
        entry = float(opened["avg_price"]) or cli.mark_price(SYMBOL)
        trigger = entry * (0.97 if position_side == "LONG" else 1.03)

        cli.algo_stop_market(
            SYMBOL,
            close_side,
            trigger,
            qty=real_qty,
            position_side=position_side,
            client_algo_id=algo_ids[0],
        )
        stop = cli.get_algo_order(algo_ids[0])
        if not stop or stop["status"] != "NEW":
            raise RuntimeError(f"stop inicial {position_side} no quedó activo: {stop}")
        if stop["position_side"] != position_side:
            raise RuntimeError(f"stop quedó en lado incorrecto: {stop}")

        step = cli.symbol_filters(SYMBOL)["qty_step"]
        partial = cli.round_qty(SYMBOL, real_qty / 2)
        if partial < step or partial >= real_qty:
            raise RuntimeError(f"cantidad {real_qty} no admite parcial seguro")
        closed = ordenar_resuelto(
            cli,
            SYMBOL,
            close_side,
            partial,
            f"{prefix}part",
            position_side=position_side,
            log=lambda message: print(f"  {message}"),
        )
        if not closed:
            raise RuntimeError(f"parcial {position_side} no confirmado")
        remaining = cli.round_qty(SYMBOL, real_qty - float(closed["executed_qty"]))
        _wait_qty(cli, position_side, remaining)

        cli.algo_stop_market(
            SYMBOL,
            close_side,
            trigger,
            qty=remaining,
            position_side=position_side,
            client_algo_id=algo_ids[1],
        )
        replacement = cli.get_algo_order(algo_ids[1])
        if not replacement or replacement["status"] != "NEW":
            raise RuntimeError(f"reemplazo {position_side} no quedó activo")
        cli.cancel_algo_order(client_algo_id=algo_ids[0])

        final = ordenar_resuelto(
            cli,
            SYMBOL,
            close_side,
            remaining,
            f"{prefix}close",
            position_side=position_side,
            log=lambda message: print(f"  {message}"),
        )
        if not final:
            raise RuntimeError(f"cierre {position_side} no confirmado")
        _wait_qty(cli, position_side, 0.0)
        cli.cancel_algo_order(client_algo_id=algo_ids[1])
        print(
            f"OK {position_side}: apertura, stop nativo, parcial, "
            "reemplazo y cierre confirmados"
        )
    finally:
        _cleanup(cli, algo_ids)


def main() -> int:
    _require_demo()
    cli = BinanceFutures()
    if cli.positions():
        raise SystemExit("ABORTADO: Demo no está plana antes de comenzar")

    if not cli.position_mode():
        cli.set_position_mode(True)
    if not cli.position_mode():
        raise RuntimeError("Binance Demo no quedó en modo HEDGE")

    cli.set_leverage(SYMBOL, 3)
    qty = _qty_for_notional(cli, SYMBOL)
    print(f"Demo validada: HEDGE, {SYMBOL}, qty={qty}, apalancamiento=3x")
    try:
        _exercise_side(cli, "LONG", qty)
        _exercise_side(cli, "SHORT", qty)
    finally:
        _cleanup(cli, [])

    open_algos = cli.algo_open_orders(SYMBOL)
    positions = cli.positions([SYMBOL])
    if positions or open_algos:
        raise RuntimeError(
            f"limpieza final incompleta: posiciones={positions}, algos={open_algos}"
        )
    print("OK FINAL: cuenta Demo plana y sin stops huérfanos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
