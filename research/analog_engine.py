"""Motor de ANÁLOGOS macro para BTC (analog forecasting honesto).

Dada una serie de precios y una fecha t, busca en la HISTORIA ANTERIOR las ventanas
más parecidas (en forma, z-normalizadas) a la ventana actual, y devuelve la
distribución empírica de lo que pasó DESPUÉS de cada análogo. No predice: mide.

Diseño anti-look-ahead (lo más importante):
  - La ventana-consulta es series[t-L+1 .. t] (solo barras ya cerradas).
  - Un vecino que termina en s es válido solo si:
       (a) NO se solapa con la consulta:           s <= t - L
       (b) su resultado forward ya ocurrió antes de t (outcome conocible):
                                                    s + max(horizontes) <= t
    Con (a)+(b) garantizamos que tanto el match como el "qué pasó después" usan
    EXCLUSIVAMENTE información anterior a t. Esto vale igual para el pronóstico en
    vivo (t = última barra) y para el walk-forward (t en el pasado).

Similitud: distancia euclidiana sobre ventanas z-normalizadas (lo mismo que usa el
matrix profile / STUMPY). Opcional: DTW con banda de Sakoe-Chiba para tolerar
desfases temporales. Se trabaja sobre LOG-precio (movimientos proporcionales).

API principal:
  find_analogs(ts, closes, t_index=None, L=26, horizons=(1,4,12), k=10,
               metric="zeuclid", dtw_band=0.1)
    → dict con: query, analogs[], forward (por horizonte: muestras + stats),
      baseline (distribución incondicional para comparar), meta.
"""
from __future__ import annotations

import math
import time
from typing import Optional, Sequence

import numpy as np


# --- utilidades ----------------------------------------------------------
def _znorm(w: np.ndarray) -> np.ndarray:
    m = w.mean()
    s = w.std()
    if s < 1e-9:
        return w - m
    return (w - m) / s


def _zwindows(logp: np.ndarray, L: int):
    """Matriz de ventanas z-normalizadas (N-L+1, L). La fila i termina en índice i+L-1."""
    if len(logp) < L:
        return np.empty((0, L)), np.array([], dtype=int)
    sw = np.lib.stride_tricks.sliding_window_view(logp, L)   # (N-L+1, L)
    mean = sw.mean(axis=1, keepdims=True)
    std = sw.std(axis=1, keepdims=True)
    std = np.where(std < 1e-9, 1.0, std)
    z = (sw - mean) / std
    end_idx = np.arange(L - 1, len(logp))
    return z, end_idx


def _dtw(a: np.ndarray, b: np.ndarray, band: float = 0.1) -> float:
    """DTW con banda de Sakoe-Chiba (fracción de L). a,b ya z-normalizados."""
    n, m = len(a), len(b)
    w = max(1, int(band * max(n, m)))
    INF = float("inf")
    prev = np.full(m + 1, INF)
    prev[0] = 0.0
    for i in range(1, n + 1):
        cur = np.full(m + 1, INF)
        lo = max(1, i - w)
        hi = min(m, i + w)
        for j in range(lo, hi + 1):
            cost = (a[i - 1] - b[j - 1]) ** 2
            cur[j] = cost + min(prev[j], cur[j - 1], prev[j - 1])
        prev = cur
    return math.sqrt(prev[m])


# --- estadística de una muestra -----------------------------------------
def _stats(x: Sequence[float]) -> dict:
    a = np.asarray(x, dtype=float)
    n = len(a)
    if n == 0:
        return {"n": 0}
    return {
        "n": n,
        "mean": float(a.mean()),
        "median": float(np.median(a)),
        "std": float(a.std(ddof=1)) if n > 1 else 0.0,
        "p_pos": float((a > 0).mean()),
        "q10": float(np.quantile(a, 0.10)),
        "q25": float(np.quantile(a, 0.25)),
        "q75": float(np.quantile(a, 0.75)),
        "q90": float(np.quantile(a, 0.90)),
        "min": float(a.min()),
        "max": float(a.max()),
    }


