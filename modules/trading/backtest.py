"""Motor de estrategia SMC + backtest (Fase 1.5: filtros de calidad y tendencia).

Estrategia mecánica (long y short, simétrica):

  1. ESTRUCTURA: swings fractales (lookback configurable).
  2. BARRIDO DE LIQUIDEZ: una vela hace wick más allá de un swing previo y CIERRA
     de vuelta adentro (toma de liquidez, sin aceptación).
  3. CAMBIO DE CARÁCTER (CHoCH): tras el barrido, el precio rompe (con cierre) el
     swing opuesto reciente, confirmando el giro.
  4. ENTRADA: en el retroceso al FVG (o, si no hay y no exigimos filtros de FVG,
     al order block) que dejó el impulso. Orden límite.
  5. STOP: más allá del extremo del barrido (con un pequeño buffer).
  6. TAKE-PROFIT: múltiplo R configurable (1.5R / 2R / 3R).

Filtros de calidad (parametrizables, para medir su impacto uno por uno):
  - Tendencia: por ESTRUCTURA del timeframe superior (HH/HL vs LH/LL) o por EMA.
  - Displacement: la vela que crea el FVG debe tener cuerpo > X·ATR.
  - Premium/discount: vender solo en premium (mitad alta del rango), comprar en discount.
  - Tamaño mínimo del FVG (en múltiplos de ATR).
  - Sesión (Asia/Londres/NY/Fuera).

Costos: comisión por lado + slippage, aplicados a los fills → R neto honesto.
Sin posiciones simultáneas por par/timeframe.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple

from . import smc


@dataclass
class Params:
    swing_lookback: int = 3
    confirm_window: int = 12
    entry_window: int = 20
    max_hold: int = 72
    stop_buffer: float = 0.0005
    min_stop_frac: float = 0.0015
    rr: float = 2.0
    # Tendencia: "none" | "ema" | "structure"
    trend_filter_mode: str = "none"
    trend_ema: int = 200
    # Filtros de calidad
    use_displacement: bool = False
    displacement_atr: float = 1.0      # cuerpo de la vela del FVG > X·ATR
    use_premium_discount: bool = False
    use_min_fvg: bool = False
    min_fvg_atr: float = 0.25          # tamaño del FVG > X·ATR
    atr_period: int = 14
    session_filter: Optional[List[str]] = None   # p.ej. ["Londres"]
    direction: str = "both"            # both | long | short
    commission: float = 0.0005
    slippage: float = 0.0002


def session_of(ts_ms: int) -> str:
    h = time.gmtime(ts_ms / 1000).tm_hour
    if 0 <= h < 7:
        return "Asia"
    if 7 <= h < 13:
        return "Londres"
    if 13 <= h < 21:
        return "NY"
    return "Fuera"


def _recent_pivots(points: List[dict], n: int):
    out = [None] * n
    p = 0
    pts = sorted(points, key=lambda x: x["confirm_idx"])
    for i in range(n):
        while p < len(pts) and pts[p]["confirm_idx"] < i:
            p += 1
        out[i] = pts[p - 1] if p > 0 else None
    return out


def run(candles: List[dict], symbol: str, timeframe: str, params: Params,
        htf_dir: Optional[List[int]] = None) -> List[dict]:
    """Corre la estrategia y devuelve la lista de trades cerrados.

    `htf_dir` (opcional): dirección de estructura del timeframe superior por vela
    (-1/0/+1), usada cuando trend_filter_mode == "structure".
    """
    n = len(candles)
    if n < 200:
        return []

    highs, lows = smc.swing_points(candles, params.swing_lookback)
    last_high = _recent_pivots(highs, n)
    last_low = _recent_pivots(lows, n)
    closes = [c["c"] for c in candles]
    ctx = {
        "last_high": last_high,
        "last_low": last_low,
        "atr": smc.atr(candles, params.atr_period),
        "ema": smc.ema(closes, params.trend_ema) if params.trend_filter_mode == "ema" else None,
        "htf_dir": htf_dir,
    }

    trades: List[dict] = []
    s = params.swing_lookback + 2
    end = n - 1
    while s < end:
        trade = _try_setup(candles, s, end, ctx, symbol, timeframe, params)
        if trade is not None:
            trades.append(trade)
            s = trade["_exit_idx"] + 1
        else:
            s += 1
    return trades


def _trend_ok(direction: str, k: int, candles, ctx, params) -> bool:
    mode = params.trend_filter_mode
    if mode == "none":
        return True
    if mode == "ema":
        ema = ctx["ema"]
        if ema is None:
            return True
        return candles[k]["c"] < ema[k] if direction == "short" else candles[k]["c"] > ema[k]
    if mode == "structure":
        hd = ctx["htf_dir"]
        if hd is None:
            return True
        d = hd[k]
        return d == -1 if direction == "short" else d == 1
    return True


def _try_setup(candles, s, end, ctx, symbol, timeframe, params):
    bar = candles[s]
    sh = ctx["last_high"][s]
    sl = ctx["last_low"][s]
    if not sh or not sl:
        return None

    if params.direction in ("both", "short"):
        if bar["h"] > sh["price"] and bar["c"] < sh["price"] and sl["price"] < sh["price"]:
            tr = _build(candles, s, end, sh, sl, ctx, symbol, timeframe, params, "short")
            if tr:
                return tr
    if params.direction in ("both", "long"):
        if bar["l"] < sl["price"] and bar["c"] > sl["price"] and sh["price"] > sl["price"]:
            tr = _build(candles, s, end, sh, sl, ctx, symbol, timeframe, params, "long")
            if tr:
                return tr
    return None


def _build(candles, s, end, sh, sl, ctx, symbol, timeframe, params, direction):
    short = direction == "short"
    sweep_extreme = candles[s]["h"] if short else candles[s]["l"]
    protected = sl["price"] if short else sh["price"]

    # CHoCH: cierre que rompe el swing opuesto dentro de la ventana.
    k = None
    klim = min(end, s + params.confirm_window)
    for j in range(s + 1, klim + 1):
        if (short and candles[j]["c"] < protected) or ((not short) and candles[j]["c"] > protected):
            k = j
            break
    if k is None:
        return None

    # Filtro de tendencia.
    if not _trend_ok(direction, k, candles, ctx, params):
        return None

    # Filtro de sesión (por hora de la vela del CHoCH; la entrada cae cerca).
    if params.session_filter and session_of(candles[k]["t"]) not in params.session_filter:
        return None

    # Rango del impulso [s, k] para premium/discount.
    imp_hi = max(candles[j]["h"] for j in range(s, k + 1))
    imp_lo = min(candles[j]["l"] for j in range(s, k + 1))
    imp_mid = (imp_hi + imp_lo) / 2.0

    # Zona de entrada: FVG (con filtros de calidad); si no exigimos filtros de FVG,
    # cae al order block como respaldo.
    post_price = candles[k]["c"]
    fvgs = smc.find_fvgs(candles, s, k, bullish=not short)
    atr = ctx["atr"]
    entry_level = None
    if short:
        cands = [f for f in fvgs if f["lo"] > post_price]
    else:
        cands = [f for f in fvgs if f["hi"] < post_price]

    chosen = None
    # Ordenamos por cercanía al precio (retroceso más probable primero).
    cands.sort(key=lambda f: f["lo"] if short else -f["hi"])
    for f in cands:
        if not _fvg_quality_ok(f, candles, atr, params):
            continue
        chosen = f
        break

    if chosen is not None:
        entry_level = chosen["lo"] if short else chosen["hi"]
    elif not (params.use_displacement or params.use_min_fvg):
        ob = smc.find_order_block(candles, s, k, bullish=not short)
        if ob and ((short and ob["lo"] > post_price) or ((not short) and ob["hi"] < post_price)):
            entry_level = ob["lo"] if short else ob["hi"]
    if entry_level is None:
        return None

    # Premium/discount: vender en premium (mitad alta), comprar en discount.
    if params.use_premium_discount:
        if short and entry_level < imp_mid:
            return None
        if (not short) and entry_level > imp_mid:
            return None

    # Stop y riesgo.
    if short:
        stop_level = sweep_extreme * (1 + params.stop_buffer)
        if entry_level >= stop_level:
            return None
        risk = stop_level - entry_level
    else:
        stop_level = sweep_extreme * (1 - params.stop_buffer)
        if entry_level <= stop_level:
            return None
        risk = entry_level - stop_level
    if risk / entry_level < params.min_stop_frac:
        return None

    # Fill de la entrada (orden límite en el retroceso).
    e = None
    elim = min(end, k + params.entry_window)
    for j in range(k + 1, elim + 1):
        if short:
            if candles[j]["h"] >= stop_level:
                return None
            if candles[j]["h"] >= entry_level:
                e = j
                break
        else:
            if candles[j]["l"] <= stop_level:
                return None
            if candles[j]["l"] <= entry_level:
                e = j
                break
    if e is None:
        return None

    tp_level = entry_level - params.rr * risk if short else entry_level + params.rr * risk
    return _simulate(candles, e, end, direction, entry_level, stop_level, tp_level,
                     risk, symbol, timeframe, params)


def _fvg_quality_ok(fvg, candles, atr, params) -> bool:
    idx = fvg["idx"]
    # Tamaño mínimo del FVG (en múltiplos de ATR).
    if params.use_min_fvg:
        a = atr[idx] if idx < len(atr) else 0.0
        if a <= 0 or (fvg["hi"] - fvg["lo"]) < params.min_fvg_atr * a:
            return False
    # Displacement: cuerpo de la vela impulsiva (la del medio del FVG) > X·ATR.
    if params.use_displacement:
        m = idx - 1
        if m < 0:
            return False
        a = atr[m] if m < len(atr) else 0.0
        body = abs(candles[m]["c"] - candles[m]["o"])
        if a <= 0 or body < params.displacement_atr * a:
            return False
    return True


def _simulate(candles, e, end, direction, entry_level, stop_level, tp_level,
              risk, symbol, timeframe, params):
    slip = params.slippage
    comm = params.commission
    exit_idx = min(end, e + params.max_hold)
    outcome = "time"
    exit_level = candles[exit_idx]["c"]
    short = direction == "short"

    for m in range(e + 1, min(end, e + params.max_hold) + 1):
        c = candles[m]
        if short:
            if c["h"] >= stop_level:
                outcome, exit_level, exit_idx = "loss", stop_level, m
                break
            if c["l"] <= tp_level:
                outcome, exit_level, exit_idx = "win", tp_level, m
                break
        else:
            if c["l"] <= stop_level:
                outcome, exit_level, exit_idx = "loss", stop_level, m
                break
            if c["h"] >= tp_level:
                outcome, exit_level, exit_idx = "win", tp_level, m
                break

    if short:
        entry_fill = entry_level * (1 - slip)
        exit_fill = exit_level * (1 + slip) if outcome != "win" else exit_level
        pnl = entry_fill - exit_fill
    else:
        entry_fill = entry_level * (1 + slip)
        exit_fill = exit_level * (1 - slip) if outcome != "win" else exit_level
        pnl = exit_fill - entry_fill

    net = pnl - comm * (entry_fill + exit_fill)
    r_mult = net / risk
    return {
        "symbol": symbol, "timeframe": timeframe, "direction": direction,
        "entry_time": candles[e]["t"], "exit_time": candles[exit_idx]["t"],
        "entry": round(entry_level, 2), "stop": round(stop_level, 2),
        "tp": round(tp_level, 2), "exit": round(exit_level, 2),
        "outcome": outcome, "R": round(r_mult, 4),
        "session": session_of(candles[e]["t"]), "_exit_idx": exit_idx,
    }


# --- Métricas ------------------------------------------------------------
def metrics(trades: List[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "win_rate": 0.0, "expectancy_R": 0.0, "avg_win_R": 0.0,
                "avg_loss_R": 0.0, "profit_factor": 0.0, "max_drawdown_R": 0.0,
                "max_losing_streak": 0, "total_R": 0.0, "wins": 0, "losses": 0,
                "timeouts": 0}
    rs = [t["R"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    ordered = sorted(trades, key=lambda t: t["entry_time"])
    equity = peak = max_dd = 0.0
    streak = max_streak = 0
    for t in ordered:
        equity += t["R"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if t["R"] <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return {
        "trades": n, "wins": len(wins), "losses": len(losses),
        "timeouts": sum(1 for t in trades if t["outcome"] == "time"),
        "win_rate": round(len(wins) / n * 100, 1),
        "expectancy_R": round(sum(rs) / n, 3),
        "avg_win_R": round(gross_win / len(wins), 3) if wins else 0.0,
        "avg_loss_R": round(sum(losses) / len(losses), 3) if losses else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "max_drawdown_R": round(max_dd, 2),
        "max_losing_streak": max_streak,
        "total_R": round(sum(rs), 2),
    }


def equity_curve(trades: List[dict]) -> List[dict]:
    ordered = sorted(trades, key=lambda t: t["entry_time"])
    eq = 0.0
    out = []
    for t in ordered:
        eq += t["R"]
        out.append({"t": t["exit_time"], "R": round(eq, 3)})
    return out


def breakdown(trades: List[dict], key: str) -> dict:
    groups = {}
    for t in trades:
        groups.setdefault(t[key], []).append(t)
    return {g: metrics(ts) for g, ts in groups.items()}
