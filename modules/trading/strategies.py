"""Biblioteca de estrategias mecánicas (Fase 2 · laboratorio).

Cada estrategia define:
  - key, name, family
  - grid(): lista de combinaciones de parámetros a probar
  - run(candles, params, ctx): devuelve la lista de trades cerrados

Las estrategias por señales usan el motor genérico (engine.simulate): emiten
señales (i, dirección, stop, rr) y el motor entra en la apertura siguiente, sin
lookahead, con costos. La estrategia SMC reutiliza el motor de la fase anterior.

Para sumar una estrategia nueva: agrega una entrada a STRATEGIES con su grilla y
su función run.
"""
from __future__ import annotations

from typing import List

from . import indicators as ind
from . import smc
from . import engine
from . import backtest
from . import binance

# ---------------------------------------------------------------------------
# Estrategias traducidas de Pine Script (TradingView) de Hugo.
# Salida por ATR como en el script: SL = 1.5·ATR, TP = 2.0·ATR, ATR len 14.
# SIN REPINTADO: las condiciones se evalúan al CIERRE de la vela i y la entrada
# es en la apertura de la vela i+1; los timeframes superiores se usan solo con
# velas YA CERRADAS (map_htf_direction). Si una vela toca SL y TP, gana el SL.
# ---------------------------------------------------------------------------
ATR_LEN = 14
SL_ATR = 1.5
TP_ATR = 2.0
RR_ATR = TP_ATR / SL_ATR   # objetivo en R equivalente (2.0/1.5)


def _ohlcv(candles):
    return ([c["c"] for c in candles], [c["h"] for c in candles],
            [c["l"] for c in candles], [c["v"] for c in candles])


def _atr_stop(close, atr_val, short):
    return close + SL_ATR * atr_val if short else close - SL_ATR * atr_val


def _recent_prices(points, n):
    """Precio del pivote más reciente YA confirmado antes de cada vela (sin futuro)."""
    out = [None] * n
    p = 0
    pts = sorted(points, key=lambda x: x["confirm_idx"])
    for i in range(n):
        while p < len(pts) and pts[p]["confirm_idx"] < i:
            p += 1
        out[i] = pts[p - 1]["price"] if p > 0 else None
    return out


# --- A) Reversión RSI ----------------------------------------------------
def _rsi_rev_dir(candles, p):
    """Dirección de la señal de reversión RSI por vela (+1 long, -1 short, 0)."""
    closes, highs, lows, vols = _ohlcv(candles)
    n = len(candles)
    rsi = ind.rsi(closes, 14)
    svol = ind.sma(vols, p.get("vol_len", 24))
    lo = ind.rolling_min(lows, p.get("ext_len", 20))
    hi = ind.rolling_max(highs, p.get("ext_len", 20))
    out = [0] * n
    for i in range(n):
        if rsi[i] is None or svol[i] is None or lo[i] is None:
            continue
        vol_ok = vols[i] > svol[i]
        if rsi[i] < p["os"] and vol_ok and lows[i] <= lo[i]:
            out[i] = 1
        elif rsi[i] > p["ob"] and vol_ok and highs[i] >= hi[i]:
            out[i] = -1
    return out


def _rsi_rev_signals(candles, p):
    closes, *_ = _ohlcv(candles)
    atr = smc.atr(candles, ATR_LEN)
    d = _rsi_rev_dir(candles, p)
    sig = []
    for i in range(len(candles) - 1):
        if d[i] == 0:
            continue
        sig.append((i, "long" if d[i] > 0 else "short",
                    _atr_stop(closes[i], atr[i], d[i] < 0), RR_ATR))
    return sig


