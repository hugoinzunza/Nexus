#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Refugios de Mediano Plazo (RMP) — estudio adversarial pre-registrado.
=====================================================================

QUE SE PRUEBA
-------------
El curso CreceTrader propone una rejilla anual anclada en la apertura del anio:

    RMP(y, k, dir) = O_y * (1 + dir * k * 0.10)      dir = +1 / -1, k = 1..K

y afirma que el precio reacciona ahi "como un reloj". La afirmacion es circular:
se muestran los niveles que reaccionaron y nunca el universo de niveles
atravesados sin reaccion, ni la frecuencia base de una reaccion equivalente en
un precio cualquiera.

La pregunta de este estudio NO es "reacciona el precio en esos niveles" (con
suficientes niveles siempre reacciona en alguno), sino:

    reacciona MAS que una rejilla de igual densidad puesta en otra parte?

Si no supera al placebo, el resultado es "no hay nada" y ese es el entregable.

POR QUE CADA DECISION ES ASI (los comentarios explican el defecto que evitan)
----------------------------------------------------------------------------
* Tolerancia y magnitud en ATR y NUNCA en % fijo. Un 0.3% es ruido en un activo
  y movimiento real en otro; un umbral absoluto sobre una cantidad de escala
  variable es el error que este repo ya cometio seis veces.
* Episodios: contactos cercanos del mismo nivel se agrupan. Contar cada vela que
  toca el nivel como observacion independiente infla n y estrecha el CI hasta
  mentir.
* Causalidad dura: la rejilla del anio y NO existe antes del 1 de enero de y.
  Sin eso, el ancla de 2025 "predice" 2024 y todo el estudio es circular.
* Niveles no positivos (k >= 10 hacia abajo) se excluyen explicitamente y se
  cuentan: O_y*(1-1.0) = 0 y por debajo es precio negativo, sin significado.
* El conjunto de niveles candidatos y la tolerancia se fijan ANTES y no se
  tocan. El curso calcula muchos porcentajes y despues borra los que caen en
  "tierra de nadie": eso fabrica la confluencia despues de ver el resultado.
* Correccion multiple Holm. En este repo ya paso: 5 de 81 variantes se veian
  significativas sin corregir y ninguna sobrevivio a Holm.
* Bootstrap por bloques: contactos vecinos comparten nivel y regimen, no son
  independientes; un bootstrap iid daria un CI falsamente angosto.

CONTROLES NEGATIVOS (los cuatro son obligatorios)
-------------------------------------------------
 (a) placebo de otra densidad: paso 7.5% y 12.5%, misma construccion.
 (b) ancla desplazada +/-3 dias: misma densidad, ancla sin significado.
 (c) niveles aleatorios emparejados por distancia al ancla.
 (d) numeros redondos: hipotesis competidora obvia que el curso nunca descarta.

USO
---
Solo se evalua utilidad como TARGET / PARCIAL (si el nivel frena al precio),
nunca como direccion de entrada. El propio curso dice que el nivel anual no
genera una entrada por si solo.

Todo el output es research_only / execution_enabled=false. Este script no toca
el bot, no lee credenciales y solo lee data/ (solo lectura).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import random
from collections import defaultdict

import numpy as np

