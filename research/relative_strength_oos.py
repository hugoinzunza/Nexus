#!/usr/bin/env python3
"""FUERZA RELATIVA vs BTC sobre el universo que el bot SÍ opera — research puro.

HIPÓTESIS (del video, traducida a algo medible): una altcoin cuyo retorno supera
al que le corresponde por su sensibilidad a BTC sería mejor candidata a LONG; la
que rinde por debajo, mejor candidata a SHORT. No se usan diferencias nominales de
precio: se normaliza por retorno, beta y volatilidad.

QUÉ SE MIDE Y SOBRE QUÉ
-----------------------
El universo NO se re-detecta. Se toma el volcado por-trade del pipeline real
(`data/setup_backtest_trades.json`, generado por `run_setup_backtest`, que reusa
`smc_live.analyze` con POIs en 1D/4h/1h proyectados sobre 1h/4h) y se filtra por
`rr >= 5`, que es el `entry_profiles` del plan. Así el baseline de comparación es
literalmente la configuración vigente y no un laboratorio paralelo.

Consecuencia deliberada: **no hay 15m en ninguna parte**. El detector del Diario
usa POI_TFS = ["1D","4h","1h"] y las TF de planeación son 1h y 4h. La lección de
2026-07-25 (el 71% de los setups de research venían de un TF que el bot no opera)
queda neutralizada de raíz, y aun así los cortes por `sel_tf` se publican aparte.

CAUSALIDAD (lo que hace o no hace este script)
----------------------------------------------
* El instante de decisión de un setup es el CIERRE de su barra de señal:
  `run_setup_backtest` llama a `smc_live.analyze` con `last = sel[i]["c"]` y
  resuelve desde `i+1`. El volcado guarda `t = sel[i]["t"]` (apertura). Por eso
  aquí la fuerza relativa se evalúa en `t + TF_MS[sel_tf]` y sólo con velas de 1h
  **ya cerradas** a ese instante (`t_open + 1h <= decisión`). Nunca la barra en curso.
* La beta se estima con una ventana de retornos horarios que TERMINA en esa última
  vela cerrada. No entra ninguna vela posterior (lección del look-ahead de la barra
  de activación: si dudas, arranca en la siguiente).
* El ranking transversal en t se calcula con la foto de t. Añadir velas posteriores
  no lo puede mover (hay un test que lo verifica).
* BTC no se rankea contra sí mismo: el corte transversal son SÓLO las altcoins.
  Los trades de BTC quedan fuera de las variantes condicionadas y se reportan aparte.

DEFINICIONES CONGELADAS ANTES DE MIRAR RESULTADOS
-------------------------------------------------
Ventanas W ∈ {24h, 3d, 7d} sobre cierres de 1h (24, 72, 168 velas).
Beta: OLS de log-retornos horarios del par contra BTC en las últimas 720 velas (30d).
  fuerza_raw    = ret_W(par) − ret_W(BTC)                    (sin ajustar: el control F)
  fuerza_resid  = ret_W(par) − beta · ret_W(BTC)             (la hipótesis)
  fuerza_z      = fuerza_resid / (sigma_resid_horaria · √W)  (ajustada por volatilidad)
Ranking transversal: posición ascendente entre las altcoins disponibles; se normaliza
  u = rank/(N−1) ∈ [0,1]; u=1 es la MÁS fuerte. No tiene parámetro ajustado.
Quintiles de z: cortes estimados SÓLO en IS y aplicados tal cual a OOS.

Split IS/OOS temporal al 70% del calendario de trades (misma convención del repo).
Bootstrap por BLOQUES MENSUALES (los trades están agrupados en el tiempo y entre
pares; remuestrear trades sueltos fabrica independencia y p-valores falsos).

Corre:   .venv/bin/python3 research/relative_strength_oos.py
Escribe: research/relative_strength_oos_results.json
         research/relative_strength_oos_trades.json  (dataset por-trade reproducible)
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import os
import random
import statistics
import sys
from collections import defaultdict

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading.setups_store import _cost_fraction  # noqa: E402

DATA_DIR = os.path.join(WT, "data")
RES_DIR = os.path.join(WT, "research")
DUMP = os.path.join(DATA_DIR, "setup_backtest_trades.json")
OUT_JSON = os.path.join(RES_DIR, "relative_strength_oos_results.json")
OUT_TRADES = os.path.join(RES_DIR, "relative_strength_oos_trades.json")

AVISO = "Research only - No senal - No bot - NO usar para activar live"

# --- universo -----------------------------------------------------------------
BTC = "BTCUSDT"
PARES_PLAN = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]      # config vigente
PARES_TODOS = PARES_PLAN + ["BNBUSDT", "DOGEUSDT"]                        # + datos extra
MIN_RR = 5.0                                                              # entry_profiles

# --- feature (congelado) ------------------------------------------------------
H_MS = 3_600_000
VENTANAS = {"24h": 24, "3d": 72, "7d": 168}
BETA_N = 720                    # 30 días de velas 1h
BETA_ALTS = (168, 2160)         # sensibilidad: 7d y 90d
FEATURES = ("raw", "resid", "z")
TF_MS = {"1h": 3_600_000, "4h": 14_400_000}

# --- costos -------------------------------------------------------------------
# base = modelo maker-aware del Diario. Los adversos se pasan como override plano.
COSTO_DURO = 0.0002 + 0.0005 + 0.0010      # maker in + taker out + 0,10% slippage
COSTO_EXTREMO = 0.0005 + 0.0005 + 0.0030   # taker ambos lados + 0,30% (el tope del plan)

# --- estadística --------------------------------------------------------------
IS_FRAC = 0.70
N_BOOT = 2000
SEED = 20260725
REGIMEN_SMA = 50


# ============================ carga y series =================================

def _load_klines(pair, tf):
    path = os.path.join(DATA_DIR, f"klines_{pair}_{tf}.json")
    with open(path, encoding="utf-8") as fh:
        c = json.load(fh)
    c.sort(key=lambda x: x["t"])
    return c


class Series:
    """Cierres 1h alineados + sumas acumuladas para beta/sigma en O(1).

    Guarda prefijos de r_a, r_b, r_a², r_b², r_a·r_b (r = log-retorno horario, b = BTC)
    para poder pedir la beta de CUALQUIER ventana sin recorrerla. La ventana siempre
    termina en una vela ya cerrada; nada de esto puede leer el futuro porque los
    prefijos se consultan con índices acotados por el instante de decisión.
    """

    def __init__(self, pares):
        self.pares = list(pares)
        raw = {p: _load_klines(p, "1h") for p in self.pares}
        base = [c["t"] for c in raw[BTC]]
        for p in self.pares:
            if [c["t"] for c in raw[p]] != base:
                raise SystemExit(f"grilla 1h desalineada en {p}: el estudio la asume igual")
        self.t = base
        self.close = {p: [c["c"] for c in raw[p]] for p in self.pares}
        self.n = len(base)
        self.lr = {}
        for p in self.pares:
            cl = self.close[p]
            self.lr[p] = [0.0] + [math.log(cl[i] / cl[i - 1]) for i in range(1, self.n)]
        b = self.lr[BTC]
        self._pref = {}
        for p in self.pares:
            a = self.lr[p]
            sa = [0.0] * (self.n + 1)
            sb = [0.0] * (self.n + 1)
            saa = [0.0] * (self.n + 1)
            sbb = [0.0] * (self.n + 1)
            sab = [0.0] * (self.n + 1)
            for i in range(self.n):
                sa[i + 1] = sa[i] + a[i]
                sb[i + 1] = sb[i] + b[i]
                saa[i + 1] = saa[i] + a[i] * a[i]
                sbb[i + 1] = sbb[i] + b[i] * b[i]
                sab[i + 1] = sab[i] + a[i] * b[i]
            self._pref[p] = (sa, sb, saa, sbb, sab)

    # -- índice de la ÚLTIMA vela 1h ya CERRADA en `ms` ------------------------
    def idx_cerrada(self, ms):
        """Mayor i tal que la vela i ya cerró en `ms` (t_open + 1h <= ms)."""
        return bisect.bisect_right(self.t, ms - H_MS) - 1

    def beta_sigma(self, pair, i, n_beta):
        """(beta, sigma_resid_horaria) con las n_beta velas que terminan en i."""
        lo = i - n_beta + 1
        if lo < 1:
            return None, None
        sa, sb, saa, sbb, sab = self._pref[pair]
        k = n_beta
        ma = (sa[i + 1] - sa[lo]) / k
        mb = (sb[i + 1] - sb[lo]) / k
        vaa = (saa[i + 1] - saa[lo]) / k - ma * ma
        vbb = (sbb[i + 1] - sbb[lo]) / k - mb * mb
        vab = (sab[i + 1] - sab[lo]) / k - ma * mb
        if vbb <= 0:
            return None, None
        beta = vab / vbb
        var_res = vaa - (vab * vab) / vbb        # var(r_a - beta·r_b)
        sigma = math.sqrt(var_res) if var_res > 0 else None
        return beta, sigma

    def fuerza(self, pair, i, w, n_beta=BETA_N):
        """dict con raw/resid/z de `pair` en la vela cerrada i, ventana w. None si falta historia."""
        if pair == BTC:
            return None
        if i - w < 0 or i - n_beta + 1 < 1:
            return None
        ca, cb = self.close[pair], self.close[BTC]
        ret_a = ca[i] / ca[i - w] - 1.0
        ret_b = cb[i] / cb[i - w] - 1.0
        beta, sigma = self.beta_sigma(pair, i, n_beta)
        if beta is None:
            return None
        resid = ret_a - beta * ret_b
        z = resid / (sigma * math.sqrt(w)) if sigma else None
        return {"raw": ret_a - ret_b, "resid": resid, "z": z,
                "beta": beta, "ret": ret_a, "ret_btc": ret_b}


def ranking(serie, i, w, alts, feat, n_beta=BETA_N):
    """Ranking transversal ascendente entre `alts` en la vela cerrada i.

    Devuelve {par: posición} con posición 0 = la más DÉBIL y N−1 = la más FUERTE.
    Se guarda la posición entera y no un `u` redondeado a propósito: comparar floats
    normalizados con tolerancia hacía que las posiciones intermedias no calzaran con
    ningún bucket y quedaran fuera de todas las tablas.

    Si algún par no tiene historia suficiente se descarta el corte transversal
    completo: un ranking con universo variable vuelve incomparables las posiciones.
    """
    vals = {}
    for p in alts:
        f = serie.fuerza(p, i, w, n_beta)
        if f is None or f[feat] is None:
            return None
        vals[p] = f[feat]
    orden = sorted(vals, key=lambda p: vals[p])
    if len(orden) < 2:
        return None
    return {p: k for k, p in enumerate(orden)}


# ============================ régimen BTC ====================================

def _regimen(candles, sma_n):
    """(timestamps_cierre, estado[]) con SMA causal: cada vela usa su propio cierre
    y los sma_n−1 anteriores. El estado de la vela j sólo es consultable después de
    que la vela j haya cerrado."""
    cl = [c["c"] for c in candles]
    out = []
    acc = 0.0
    for j, v in enumerate(cl):
        acc += v
        if j >= sma_n:
            acc -= cl[j - sma_n]
        if j + 1 < sma_n:
            out.append(None)
        else:
            out.append("alcista" if v > acc / sma_n else "bajista")
    return out


class Regimen:
    def __init__(self):
        self.tf = {}
        for tf, ms in (("1d", 86_400_000), ("4h", 14_400_000)):
            c = _load_klines(BTC, tf)
            self.tf[tf] = ([x["t"] for x in c], _regimen(c, REGIMEN_SMA), ms)

    def estado(self, tf, ms):
        ts, est, tf_ms = self.tf[tf]
        i = bisect.bisect_right(ts, ms - tf_ms) - 1   # sólo velas ya cerradas
        return est[i] if 0 <= i < len(est) else None


# ============================ métricas =======================================

def net_r(r, sl_pct, override=None):
    if not sl_pct or sl_pct <= 0:
        return None
    return r - _cost_fraction(r > 0, override=override) / sl_pct


def _dd(netos):
    eq = pico = dd = 0.0
    for v in netos:
        eq += v
        pico = max(pico, eq)
        dd = max(dd, pico - eq)
    return dd


def metricas(trades, campo="net", base_n=None):
    if not trades:
        return {"n": 0}
    orden = sorted(trades, key=lambda t: t["t"])
    netos = [t[campo] for t in orden]
    n = len(netos)
    gan = sum(v for v in netos if v > 0)
    per = -sum(v for v in netos if v < 0)
    k = max(1, n // 100)
    top = sorted(netos, reverse=True)[:k]
    sin_cola = sorted(netos)[:-k]
    total = sum(netos)
    return {
        "n": n,
        "win_pct": round(100 * sum(1 for t in orden if t["r"] > 0) / n, 1),
        "avg_netR": round(total / n, 4),
        "med_netR": round(statistics.median(netos), 4),
        "total_netR": round(total, 1),
        "pf": round(gan / per, 3) if per > 0 else None,
        "dd_R": round(_dd(netos), 1),
        "avg_sin_top1pct": round(sum(sin_cola) / len(sin_cola), 4) if sin_cola else None,
        "aporte_top1pct_pct": round(100 * sum(top) / total, 0) if total > 0 else None,
        "cobertura_pct": round(100 * n / base_n, 1) if base_n else None,
        "dias_distintos": len({t["dia"] for t in orden}),
    }


# ---------------------- bootstrap por bloques MENSUALES ----------------------

def _sumas_por_mes(trades, campo):
    """{mes: (suma, n)}. Remuestrear sumas es idéntico a concatenar los trades del
    bloque y promediar, pero cuesta O(1) por bloque en vez de O(largo del bloque)."""
    d = defaultdict(lambda: [0.0, 0])
    for t in trades:
        d[t["mes"]][0] += t[campo]
        d[t["mes"]][1] += 1
    return d


def boot_media(trades, rng, campo="net", n_boot=N_BOOT):
    """CI95 y p unilateral del promedio, remuestreando MESES completos.

    Los trades vienen agrupados: en un mismo día caen varios pares. Un bootstrap de
    trades sueltos finge independencia y devuelve p-valores absurdos. El bloque
    mensual respeta que los vecinos comparten régimen.
    """
    if not trades:
        return None
    bloques = list(_sumas_por_mes(trades, campo).values())
    B = len(bloques)
    if B < 6:
        return None
    medias = []
    for _ in range(n_boot):
        s = c = 0.0
        for _ in range(B):
            b = bloques[rng.randrange(B)]
            s += b[0]
            c += b[1]
        medias.append(s / c)
    medias.sort()
    obs = sum(t[campo] for t in trades) / len(trades)
    p = (sum(1 for v in medias if v <= 0) + 1) / (n_boot + 1)
    return {"meses": B, "obs": round(obs, 4),
            "ci95": [round(medias[int(0.025 * n_boot)], 4),
                     round(medias[int(0.975 * n_boot)], 4)],
            "cruza_cero": medias[int(0.025 * n_boot)] <= 0,
            "p_mayor_que_cero": round(p, 4)}


def boot_dif(sel, base, rng, campo="net", n_boot=N_BOOT):
    """CI95 y p de (media_variante − media_baseline) remuestreando los MISMOS meses.

    Pareado por mes: en cada remuestreo se toman los mismos meses para las dos ramas,
    así la diferencia no se contamina con el hecho de que la variante viva en otros
    meses que el baseline.
    """
    if not sel or not base:
        return None
    sb = _sumas_por_mes(base, campo)
    ss = _sumas_por_mes(sel, campo)
    meses = [m for m in sb if m in ss]
    if len(meses) < 6:
        return None
    pares = [(sb[m][0], sb[m][1], ss[m][0], ss[m][1]) for m in meses]
    B = len(pares)
    difs = []
    for _ in range(n_boot):
        b_s = b_n = s_s = s_n = 0.0
        for _ in range(B):
            p = pares[rng.randrange(B)]
            b_s += p[0]
            b_n += p[1]
            s_s += p[2]
            s_n += p[3]
        difs.append(s_s / s_n - b_s / b_n)
    difs.sort()
    ob = sum(t[campo] for t in base) / len(base)
    os_ = sum(t[campo] for t in sel) / len(sel)
    p_pos = (sum(1 for v in difs if v <= 0) + 1) / (n_boot + 1)
    return {"meses_pareados": B, "dif_obs": round(os_ - ob, 4),
            "ci95": [round(difs[int(0.025 * n_boot)], 4),
                     round(difs[int(0.975 * n_boot)], 4)],
            "cruza_cero": difs[int(0.025 * n_boot)] <= 0 <= difs[int(0.975 * n_boot)],
            "p_dif_mayor_que_cero": round(p_pos, 4)}


def pendiente(trades, clave, rng, campo="net", n_boot=N_BOOT):
    """Pendiente OLS de netR contra la POSICIÓN del ranking, con CI por bloques.

    Responde la pregunta 8 sin elegir umbral: si la fuerza relativa informa, la
    relación debería ser monotónica y la pendiente distinta de cero. Un umbral
    puntual que funciona con pendiente nula es un umbral elegido mirando los datos.
    """
    pts = [(f["pos"][clave], f[campo], f["mes"]) for f in trades if clave in f["pos"]]
    if len(pts) < 100:
        return None
    def _slope(rows):
        n = len(rows)
        sx = sum(r[0] for r in rows)
        sy = sum(r[1] for r in rows)
        sxx = sum(r[0] * r[0] for r in rows)
        sxy = sum(r[0] * r[1] for r in rows)
        den = n * sxx - sx * sx
        return (n * sxy - sx * sy) / den if den else None
    obs = _slope(pts)
    if obs is None:
        return None
    por_mes = defaultdict(list)
    for p in pts:
        por_mes[p[2]].append(p)
    bloques = list(por_mes.values())
    B = len(bloques)
    if B < 6:
        return {"pendiente_obs": round(obs, 4), "meses": B, "ci95": None}
    ss = []
    for _ in range(n_boot):
        m = []
        for _ in range(B):
            m.extend(bloques[rng.randrange(B)])
        s = _slope(m)
        if s is not None:
            ss.append(s)
    ss.sort()
    lo, hi = ss[int(0.025 * len(ss))], ss[int(0.975 * len(ss))]
    return {"pendiente_obs": round(obs, 4), "meses": B,
            "ci95": [round(lo, 4), round(hi, 4)], "cruza_cero": lo <= 0 <= hi}


def holm(pruebas):
    """Holm-Bonferroni sobre la familia de filtros pre-registrados.

    Se corre sobre TODOS los umbrales publicados, no sólo sobre el mejor: la pregunta
    del encargo es justamente si el mejor umbral sobrevive a haber probado muchos.
    """
    orden = sorted(pruebas, key=lambda x: x["p"])
    m = len(orden)
    out = []
    prev = 0.0
    for k, x in enumerate(orden):
        aj = min(1.0, max(prev, (m - k) * x["p"]))
        prev = aj
        out.append({**x, "p_holm": round(aj, 4), "significativo_005": aj < 0.05})
    return out


# ============================ construcción del panel =========================

def construir(pares, serie, reg):
    """Trades del pipeline real + la foto de fuerza relativa en su instante de decisión."""
    with open(DUMP, encoding="utf-8") as fh:
        crudos = json.load(fh)

    alts = [p for p in pares if p != BTC]
    cache_rank = {}          # (i, w, feat) -> {par: u}
    filas = []
    descartes = defaultdict(int)

    for t in crudos:
        if t["pair"] not in pares:
            continue
        if t.get("status") not in ("ganada", "perdida"):
            descartes["no_activado"] += 1
            continue
        if (t.get("rr") or 0) < MIN_RR:
            descartes["rr_menor_a_5"] += 1
            continue
        n = net_r(t["r"], t.get("sl_pct"))
        if n is None:
            descartes["sin_sl_pct"] += 1
            continue

        # instante de decisión = CIERRE de la barra de señal (lo que vio smc_live)
        dec = t["t"] + TF_MS[t["sel_tf"]]
        i = serie.idx_cerrada(dec)
        d = dt.datetime.utcfromtimestamp(t["t"] / 1000)

        fila = {
            "pair": t["pair"], "dir": t["dir"], "sel_tf": t["sel_tf"],
            "poi_tf": t["poi_tf"], "rr": t["rr"], "r": t["r"],
            "sl_pct": t["sl_pct"], "t": t["t"], "t_decision": dec,
            "net": round(n, 5),
            "net_duro": round(net_r(t["r"], t["sl_pct"], COSTO_DURO), 5),
            "net_extremo": round(net_r(t["r"], t["sl_pct"], COSTO_EXTREMO), 5),
            "year": d.year, "mes": d.strftime("%Y-%m"), "dia": d.strftime("%Y-%m-%d"),
            "reg_1d": reg.estado("1d", dec), "reg_4h": reg.estado("4h", dec),
            "pos": {}, "z": {}, "beta": None, "n_alts": len(alts),
        }

        if i >= 0:
            for wn, w in VENTANAS.items():
                for feat in FEATURES:
                    key = (i, w, feat)
                    if key not in cache_rank:
                        cache_rank[key] = ranking(serie, i, w, alts, feat)
                    rk = cache_rank[key]
                    if rk is not None and t["pair"] in rk:
                        fila["pos"][f"{feat}_{wn}"] = rk[t["pair"]]
                f = serie.fuerza(t["pair"], i, w)
                if f and f["z"] is not None:
                    fila["z"][wn] = round(f["z"], 4)
                    fila["beta"] = round(f["beta"], 4)
        filas.append(fila)

    filas.sort(key=lambda x: x["t"])
    return filas, dict(descartes)


# ============================ variantes ======================================

def cortes_is(filas, corte_t, w_name):
    """Cortes de quintil del z-score estimados SÓLO con IS."""
    vals = sorted(f["z"][w_name] for f in filas
                  if f["t"] <= corte_t and w_name in f["z"])
    if len(vals) < 100:
        return None
    return [vals[int(q * len(vals))] for q in (0.2, 0.4, 0.6, 0.8)]


def quintil(v, cortes):
    if v is None or cortes is None:
        return None
    return 1 + sum(1 for c in cortes if v > c)


def filtro_direccional(filas, clave, k, n_alts, contrario=False):
    """Variante D (y su placebo E).

    D: long sólo si el par está entre los k MÁS fuertes; short sólo si entre los k
    más débiles. E (contrario=True): exactamente al revés, mismo procedimiento.
    El umbral se expresa en posiciones del ranking (k de N), no en un número elegido
    mirando resultados; se publican TODOS los k.
    """
    out = []
    for f in filas:
        pos = f["pos"].get(clave)
        if pos is None:
            continue
        largo = f["dir"] == "long"
        if contrario:
            largo = not largo
        if (largo and pos >= n_alts - k) or ((not largo) and pos <= k - 1):
            out.append(f)
    return out


def prioriza_por_dia(filas, clave, rng, n_boot=N_BOOT):
    """Variante C: cuando varios setups coinciden el MISMO día y dirección, quedarse
    con el mejor rankeado.

    El control NO es el baseline completo. Quedarse con uno por grupo ya cambia el
    resultado por sí solo (pasa a ponderar días en vez de trades) y esa mejora no
    tiene nada que ver con la fuerza relativa. El control honesto es elegir uno AL
    AZAR del mismo grupo; la diferencia contra ese sorteo es el aporte del ranking.
    Ambas ramas se remuestrean con los MISMOS bloques mensuales.
    """
    grupos = defaultdict(list)
    for f in filas:
        if f["pos"].get(clave) is not None:
            grupos[(f["dia"], f["dir"])].append(f)
    elegidos, multiples = [], 0
    por_mes = defaultdict(list)
    for (dia, d), g in grupos.items():
        if len(g) > 1:
            multiples += 1
        el = (max(g, key=lambda f: f["pos"][clave]) if d == "long"
              else min(g, key=lambda f: f["pos"][clave]))
        elegidos.append(el)
        por_mes[el["mes"]].append((el["net"], g))

    bloques = list(por_mes.values())
    B = len(bloques)
    difs = []
    if B >= 6:
        for _ in range(n_boot):
            s_el = s_az = 0.0
            c = 0
            for _ in range(B):
                for net_el, g in bloques[rng.randrange(B)]:
                    s_el += net_el
                    s_az += g[rng.randrange(len(g))]["net"]
                    c += 1
            difs.append((s_el - s_az) / c)
        difs.sort()
    azar_obs = []
    for _ in range(200):
        pick = [g[rng.randrange(len(g))] for g in grupos.values()]
        azar_obs.append(sum(f["net"] for f in pick) / len(pick))
    az = sum(azar_obs) / len(azar_obs)
    el_avg = sum(f["net"] for f in elegidos) / len(elegidos)
    info = {"grupos": len(grupos), "grupos_con_varios": multiples,
            "control_azar_avg_netR": round(az, 4),
            "dif_ranking_vs_azar": round(el_avg - az, 4)}
    if difs:
        info["bootstrap_dif_vs_azar"] = {
            "meses": B,
            "ci95": [round(difs[int(0.025 * len(difs))], 4),
                     round(difs[int(0.975 * len(difs))], 4)],
            "cruza_cero": difs[int(0.025 * len(difs))] <= 0 <= difs[int(0.975 * len(difs))],
            "p_dif_mayor_que_cero": round(
                (sum(1 for v in difs if v <= 0) + 1) / (len(difs) + 1), 4)}
    return elegidos, info


# ============================ CoinGlass ======================================

def coinglass_cobertura(filas):
    """Sólo se reporta cobertura y se dice si alcanza. No se fuerza nada."""
    path = os.path.join(DATA_DIR, "coinsignals_coinglass.json")
    if not os.path.isfile(path):
        return {"disponible": False}
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    hist = d.get("history") or []
    if not hist:
        return {"disponible": False}
    simbolos = sorted({h.get("symbol") for h in hist})
    caps = sorted(h["captured_at"] for h in hist if h.get("captured_at"))
    t0 = dt.datetime.fromisoformat(caps[0]).timestamp() * 1000
    t1 = dt.datetime.fromisoformat(caps[-1]).timestamp() * 1000
    dentro = [f for f in filas if t0 <= f["t"] <= t1]
    span_trades = (filas[-1]["t"] - filas[0]["t"]) / 86_400_000 if filas else 0
    return {
        "disponible": True,
        "simbolos": simbolos,
        "solo_btc": simbolos == ["BTC"],
        "desde": caps[0], "hasta": caps[-1],
        "snapshots": len(hist),
        "intervalo": "4h",
        "trades_del_backtest_dentro_de_la_ventana": len(dentro),
        "trades_totales": len(filas),
        "meses_solapados": len({f["mes"] for f in dentro}),
        "span_backtest_dias": round(span_trades),
        "veredicto": (
            "NO ALCANZA para cruzar con los años del backtest: el store es sólo BTC "
            "y arranca en 2026-01. Una fuerza relativa TRANSVERSAL necesita OI/funding/"
            "taker POR PAR, que no existen en el store. Y aunque se usara como contexto "
            "de mercado, el solape deja pocos meses efectivos, que es la unidad válida "
            "de remuestreo. No se fuerza el cruce."
        ),
    }


# ============================ main ===========================================

def main():
    if not os.path.isfile(DUMP):
        raise SystemExit(f"falta {DUMP} (se genera con "
                         "`python3 -m modules.trading.run_setup_backtest`)")
    rng = random.Random(SEED)
    reg = Regimen()

    salida = {"meta": {
        "research_only": True, "execution_enabled": False, "validated": False,
        "aviso": AVISO,
        "pregunta": "la fuerza relativa vs BTC mejora la seleccion de pares del baseline rr>=5",
        "universo": ("data/setup_backtest_trades.json = pipeline REAL del bot "
                     "(smc_live.analyze, POIs 1D/4h/1h, planeacion 1h/4h). "
                     "NO hay 15m en ninguna parte de este estudio."),
        "min_rr": MIN_RR,
        "instante_de_evaluacion": "cierre de la barra de senal (t + TF_MS[sel_tf])",
        "causalidad": "solo velas 1h con t_open + 1h <= instante de decision",
        "beta": f"OLS log-retornos horarios vs BTC, ventana {BETA_N} velas (30d)",
        "btc_en_el_ranking": "NO: BTC nunca se rankea contra si mismo",
        "bootstrap": "bloques MENSUALES, 2000 remuestreos",
        "costos": {"base": "maker-aware del Diario (_cost_fraction)/sl_pct",
                   "duro": COSTO_DURO, "extremo": COSTO_EXTREMO},
        "seed": SEED,
    }}

    for etiqueta, pares in (("plan_5_pares", PARES_PLAN), ("todos_7_pares", PARES_TODOS)):
        serie = Series(pares)
        filas, descartes = construir(pares, serie, reg)
        alts = [p for p in pares if p != BTC]
        n_alts = len(alts)
        bloque = analiza(filas, descartes, alts, n_alts, rng, serie)
        salida[etiqueta] = bloque
        if etiqueta == "plan_5_pares":
            salida["coinglass"] = coinglass_cobertura(filas)
            with open(OUT_TRADES, "w", encoding="utf-8") as fh:
                json.dump({"meta": {"research_only": True, "execution_enabled": False,
                                    "validated": False, "aviso": AVISO,
                                    "pares": pares, "min_rr": MIN_RR},
                           "trades": filas}, fh, ensure_ascii=False)
        print(f"[{etiqueta}] {len(filas)} trades rr>=5 · "
              f"con ranking: {sum(1 for f in filas if f['pos'])}", flush=True)

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=1)
    print(f"\nresultados: {OUT_JSON}\n            {OUT_TRADES}")
    _resumen(salida)


def analiza(filas, descartes, alts, n_alts, rng, serie):
    ts = [f["t"] for f in filas]
    corte = ts[0] + IS_FRAC * (ts[-1] - ts[0])
    for f in filas:
        f["oos"] = f["t"] > corte

    def part(rows):
        return {"ALL": metricas(rows), "IS": metricas([r for r in rows if not r["oos"]]),
                "OOS": metricas([r for r in rows if r["oos"]])}

    fmt = "%Y-%m-%d"
    B = {
        "descartes": descartes,
        "span": [dt.datetime.utcfromtimestamp(ts[0] / 1000).strftime(fmt),
                 dt.datetime.utcfromtimestamp(ts[-1] / 1000).strftime(fmt)],
        "corte_is_oos": dt.datetime.utcfromtimestamp(corte / 1000).strftime(fmt),
        "altcoins_en_el_ranking": alts,
    }

    # ---------- A: BASELINE ----------
    con_rank = [f for f in filas if f["pos"]]
    sin_rank = [f for f in filas if not f["pos"]]
    btc = [f for f in filas if f["pair"] == BTC]
    B["A_baseline"] = {
        "todos": part(filas),
        "solo_altcoins_con_ranking": part(con_rank),
        "btc_sin_ranking": part(btc),
        "sin_ranking_por_falta_de_historia": metricas(sin_rank) if sin_rank else {"n": 0},
        "bootstrap_ALL": boot_media(filas, rng),
        "bootstrap_OOS": boot_media([f for f in filas if f["oos"]], rng),
        "por_ano": {str(y): metricas([f for f in filas if f["year"] == y])
                    for y in sorted({f["year"] for f in filas})},
        "por_par": {p: metricas([f for f in filas if f["pair"] == p])
                    for p in sorted({f["pair"] for f in filas})},
        "por_dir": {d: metricas([f for f in filas if f["dir"] == d])
                    for d in ("long", "short")},
        "por_sel_tf": {tf: metricas([f for f in filas if f["sel_tf"] == tf])
                       for tf in ("1h", "4h")},
        "por_regimen_1d": {r: metricas([f for f in filas if f["reg_1d"] == r])
                           for r in ("alcista", "bajista")},
        "costos": {c: metricas(filas, campo=c)
                   for c in ("net", "net_duro", "net_extremo")},
    }
    base_n = len(con_rank)

    # ---------- B: DESCRIPTIVO (monotonía) ----------
    desc = {}
    for feat in FEATURES:
        for wn in VENTANAS:
            clave = f"{feat}_{wn}"
            porpos = {}
            for k in range(n_alts):
                sel = [f for f in con_rank if f["pos"].get(clave) == k]
                porpos[f"pos_{k+1}_de_{n_alts}"] = {
                    "long": metricas([f for f in sel if f["dir"] == "long"]),
                    "short": metricas([f for f in sel if f["dir"] == "short"]),
                    "ambas": metricas(sel)}
            desc[clave] = porpos
    B["B_descriptivo_por_posicion_de_ranking"] = desc

    # monotonía: pendiente de netR contra la posición del ranking (sin umbral)
    tend = {}
    for feat in FEATURES:
        for wn in VENTANAS:
            clave = f"{feat}_{wn}"
            tend[clave] = {
                "long": pendiente([f for f in con_rank if f["dir"] == "long"], clave, rng),
                "short": pendiente([f for f in con_rank if f["dir"] == "short"], clave, rng),
                "long_OOS": pendiente([f for f in con_rank
                                       if f["dir"] == "long" and f["oos"]], clave, rng),
                "short_OOS": pendiente([f for f in con_rank
                                        if f["dir"] == "short" and f["oos"]], clave, rng),
            }
    B["B_monotonia_pendiente_vs_posicion"] = tend

    # quintiles del z con cortes estimados SÓLO en IS
    zq = {}
    for wn in VENTANAS:
        cortes = cortes_is(filas, corte, wn)
        if cortes is None:
            continue
        for f in filas:
            f.setdefault("quintil_z", {})[wn] = quintil(f["z"].get(wn), cortes)
        zq[wn] = {"cortes_estimados_en_IS": [round(c, 4) for c in cortes],
                  "quintiles": {}}
        for q in range(1, 6):
            sel = [f for f in filas if f.get("quintil_z", {}).get(wn) == q]
            zq[wn]["quintiles"][f"Q{q}"] = {
                "long": part([f for f in sel if f["dir"] == "long"]),
                "short": part([f for f in sel if f["dir"] == "short"])}
    B["B_quintiles_zscore_cortes_IS"] = zq

    # ---------- C: ranking para priorizar coincidencias ----------
    clave_pri = "resid_3d"
    eleg, info = prioriza_por_dia(con_rank, clave_pri, rng)
    B["C_prioriza_coincidencias"] = {
        "clave": clave_pri, **info,
        "elegidos": part(eleg),
        "baseline_mismo_universo": part(con_rank),
        "nota": ("`bootstrap_dif_vs_baseline` MEZCLA dos cosas: el efecto de quedarse "
                 "con uno por dia (que no requiere fuerza relativa) y el del ranking. "
                 "El aporte del ranking es `bootstrap_dif_vs_azar`."),
        "bootstrap_dif_vs_baseline": boot_dif(eleg, con_rank, rng),
    }

    # ---------- D y E: filtro y placebo, TODOS los umbrales ----------
    # Tres FAMILIAS pre-registradas, porque el encargo hace tres preguntas distintas:
    #   solo_long  -> ¿los longs mejoran con más fuerza residual?      (pregunta 1)
    #   solo_short -> ¿los shorts mejoran con más debilidad residual?  (pregunta 2)
    #   ambas      -> el filtro combinado, que es lo que se implementaría
    # Holm se aplica DENTRO de cada familia (el tamaño de cada una queda declarado).
    familias = {"solo_long": lambda f: f["dir"] == "long",
                "solo_short": lambda f: f["dir"] == "short",
                "ambas": lambda f: True}
    grid_d = {fam: {} for fam in familias}
    grid_e = {fam: {} for fam in familias}
    pruebas = {fam: [] for fam in familias}
    for feat in FEATURES:
        for wn in VENTANAS:
            clave = f"{feat}_{wn}"
            for k in range(1, n_alts):
                nombre = f"{clave}_top{k}de{n_alts}"
                sel_all = filtro_direccional(con_rank, clave, k, n_alts)
                pla_all = filtro_direccional(con_rank, clave, k, n_alts, contrario=True)
                for fam, cond in familias.items():
                    base_f = [f for f in con_rank if cond(f)]
                    sel = [f for f in sel_all if cond(f)]
                    pla = [f for f in pla_all if cond(f)]
                    dif = boot_dif(sel, base_f, rng) if sel else None
                    grid_d[fam][nombre] = {
                        **part(sel),
                        "cobertura_pct": round(100 * len(sel) / len(base_f), 1)
                        if base_f else None,
                        "bootstrap_dif_vs_baseline": dif,
                        "OOS_bootstrap": boot_media([f for f in sel if f["oos"]], rng),
                        "OOS_dif_vs_baseline": boot_dif(
                            [f for f in sel if f["oos"]],
                            [f for f in base_f if f["oos"]], rng),
                    }
                    grid_e[fam][nombre] = {
                        **part(pla),
                        "cobertura_pct": round(100 * len(pla) / len(base_f), 1)
                        if base_f else None,
                        "bootstrap_dif_vs_baseline":
                            boot_dif(pla, base_f, rng) if pla else None}
                    if dif:
                        pruebas[fam].append({"variante": nombre,
                                             "p": dif["p_dif_mayor_que_cero"],
                                             "dif": dif["dif_obs"]})
    B["D_filtro_direccional"] = grid_d
    B["E_placebo_contrario"] = grid_e
    B["D_correccion_multiple_holm"] = {
        fam: {"n_pruebas_en_la_familia": len(p), "resultados": holm(p)}
        for fam, p in pruebas.items() if p}
    B["baseline_por_familia"] = {
        fam: part([f for f in con_rank if cond(f)]) for fam, cond in familias.items()}

    # ---------- F: raw vs resid vs z, mismo umbral ----------
    k_med = max(1, n_alts // 2)
    B["F_raw_vs_residual_vs_vol"] = {
        f"{feat}_{wn}": {
            **part(filtro_direccional(con_rank, f"{feat}_{wn}", k_med, n_alts)),
            "bootstrap_dif_vs_baseline": boot_dif(
                filtro_direccional(con_rank, f"{feat}_{wn}", k_med, n_alts), con_rank, rng)
            if filtro_direccional(con_rank, f"{feat}_{wn}", k_med, n_alts) else None}
        for feat in FEATURES for wn in VENTANAS}
    B["F_umbral_usado"] = f"top{k_med}de{n_alts}"

    # ---------- G: con y sin régimen BTC ----------
    clave_g = "resid_3d"
    k_g = max(1, n_alts // 2)
    sel_g = set(id(f) for f in filtro_direccional(con_rank, clave_g, k_g, n_alts))
    g = {"clave": clave_g, "umbral": f"top{k_g}de{n_alts}"}
    for tf in ("1d", "4h"):
        rk = f"reg_{tf}"
        cel = {}
        for r in ("alcista", "bajista"):
            base_r = [f for f in con_rank if f[rk] == r]
            sel_r = [f for f in base_r if id(f) in sel_g]
            cel[r] = {"baseline": part(base_r), "con_fuerza": part(sel_r),
                      "bootstrap_dif": boot_dif(sel_r, base_r, rng) if sel_r else None}
        # ¿el régimen y el ranking dicen lo mismo? (¿es información nueva?)
        alin = defaultdict(int)
        for f in con_rank:
            if f[rk] and id(f) in sel_g:
                alin[f"{f[rk]}_pasa_filtro_{f['dir']}"] += 1
            elif f[rk]:
                alin[f"{f[rk]}_no_pasa_{f['dir']}"] += 1
        g[rk] = {"celdas": cel, "cruce": dict(alin)}
    B["G_regimen_btc"] = g

    # ---------- variante TITULAR: desglose completo + walk-forward anual ----------
    # Declarada antes de mirar resultados: `resid_3d` (la formulación literal de la
    # hipótesis: residuo ajustado por beta) con el umbral del MEDIO de la grilla
    # (mitad más fuerte / mitad más débil). No es la mejor de la grilla; es la que
    # corresponde elegir sin mirar.
    clave_t, k_t = "resid_3d", max(1, n_alts // 2)
    ids_t = {id(f) for f in filtro_direccional(con_rank, clave_t, k_t, n_alts)}

    def _desglose(cond):
        base_f = [f for f in con_rank if cond(f)]
        sel_f = [f for f in base_f if id(f) in ids_t]
        if not sel_f:
            return None
        def dif(b, s):
            if not b or not s:
                return None
            return round(sum(x["net"] for x in s) / len(s)
                         - sum(x["net"] for x in b) / len(b), 4)
        blk = {"global": part(sel_f), "baseline": part(base_f),
               "cobertura_pct": round(100 * len(sel_f) / len(base_f), 1),
               "bootstrap_dif": boot_dif(sel_f, base_f, rng),
               "bootstrap_dif_IS": boot_dif([f for f in sel_f if not f["oos"]],
                                            [f for f in base_f if not f["oos"]], rng),
               "bootstrap_dif_OOS": boot_dif([f for f in sel_f if f["oos"]],
                                             [f for f in base_f if f["oos"]], rng),
               "walk_forward_anual": {}, "sensibilidad_costos": {}}
        for y in sorted({f["year"] for f in base_f}):
            b = [f for f in base_f if f["year"] == y]
            s = [f for f in b if id(f) in ids_t]
            blk["walk_forward_anual"][str(y)] = {
                "baseline": metricas(b), "con_fuerza": metricas(s),
                "dif_avg_netR": dif(b, s)}
        for campo, llaves, destino in (
                ("pair", sorted({f["pair"] for f in base_f}), "por_par"),
                ("dir", ["long", "short"], "por_dir"),
                ("sel_tf", ["1h", "4h"], "por_sel_tf"),
                ("poi_tf", sorted({f["poi_tf"] for f in base_f}), "por_poi_tf"),
                ("reg_1d", ["alcista", "bajista"], "por_regimen_1d"),
                ("reg_4h", ["alcista", "bajista"], "por_regimen_4h")):
            blk[destino] = {}
            for v in llaves:
                b = [f for f in base_f if f[campo] == v]
                s = [f for f in b if id(f) in ids_t]
                if not b:
                    continue
                blk[destino][str(v)] = {"baseline": metricas(b), "con_fuerza": metricas(s),
                                        "dif_avg_netR": dif(b, s)}
        for campo in ("net", "net_duro", "net_extremo"):
            blk["sensibilidad_costos"][campo] = {
                "baseline_avg": metricas(base_f, campo=campo)["avg_netR"],
                "con_fuerza_avg": metricas(sel_f, campo=campo)["avg_netR"],
                "bootstrap_dif": boot_dif(sel_f, base_f, rng, campo=campo)}
        return blk

    B["variante_titular"] = {
        "clave": clave_t, "umbral": f"top{k_t}de{n_alts}",
        "por_que_esta": ("formulacion literal de la hipotesis (residuo ajustado por beta) "
                         "con el umbral del MEDIO de la grilla; no es la mejor, es la que "
                         "corresponde elegir sin mirar resultados"),
        "ambas": _desglose(lambda f: True),
        "solo_long": _desglose(lambda f: f["dir"] == "long"),
        "solo_short": _desglose(lambda f: f["dir"] == "short"),
    }

    # ---------- H: POST-HOC declarado (no es hipótesis pre-registrada) ----------
    # Surge DESPUÉS de ver las tablas: los extremos del ranking (fuerte Y débil) rinden
    # mejor que el medio en shorts, lo que sugiere que lo que informa no es el SIGNO del
    # residuo sino su MAGNITUD — o sea un proxy de "este par se está moviendo mucho",
    # que con un TP a rr>=5 ayuda en cualquier dirección. Se mide y se etiqueta como
    # post-hoc: NO cuenta como evidencia, sólo define el próximo experimento.
    posthoc = {"advertencia": "hallazgo POST-HOC, sin poder confirmatorio en estos datos"}
    for wn in VENTANAS:
        vals = sorted(abs(f["z"][wn]) for f in filas if wn in f["z"] and f["t"] <= corte)
        if len(vals) < 100:
            continue
        cortes = [vals[int(q * len(vals))] for q in (0.2, 0.4, 0.6, 0.8)]
        qs = {}
        for q in range(1, 6):
            sel = [f for f in con_rank if wn in f["z"]
                   and quintil(abs(f["z"][wn]), cortes) == q]
            qs[f"Q{q}"] = {"ambas": part(sel),
                           "long": metricas([f for f in sel if f["dir"] == "long"]),
                           "short": metricas([f for f in sel if f["dir"] == "short"])}
        posthoc[wn] = {"cortes_abs_z_estimados_en_IS": [round(c, 4) for c in cortes],
                       "quintiles": qs}
    B["H_posthoc_magnitud_absoluta_del_residuo"] = posthoc

    # ---------- sensibilidad de la beta ----------
    sens = {}
    for nb in BETA_ALTS:
        cache = {}
        sel = []
        clave = "resid_3d"
        w = VENTANAS["3d"]
        k = max(1, n_alts // 2)
        for f in con_rank:
            i = serie.idx_cerrada(f["t_decision"])
            key = (i, nb)
            if key not in cache:
                cache[key] = ranking(serie, i, w, alts, "resid", nb)
            rk = cache[key]
            if rk is None or f["pair"] not in rk:
                continue
            pos = rk[f["pair"]]
            if (f["dir"] == "long" and pos >= n_alts - k) or \
               (f["dir"] == "short" and pos <= k - 1):
                sel.append(f)
        sens[f"beta_{nb}_velas"] = {**part(sel),
                                    "bootstrap_dif_vs_baseline":
                                        boot_dif(sel, con_rank, rng) if sel else None}
    B["sensibilidad_beta"] = sens
    return B


def _resumen(salida):
    for et in ("plan_5_pares", "todos_7_pares"):
        B = salida[et]
        a = B["A_baseline"]["solo_altcoins_con_ranking"]
        print(f"\n=== {et} ===  span {B['span'][0]} .. {B['span'][1]} "
              f"(corte {B['corte_is_oos']})")
        print(f"  A baseline altcoins: ALL n={a['ALL']['n']} avg={a['ALL']['avg_netR']:+.3f} "
              f"| OOS n={a['OOS']['n']} avg={a['OOS']['avg_netR']:+.3f}")
        for fam, blk in B["D_correccion_multiple_holm"].items():
            print(f"  -- familia {fam} ({blk['n_pruebas_en_la_familia']} pruebas)")
            for m in sorted(blk["resultados"], key=lambda x: x["p"])[:3]:
                print(f"     {m['variante']:>22}  dif={m['dif']:+.3f}  p={m['p']:.4f}  "
                      f"holm={m['p_holm']:.3f}  "
                      f"{'SIGNIFICATIVO' if m['significativo_005'] else '-'}")


if __name__ == "__main__":
    main()
