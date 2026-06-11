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
    return str(params)