# --- B) Reversión RSI con confluencia multi-temporalidad ----------------
def _rsi_rev_mtf_signals(candles, p, ctx):
    closes, *_ = _ohlcv(candles)
    atr = smc.atr(candles, ATR_LEN)
    base = _rsi_rev_dir(candles, p)
    mapped = []
    for tf, hc in (ctx.get("htf") or {}).items():
        hdir = _rsi_rev_dir(hc, p)
        mapped.append(smc.map_htf_direction(candles, hc, hdir, binance.INTERVAL_MS[tf]))
    sig = []
    for i in range(len(candles) - 1):
        d = base[i]
        if d == 0:
            continue
        # Confirmación: todos los TF superiores (ya cerrados) en la misma dirección.
        if mapped and not all(m[i] == d for m in mapped):
            continue
        sig.append((i, "long" if d > 0 else "short",
                    _atr_stop(closes[i], atr[i], d < 0), RR_ATR))
    return sig


# --- C) Cruce de media (scalp) ------------------------------------------
def _ma_crosses(candles, p):
    closes, *_ = _ohlcv(candles)
    sma = ind.sma(closes, p.get("sma_len", 20))
    out = []
    for i in range(1, len(candles)):
        if sma[i] is None or sma[i - 1] is None:
            continue
        if closes[i] > sma[i] and closes[i - 1] <= sma[i - 1]:
            out.append((i, "long"))
        elif closes[i] < sma[i] and closes[i - 1] >= sma[i - 1]:
            out.append((i, "short"))
    return out


def _ma_cross_run(candles, params, ctx):
    closes, *_ = _ohlcv(candles)
    atr = smc.atr(candles, ATR_LEN)
    crosses = _ma_crosses(candles, params)
    if params.get("exit") == "cross":
        # Salida por cruce opuesto, con stop ATR de protección (sin TP: rr alto).
        sig = [(i, d, _atr_stop(closes[i], atr[i], d == "short"), 100.0) for (i, d) in crosses]
        exit_at = {i for (i, _) in crosses}
        return engine.simulate(candles, sig, ctx["symbol"], ctx["timeframe"], "ma_cross_scalp",
                               exit_at=exit_at, allow_immediate_reentry=True)
    # Salida por ATR (SL 1.5 / TP 2.0).
    sig = [(i, d, _atr_stop(closes[i], atr[i], d == "short"), RR_ATR) for (i, d) in crosses]
    return engine.simulate(candles, sig, ctx["symbol"], ctx["timeframe"], "ma_cross_scalp")


# --- D) Cruce EMA + MACD + divergencia RSI ------------------------------
def _ema_macd_div_signals(candles, p):
    closes, highs, lows, vols = _ohlcv(candles)
    n = len(candles)
    ef = ind.ema(closes, 53)
    es = ind.ema(closes, 200)
    _, _, hist = ind.macd(closes, 12, 26, 9)
    rsi = ind.rsi(closes, 14)
    svol = ind.sma(vols, 20)
    atr = smc.atr(candles, ATR_LEN)
    lb = p.get("div_lb", 5)
    sig = []
    for i in range(max(200, lb + 1), n - 1):
        if rsi[i] is None or rsi[i - lb] is None or svol[i] is None:
            continue
        golden = ef[i] > es[i] and ef[i - 1] <= es[i - 1]
        death = ef[i] < es[i] and ef[i - 1] >= es[i - 1]
        vol_ok = vols[i] > 1.5 * svol[i]
        bull_div = lows[i] < lows[i - lb] and rsi[i] > rsi[i - lb]
        bear_div = highs[i] > highs[i - lb] and rsi[i] < rsi[i - lb]
        if golden and vol_ok and hist[i] > 0 and rsi[i] > 20 and bull_div:
            sig.append((i, "long", _atr_stop(closes[i], atr[i], False), RR_ATR))
        elif death and vol_ok and hist[i] < 0 and rsi[i] < 80 and bear_div:
            sig.append((i, "short", _atr_stop(closes[i], atr[i], True), RR_ATR))
    return sig