# --------------------------------------------------------------------------
# DISEÑO PRE-REGISTRADO — congelado antes de mirar un solo resultado.
# Cualquier cambio aqui despues de ver resultados invalida el estudio.
# --------------------------------------------------------------------------
PREREG = {
    "study": "refugios_anuales_rmp",
    "frozen_at": "2026-07-26",
    # Sin venue/symbol/quote/timezone explicitos, dos rejillas "correctas"
    # difieren y el estudio deja de ser reproducible. El propio curso admite
    # que Bitstamp, Binance y el indice de TradingView dan aperturas distintas.
    "venue": "binance",
    "market": "klines snapshot versionado en el repo (data/klines_*.json)",
    "quote_asset": "USDT",
    "timezone": "UTC",
    "universe": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"],
    "timeframe_primary": "1d",
    "timeframe_weekly_test": "1h",
    "years_requested": [2022, 2023, 2024, 2025, 2026],
    "anchor_rule": "apertura de la vela diaria cuyo open_time == 1 de enero 00:00 UTC; si no existe, el anio se excluye (no se inventa el ancla)",
    "step": 0.10,
    "k_max": 15,  # la hoja del curso llega a +/-150%
    "drop_non_positive_levels": True,
    # Escala-invariante por construccion: la tolerancia es una fraccion del ATR
    # del propio activo, no un porcentaje fijo.
    "touch_tolerance_atr": 0.25,
    "atr_period": 14,
    "atr_is_causal": "se usa ATR calculado hasta la vela i-1 para evaluar la vela i",
    "episode_gap_bars": 5,
    "reaction_horizon_bars": 5,
    "reaction_threshold_atr": 1.0,
    "penetration_threshold_atr": 0.5,
    "followup_window_bars": 20,  # reclaim / retest
    "level_validity": "solo dentro del anio calendario del ancla (el curso recalcula cada anio)",
    "random_control_replicas": 20,
    "random_control_offset": "u ~ U(0.02, 0.05) con signo aleatorio, sumado al desplazamiento relativo del nivel real",
    "bootstrap_iters": 5000,
    "bootstrap_block": "(activo, anio, trimestre del primer contacto)",
    "multiple_correction": "holm",
    "alpha": 0.05,
    "primary_family": "primer contacto (first_arrival), metricas hit_rate y mean_reaction_atr, 6 contrastes vs controles",
    "decision_rule": {
        "PROMOVER": "supera a los CUATRO controles tras Holm",
        "SEGUIR": "supera a (c) aleatorio y (d) redondos pero no a (a) densidad / (b) ancla desplazada",
        "DESCARTAR": "no separa del placebo de igual densidad",
    },
    "seed": 12345,
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DAY_MS = 86_400_000
HOUR_MS = 3_600_000


# --------------------------------------------------------------------------
# Carga de datos (solo lectura)
# --------------------------------------------------------------------------
def load_klines(pair: str, tf: str):
    """Lee el snapshot local. NO es un feed: tiene ~41 dias de antiguedad y eso
    es lo esperado; el estudio no intenta actualizarlo."""
    path = os.path.join(DATA, f"klines_{pair}_{tf}.json")
    with open(path) as fh:
        raw = json.load(fh)
    raw = sorted(raw, key=lambda x: x["t"])
    return {
        "t": np.array([x["t"] for x in raw], dtype=np.int64),
        "o": np.array([float(x["o"]) for x in raw]),
        "h": np.array([float(x["h"]) for x in raw]),
        "l": np.array([float(x["l"]) for x in raw]),
        "c": np.array([float(x["c"]) for x in raw]),
    }


def atr_prev(bars, period: int):
    """ATR de Wilder desplazado un bar.

    Devuelve un vector donde la posicion i contiene el ATR calculado SOLO con
    informacion hasta i-1. Usar el ATR de la propia vela i seria mirar el
    futuro dentro de la vela que estamos evaluando.
    """
    h, l, c = bars["h"], bars["l"], bars["c"]
    n = len(c)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
    atr = np.full(n, np.nan)
    if n <= period:
        return atr
    atr[period - 1] = tr[:period].mean()
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    out = np.full(n, np.nan)
    out[1:] = atr[:-1]
    return out


def utc_ms(y, m=1, d=1, hh=0):
    return int(dt.datetime(y, m, d, hh, tzinfo=dt.timezone.utc).timestamp() * 1000)


def ms_to_date(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# Construccion de rejillas
# --------------------------------------------------------------------------
def rmp_levels(anchor: float, step: float, k_max: int):
    """Rejilla lineal respecto del ancla (NO compuesta): +20% es O*1.20, no
    O*1.10^2. Devuelve (niveles_validos, n_excluidos_no_positivos).

    Con paso 0.10 y k>=10 hacia abajo el precio es cero o negativo: no tiene
    significado para un activo spot y se descarta explicitamente.
    """
    keep, dropped = [], 0
    for k in range(1, k_max + 1):
        for d in (+1, -1):
            lvl = anchor * (1.0 + d * k * step)
            if lvl <= 0:
                dropped += 1
                continue
            keep.append({"k": k, "dir": d, "rel": d * k * step, "level": lvl})
    return keep, dropped


def round_number_levels(prices: np.ndarray):
    """Rejilla de numeros redondos con paso DERIVADO de los datos.

    Un paso fijo (1000) seria otra vez un umbral absoluto sobre una cantidad de
    escala variable: sirve para BTC y es absurdo para ADA. Se usa
    R = 10^(floor(log10(precio_mediano)) - 1), que reproduce "multiplos de 1000
    en BTC" sin codificarlo a mano.
    """
    med = float(np.median(prices))
    R = 10.0 ** (math.floor(math.log10(med)) - 1)
    lo, hi = float(prices.min()), float(prices.max())
    k0, k1 = int(math.floor(lo / R)), int(math.ceil(hi / R))
    return [{"k": k, "dir": 0, "rel": None, "level": k * R} for k in range(k0, k1 + 1) if k * R > 0], R


def random_levels(base_levels, rng: random.Random, replicas: int, anchor: float):
    """Control (c): niveles aleatorios emparejados por distancia al ancla.

    Cada nivel real O*(1+d) se sustituye por O*(1+d+u) con |u| en [0.02, 0.05].
    Asi la distribucion de distancias al precio se conserva (ese es el
    emparejamiento) pero la rejilla deja de caer en multiplos exactos de 10%.
    La banda inferior 0.02 evita que el "aleatorio" coincida con el nivel real.
    """
    out = []
    for lv in base_levels:
        for r in range(replicas):
            u = rng.uniform(0.02, 0.05) * rng.choice([-1, 1])
            lvl = anchor * (1.0 + lv["rel"] + u)
            if lvl <= 0:
                continue
            out.append({"k": lv["k"], "dir": lv["dir"], "rel": lv["rel"] + u, "level": lvl, "rep": r})
    return out


# --------------------------------------------------------------------------
# Contactos, episodios y metricas de reaccion
# --------------------------------------------------------------------------
def find_episodes(level, bars, atrp, i_start, i_end, tol_mult, gap):
    """Indices del primer bar de cada episodio de contacto.

    Un contacto es: nivel dentro de [low - tol, high + tol] con
    tol = tol_mult * ATR_previo. Contactos separados por menos de `gap` velas
    son el MISMO episodio; si no, cada vela de una consolidacion contra el nivel
    contaria como observacion independiente e inflaria n.
    """
    h, l = bars["h"], bars["l"]
    contacts = []
    for i in range(i_start, i_end):
        a = atrp[i]
        if not np.isfinite(a) or a <= 0:
            continue
        tol = tol_mult * a
        if (l[i] - tol) <= level <= (h[i] + tol):
            contacts.append(i)
    if not contacts:
        return []
    eps, prev = [contacts[0]], contacts[0]
    for i in contacts[1:]:
        if i - prev > gap:
            eps.append(i)
        prev = i
    return eps


def episode_metrics(level, bars, atrp, i0, H, pen_thr, react_thr, follow):
    """Metricas del primer contacto. Devuelve None si no hay ventana completa.

    Separa explicitamente los eventos que el curso mezcla: primera llegada,
    cierre al otro lado, ruptura, reclaim y retest.
    """
    o, h, l, c = bars["o"], bars["h"], bars["l"], bars["c"]
    n = len(c)
    if i0 - 1 < 0 or i0 + H >= n:
        return None
    a = atrp[i0]
    if not np.isfinite(a) or a <= 0:
        return None

    # Direccion de aproximacion segun el cierre PREVIO: si venia por arriba el
    # nivel actua como soporte; si venia por abajo, como resistencia. Usar la
    # propia vela de contacto seria decidir la direccion con el resultado.
    prev_c = float(c[i0 - 1])
    if prev_c == level:
        return None
    # bool() explicito: un np.bool_ se serializa a JSON como el string "True"
    # via default=str y contaminaria las claves de agrupacion del reporte.
    support = bool(prev_c > level)

    win_h = h[i0 : i0 + H + 1]
    win_l = l[i0 : i0 + H + 1]
    win_c = c[i0 : i0 + H + 1]
    fwd_h = h[i0 + 1 : i0 + H + 1]
    fwd_l = l[i0 + 1 : i0 + H + 1]

    if support:
        penetration = max(0.0, level - float(win_l.min())) / a
        reaction = (float(fwd_h.max()) - level) / a
        beyond = bool((win_c < level).any())
        brk_idx = np.where(win_c < level - pen_thr * a)[0]
    else:
        penetration = max(0.0, float(win_h.max()) - level) / a
        reaction = (level - float(fwd_l.min())) / a
        beyond = bool((win_c > level).any())
        brk_idx = np.where(win_c > level + pen_thr * a)[0]

    held = penetration <= pen_thr
    moved = reaction >= react_thr
    hit = bool(held and moved)

    reclaim = retest = None
    broke = len(brk_idx) > 0
    if broke:
        b = i0 + int(brk_idx[0])
        j1 = min(n, b + 1 + follow)
        if b + 1 + follow <= n:  # sin ventana completa el evento queda censurado
            seg_c = c[b + 1 : j1]
            if support:
                reclaim = bool((seg_c > level).any())
            else:
                reclaim = bool((seg_c < level).any())
            rt = False
            for i in range(b + 1, j1):
                aa = atrp[i]
                if np.isfinite(aa) and aa > 0 and (l[i] - pen_thr * aa) <= level <= (h[i] + pen_thr * aa):
                    rt = True
                    break
            retest = rt

    return {
        "i0": int(i0),
        "t": int(bars["t"][i0]),
        "date": ms_to_date(int(bars["t"][i0])),
        "support": support,
        "atr": float(a),
        "reaction_atr": float(reaction),
        "penetration_atr": float(penetration),
        "held": bool(held),
        "moved": bool(moved),
        "hit": hit,
        "close_beyond": beyond,
        "broke": bool(broke),
        "reclaim": reclaim,
        "retest": retest,
    }


# --------------------------------------------------------------------------
# Pivotes causales y regresion (utilidad incremental)
# --------------------------------------------------------------------------
def causal_pivots(bars, wing=5):
    """Pivotes swing con confirmacion causal.

    Un pivote en j solo se conoce en j+wing. Guardamos (confirmed_at, precio)
    para que la distancia a pivote nunca use informacion futura: ese es el
    error clasico que convierte cualquier estudio de niveles en un oraculo.
    """
    h, l = bars["h"], bars["l"]
    n = len(h)
    piv = []
    for j in range(wing, n - wing):
        if h[j] == h[j - wing : j + wing + 1].max():
            piv.append((j + wing, float(h[j])))
        if l[j] == l[j - wing : j + wing + 1].min():
            piv.append((j + wing, float(l[j])))
    piv.sort()
    return piv


def dist_to_pivot_atr(piv, i, level, atr):
    known = [p for (ca, p) in piv if ca <= i]
    if not known or atr <= 0:
        return None
    return min(abs(p - level) for p in known) / atr


def logistic_irls(X, y, ridge=1e-3, iters=60):
    """Regresion logistica minima (no hay scipy en este entorno).

    IRLS con ridge pequeño solo para que no explote con columnas casi
    colineales; no es un modelo de produccion, es una comprobacion de que el
    efecto (si existiera) no es solo distancia a pivote o volatilidad.
    """
    n, k = X.shape
    b = np.zeros(k)
    # numpy 2.x + el BLAS de este Mac levantan flags FP espurios en matmul con
    # entradas perfectamente finitas. Se silencian aqui y se verifica la
    # finitud a mano mas abajo, en vez de esconder un problema real.
    if not np.all(np.isfinite(X)) or not np.all(np.isfinite(y)):
        return np.full(k, np.nan)
    with np.errstate(all="ignore"):
        for _ in range(iters):
            z = np.clip(X @ b, -30, 30)
            p = 1.0 / (1.0 + np.exp(-z))
            W = np.clip(p * (1 - p), 1e-6, None)
            H = X.T @ (X * W[:, None]) + ridge * np.eye(k)
            g = X.T @ (y - p) - ridge * b
            try:
                step = np.linalg.solve(H, g)
            except np.linalg.LinAlgError:
                break
            # Amortiguacion: sin esto, con bloques bootstrap casi separables el
            # paso de Newton diverge y el coeficiente reportado seria basura.
            step = np.clip(step, -2.0, 2.0)
            b_new = b + step
            if not np.all(np.isfinite(b_new)):
                break
            b = b_new
            if np.max(np.abs(step)) < 1e-8:
                break
    return b


# --------------------------------------------------------------------------
# Estadistica: bootstrap por bloques + Holm
# --------------------------------------------------------------------------
def block_bootstrap_diff(blocks_a, blocks_b, iters, rng_seed, stat="mean"):
    """CI y p de la diferencia media(A) - media(B) remuestreando BLOQUES.

    Los episodios vecinos comparten nivel y regimen: un bootstrap iid sobre
    episodios daria un CI angosto y mentiroso. Se remuestrean los bloques
    (activo, anio, trimestre) y ambos brazos viajan juntos, lo que ademas
    preserva el emparejamiento temporal entre rejilla real y control.
    """
    keys = sorted(set(blocks_a) | set(blocks_b))
    A = defaultdict(list)
    B = defaultdict(list)
    for k, v in blocks_a.items():
        A[k] = list(v)
    for k, v in blocks_b.items():
        B[k] = list(v)
    obs_a = [x for k in keys for x in A.get(k, [])]
    obs_b = [x for k in keys for x in B.get(k, [])]
    if not obs_a or not obs_b:
        return None
    point = float(np.mean(obs_a) - np.mean(obs_b))
    rs = np.random.RandomState(rng_seed)
    kidx = np.arange(len(keys))
    diffs = np.empty(iters)
    packA = [np.array(A.get(k, []), dtype=float) for k in keys]
    packB = [np.array(B.get(k, []), dtype=float) for k in keys]
    for it in range(iters):
        pick = rs.choice(kidx, size=len(keys), replace=True)
        sa = np.concatenate([packA[i] for i in pick if packA[i].size]) if any(packA[i].size for i in pick) else None
        sb = np.concatenate([packB[i] for i in pick if packB[i].size]) if any(packB[i].size for i in pick) else None
        if sa is None or sb is None:
            diffs[it] = np.nan
            continue
        diffs[it] = sa.mean() - sb.mean()
    d = diffs[np.isfinite(diffs)]
    if d.size < 100:
        return None
    lo, hi = float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))
    p = 2.0 * min((d <= 0).mean(), (d >= 0).mean())
    return {
        "n_a": len(obs_a),
        "n_b": len(obs_b),
        "mean_a": float(np.mean(obs_a)),
        "mean_b": float(np.mean(obs_b)),
        "diff": point,
        "ci95": [lo, hi],
        "p_raw": float(min(1.0, p)),
        "n_blocks": len(keys),
    }