def find_analogs(ts: Sequence[int], closes: Sequence[float],
                 t_index: Optional[int] = None, L: int = 26,
                 horizons: Sequence[int] = (1, 4, 12), k: int = 10,
                 metric: str = "zeuclid", dtw_band: float = 0.1,
                 min_sep: Optional[int] = None) -> dict:
    """Encuentra los k análogos de la ventana que termina en t_index y la
    distribución forward. Ver docstring del módulo para el detalle anti-look-ahead.

    min_sep: separación mínima en barras entre vecinos elegidos (deduplica solapados);
             por defecto L//2 para que no salgan k copias casi iguales del mismo tramo.
    """
    closes = np.asarray(closes, dtype=float)
    ts = np.asarray(ts)
    n = len(closes)
    if t_index is None:
        t_index = n - 1
    Hmax = max(horizons)
    if min_sep is None:
        min_sep = max(1, L // 2)
    if t_index < L - 1:
        raise ValueError("t_index demasiado temprano para una ventana de largo L")

    logp = np.log(closes)
    z, end_idx = _zwindows(logp, L)
    # Ventana-consulta (z-norm) que termina en t_index.
    qrow = np.where(end_idx == t_index)[0]
    if len(qrow) == 0:
        raise ValueError("t_index fuera de rango para ventanas")
    q = z[qrow[0]]

    # Candidatos válidos: terminan en s con s <= t-L (no solape) y s+Hmax <= t.
    s_max = min(t_index - L, t_index - Hmax)
    valid_mask = end_idx <= s_max
    cand_z = z[valid_mask]
    cand_end = end_idx[valid_mask]
    if len(cand_end) == 0:
        raise ValueError("sin candidatos válidos (historia insuficiente antes de t)")

    # Distancias.
    if metric == "zeuclid":
        dist = np.sqrt(((cand_z - q) ** 2).sum(axis=1))
    elif metric == "dtw":
        dist = np.array([_dtw(q, cand_z[i], dtw_band) for i in range(len(cand_z))])
    else:
        raise ValueError(metric)

    order = np.argsort(dist)
    # Selección top-k con separación mínima (evita vecinos casi idénticos del mismo tramo).
    chosen = []
    for oi in order:
        s = int(cand_end[oi])
        if all(abs(s - c) >= min_sep for c, _ in chosen):
            chosen.append((s, float(dist[oi])))
        if len(chosen) >= k:
            break

    # Retornos forward (log) de cada análogo y del baseline incondicional.
    def fwd(s, h):
        return float(logp[s + h] - logp[s])

    analogs = []
    fwd_by_h = {h: [] for h in horizons}
    for s, d in chosen:
        rec = {"end_index": s, "date": time.strftime("%Y-%m-%d", time.gmtime(ts[s] / 1000)),
               "t_ms": int(ts[s]), "distance": round(d, 4), "forward": {}}
        for h in horizons:
            r = fwd(s, h)
            rec["forward"][h] = r
            fwd_by_h[h].append(r)
        analogs.append(rec)

    # Baseline incondicional: TODOS los candidatos válidos (misma restricción temporal).
    base_by_h = {h: [fwd(int(s), h) for s in cand_end] for h in horizons}

    # Similitud→peso (para una versión ponderada por cercanía).
    dists = np.array([d for _, d in chosen]) if chosen else np.array([])
    weights = np.exp(-dists / (dists.mean() + 1e-9)) if len(dists) else np.array([])
    weights = (weights / weights.sum()) if weights.sum() > 0 else weights

    forward = {}
    for h in horizons:
        s_an = _stats(fwd_by_h[h])
        s_bl = _stats(base_by_h[h])
        wmean = float(np.dot(weights, fwd_by_h[h])) if len(weights) else s_an.get("mean", 0.0)
        forward[h] = {
            "samples": [round(x, 4) for x in fwd_by_h[h]],
            "analog": s_an,
            "weighted_mean": wmean,
            "baseline": s_bl,                       # distribución incondicional
            "edge_mean": s_an.get("mean", 0.0) - s_bl.get("mean", 0.0),
        }

    return {
        "query": {"t_index": t_index, "L": L, "metric": metric,
                  "date": time.strftime("%Y-%m-%d", time.gmtime(ts[t_index] / 1000)),
                  "price": float(closes[t_index])},
        "k": len(analogs), "horizons": list(horizons),
        "analogs": analogs,
        "forward": forward,
        "n_candidates": int(len(cand_end)),
    }


# --- STUMPY: descubrimiento de motifs macro (vista global, cross-check) ---
def top_motifs(closes: Sequence[float], L: int = 26, n_motifs: int = 3):
    """Usa el matrix profile (STUMPY) para encontrar los pares de ventanas macro más
    parecidos de TODA la historia (motifs). Vista descriptiva, NO para pronóstico
    (un matrix profile self-join mira toda la serie). Devuelve índices de cada par."""
    import stumpy
    arr = np.log(np.asarray(closes, dtype=float))
    mp = stumpy.stump(arr, m=L)
    prof = mp[:, 0].astype(float).copy()
    out = []
    excl = L
    for _ in range(n_motifs):
        i = int(np.argmin(prof))
        if not np.isfinite(prof[i]):
            break
        j = int(mp[i, 1])
        out.append({"i": i, "j": j, "dist": float(mp[i, 0])})
        lo, hi = max(0, i - excl), min(len(prof), i + excl)
        prof[lo:hi] = np.inf
        lo, hi = max(0, j - excl), min(len(prof), j + excl)
        prof[lo:hi] = np.inf
    return out


if __name__ == "__main__":
    import btc_history
    ts, cl = btc_history.get_series("weekly")
    res = find_analogs(ts, cl, L=26, horizons=(1, 4, 12), k=8)
    print(f"Consulta: {res['query']['date']} precio {res['query']['price']:.0f} "
          f"· L={res['query']['L']} · candidatos={res['n_candidates']}")
    print("\nTop análogos (fecha · distancia · fwd +12s):")
    for a in res["analogs"]:
        print(f"  {a['date']}  d={a['distance']:.3f}  +12s={a['forward'][12]*100:+.1f}%")
    print("\nDistribución forward (análogos vs baseline incondicional):")
    for h in res["horizons"]:
        f = res["forward"][h]
        a, b = f["analog"], f["baseline"]
        print(f"  +{h:2}s: análogo media {a['mean']*100:+5.1f}% (mediana {a['median']*100:+5.1f}%, "
              f"%+={a['p_pos']*100:.0f}%, n={a['n']}) | base media {b['mean']*100:+5.1f}% "
              f"| edge {f['edge_mean']*100:+.1f}%")