# --- E) Liquidity grab (barrido de pivote) ------------------------------
def _liq_grab_signals(candles, p):
    closes, highs, lows, vols = _ohlcv(candles)
    n = len(candles)
    phs, pls = smc.swing_points(candles, p.get("piv", 5))
    last_ph = _recent_prices(phs, n)
    last_pl = _recent_prices(pls, n)
    atr = smc.atr(candles, ATR_LEN)
    sig = []
    for i in range(1, n - 1):
        ph, pl = last_ph[i], last_pl[i]
        if ph is not None and highs[i] > ph and highs[i - 1] <= ph:
            sig.append((i, "short", _atr_stop(closes[i], atr[i], True), RR_ATR))
        if pl is not None and lows[i] < pl and lows[i - 1] >= pl:
            sig.append((i, "long", _atr_stop(closes[i], atr[i], False), RR_ATR))
    return sig


def _ctx_runner(signal_fn, key):
    """Runner que pasa ctx a la función de señales (para MTF)."""
    def run(candles, params, ctx):
        return engine.simulate(candles, signal_fn(candles, params, ctx),
                               ctx["symbol"], ctx["timeframe"], key)
    return run


# ---------------------------------------------------------------------------
# Momentum / tendencia
# ---------------------------------------------------------------------------
def _donchian_signals(candles, p):
    up, lo = ind.donchian(candles, p["n"])
    atr = smc.atr(candles, 14)
    sig = []
    for i in range(p["n"] + 1, len(candles) - 1):
        if up[i] is None or up[i - 1] is None:
            continue
        c, pc = candles[i]["c"], candles[i - 1]["c"]
        if c > up[i] and pc <= up[i - 1]:                 # ruptura alcista nueva
            sig.append((i, "long", c - p["atr_mult"] * atr[i], p["rr"]))
        elif c < lo[i] and pc >= lo[i - 1]:               # ruptura bajista nueva
            sig.append((i, "short", c + p["atr_mult"] * atr[i], p["rr"]))
    return sig


def _ma_cross_signals(candles, p):
    closes = [c["c"] for c in candles]
    ef = ind.ema(closes, p["fast"])
    es = ind.ema(closes, p["slow"])
    atr = smc.atr(candles, 14)
    sig = []
    for i in range(p["slow"] + 1, len(candles) - 1):
        up = ef[i] > es[i] and ef[i - 1] <= es[i - 1]
        dn = ef[i] < es[i] and ef[i - 1] >= es[i - 1]
        if up:
            sig.append((i, "long", candles[i]["c"] - p["atr_mult"] * atr[i], p["rr"]))
        elif dn:
            sig.append((i, "short", candles[i]["c"] + p["atr_mult"] * atr[i], p["rr"]))
    return sig


# ---------------------------------------------------------------------------
# Reversión a la media
# ---------------------------------------------------------------------------
def _rsi_meanrev_signals(candles, p):
    closes = [c["c"] for c in candles]
    rsi = ind.rsi(closes, 14)
    atr = smc.atr(candles, 14)
    ema100 = ind.ema(closes, 100)
    sig = []
    for i in range(120, len(candles) - 1):
        if rsi[i] is None or rsi[i - 1] is None:
            continue
        if p.get("regime"):  # solo en rango: EMA larga plana
            slope = abs(ema100[i] - ema100[i - 20]) / closes[i] if closes[i] else 1
            if slope > p.get("flat", 0.02):
                continue
        if rsi[i - 1] >= p["os"] and rsi[i] < p["os"]:
            sig.append((i, "long", candles[i]["c"] - p["atr_mult"] * atr[i], p["rr"]))
        elif rsi[i - 1] <= p["ob"] and rsi[i] > p["ob"]:
            sig.append((i, "short", candles[i]["c"] + p["atr_mult"] * atr[i], p["rr"]))
    return sig