def binom_two_sided(k, n, p):
    """Test binomial exacto de dos colas (no hay scipy).

    Se usa para los cortes por k: son 20 celdas, y sin correccion alguna
    aparecera "el nivel magico" por puro azar. Este test existe para poder
    matarlo con Holm, no para venderlo.
    """
    if n == 0:
        return 1.0
    lg = math.lgamma

    def pmf(i):
        return math.exp(lg(n + 1) - lg(i + 1) - lg(n - i + 1) + i * math.log(p) + (n - i) * math.log(1 - p))

    obs = pmf(k)
    tot = sum(pmf(i) for i in range(n + 1) if pmf(i) <= obs * (1 + 1e-9))
    return min(1.0, tot)


def holm(pvals):
    """Holm-Bonferroni. Sin esto, con muchos k, pares y eventos se "encuentra"
    algo por puro azar; ya paso en este repo (5/81 variantes "significativas",
    ninguna sobrevivio)."""
    idx = sorted(range(len(pvals)), key=lambda i: pvals[i])
    m = len(pvals)
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(idx):
        val = (m - rank) * pvals[i]
        running = max(running, val)
        adj[i] = min(1.0, running)
    return adj


# --------------------------------------------------------------------------
# Motor del estudio diario
# --------------------------------------------------------------------------
FAMILIES = ["rmp_10", "placebo_7.5", "placebo_12.5", "shift_-3", "shift_+3", "random", "round"]


