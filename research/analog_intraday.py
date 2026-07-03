"""Fase 2 del motor de análogos: ZOOM INTRADÍA.

El macro no tuvo edge (solo ~3 ciclos, ~30 casos efectivos). Acá bajamos a 15m/1h de
Binance (~4 años, 4 pares) donde hay MILES de casos y un edge chico SÍ se podría medir.

Reusa el andamiaje de la fase 1 (analog_engine._zwindows / find_analogs): ventanas de
log-precio z-normalizadas, distancia euclidiana z-norm, vecinos válidos solo con datos
anteriores a t (cero look-ahead, igual criterio s<=t-L y s+Hmax<=t).

DISCIPLINA ANTI-DATA-MINING (clave en intradía, donde probamos muchas combinaciones):
  - Split temporal: DESCUBRIMIENTO en el 60% antiguo (IS), CONFIRMACIÓN en el 40%
    reciente (OOS). Un edge solo cuenta si aparece en AMBOS con el mismo signo.
  - Significancia por PERMUTACIÓN vs baseline aleatorio (k vecinos al azar, misma
    estructura de solape) — no binomial ingenuo.
  - Multiplicidad: se prueban pares × escalas × L × horizontes = N hipótesis. Se reporta
    el umbral de Bonferroni y el control de FDR (Benjamini-Hochberg), y cuántos
    "significativos" se esperarían por puro azar.
  - Tamaño efectivo ≈ barras_de_prueba / horizonte (los forward solapan).

Uso:  .venv/bin/python research/analog_intraday.py
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analog_engine import _zwindows, find_analogs   # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
SCALES = ["1h", "15m"]
L_GRID = [16, 24, 48]
HORIZONS = (1, 4, 12)
K = 20
IS_FRAC = 0.60
N_RANDOM = 200
SEED = 20260612

# Submuestreo de puntos de prueba por escala (para acotar el cómputo sin sesgar:
# tomamos 1 de cada `stride` barras, espaciado uniforme).
STRIDE = {"1h": 3, "15m": 12}


def load_series(pair, scale):
    with open(os.path.join(DATA, f"klines_{pair}_{scale}.json"), "r", encoding="utf-8") as fh:
        d = json.load(fh)
    d.sort(key=lambda c: c["t"])
    ts = np.array([c["t"] for c in d], dtype=np.int64)
    cl = np.array([c["c"] for c in d], dtype=float)
    return ts, cl


def _fwd_arrays(logp, horizons):
    n = len(logp)
    fwd = {}
    for h in horizons:
        a = np.full(n, np.nan)
        a[:n - h] = logp[h:] - logp[:n - h]
        fwd[h] = a
    return fwd


def _knn(z, q, last_row, L, K, min_sep):
    """Top-K vecinos (índices de fin s) entre las filas 0..last_row, con separación
    mínima. Usa argpartition para no ordenar toda la historia."""
    cand = z[:last_row + 1]
    d = ((cand - q) ** 2).sum(axis=1)
    M = min(len(d), max(200, K * 12))
    part = np.argpartition(d, M - 1)[:M]
    part = part[np.argsort(d[part])]
    chosen = []
    for r in part:
        s = int(r) + (L - 1)
        if all(abs(s - c) >= min_sep for c in chosen):
            chosen.append(s)
        if len(chosen) >= K:
            break
    return chosen


def validate(pair, scale, L, horizons=HORIZONS, k=K, n_random=N_RANDOM, seed=SEED):
    ts, cl = load_series(pair, scale)
    logp = np.log(cl)
    n = len(cl)
    z, end_idx = _zwindows(logp, L)
    fwd = _fwd_arrays(logp, horizons)
    Hmax = max(horizons)
    min_sep = L
    stride = STRIDE[scale]
    split_t = ts[0] + IS_FRAC * (ts[-1] - ts[0])
    rng = np.random.default_rng(seed + L)

    # acumuladores por (periodo, horizonte)
    def blank():
        return {h: {"an_hit": [], "base_hit": [], "pred": [], "real": [],
                    "edge": [], "rnd": np.zeros(n_random), "cnt": 0, "tms": []}
                for h in horizons}
    acc = {"is": blank(), "oos": blank()}

    t_start = L + Hmax + 50
    for t in range(t_start, n - Hmax, stride):
        s_max = min(t - L, t - Hmax)
        last_row = s_max - (L - 1)
        if last_row < 200:            # historia mínima para tener vecinos
            continue
        q = z[t - (L - 1)]
        chosen = _knn(z, q, last_row, L, k, min_sep)
        if len(chosen) < k:
            continue
        chosen = np.array(chosen)
        period = "is" if ts[t] <= split_t else "oos"
        cand_lo, cand_hi = L - 1, s_max
        for h in horizons:
            real = float(fwd[h][t])
            an_mean = float(np.mean(fwd[h][chosen]))
            base_slice = fwd[h][cand_lo:cand_hi + 1]
            base_mean = float(np.nanmean(base_slice))
            a = acc[period][h]
            a["pred"].append(an_mean); a["real"].append(real)
            a["edge"].append(an_mean - base_mean)
            a["an_hit"].append(int(np.sign(an_mean) == np.sign(real)))
            a["base_hit"].append(int(np.sign(base_mean) == np.sign(real)))
            a["tms"].append(int(ts[t]))
            # baseline aleatorio: k índices al azar del rango de candidatos
            ridx = rng.integers(cand_lo, cand_hi + 1, size=(n_random, k))
            rnd_mean = fwd[h][ridx].mean(axis=1)
            a["rnd"] += (np.sign(rnd_mean) == np.sign(real)).astype(float)
            a["cnt"] += 1

    def summarize(a, h):
        m = len(a[h]["real"])
        if m < 30:
            return {"n": m}
        d = a[h]
        an_hit = float(np.mean(d["an_hit"]))
        base_hit = float(np.mean(d["base_hit"]))
        rnd_rate = d["rnd"] / max(1, d["cnt"])
        p = float((rnd_rate >= an_hit).mean())
        pred = np.array(d["pred"]); real = np.array(d["real"])
        corr = float(np.corrcoef(pred, real)[0, 1]) if pred.std() > 0 else 0.0
        span_bars = (max(d["tms"]) - min(d["tms"])) / (ts[1] - ts[0])
        return {"n": m, "eff_n": int(span_bars / h) + 1,
                "analog_hit": round(an_hit, 4), "baseline_hit": round(base_hit, 4),
                "random_hit_mean": round(float(rnd_rate.mean()), 4),
                "p_value": round(p, 4), "skill": round(an_hit - base_hit, 4),
                "corr": round(corr, 4), "mean_edge": round(float(np.mean(d["edge"])), 5),
                "up_rate": round(float((real > 0).mean()), 4)}

    return {h: {"is": summarize(acc["is"], h), "oos": summarize(acc["oos"], h)}
            for h in horizons}


# --- sesión / régimen (condicionamiento del mejor caso) ------------------
def session_of(t_ms):
    h = time.gmtime(t_ms / 1000).tm_hour
    if 0 <= h < 7:
        return "Asia"
    if 7 <= h < 13:
        return "Londres"
    if 13 <= h < 21:
        return "NY"
    return "Fuera"


def by_session(pair, scale, L, horizon=4, k=K, seed=SEED):
    """Acierto direccional del análogo segmentado por sesión de la barra t (OOS)."""
    ts, cl = load_series(pair, scale)
    logp = np.log(cl); n = len(cl)
    z, end_idx = _zwindows(logp, L)
    fwd = _fwd_arrays(logp, (horizon,))
    Hmax = horizon; min_sep = L; stride = STRIDE[scale]
    split_t = ts[0] + IS_FRAC * (ts[-1] - ts[0])
    groups = {s: [] for s in ("Asia", "Londres", "NY", "Fuera")}
    for t in range(L + Hmax + 50, n - Hmax, stride):
        if ts[t] <= split_t:
            continue
        s_max = min(t - L, t - Hmax); last_row = s_max - (L - 1)
        if last_row < 200:
            continue
        q = z[t - (L - 1)]
        chosen = _knn(z, q, last_row, L, k, min_sep)
        if len(chosen) < k:
            continue
        real = float(fwd[horizon][t])
        an = float(np.mean(fwd[horizon][np.array(chosen)]))
        groups[session_of(int(ts[t]))].append(int(np.sign(an) == np.sign(real)))
    return {s: (len(v), round(float(np.mean(v)), 4) if v else None) for s, v in groups.items()}


# --- multiplicidad -------------------------------------------------------
def bh_fdr(pvals, alpha=0.05):
    """Benjamini-Hochberg: devuelve umbral de p y lista de índices rechazados."""
    idx = np.argsort(pvals)
    m = len(pvals)
    thresh = 0.0
    rejected = []
    for rank, i in enumerate(idx, 1):
        if pvals[i] <= rank / m * alpha:
            thresh = rank / m * alpha
            rejected = list(idx[:rank])
    return thresh, rejected


def current_analogs(pair="BTCUSDT", scale="1h", L=24, k=12):
    ts, cl = load_series(pair, scale)
    res = find_analogs(ts.tolist(), cl.tolist(), L=L, horizons=HORIZONS, k=k)
    # permutación para la foto actual
    logp = np.log(cl); t = len(cl) - 1
    Hmax = max(HORIZONS); s_max = min(t - L, t - Hmax)
    z, end_idx = _zwindows(logp, L)
    cand_end = end_idx[end_idx <= s_max]
    rng = np.random.default_rng(SEED)
    perm = {}
    for h in HORIZONS:
        an = res["forward"][h]["analog"]["mean"]
        base = np.array([logp[int(s) + h] - logp[int(s)] for s in cand_end])
        nm = base[rng.integers(0, len(cand_end), size=(5000, k))].mean(axis=1)
        pct = float((nm <= an).mean())
        perm[h] = {"analog_mean": an, "p_two": round(2 * min(pct, 1 - pct), 3),
                   "percentile": round(pct, 3)}
    return res, perm


def main():
    t0 = time.time()
    print("=" * 92)
    print("  MOTOR DE ANÁLOGOS · FASE 2 INTRADÍA · validación con anti-data-mining")
    print("=" * 92)
    print(f"  Pares {PAIRS} · escalas {SCALES} · L {L_GRID} · horizontes {HORIZONS} · K={K}")
    print(f"  Split IS {int(IS_FRAC*100)}% / OOS {100-int(IS_FRAC*100)}% · permutación N={N_RANDOM}\n")

    rows = []   # (label, scale, L, h, is_dict, oos_dict)
    for scale in SCALES:
        for pair in PAIRS:
            for L in L_GRID:
                res = validate(pair, scale, L)
                for h in HORIZONS:
                    rows.append((pair, scale, L, h, res[h]["is"], res[h]["oos"]))
            print(f"  · {pair} {scale} listo ({time.time()-t0:.0f}s)")

    # Tabla: foco en OOS (confirmación). Edge real ⇒ hit≫random, p<umbral, corr>0, y IS coherente.
    print("\n" + "-" * 92)
    print("  RESULTADOS (foco OOS = confirmación). hitAn vs hitBase('tonto') vs rnd · p=perm · IScoh=signo IS=OOS")
    print("-" * 92)
    hdr = f"  {'par':<8}{'tf':>4}{'L':>4}{'H':>4}{'OOSn':>7}{'effN':>6}{'hitAn':>7}{'hitBase':>8}{'rnd':>7}{'p':>7}{'skill':>7}{'corr':>7}{'IScoh':>6}"
    print(hdr)
    pvals_oos = []
    valid_rows = []
    for (pair, scale, L, h, is_d, oos_d) in rows:
        if oos_d.get("n", 0) < 30 or is_d.get("n", 0) < 30:
            continue
        is_coh = "sí" if np.sign(is_d["analog_hit"] - is_d["random_hit_mean"]) == \
            np.sign(oos_d["analog_hit"] - oos_d["random_hit_mean"]) else "no"
        pvals_oos.append(oos_d["p_value"])
        valid_rows.append((pair, scale, L, h, is_d, oos_d, is_coh))
        print(f"  {pair:<8}{scale:>4}{L:>4}{h:>4}{oos_d['n']:>7}{oos_d['eff_n']:>6}"
              f"{oos_d['analog_hit']:>7}{oos_d['baseline_hit']:>8}{oos_d['random_hit_mean']:>7}"
              f"{oos_d['p_value']:>7}{oos_d['skill']:>7}{oos_d['corr']:>7}{is_coh:>6}")

    # Multiplicidad.
    m = len(pvals_oos)
    bonf = 0.05 / m if m else 0.0
    pv = np.array(pvals_oos)
    thr, rej = bh_fdr(pv, 0.05)
    n_raw = int((pv < 0.05).sum())
    print("\n" + "-" * 92)
    print("  MULTIPLICIDAD (anti-data-mining)")
    print("-" * 92)
    print(f"    Hipótesis OOS probadas: {m}")
    print(f"    Significativos p<0.05 SIN corregir: {n_raw}  (esperados por azar: {0.05*m:.1f})")
    print(f"    Umbral Bonferroni (0.05/{m}): {bonf:.5f}  → significativos: "
          f"{int((pv<bonf).sum())}")
    print(f"    Benjamini-Hochberg FDR 5%: umbral {thr:.5f} → rechazos: {len(rej)}")
    # Listar los que cruzan Bonferroni Y son IS-coherentes (lo único creíble).
    survivors = [vr for vr in valid_rows if vr[5]["p_value"] < bonf and vr[6] == "sí"
                 and vr[5]["skill"] > 0]
    print(f"\n    Sobreviven (p<Bonferroni Y signo coherente IS↔OOS Y skill>0): {len(survivors)}")
    for (pair, scale, L, h, is_d, oos_d, _) in survivors:
        print(f"      {pair} {scale} L={L} H={h}: OOS hit {oos_d['analog_hit']} "
              f"(rnd {oos_d['random_hit_mean']}, p {oos_d['p_value']}), IS hit {is_d['analog_hit']}")

    # Sesión (mejor par/escala, L=24, H=4) para ver si el edge se concentra.
    print("\n" + "-" * 92)
    print("  CONDICIONAMIENTO POR SESIÓN (BTC, L=24, H=4, OOS) — acierto direccional")
    print("-" * 92)
    for scale in SCALES:
        sess = by_session("BTCUSDT", scale, 24, 4)
        cells = "  ".join(f"{s}:{v[1]}(n{v[0]})" for s, v in sess.items())
        print(f"    {scale}: {cells}")

    # Aplicación a BTC actual.
    print("\n" + "=" * 92)
    print("  BTC AHORA — análogos intradía más parecidos (1h, L=24)")
    print("=" * 92)
    res, perm = current_analogs("BTCUSDT", "1h", 24, 12)
    print(f"  Consulta {res['query']['date']} ${res['query']['price']:,.0f} · "
          f"{res['n_candidates']:,} candidatos históricos")
    print(f"  {'fecha':<12}{'dist':>6}{'+1b':>8}{'+4b':>8}{'+12b':>8}")
    for a in res["analogs"]:
        print(f"  {a['date']:<12}{a['distance']:>6.3f}{a['forward'][1]*100:>+7.2f}%"
              f"{a['forward'][4]*100:>+7.2f}%{a['forward'][12]*100:>+7.2f}%")
    print(f"\n  Distribución forward agregada (vs permutación):")
    for h in HORIZONS:
        f = res["forward"][h]["analog"]; pm = perm[h]
        print(f"    +{h:>2}b: media {f['mean']*100:+.2f}% mediana {f['median']*100:+.2f}% "
              f"%+ {f['p_pos']*100:.0f}% | p2lados {pm['p_two']}")

    out = {"generated": int(time.time() * 1000), "grid": {"pairs": PAIRS, "scales": SCALES,
           "L": L_GRID, "horizons": list(HORIZONS), "K": K},
           "rows": [{"pair": p, "scale": s, "L": L, "h": h, "is": isd, "oos": ood}
                    for (p, s, L, h, isd, ood) in rows],
           "multiplicity": {"n_hypotheses": m, "n_raw_sig": n_raw, "bonferroni": bonf,
                            "expected_false_pos": 0.05 * m, "survivors": len(survivors)},
           "current_btc": {"analogs": res["analogs"], "forward": res["forward"], "perm": perm,
                           "query": res["query"]}}
    import math
    def _safe(o):
        if isinstance(o, float):
            return None if (math.isinf(o) or math.isnan(o)) else o
        if isinstance(o, dict):
            return {k: _safe(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_safe(v) for v in o]
        return o
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "analog_intraday.json"), "w", encoding="utf-8") as fh:
        json.dump(_safe(out), fh, ensure_ascii=False, indent=1)
    print(f"\n→ research/analog_intraday.json · total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
