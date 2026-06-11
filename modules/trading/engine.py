"""Motor genérico de backtest por señales (Fase 2).

Las estrategias producen SEÑALES (cuándo, dirección, stop y objetivo R). Este
motor las convierte en trades: entra en la apertura de la vela SIGUIENTE (sin
mirar el futuro), simula el stop / take-profit / time-stop vela a vela, aplica
comisión y slippage, y devuelve el R neto. No abre una nueva operación hasta
cerrar la anterior (sin solapamiento).

Una señal es la tupla:  (i, direction, stop_price, rr)
  i           índice de la vela donde se gatilla (la entrada es en i+1)
  direction   "long" | "short"
  stop_price  precio del stop (calculado con datos hasta la vela i)
  rr          objetivo en múltiplos de R
"""
from __future__ import annotations

from typing import List, Tuple

from .backtest import session_of

COMMISSION = 0.0005   # 0.05% por lado
SLIPPAGE = 0.0002     # 0.02% por fill


def simulate(candles: List[dict], signals: List[Tuple], symbol: str, timeframe: str,
             strategy: str, max_hold: int = 96, min_stop_frac: float = 0.0015,
             commission: float = COMMISSION, slippage: float = SLIPPAGE,
             exit_at=None, allow_immediate_reentry: bool = False) -> List[dict]:
    """Simula las señales. `exit_at` (set opcional de índices) cierra la posición
    al cierre de esa vela (p.ej. señal opuesta), con prioridad para stop/TP si
    caen en la misma vela (conservador). `allow_immediate_reentry` permite que una
    señal en la misma vela del cierre por señal abra la siguiente operación."""
    n = len(candles)
    trades: List[dict] = []
    occupied_until = -1
    signals.sort(key=lambda s: s[0])

    for (i, direction, stop_price, rr) in signals:
        if i <= occupied_until or i + 1 >= n:
            continue
        e = i + 1
        entry = candles[e]["o"]
        short = direction == "short"
        risk = (stop_price - entry) if short else (entry - stop_price)
        if risk <= 0 or risk / entry < min_stop_frac:
            continue
        tp = entry - rr * risk if short else entry + rr * risk

        outcome = "time"
        exit_idx = min(n - 1, e + max_hold)
        exit_level = candles[exit_idx]["c"]
        for m in range(e + 1, min(n - 1, e + max_hold) + 1):
            c = candles[m]
            if short:
                if c["h"] >= stop_price:
                    outcome, exit_level, exit_idx = "loss", stop_price, m
                    break
                if c["l"] <= tp:
                    outcome, exit_level, exit_idx = "win", tp, m
                    break
            else:
                if c["l"] <= stop_price:
                    outcome, exit_level, exit_idx = "loss", stop_price, m
                    break
                if c["h"] >= tp:
                    outcome, exit_level, exit_idx = "win", tp, m
                    break
            if exit_at is not None and m in exit_at:  # señal opuesta → cierre
                outcome, exit_level, exit_idx = "signal", c["c"], m
                break

        if short:
            entry_fill = entry * (1 - slippage)
            exit_fill = exit_level * (1 + slippage) if outcome != "win" else exit_level
            pnl = entry_fill - exit_fill
        else:
            entry_fill = entry * (1 + slippage)
            exit_fill = exit_level * (1 - slippage) if outcome != "win" else exit_level
            pnl = exit_fill - entry_fill
        net = pnl - commission * (entry_fill + exit_fill)
        r_mult = net / risk

        trades.append({
            "symbol": symbol, "timeframe": timeframe, "strategy": strategy,
            "direction": direction,
            "entry_time": candles[e]["t"], "exit_time": candles[exit_idx]["t"],
            "entry": round(entry, 4), "stop": round(stop_price, 4),
            "tp": round(tp, 4), "exit": round(exit_level, 4),
            "outcome": outcome, "R": round(r_mult, 4),
            "session": session_of(candles[e]["t"]),
        })
        # Tras un cierre por señal, opcionalmente permitimos reentrar en la misma
        # vela (la nueva entrada es en la apertura siguiente, sin solape real).
        occupied_until = (exit_idx - 1) if (allow_immediate_reentry and outcome == "signal") else exit_idx
    return trades
