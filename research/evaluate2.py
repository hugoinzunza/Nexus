"""Segunda etapa: combinaciones de los filtros ganadores, validación IS+OOS juntas,
bootstrap de confianza (clave por el fat-tail) y slice BTC+ETH (lo que Hugo opera).

Toda mejora se exige en IS Y OOS (no solo OOS), con costos. El bootstrap estima la
incertidumbre de la expectativa dado que pocas ganadoras grandes dominan.

Uso:  python3 research/evaluate2.py
"""
from __future__ import annotations

import json
import os

from evaluate import (TRADES, metrics, evaluate, split, win, net_R, cost_R,  # noqa: F401
                      MIN_OOS_TRADES, MIN_PF, feat, long)

HERE = os.path.dirname(os.path.abspath(__file__))


def _pf(v):
    return "∞" if v == float("inf") else v


def line(m):
    return f"n={m['n']:<4} win={m['win']:>4}%  exp={m['exp']:>6}R  PF={_pf(m['pf']):>5}  ΣR={m['totalR']}"


# Predicados base reutilizables.
def trend_2050(t): return feat(t, "ema_20_50") == 1
def trend_slope(t): return feat(t, "ema200_slope_dir") == 1
def trend_any(t):
    """Tendencia 'suave': al menos 2 de 3 señales de tendencia a favor."""
    s = sum(1 for k in ("ema_9_21", "ema_20_50", "ema200_slope_dir") if feat(t, k) == 1)
    return s >= 2
def vix_calm(t): return feat(t, "vix") is not None and feat(t, "vix") < 20
def vix_mid(t): return feat(t, "vix") is not None and feat(t, "vix") < 25
def adx_strong(t): return (feat(t, "adx") or 0) > 25


COMBOS = [
    ("BASE (sin filtro)", lambda t: True),
    ("VIX<25", vix_mid),
    ("VIX<20", vix_calm),
    ("Tendencia EMA20/50", trend_2050),
    ("Pendiente EMA200 a favor", trend_slope),
    ("ADX>25", adx_strong),
    ("VIX<25 + Tendencia EMA20/50", lambda t: vix_mid(t) and trend_2050(t)),
    ("VIX<25 + Pendiente EMA200", lambda t: vix_mid(t) and trend_slope(t)),
    ("VIX<20 + Tendencia EMA20/50", lambda t: vix_calm(t) and trend_2050(t)),
    ("VIX<25 + ADX>25", lambda t: vix_mid(t) and adx_strong(t)),
    ("VIX<25 + tendencia(2 de 3)", lambda t: vix_mid(t) and trend_any(t)),
    ("Tendencia EMA20/50 + ADX>25", lambda t: trend_2050(t) and adx_strong(t)),
]


def bootstrap_ci(trades, pred, costs=True, B=2000, seed=12345):
    """IC 90% de la expectativa (R) del subconjunto filtrado, por remuestreo.
    Sin Math.random (no disponible en workflows, sí en script normal): usamos un PRNG
    determinista propio para reproducibilidad."""
    kept = [t for t in trades if pred(t) and t["status"] in ("ganada", "perdida")]
    rs = [(net_R(t) if costs else t["r_gross"]) for t in kept]
    n = len(rs)
    if n < 10:
        return None
    # LCG determinista.
    state = seed
    def rnd():
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return state / 0x7FFFFFFF
    means = []
    for _ in range(B):
        s = 0.0
        for _ in range(n):
            s += rs[int(rnd() * n)]
        means.append(s / n)
    means.sort()
    lo = means[int(0.05 * B)]
    hi = means[int(0.95 * B)]
    p_pos = sum(1 for m in means if m > 0) / B
    return {"n": n, "mean": round(sum(rs) / n, 3), "ci90": [round(lo, 3), round(hi, 3)],
            "p_exp_gt0": round(p_pos, 3)}


def main():
    with open(TRADES, "r", encoding="utf-8") as fh:
        trades = json.load(fh)
    closed = [t for t in trades if t["status"] in ("ganada", "perdida")]
    btc_eth = [t for t in closed if t["pair"] in ("BTCUSDT", "ETHUSDT")]

    print("=" * 80)
    print("COMBINACIONES · IS y OOS juntas (con costos). Mejora exigida en AMBAS.")
    print("=" * 80)
    print(f"  {'variante':<34}{'IS exp':>8}{'ISpf':>6}{'OOS exp':>9}{'OOSpf':>7}{'OOSn':>6}{'WFexp':>7}")
    rows = []
    for name, pred in COMBOS:
        e = evaluate(closed, pred, True)
        i, o, w = e["is"], e["oos"], e["wf"]
        rows.append((name, e))
        both = "✅" if (i["exp"] > 0 and o["exp"] > 0 and o["n"] >= MIN_OOS_TRADES
                       and (o["pf"] if o["pf"] != float("inf") else 9) >= MIN_PF and w["exp"] > 0) else "  "
        print(f"  {name[:33]:<34}{i['exp']:>8}{_pf(i['pf']):>6}{o['exp']:>9}"
              f"{_pf(o['pf']):>7}{o['n']:>6}{w['exp']:>7}  {both}")

    print("\n" + "=" * 80)
    print("BOOTSTRAP de la expectativa OOS (IC 90%, 2000 resamples) — finalistas")
    print("=" * 80)
    sp = split(closed)
    oos = [t for t in closed if t["t"] >= sp]
    for name, pred in COMBOS:
        ci = bootstrap_ci(oos, pred, True)
        if ci:
            print(f"  {name[:38]:<40} exp={ci['mean']:>6}R  IC90=[{ci['ci90'][0]:>6},{ci['ci90'][1]:>6}]  "
                  f"P(exp>0)={ci['p_exp_gt0']}  n={ci['n']}")

    print("\n" + "=" * 80)
    print("SLICE BTC+ETH (lo que Hugo opera de verdad) · con costos")
    print("=" * 80)
    print(f"  {'variante':<34}{'IS exp':>8}{'OOS exp':>9}{'OOSpf':>7}{'OOSn':>6}{'fullExp':>8}{'fulln':>6}")
    for name, pred in COMBOS:
        e = evaluate(btc_eth, pred, True)
        i, o, f = e["is"], e["oos"], e["full"]
        print(f"  {name[:33]:<34}{i['exp']:>8}{o['exp']:>9}{_pf(o['pf']):>7}{o['n']:>6}"
              f"{f['exp']:>8}{f['n']:>6}")

    # Guardar resumen para el informe.
    out = {"combos": [{"name": n, "is": e["is"], "oos": e["oos"], "wf": e["wf"],
                       "full": e["full"]} for n, e in rows],
           "bootstrap_oos": {n: bootstrap_ci(oos, p, True) for n, p in COMBOS},
           "btc_eth": {n: evaluate(btc_eth, p, True) for n, p in COMBOS}}
    import math
    def _safe(o):
        if isinstance(o, float):
            return None if (math.isinf(o) or math.isnan(o)) else o
        if isinstance(o, dict):
            return {k: _safe(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_safe(v) for v in o]
        return o
    with open(os.path.join(HERE, "combo_results.json"), "w", encoding="utf-8") as fh:
        json.dump(_safe(out), fh, ensure_ascii=False, indent=1)
    print("\n→ research/combo_results.json")


if __name__ == "__main__":
    main()