def build_year_families(pair, bars, atrp, year, rng):
    """Construye todas las familias de niveles para (pair, year).

    CAUSALIDAD: todas las familias existen desde el 1 de enero de `year` y solo
    dentro de ese anio. La rejilla de y jamas se evalua sobre y-1.
    """
    t = bars["t"]
    j0, j1 = utc_ms(year, 1, 1), utc_ms(year + 1, 1, 1)
    idx0 = np.where(t == j0)[0]
    if idx0.size == 0:
        return None  # no hay vela del 1 de enero: el anio se excluye, no se inventa el ancla
    i_anchor = int(idx0[0])
    anchor = float(bars["o"][i_anchor])
    i_end = int(np.searchsorted(t, j1))

    fam = {}
    base, dropped = rmp_levels(anchor, PREREG["step"], PREREG["k_max"])
    fam["rmp_10"] = base
    p75, d75 = rmp_levels(anchor, 0.075, PREREG["k_max"])
    fam["placebo_7.5"] = p75
    p125, d125 = rmp_levels(anchor, 0.125, PREREG["k_max"])
    fam["placebo_12.5"] = p125

    shifts = {}
    for lbl, off in (("shift_-3", -3), ("shift_+3", +3)):
        k = np.where(t == j0 + off * DAY_MS)[0]
        if k.size == 0:
            shifts[lbl] = None
            continue
        a2 = float(bars["o"][int(k[0])])
        lv, _ = rmp_levels(a2, PREREG["step"], PREREG["k_max"])
        shifts[lbl] = (a2, lv)
        fam[lbl] = lv
    for lbl in ("shift_-3", "shift_+3"):
        fam.setdefault(lbl, [])

    fam["random"] = random_levels(base, rng, PREREG["random_control_replicas"], anchor)

    yr_prices = np.concatenate([bars["l"][i_anchor:i_end], bars["h"][i_anchor:i_end]])
    rnd_levels, R = round_number_levels(yr_prices)
    fam["round"] = rnd_levels

    return {
        "anchor": anchor,
        "anchor_t": int(t[i_anchor]),
        "anchor_date": ms_to_date(int(t[i_anchor])),
        "i_anchor": i_anchor,
        "i_end": i_end,
        "families": fam,
        "dropped_non_positive": {"rmp_10": dropped, "placebo_7.5": d75, "placebo_12.5": d125},
        "round_step": R,
        "shift_anchors": {k: (v[0] if v else None) for k, v in shifts.items()},
    }