def _bollinger_meanrev_signals(candles, p):
    closes = [c["c"] for c in candles]
    mid, up, lo, bw = ind.bollinger(closes, p["n"], p["k"])
    atr = smc.atr(candles, 14)
    sig = []
    for i in range(p["n"] + 1, len(candles) - 1):
        if lo[i] is None or lo[i - 1] is None:
            continue
        c, pc = candles[i]["c"], candles[i - 1]["c"]
        if c < lo[i] and pc >= lo[i - 1]:                 # cerró bajo la banda → fade al alza
            sig.append((i, "long", c - p["atr_mult"] * atr[i], p["rr"]))
        elif c > up[i] and pc <= up[i - 1]:               # cerró sobre la banda → fade a la baja
            sig.append((i, "short", c + p["atr_mult"] * atr[i], p["rr"]))
    return sig


# ---------------------------------------------------------------------------
# Ruptura de volatilidad (squeeze de Bollinger)
# ---------------------------------------------------------------------------
def _vol_breakout_signals(candles, p):
    closes = [c["c"] for c in candles]
    mid, up, lo, bw = ind.bollinger(closes, p["n"], 2.0)
    atr = smc.atr(candles, 14)
    sig = []
    for i in range(p["n"] + 1, len(candles) - 1):
        if bw[i] is None or up[i] is None:
            continue
        if bw[i] < p["squeeze"]:                          # bandas comprimidas
            c = candles[i]["c"]
            if c > up[i]:
                sig.append((i, "long", c - p["atr_mult"] * atr[i], p["rr"]))
            elif c < lo[i]:
                sig.append((i, "short", c + p["atr_mult"] * atr[i], p["rr"]))
    return sig


def _signal_runner(signal_fn, key):
    def run(candles, params, ctx):
        sigs = signal_fn(candles, params)
        return engine.simulate(candles, sigs, ctx["symbol"], ctx["timeframe"], key,
                               max_hold=params.get("max_hold", 96))
    return run


# ---------------------------------------------------------------------------
# SMC (reutiliza el motor de la fase 1.5)
# ---------------------------------------------------------------------------
def _smc_run(candles, params, ctx):
    p = backtest.Params(rr=params["rr"], trend_filter_mode=params["trend"],
                        use_premium_discount=params.get("pd", False),
                        session_filter=params.get("sess"))
    trades = backtest.run(candles, ctx["symbol"], ctx["timeframe"], p, ctx.get("htf_dir"))
    for t in trades:
        t["strategy"] = "smc"
    return trades


def _grid(*axes):
    """Producto cartesiano de ejes [(clave, [valores])...] → lista de dicts."""
    combos = [{}]
    for key, vals in axes:
        combos = [{**c, key: v} for c in combos for v in vals]
    return combos


