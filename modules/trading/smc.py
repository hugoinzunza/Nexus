"""Primitivas de Smart Money Concepts (SMC) para el motor de estrategia.

Todo es mecánico y determinista (mismos datos → mismos resultados). Trabaja sobre
una lista de velas {t,o,h,l,c,v}. No hay nada discrecional ni de "ojo".

Conceptos implementados:
  - Swings / pivotes fractales (estructura de mercado).
  - Barrido de liquidez (liquidity sweep): wick más allá de un swing y cierre
    de vuelta adentro.
  - Cambio de carácter / ruptura de estructura (CHoCH/BOS).
  - Fair Value Gap (FVG): hueco de ineficiencia de 3 velas.
  - Order block (OB): última vela opuesta antes del impulso.

Las funciones devuelven estructuras simples (dicts) para que el backtest las use.
"""
from __future__ import annotations

from typing import List, Optional


# --- Swings / pivotes fractales -----------------------------------------
def swing_points(candles: List[dict], lookback: int = 3):
    """Marca swing highs y swing lows fractales.

    Un swing high en i exige que high[i] sea estrictamente el mayor de la ventana
    [i-lookback, i+lookback]. Swing low, simétrico con los mínimos. Como necesita
    `lookback` velas a la derecha, el pivote queda CONFIRMADO recién en i+lookback
    (eso es lo realista: no se conoce antes).

    Devuelve dos listas de dicts: highs y lows, cada uno {idx, price, confirm_idx}.
    """
    highs, lows = [], []
    n = len(candles)
    for i in range(lookback, n - lookback):
        hi = candles[i]["h"]
        lo = candles[i]["l"]
        is_high = all(hi > candles[j]["h"] for j in range(i - lookback, i)) and \
            all(hi > candles[j]["h"] for j in range(i + 1, i + lookback + 1))
        is_low = all(lo < candles[j]["l"] for j in range(i - lookback, i)) and \
            all(lo < candles[j]["l"] for j in range(i + 1, i + lookback + 1))
        if is_high:
            highs.append({"idx": i, "price": hi, "confirm_idx": i + lookback})
        if is_low:
            lows.append({"idx": i, "price": lo, "confirm_idx": i + lookback})
    return highs, lows


def last_confirmed(points: List[dict], before_idx: int) -> Optional[dict]:
    """El pivote más reciente cuya confirmación (confirm_idx) ya ocurrió antes de
    `before_idx`. Así nunca usamos información del futuro."""
    found = None
    for p in points:
        if p["confirm_idx"] < before_idx:
            found = p
        else:
            break
    return found


# --- Fair Value Gap -----------------------------------------------------
def find_fvgs(candles: List[dict], start: int, end: int, bullish: bool):
    """Busca FVGs en el tramo [start, end] (índices de velas).

    FVG alcista entre las velas i-2 e i: high[i-2] < low[i] → zona (high[i-2], low[i]).
    FVG bajista entre i-2 e i: low[i-2] > high[i] → zona (high[i], low[i-2]).

    Devuelve lista de zonas {lo, hi, idx} (lo<hi), de la más antigua a la más nueva.
    """
    out = []
    lo_i = max(start, 2)
    for i in range(lo_i, end + 1):
        if i >= len(candles):
            break
        a = candles[i - 2]
        c = candles[i]
        if bullish and a["h"] < c["l"]:
            out.append({"lo": a["h"], "hi": c["l"], "idx": i})
        if (not bullish) and a["l"] > c["h"]:
            out.append({"lo": c["h"], "hi": a["l"], "idx": i})
    return out


# --- Order block ---------------------------------------------------------
def find_order_block(candles: List[dict], start: int, end: int, bullish: bool):
    """Order block: la última vela OPUESTA al impulso dentro de [start, end].

    Para un setup alcista (impulso al alza) buscamos la última vela bajista
    (c<o) del tramo; su rango (lo, hi) es la zona de entrada. Para bajista, la
    última vela alcista. Devuelve {lo, hi, idx} o None.
    """
    for i in range(min(end, len(candles) - 1), start - 1, -1):
        cndl = candles[i]
        bear = cndl["c"] < cndl["o"]
        bull = cndl["c"] > cndl["o"]
        if bullish and bear:
            return {"lo": cndl["l"], "hi": cndl["h"], "idx": i}
        if (not bullish) and bull:
            return {"lo": cndl["l"], "hi": cndl["h"], "idx": i}
    return None


# --- EMA (para filtro de tendencia opcional) ----------------------------
def ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


# --- ATR (rango medio verdadero) ----------------------------------------
def atr(candles: List[dict], period: int = 14) -> List[float]:
    """ATR simple (media móvil del true range). Devuelve un valor por vela."""
    n = len(candles)
    out = [0.0] * n
    if n == 0:
        return out
    trs = [candles[0]["h"] - candles[0]["l"]]
    for i in range(1, n):
        pc = candles[i - 1]["c"]
        c = candles[i]
        trs.append(max(c["h"] - c["l"], abs(c["h"] - pc), abs(c["l"] - pc)))
    s = 0.0
    for i in range(n):
        s += trs[i]
        if i >= period:
            s -= trs[i - period]
            out[i] = s / period
        else:
            out[i] = s / (i + 1)
    return out


# --- Dirección por estructura de mercado (HH/HL vs LH/LL) ----------------
def structure_direction(candles: List[dict], lookback: int = 2) -> List[int]:
    """Tendencia según la estructura: +1 alcista (máximos y mínimos crecientes),
    -1 bajista (decrecientes), persistiendo el último régimen hasta que cambie.

    Usa solo swings YA confirmados en cada vela (confirm_idx), sin mirar el futuro.
    Devuelve un entero (-1/0/+1) por vela.
    """
    n = len(candles)
    out = [0] * n
    highs, lows = swing_points(candles, lookback)
    # Ordenamos por el momento en que se confirman.
    hi_evt = sorted(highs, key=lambda p: p["confirm_idx"])
    lo_evt = sorted(lows, key=lambda p: p["confirm_idx"])
    ph = pl = 0
    seen_highs, seen_lows = [], []
    cur = 0
    for i in range(n):
        while ph < len(hi_evt) and hi_evt[ph]["confirm_idx"] <= i:
            seen_highs.append(hi_evt[ph]["price"]); ph += 1
        while pl < len(lo_evt) and lo_evt[pl]["confirm_idx"] <= i:
            seen_lows.append(lo_evt[pl]["price"]); pl += 1
        if len(seen_highs) >= 2 and len(seen_lows) >= 2:
            hh = seen_highs[-1] > seen_highs[-2]
            hl = seen_lows[-1] > seen_lows[-2]
            lh = seen_highs[-1] < seen_highs[-2]
            ll = seen_lows[-1] < seen_lows[-2]
            if hh and hl:
                cur = 1
            elif lh and ll:
                cur = -1
            # si es mixto (rango), conservamos el último régimen claro
        out[i] = cur
    return out


def map_htf_direction(ltf_candles: List[dict], htf_candles: List[dict],
                      htf_dir: List[int], htf_interval_ms: int) -> List[int]:
    """Proyecta la dirección de estructura del timeframe SUPERIOR sobre cada vela
    del timeframe inferior, usando solo velas HTF YA cerradas (sin lookahead)."""
    out = [0] * len(ltf_candles)
    jj = 0
    for i, c in enumerate(ltf_candles):
        tl = c["t"]
        while jj < len(htf_candles) and htf_candles[jj]["t"] + htf_interval_ms <= tl:
            jj += 1
        idx = jj - 1
        out[i] = htf_dir[idx] if idx >= 0 else 0
    return out
