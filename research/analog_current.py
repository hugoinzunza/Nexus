"""Aplicación del motor de análogos a la situación ACTUAL de BTC (jun 2026).

Entrega lo que Hugo quiere ver:
  - los N ciclos/ventanas históricas más parecidas a la ventana actual,
  - qué siguió en cada una (+1, +4, +12 semanas),
  - la distribución agregada con stats de confianza,
  - un TEST DE PERMUTACIÓN: ¿la distribución de los análogos es distinguible de elegir
    fechas al azar? (p-valor honesto para la foto de hoy),
  - cross-check con STUMPY (motifs macro de toda la historia),
  - contexto top-down (BTC vs SPX, VIX, BTC vs MA50s, RSI de ciclo) — DESCRIPTIVO.

Guarda research/analog_current.json para el informe.
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import btc_history
from analog_engine import find_analogs, top_motifs, _zwindows

HORIZONS = (1, 4, 12)
SEED = 20260612


def permutation_test(ts, closes, t_index, L, horizons, k, B=5000, seed=SEED):
    """Para cada horizonte: ¿qué tan inusual es la media forward de los k análogos
    frente a 5000 selecciones de k fechas válidas al azar? Devuelve p (dos colas) y
    el percentil del análogo en la distribución nula."""
    logp = np.log(np.asarray(closes, dtype=float))
    z, end_idx = _zwindows(logp, L)
    Hmax = max(horizons)
    s_max = min(t_index - L, t_index - Hmax)
    cand_end = end_idx[end_idx <= s_max]
    rng = np.random.default_rng(seed)
    res = {}
    # análogos reales
    fa = find_analogs(ts, closes, t_index=t_index, L=L, horizons=horizons, k=k)
    for h in horizons:
        an_mean = fa["forward"][h]["analog"]["mean"]
        base_fwd = np.array([logp[int(s) + h] - logp[int(s)] for s in cand_end])
        idxs = rng.integers(0, len(cand_end), size=(B, k))
        null_means = base_fwd[idxs].mean(axis=1)
        pct = float((null_means <= an_mean).mean())
        p_two = 2 * min(pct, 1 - pct)
        res[h] = {"analog_mean": an_mean, "null_mean": float(null_means.mean()),
                  "percentile": round(pct, 3), "p_two_sided": round(p_two, 3),
                  "null_q10": float(np.quantile(null_means, 0.10)),
                  "null_q90": float(np.quantile(null_means, 0.90))}
    return res, fa


def macro_context(ts_now):
    """Contexto top-down descriptivo (no predictivo): VIX, corr BTC-SPX, BTC vs MA50s,
    RSI semanal de ciclo."""
    ctx = {}
    try:
        import macro as macro_mod
        m = macro_mod.Macro()
        ctx["vix"] = round(m.vix_at(ts_now), 1) if m.vix_at(ts_now) else None
        ctx["btc_spx_corr30"] = round(m.corr_at(ts_now), 2) if m.corr_at(ts_now) is not None else None
    except Exception as e:  # noqa: BLE001
        ctx["macro_error"] = str(e)[:80]
    ts, cl = btc_history.get_series("weekly")
    cl = np.asarray(cl)
    ma50 = cl[-50:].mean()
    ctx["btc_price"] = float(cl[-1])
    ctx["btc_ma50w"] = round(float(ma50), 0)
    ctx["btc_vs_ma50w"] = "sobre" if cl[-1] > ma50 else "bajo"
    # RSI semanal (14) de cierre, como proxy de "RSI de ciclo".
    diff = np.diff(cl)
    gain = np.where(diff > 0, diff, 0.0)
    loss = np.where(diff < 0, -diff, 0.0)
    p = 14
    ag = gain[:p].mean(); al = loss[:p].mean()
    for i in range(p, len(diff)):
        ag = (ag * (p - 1) + gain[i]) / p
        al = (al * (p - 1) + loss[i]) / p
    rs = ag / al if al > 0 else 99
    ctx["rsi_weekly"] = round(100 - 100 / (1 + rs), 1)
    return ctx


def main():
    print("=" * 78)
    print("  MOTOR DE ANÁLOGOS · BTC situación actual (jun 2026)")
    print("=" * 78)
    out = {"generated": int(time.time() * 1000), "scales": {}}

    for scale in ("weekly", "biweekly"):
        ts, cl = btc_history.get_series(scale)
        L = 26 if scale == "weekly" else 13     # ~6 meses en ambas escalas
        k = 8
        perm, fa = permutation_test(ts, cl, len(cl) - 1, L, HORIZONS, k)
        print(f"\n## {scale.upper()} · ventana L={L} (~6 meses) · consulta "
              f"{fa['query']['date']} ${fa['query']['price']:,.0f} · "
              f"{fa['n_candidates']} candidatos históricos")
        print(f"\n  {k} ventanas históricas más parecidas a HOY:")
        print(f"    {'fecha':<12}{'dist':>6}   {'+1s':>7}{'+4s':>8}{'+12s':>8}")
        for a in fa["analogs"]:
            print(f"    {a['date']:<12}{a['distance']:>6.3f}   "
                  f"{a['forward'][1]*100:>+6.1f}%{a['forward'][4]*100:>+7.1f}%"
                  f"{a['forward'][12]*100:>+7.1f}%")
        print(f"\n  Distribución agregada (análogos) vs baseline incondicional + permutación:")
        print(f"    {'H':>4}{'media':>8}{'mediana':>9}{'%+':>6}{'q10':>8}{'q90':>8}"
              f"{'base':>8}{'pctil':>7}{'p2lados':>9}")
        for h in HORIZONS:
            f = fa["forward"][h]; a = f["analog"]; b = f["baseline"]; pm = perm[h]
            print(f"    +{h:>2}{a['mean']*100:>7.1f}%{a['median']*100:>8.1f}%"
                  f"{a['p_pos']*100:>5.0f}%{a['q10']*100:>7.1f}%{a['q90']*100:>7.1f}%"
                  f"{b['mean']*100:>7.1f}%{pm['percentile']:>7}{pm['p_two_sided']:>9}")
        out["scales"][scale] = {"query": fa["query"], "analogs": fa["analogs"],
                                "forward": {h: fa["forward"][h] for h in HORIZONS},
                                "permutation": perm}

    # STUMPY: motifs macro de toda la historia (cross-check descriptivo).
    ts, cl = btc_history.get_series("weekly")
    print("\n" + "-" * 78)
    print("  STUMPY · motifs macro más repetidos en la historia (L=26, descriptivo)")
    try:
        motifs = top_motifs(cl, L=26, n_motifs=3)
        for mt in motifs:
            di = time.strftime("%Y-%m", time.gmtime(ts[mt["i"]] / 1000))
            dj = time.strftime("%Y-%m", time.gmtime(ts[mt["j"]] / 1000))
            print(f"    {di}  ≈  {dj}   (dist z-norm {mt['dist']:.2f})")
        out["motifs"] = motifs
    except Exception as e:  # noqa: BLE001
        print("    STUMPY no disponible:", str(e)[:80])

    # Contexto top-down.
    ctx = macro_context(int(ts[-1]))
    print("\n  CONTEXTO top-down (descriptivo, NO predictivo):")
    print(f"    BTC ${ctx['btc_price']:,.0f} · {ctx['btc_vs_ma50w']} su MA50s "
          f"(${ctx['btc_ma50w']:,.0f}) · RSI semanal {ctx.get('rsi_weekly')}")
    print(f"    VIX {ctx.get('vix')} · corr BTC-SPX 30d {ctx.get('btc_spx_corr30')}")
    out["context"] = ctx

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "analog_current.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
    print("\n→ research/analog_current.json")


if __name__ == "__main__":
    main()