STRATEGIES = [
    {
        "key": "donchian", "name": "Ruptura Donchian", "family": "Tendencia",
        "grid": _grid(("n", [20, 55]), ("atr_mult", [2.0, 3.0]), ("rr", [2.0, 3.0])),
        "run": _signal_runner(_donchian_signals, "donchian"),
    },
    {
        "key": "ma_cross", "name": "Cruce de medias (EMA)", "family": "Tendencia",
        "grid": [{"fast": f, "slow": s, "atr_mult": a, "rr": r}
                 for (f, s) in [(20, 50), (50, 200)] for a in [2.0, 3.0] for r in [2.0, 3.0]],
        "run": _signal_runner(_ma_cross_signals, "ma_cross"),
    },
    {
        "key": "rsi_meanrev", "name": "Reversión RSI (en rango)", "family": "Reversión",
        "grid": [{"os": o, "ob": b, "atr_mult": a, "rr": r, "regime": True, "flat": 0.02}
                 for (o, b) in [(30, 70), (25, 75)] for a in [2.0, 3.0] for r in [1.0, 1.5]],
        "run": _signal_runner(_rsi_meanrev_signals, "rsi_meanrev"),
    },
    {
        "key": "bollinger_meanrev", "name": "Reversión Bollinger", "family": "Reversión",
        "grid": _grid(("n", [20]), ("k", [2.0, 2.5]), ("atr_mult", [2.0, 3.0]), ("rr", [1.0, 1.5])),
        "run": _signal_runner(_bollinger_meanrev_signals, "bollinger_meanrev"),
    },
    {
        "key": "vol_breakout", "name": "Ruptura de volatilidad (squeeze)", "family": "Volatilidad",
        "grid": _grid(("n", [20]), ("squeeze", [0.03, 0.05]), ("atr_mult", [2.0, 3.0]), ("rr", [2.0, 3.0])),
        "run": _signal_runner(_vol_breakout_signals, "vol_breakout"),
    },
    {
        "key": "smc", "name": "SMC (barrido + CHoCH + FVG)", "family": "SMC",
        "grid": _grid(("rr", [2.0, 3.0]), ("trend", ["ema", "structure"])),
        "run": _smc_run,
    },
    # --- Traducidas del Pine Script de Hugo (salida ATR 1.5/2.0) ---
    {
        "key": "rsi_rev", "name": "Reversión RSI (TV)", "family": "Reversión",
        "grid": [{"os": 30, "ob": 70}, {"os": 25, "ob": 75}],
        "run": _signal_runner(_rsi_rev_signals, "rsi_rev"),
    },
    {
        "key": "rsi_rev_mtf", "name": "Reversión RSI + confluencia MTF (TV)", "family": "Reversión",
        "grid": [{"os": 30, "ob": 70}, {"os": 25, "ob": 75}],
        "run": _ctx_runner(_rsi_rev_mtf_signals, "rsi_rev_mtf"),
    },
    {
        "key": "ma_cross_scalp", "name": "Cruce de media SMA20 (TV)", "family": "Tendencia",
        "grid": [{"sma_len": 20, "exit": "atr"}, {"sma_len": 20, "exit": "cross"}],
        "run": _ma_cross_run,
    },
    {
        "key": "ema_macd_div", "name": "EMA 53/200 + MACD + divergencia (TV)", "family": "Confluencia",
        "grid": [{"div_lb": 5}],
        "run": _signal_runner(_ema_macd_div_signals, "ema_macd_div"),
    },
    {
        "key": "liq_grab", "name": "Liquidity grab (barrido de pivote, TV)", "family": "SMC",
        "grid": [{"piv": 5}, {"piv": 10}],
        "run": _signal_runner(_liq_grab_signals, "liq_grab"),
    },
]


def describe(key, params) -> str:
    """Etiqueta legible de una config (para el reporte)."""
    if key == "donchian":
        return f"Donchian n={params['n']} · stop {params['atr_mult']}·ATR · {params['rr']}R"
    if key == "ma_cross":
        return f"EMA {params['fast']}/{params['slow']} · stop {params['atr_mult']}·ATR · {params['rr']}R"
    if key == "rsi_meanrev":
        return f"RSI {params['os']}/{params['ob']} · stop {params['atr_mult']}·ATR · {params['rr']}R · en rango"
    if key == "bollinger_meanrev":
        return f"Bollinger {params['n']}/{params['k']} · stop {params['atr_mult']}·ATR · {params['rr']}R"
    if key == "vol_breakout":
        return f"Squeeze<{params['squeeze']} · stop {params['atr_mult']}·ATR · {params['rr']}R"
    if key == "smc":
        return f"SMC {params['rr']}R · tendencia {params['trend']}"
    if key == "rsi_rev":
        return f"RSI<{params['os']}/>{params['ob']} + vol + extremo20 · salida ATR"
    if key == "rsi_rev_mtf":
        return f"RSI<{params['os']}/>{params['ob']} + confluencia TF superiores · salida ATR"
    if key == "ma_cross_scalp":
        return f"SMA{params['sma_len']} cruce · salida {params['exit']}"
    if key == "ema_macd_div":
        return f"EMA 53/200 + MACD>0 + vol·1.5 + divergencia (lb {params['div_lb']})"
    if key == "liq_grab":
        return f"Barrido de pivote (sens {params['piv']}) · salida ATR"
    return str(params)
