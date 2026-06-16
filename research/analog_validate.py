"""Validación honesta del motor de análogos: ¿tienen EDGE CONDICIONAL real, o son
ruido disfrazado?

Tres pruebas, todas sin look-ahead (cada pronóstico en t usa solo datos < t; el
retorno realizado en t+h se usa solo para PUNTUAR, que es evaluación OOS legítima):

  1) WALK-FORWARD direccional. Para cada t del set de prueba, el motor predice el
     signo del retorno forward (media de los k análogos). Se compara con:
       - el retorno realizado (acierto/falla),
       - un BASELINE de deriva (predecir el signo de la media incondicional),
       - un BASELINE ALEATORIO (k vecinos al azar, B repeticiones) → p-valor que
         respeta la autocorrelación por solape.
  2) EDGE de la media: ¿la media forward de los análogos supera a la incondicional,
     de forma consistente (no por un outlier)?
  3) RÉGIMEN: desglose por tendencia macro de BTC (sobre/bajo su MA de 50 semanas)
     y por calidad del match (distancia del vecino más cercano).

Honestidad de muestra: con horizonte H y solape, los t consecutivos NO son
independientes. Se reporta el TAMAÑO EFECTIVO ≈ semanas_de_prueba / H y se usa el
baseline aleatorio (misma estructura de solape) para la significancia, no un binomial
ingenuo.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import btc_history
from analog_engine import _zwindows

HORIZONS = (1, 4, 12)
L_GRID = (13, 26, 52)
K = 8
TEST_FROM = "2018-01-01"     # set de prueba: cuando ya hay historia suficiente
RNG_SEED = 20260612


def _lean_forecast(logp, z, end_idx, t, L, Hmax, k, min_sep):
    """Media forward de los k análogos en t y candidatos válidos. Sin dicts pesados."""
    qpos = t - (L - 1)                      # fila de la ventana que termina en t
    if qpos < 0 or qpos >= len(z):
        return None
    q = z[qpos]
    s_max = min(t - L, t - Hmax)
    if s_max < L - 1:
        return None
    # candidatos: filas cuyo end_idx <= s_max
    last = s_max - (L - 1)                  # índice de fila para end_idx==s_max
    if last < 0:
        return None
    cz = z[:last + 1]
    ce = end_idx[:last + 1]
    dist = np.sqrt(((cz - q) ** 2).sum(axis=1))
    order = np.argsort(dist)
    chosen = []
    for oi in order:
        s = int(ce[oi])
        if all(abs(s - c) >= min_sep for c in chosen):
            chosen.append(s)
        if len(chosen) >= k:
            break
    return {"chosen": chosen, "cand_end": ce, "nearest_dist": float(dist[order[0]])}


def run_walkforward(ts, closes, L, horizons=HORIZONS, k=K, test_from=TEST_FROM,
                    n_random=400, seed=RNG_SEED):
    logp = np.log(np.asarray(closes, dtype=float))
    z, end_idx = _zwindows(logp, L)
    n = len(closes)
    Hmax = max(horizons)
    min_sep = max(1, L // 2)
    t_from = time.mktime(time.strptime(test_from, "%Y-%m-%d")) * 1000
    rng = np.random.default_rng(seed)

    # acumuladores por horizonte
    recs = {h: {"an_hit": [], "base_hit": [], "pred": [], "real": [],
                "edge": [], "rnd_hits": np.zeros(n_random), "nearest": [], "t_ms": []}
            for h in horizons}
    rnd_counts = {h: 0 for h in horizons}

    for t in range(L - 1, n - Hmax):
        if ts[t] < t_from:
            continue
        fc = _lean_forecast(logp, z, end_idx, t, L, Hmax, k, min_sep)
        if fc is None or len(fc["chosen"]) < k:
            continue
        chosen = fc["chosen"]
        ce = fc["cand_end"]
        for h in horizons:
            real = float(logp[t + h] - logp[t])
            an_fwd = np.array([logp[s + h] - logp[s] for s in chosen])
            an_mean = float(an_fwd.mean())
            base_fwd = np.array([logp[int(s) + h] - logp[int(s)] for s in ce])
            base_mean = float(base_fwd.mean())
            r = recs[h]
            r["pred"].append(an_mean); r["real"].append(real)
            r["edge"].append(an_mean - base_mean)
            r["an_hit"].append(int(np.sign(an_mean) == np.sign(real)))
            r["base_hit"].append(int(np.sign(base_mean) == np.sign(real)))
            r["nearest"].append(fc["nearest_dist"]); r["t_ms"].append(int(ts[t]))
            # baseline aleatorio: k vecinos al azar de los candidatos
            idxs = rng.integers(0, len(ce), size=(n_random, k))
            rnd_mean = base_fwd[idxs].mean(axis=1)
            r["rnd_hits"] += (np.sign(rnd_mean) == np.sign(real)).astype(float)
            rnd_counts[h] += 1

    out = {}
    for h in horizons:
        r = recs[h]
        m = len(r["real"])
        if m == 0:
            out[h] = {"n": 0}
            continue
        an_hit = float(np.mean(r["an_hit"]))
        base_hit = float(np.mean(r["base_hit"]))
        rnd_hit_dist = r["rnd_hits"] / max(1, rnd_counts[h])    # tasa de acierto por réplica
        p_val = float((rnd_hit_dist >= an_hit).mean())          # p de superar al azar
        pred = np.array(r["pred"]); real = np.array(r["real"])
        corr = float(np.corrcoef(pred, real)[0, 1]) if m > 1 and pred.std() > 0 else 0.0
        eff_n = _effective_n(r["t_ms"], h)
        out[h] = {
            "n": m, "eff_n": eff_n,
            "analog_hit": round(an_hit, 3), "baseline_hit": round(base_hit, 3),
            "random_hit_mean": round(float(rnd_hit_dist.mean()), 3),
            "random_hit_p95": round(float(np.quantile(rnd_hit_dist, 0.95)), 3),
            "p_value_vs_random": round(p_val, 3),
            "skill_vs_baseline": round(an_hit - base_hit, 3),
            "corr_pred_real": round(corr, 3),
            "mean_edge": round(float(np.mean(r["edge"])), 4),
            "up_rate_real": round(float((real > 0).mean()), 3),
        }
    return out


def _effective_n(t_ms_list, h):
    """N efectivo ≈ semanas cubiertas / h (los forward solapan)."""
    if not t_ms_list:
        return 0
    span_weeks = (max(t_ms_list) - min(t_ms_list)) / (7 * 86_400_000)
    return int(span_weeks / h) + 1


def run_regime(ts, closes, L=26, horizons=HORIZONS, k=K, test_from=TEST_FROM):
    """Acierto direccional del análogo por régimen de tendencia (BTC vs MA50 semanas)
    y por calidad de match (distancia del vecino más cercano: tercil bajo = buen match)."""
    logp = np.log(np.asarray(closes, dtype=float))
    z, end_idx = _zwindows(logp, L)
    n = len(closes)
    Hmax = max(horizons)
    min_sep = max(1, L // 2)
    t_from = time.mktime(time.strptime(test_from, "%Y-%m-%d")) * 1000
    ma_w = 50
    ma = np.convolve(closes, np.ones(ma_w) / ma_w, mode="full")[:n]
    ma[:ma_w] = np.nan

    rows = []
    for t in range(L - 1, n - Hmax):
        if ts[t] < t_from or np.isnan(ma[t]):
            continue
        fc = _lean_forecast(logp, z, end_idx, t, L, Hmax, k, min_sep)
        if fc is None or len(fc["chosen"]) < k:
            continue
        chosen = fc["chosen"]
        bull = closes[t] > ma[t]
        row = {"t": t, "bull": bull, "nearest": fc["nearest_dist"]}
        for h in horizons:
            real = float(logp[t + h] - logp[t])
            an_mean = float(np.mean([logp[s + h] - logp[s] for s in chosen]))
            row[f"hit_{h}"] = int(np.sign(an_mean) == np.sign(real))
        rows.append(row)

    def agg(sub, h):
        if not sub:
            return (0, 0.0)
        return (len(sub), round(float(np.mean([r[f"hit_{h}"] for r in sub])), 3))

    near = sorted(r["nearest"] for r in rows)
    thr = near[len(near) // 3] if near else 0.0
    res = {"all": {}, "bull": {}, "bear": {}, "good_match": {}, "poor_match": {}}
    for h in horizons:
        res["all"][h] = agg(rows, h)
        res["bull"][h] = agg([r for r in rows if r["bull"]], h)
        res["bear"][h] = agg([r for r in rows if not r["bull"]], h)
        res["good_match"][h] = agg([r for r in rows if r["nearest"] <= thr], h)
        res["poor_match"][h] = agg([r for r in rows if r["nearest"] > thr], h)
    return res


def main():
    for scale in ("weekly", "biweekly"):
        ts, cl = btc_history.get_series(scale)
        print("\n" + "#" * 78)
        print(f"#  ESCALA: {scale.upper()}  ({len(cl)} barras)")
        print("#" * 78)
        for L in L_GRID:
            if scale == "biweekly" and L > len(cl) // 4:
                continue
            wf = run_walkforward(ts, cl, L)
            print(f"\n  L={L} barras · walk-forward desde {TEST_FROM}")
            print(f"    {'H':>3} {'n':>4} {'effN':>5} {'hitAn':>6} {'hitBase':>8} "
                  f"{'rndMean':>8} {'p_rnd':>6} {'skill':>6} {'corr':>6} {'edge%':>6}")
            for h in HORIZONS:
                r = wf[h]
                if r.get("n", 0) == 0:
                    continue
                print(f"    {h:>3} {r['n']:>4} {r['eff_n']:>5} {r['analog_hit']:>6} "
                      f"{r['baseline_hit']:>8} {r['random_hit_mean']:>8} {r['p_value_vs_random']:>6} "
                      f"{r['skill_vs_baseline']:>6} {r['corr_pred_real']:>6} {r['mean_edge']*100:>6.1f}")

    # Régimen (semanal, L=26)
    ts, cl = btc_history.get_series("weekly")
    reg = run_regime(ts, cl, L=26)
    print("\n" + "=" * 78)
    print("  RÉGIMEN (semanal, L=26): acierto direccional del análogo")
    print("=" * 78)
    print(f"    {'grupo':<12}" + "".join(f"+{h}s(n/hit)".rjust(16) for h in HORIZONS))
    for g in ("all", "bull", "bear", "good_match", "poor_match"):
        cells = "".join(f"{reg[g][h][0]}/{reg[g][h][1]}".rjust(16) for h in HORIZONS)
        print(f"    {g:<12}{cells}")


if __name__ == "__main__":
    main()
