"""Indicadores técnicos para la biblioteca de estrategias (Fase 2).

Todo sobre listas de velas {t,o,h,l,c,v} o de valores. Sin dependencias externas.
Cada función devuelve una lista alineada a la entrada (None donde no hay datos).
"""
from __future__ import annotations

import math
from typing import List, Optional


def sma(values: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period:
            s -= values[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


def ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: List[float], period: int = 14) -> List[Optional[float]]:
    """RSI de Wilder."""
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    ag = gains / period
    al = losses / period
    out[period] = 100.0 - 100.0 / (1.0 + (ag / al if al > 0 else 1e9))
    for i in range(period + 1, n):
        ch = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(ch, 0.0)) / period
        al = (al * (period - 1) + max(-ch, 0.0)) / period
        rs = ag / al if al > 0 else 1e9
        out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def bollinger(closes: List[float], period: int = 20, k: float = 2.0):
    """Bandas de Bollinger. Devuelve (mid, upper, lower, bandwidth)."""
    n = len(closes)
    mid: List[Optional[float]] = [None] * n
    up: List[Optional[float]] = [None] * n
    lo: List[Optional[float]] = [None] * n
    bw: List[Optional[float]] = [None] * n
    s = ss = 0.0
    for i in range(n):
        c = closes[i]
        s += c
        ss += c * c
        if i >= period:
            old = closes[i - period]
            s -= old
            ss -= old * old
        if i >= period - 1:
            m = s / period
            var = max(0.0, ss / period - m * m)
            sd = math.sqrt(var)
            mid[i] = m
            up[i] = m + k * sd
            lo[i] = m - k * sd
            bw[i] = (up[i] - lo[i]) / m if m > 0 else None
    return mid, up, lo, bw


def donchian(candles: List[dict], period: int):
    """Canal de Donchian: máximo de los `period` máximos PREVIOS y mínimo de los
    mínimos previos (excluye la vela actual, para detectar ruptura sin lookahead).
    Implementado con deques monótonas (O(n)). Devuelve (upper, lower)."""
    from collections import deque
    n = len(candles)
    up: List[Optional[float]] = [None] * n
    lo: List[Optional[float]] = [None] * n
    dqmax, dqmin = deque(), deque()  # índices, ventana [i-period, i-1]
    for i in range(n):
        if i - 1 >= 0:
            h = candles[i - 1]["h"]
            l = candles[i - 1]["l"]
            while dqmax and candles[dqmax[-1]]["h"] <= h:
                dqmax.pop()
            dqmax.append(i - 1)
            while dqmin and candles[dqmin[-1]]["l"] >= l:
                dqmin.pop()
            dqmin.append(i - 1)
        lo_bound = i - period
        while dqmax and dqmax[0] < lo_bound:
            dqmax.popleft()
        while dqmin and dqmin[0] < lo_bound:
            dqmin.popleft()
        if i >= period:
            up[i] = candles[dqmax[0]]["h"]
            lo[i] = candles[dqmin[0]]["l"]
    return up, lo