def run_daily_study():
    rng = random.Random(PREREG["seed"])
    episodes = []  # cada primer contacto con ventana completa
    coverage = []  # niveles totales / tocados por familia
    anchors_meta = []
    dropped_total = defaultdict(int)
    years_excluded = []

    pivots_cache = {}

    for pair in PREREG["universe"]:
        bars = load_klines(pair, "1d")
        atrp = atr_prev(bars, PREREG["atr_period"])
        piv = causal_pivots(bars, wing=5)
        pivots_cache[pair] = (bars, atrp, piv)

        for year in PREREG["years_requested"]:
            built = build_year_families(pair, bars, atrp, year, rng)
            if built is None:
                years_excluded.append({"pair": pair, "year": year, "reason": "sin vela diaria del 1-ene 00:00 UTC en el snapshot"})
                continue
            anchors_meta.append(
                {
                    "pair": pair,
                    "year": year,
                    "venue": PREREG["venue"],
                    "quote_asset": PREREG["quote_asset"],
                    "timezone": PREREG["timezone"],
                    "annual_open_t": built["anchor_t"],
                    "annual_open_date": built["anchor_date"],
                    "annual_open_price": built["anchor"],
                    "shift_anchors": built["shift_anchors"],
                    "round_step": built["round_step"],
                    "window_end_date": ms_to_date(int(bars["t"][min(built["i_end"], len(bars["t"]) - 1)])),
                }
            )
            for kfam, v in built["dropped_non_positive"].items():
                dropped_total[kfam] += v

            i0, i1 = built["i_anchor"], built["i_end"]
            for fam_name, levels in built["families"].items():
                touched = 0
                for lv in levels:
                    eps = find_episodes(
                        lv["level"], bars, atrp, i0, i1,
                        PREREG["touch_tolerance_atr"], PREREG["episode_gap_bars"],
                    )
                    if not eps:
                        continue
                    touched += 1
                    m = episode_metrics(
                        lv["level"], bars, atrp, eps[0],
                        PREREG["reaction_horizon_bars"], PREREG["penetration_threshold_atr"],
                        PREREG["reaction_threshold_atr"], PREREG["followup_window_bars"],
                    )
                    if m is None:
                        continue
                    q = (int(m["date"][5:7]) - 1) // 3 + 1
                    m.update(
                        {
                            "pair": pair,
                            "year": year,
                            "family": fam_name,
                            "k": lv["k"],
                            "dir": lv["dir"],
                            "level": lv["level"],
                            "n_episodes_year": len(eps),
                            "block": f"{pair}|{year}|Q{q}",
                            "dist_pivot_atr": dist_to_pivot_atr(piv, eps[0], lv["level"], m["atr"]),
                            "vol_ratio": m["atr"] / float(bars["c"][eps[0]]),
                        }
                    )
                    episodes.append(m)
                coverage.append(
                    {
                        "pair": pair,
                        "year": year,
                        "family": fam_name,
                        "n_levels": len(levels),
                        "n_levels_touched": touched,
                    }
                )

    return episodes, coverage, anchors_meta, dict(dropped_total), years_excluded, pivots_cache


# --------------------------------------------------------------------------
# Apertura semanal (1h)
# --------------------------------------------------------------------------
def run_weekly_study():
    """Apertura semanal vs precio aleatorio de la semana anterior.

    Semana Binance UTC: lunes 00:00 UTC. NO se usa la semana de Londres de los
    ejemplos del curso, que ademas cambia con DST y haria el nivel irreproducible.
    Se saltan las primeras 24h porque el precio TOCA la apertura por definicion
    al abrir la semana: contarlo seria un contacto trivial garantizado.
    """
    rng = random.Random(PREREG["seed"] + 7)
    rows = []
    for pair in PREREG["universe"]:
        bars = load_klines(pair, "1h")
        atrp = atr_prev(bars, PREREG["atr_period"])
        t = bars["t"]
        # lunes 00:00 UTC: epoch 1970-01-01 fue jueves -> offset 4 dias
        week_id = ((t // HOUR_MS) + 24 * 3) // (24 * 7)
        uniq = np.unique(week_id)
        for w in uniq[1:]:
            idx = np.where(week_id == w)[0]
            if idx.size < 24 * 5:
                continue
            i_open = int(idx[0])
            i_from, i_to = i_open + 24, int(idx[-1]) + 1
            if i_from >= i_to:
                continue
            wopen = float(bars["o"][i_open])
            prev_idx = np.where(week_id == w - 1)[0]
            if prev_idx.size < 24:
                continue
            rnd_level = float(bars["c"][int(rng.choice(list(prev_idx)))])
            d = ms_to_date(int(t[i_open]))
            q = (int(d[5:7]) - 1) // 3 + 1
            block = f"{pair}|{d[:4]}|Q{q}"
            for name, lvl in (("weekly_open", wopen), ("random_prev_week", rnd_level)):
                eps = find_episodes(lvl, bars, atrp, i_from, i_to, PREREG["touch_tolerance_atr"], 12)
                if not eps:
                    continue
                m = episode_metrics(lvl, bars, atrp, eps[0], 12, PREREG["penetration_threshold_atr"], PREREG["reaction_threshold_atr"], 48)
                if m is None:
                    continue
                m.update({"pair": pair, "family": name, "block": block, "level": lvl, "date": d})
                rows.append(m)
    return rows


# --------------------------------------------------------------------------
# Contrastes
# --------------------------------------------------------------------------
def by_block(eps, family, metric):
    out = defaultdict(list)
    for e in eps:
        if e["family"] != family:
            continue
        v = e[metric]
        if v is None:
            continue
        out[e["block"]].append(float(v))
    return out


def run_contrasts(episodes, metrics, treat, controls, seed_base, label):
    tests = []
    for mi, metric in enumerate(metrics):
        A = by_block(episodes, treat, metric)
        for ci, ctrl in enumerate(controls):
            B = by_block(episodes, ctrl, metric)
            res = block_bootstrap_diff(A, B, PREREG["bootstrap_iters"], seed_base + 100 * mi + ci)
            if res is None:
                continue
            res.update({"family_test": label, "metric": metric, "treatment": treat, "control": ctrl})
            tests.append(res)
    if tests:
        adj = holm([t["p_raw"] for t in tests])
        for t, a in zip(tests, adj):
            t["p_holm"] = a
            t["significant_holm"] = bool(a < PREREG["alpha"] and t["diff"] > 0)
    return tests


def summarize(episodes, group_keys=("family",)):
    agg = defaultdict(list)
    for e in episodes:
        key = tuple(e[k] for k in group_keys)
        agg[key].append(e)
    out = {}
    for key, rows in sorted(agg.items()):
        def rate(f):
            vals = [r[f] for r in rows if r[f] is not None]
            return (float(np.mean(vals)) if vals else None, len(vals))
        hr, nh = rate("hit")
        hd, _ = rate("held")
        mv, _ = rate("moved")
        cb, _ = rate("close_beyond")
        bk, _ = rate("broke")
        rc, nrc = rate("reclaim")
        rt, nrt = rate("retest")
        out["|".join(str(x) for x in key)] = {
            "n_episodes": len(rows),
            "mean_reaction_atr": float(np.mean([r["reaction_atr"] for r in rows])),
            "median_reaction_atr": float(np.median([r["reaction_atr"] for r in rows])),
            "mean_penetration_atr": float(np.mean([r["penetration_atr"] for r in rows])),
            "hit_rate": hr,
            "held_rate": hd,
            "moved_rate": mv,
            "close_beyond_rate": cb,
            "break_rate": bk,
            "reclaim_rate": rc, "n_reclaim": nrc,
            "retest_rate": rt, "n_retest": nrt,
        }
    return out


def incremental_utility(episodes):
    """hit ~ is_rmp + distancia al pivote causal + volatilidad relativa.

    Si el coeficiente de is_rmp se apaga al controlar por pivote y volatilidad,
    la rejilla no aporta informacion propia: es lo que el curso nunca chequea.
    """
    pool = [e for e in episodes if e["family"] in ("rmp_10", "random", "round") and e["dist_pivot_atr"] is not None]
    if len(pool) < 200:
        return {"status": "muestra insuficiente", "n": len(pool)}
    # Los continuos van estandarizados: en escala cruda (ATR vs ratio de
    # volatilidad) el Hessiano queda mal condicionado y el coeficiente de
    # is_rmp se vuelve numericamente inestable, no informativo.
    def z(v):
        v = np.asarray(v, dtype=float)
        s = v.std()
        return (v - v.mean()) / (s if s > 0 else 1.0)

    X = np.column_stack([
        np.ones(len(pool)),
        np.array([1.0 if e["family"] == "rmp_10" else 0.0 for e in pool]),
        z([min(e["dist_pivot_atr"], 10.0) for e in pool]),
        z([e["vol_ratio"] for e in pool]),
        np.array([1.0 if e["family"] == "round" else 0.0 for e in pool]),
    ])
    y = np.array([1.0 if e["hit"] else 0.0 for e in pool])
    b = logistic_irls(X, y)
    # CI por bootstrap de bloques sobre el coeficiente de is_rmp
    blocks = defaultdict(list)
    for i, e in enumerate(pool):
        blocks[e["block"]].append(i)
    keys = list(blocks)
    rs = np.random.RandomState(PREREG["seed"])
    boots = []
    for _ in range(400):
        pick = rs.choice(len(keys), size=len(keys), replace=True)
        idx = [i for p in pick for i in blocks[keys[p]]]
        if len(set(y[idx])) < 2:
            continue
        boots.append(logistic_irls(X[idx], y[idx])[1])
    ci = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))] if len(boots) > 50 else None
    return {
        "n": len(pool),
        "terms": ["intercept", "is_rmp", "dist_pivot_atr_z", "vol_ratio_z", "is_round"],
        "coef": [float(x) for x in b],
        "is_rmp_coef": float(b[1]),
        "is_rmp_ci95_block_bootstrap": ci,
    }


# --------------------------------------------------------------------------
def main():
    episodes, coverage, anchors, dropped, years_excluded, _ = run_daily_study()
    weekly = run_weekly_study()

    controls = ["placebo_7.5", "placebo_12.5", "shift_-3", "shift_+3", "random", "round"]

    # FAMILIA PRIMARIA pre-registrada: primer contacto, 2 metricas x 6 controles
    # = 12 contrastes, con Holm dentro de la familia.
    primary = run_contrasts(episodes, ["hit", "reaction_atr"], "rmp_10", controls, 1000, "primary")

    # Utilidad como target/parcial: 'held' = el nivel freno al precio (no lo
    # atraveso 0.5 ATR). Es lo unico que el curso permite evaluar; la direccion
    # de entrada queda fuera por diseño.
    target_tests = run_contrasts(episodes, ["held"], "rmp_10", controls, 3000, "target_utility")

    # Secundario exploratorio por activo, con su propio Holm. Se reporta como
    # exploratorio para que nadie lo lea como confirmatorio.
    secondary = []
    for pair in PREREG["universe"]:
        eps_p = [e for e in episodes if e["pair"] == pair]
        A = by_block(eps_p, "rmp_10", "hit")
        for ci, ctrl in enumerate(controls):
            B = by_block(eps_p, ctrl, "hit")
            res = block_bootstrap_diff(A, B, 2000, 5000 + ci)
            if res is None:
                continue
            res.update({"family_test": "secondary_per_asset", "pair": pair, "metric": "hit", "control": ctrl})
            secondary.append(res)
    if secondary:
        adj = holm([t["p_raw"] for t in secondary])
        for t, a in zip(secondary, adj):
            t["p_holm"] = a
            t["significant_holm"] = bool(a < PREREG["alpha"] and t["diff"] > 0)

    # Cortes por k: EXPLORATORIO. Aqui es donde el data-mining seria mas
    # tentador ("el -40% funciona!"), asi que cada celda se contrasta contra la
    # tasa base del control aleatorio y se corrige por Holm sobre las 20 celdas.
    base_rate = float(np.mean([e["hit"] for e in episodes if e["family"] == "random"]))
    per_k, pk_keys, pk_p = {}, [], []
    for k in range(1, PREREG["k_max"] + 1):
        for d in (1, -1):
            rows = [e for e in episodes if e["family"] == "rmp_10" and e["k"] == k and e["dir"] == d]
            if len(rows) < 5:
                continue
            nhit = int(sum(1 for r in rows if r["hit"]))
            key = f"{'+' if d>0 else '-'}{k*10}%"
            pv = binom_two_sided(nhit, len(rows), base_rate)
            per_k[key] = {
                "n": len(rows),
                "n_hit": nhit,
                "hit_rate": nhit / len(rows),
                "mean_reaction_atr": float(np.mean([r["reaction_atr"] for r in rows])),
                "p_raw_vs_base_rate": pv,
            }
            pk_keys.append(key)
            pk_p.append(pv)
    for key, a in zip(pk_keys, holm(pk_p)):
        per_k[key]["p_holm"] = a
        per_k[key]["significant_holm"] = bool(a < PREREG["alpha"])

    # Auditoria del corte por k: si una celda de la rejilla real sobrevive a
    # Holm, hay que correr EXACTAMENTE el mismo barrido sobre los controles.
    # Si el ancla desplazada (sin significado) produce la misma celda magica,
    # la celda no mide el ancla anual: mide el regimen. Sin este chequeo se
    # publicaria un "nivel que funciona" que es puro ruido correlacionado.
    per_k_control = {}
    for fam in ["rmp_10", "placebo_7.5", "placebo_12.5", "shift_-3", "shift_+3"]:
        keys, ps, cells = [], [], {}
        for k in range(1, PREREG["k_max"] + 1):
            for d in (1, -1):
                rows = [e for e in episodes if e["family"] == fam and e["k"] == k and e["dir"] == d]
                if len(rows) < 5:
                    continue
                nh = int(sum(1 for r in rows if r["hit"]))
                key = f"{'+' if d>0 else '-'}{k*10}%"
                keys.append(key)
                ps.append(binom_two_sided(nh, len(rows), base_rate))
                cells[key] = {"n_hit": nh, "n": len(rows)}
        adj = holm(ps)
        per_k_control[fam] = {
            "n_cells": len(keys),
            "min_p_raw": (min(ps) if ps else None),
            "cells_surviving_holm": [
                {"k_label": k, **cells[k], "p_raw": p, "p_holm": a}
                for k, p, a in zip(keys, ps, adj) if a < PREREG["alpha"]
            ],
        }

    weekly_tests = []
    A = by_block(weekly, "weekly_open", "hit")
    B = by_block(weekly, "random_prev_week", "hit")
    r1 = block_bootstrap_diff(A, B, PREREG["bootstrap_iters"], 9001)
    A2 = by_block(weekly, "weekly_open", "reaction_atr")
    B2 = by_block(weekly, "random_prev_week", "reaction_atr")
    r2 = block_bootstrap_diff(A2, B2, PREREG["bootstrap_iters"], 9002)
    for r, m in ((r1, "hit"), (r2, "reaction_atr")):
        if r:
            r.update({"family_test": "weekly_open", "metric": m, "treatment": "weekly_open", "control": "random_prev_week"})
            weekly_tests.append(r)
    if weekly_tests:
        adj = holm([t["p_raw"] for t in weekly_tests])
        for t, a in zip(weekly_tests, adj):
            t["p_holm"] = a
            t["significant_holm"] = bool(a < PREREG["alpha"] and t["diff"] > 0)

    # cobertura honesta: cuantos niveles NUNCA fueron tocados
    cov = defaultdict(lambda: {"n_levels": 0, "n_levels_touched": 0})
    for c in coverage:
        cov[c["family"]]["n_levels"] += c["n_levels"]
        cov[c["family"]]["n_levels_touched"] += c["n_levels_touched"]
    hits_by_fam = defaultdict(int)
    for e in episodes:
        if e["hit"]:
            hits_by_fam[e["family"]] += 1
    # La tasa incondicional es la respuesta honesta a "reacciona el precio en
    # esos niveles?": el denominador incluye los niveles que el precio NUNCA
    # visito, que es justo lo que el curso no publica.
    cov = {
        k: {
            **v,
            "touch_rate": (v["n_levels_touched"] / v["n_levels"] if v["n_levels"] else None),
            "n_reactions": hits_by_fam.get(k, 0),
            "unconditional_reaction_rate": (hits_by_fam.get(k, 0) / v["n_levels"] if v["n_levels"] else None),
        }
        for k, v in cov.items()
    }

    # veredicto automatico segun la regla pre-registrada
    def beat(ctrls, tests_list, metric=None):
        rel = [t for t in tests_list if t["control"] in ctrls and (metric is None or t["metric"] == metric)]
        return bool(rel) and all(t["significant_holm"] for t in rel)

    density = ["placebo_7.5", "placebo_12.5"]
    shift = ["shift_-3", "shift_+3"]
    beats_all = beat(density + shift + ["random", "round"], primary)
    beats_cd = beat(["random", "round"], primary)
    if beats_all:
        verdict = "PROMOVER"
    elif beats_cd:
        verdict = "SEGUIR"
    else:
        verdict = "DESCARTAR"

    out = {
        "meta": {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "script": "research/refugios_anuales.py",
            "prereg": PREREG,
            "anchors": anchors,
            "years_excluded": years_excluded,
            "non_positive_levels_dropped": dropped,
            "data_note": "snapshot local versionado en el repo, ~41 dias de antiguedad; no es un feed",
        },
        "coverage_levels": cov,
        "coverage_detail": coverage,
        "summary_by_family": summarize(episodes),
        "summary_by_family_year": summarize(episodes, ("family", "year")),
        "summary_by_family_pair": summarize(episodes, ("family", "pair")),
        "summary_by_family_direction": summarize(episodes, ("family", "support")),
        "per_k_exploratory": per_k,
        "per_k_control_check": per_k_control,
        "per_k_control_check_note": (
            "El test binomial por celda asume independencia y NO la hay: los episodios "
            "de distintos activos en la misma semana son el mismo evento de mercado. "
            "Ademas el ancla desplazada reproduce la misma celda 'significativa', "
            "asi que la celda no mide el ancla anual."
        ),
        "tests_primary": primary,
        "tests_target_utility": target_tests,
        "tests_secondary_per_asset": secondary,
        "weekly_open": {"summary": summarize(weekly), "tests": weekly_tests},
        "incremental_utility": incremental_utility(episodes),
        "verdict": verdict,
        "n_episodes_total": len(episodes),
    }

    dest = os.path.join(ROOT, "research", "refugios_anuales_results.json")
    with open(dest, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False, default=str)
    print(f"escrito {dest}")
    print(f"episodios={len(episodes)} veredicto={verdict}")
    for t in primary:
        print(f"  {t['metric']:14s} vs {t['control']:13s} diff={t['diff']:+.4f} "
              f"CI=[{t['ci95'][0]:+.4f},{t['ci95'][1]:+.4f}] p={t['p_raw']:.4f} holm={t['p_holm']:.4f}")
    return out


if __name__ == "__main__":
    main()
