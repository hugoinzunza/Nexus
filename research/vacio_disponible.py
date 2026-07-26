#!/usr/bin/env python3
"""¿El TP del bot atraviesa paredes? — estudio del "vacío disponible" (CreceTrader).

PREGUNTA
--------
`smc_live._opposite_liquidity()` (modules/trading/smc_live.py:525) pone el TP en
`min(weak highs > ref)` para largos. Ese TP es la liquidez WEAK más cercana, pero el
cálculo NO mira si entre la entrada y ese TP hay:
  - niveles STRONG (rhi/rlo entran sólo como RESPALDO cuando no hay weak, jamás como
    obstrucción intermedia),
  - POIs de otras temporalidades (1D/4h/1h) en el camino,
  - liquidez del lado contrario.
No existe en todo el repo ninguna variable de conteo de obstáculos (grep verificado).
El gate `rr>=5` del Diario selecciona sobre ese TP.

La clase 7 del curso llama "vacío disponible" a la distancia entrada → PRIMER referente
capaz de obstaculizar, no a la distancia a un objetivo lejano detrás de varias paredes.

HIPÓTESIS PRE-REGISTRADA
------------------------
`obstacle_count_before_target > 0` predice MENOR realización del objetivo, controlando
por RR planificado, par, dirección y régimen.

ALCANCE — lo que este estudio NO puede explicar
-----------------------------------------------
NO explica la brecha backtest (67,4% llega a TP1) vs Diario real (33,3%): backtest y
Diario comparten `_tpsl`, y una ceguera COMPARTIDA no produce divergencia entre dos
sistemas que la comparten. Lo que sí puede poner en duda es la COHERENCIA INTERNA del
gate rr>=5 (si el rr mide un recorrido que atraviesa paredes, no mide lo que dice).

DISEÑO CONGELADO ANTES DE MIRAR RESULTADOS  (ver DESIGN, abajo)
---------------------------------------------------------------
Obstáculo = nivel Weak o Strong, o POI de cualquier POI_TFS, confirmado en el `as_of`
del plan, cuyo precio cae ESTRICTAMENTE entre `entry` y `tp` en la dirección del trade.

Para un POI se usa el BORDE CERCANO (lo para largos, hi para cortos), no el centro:
la clase 7 lo dice explícito ("la distancia al borde cercano de una zona es más honesta")
y además es lo conservador — el precio choca con el borde, no con el punto medio.

Por qué el de-duplicado usa ATR y no un %: agrupar obstáculos "que son la misma pared"
con un umbral fijo (0,1%, $50) es exactamente el defecto que ya apareció SEIS veces en
este proyecto (MIN_USD, ±5% fijo, tope de 41 elementos). El corte acá es 0,25×ATR de la
TF de planeación en el `as_of`: relativo a la volatilidad del propio instrumento y
derivado de los datos. Se reporta sensibilidad a 0 / 0,25 / 0,50 ATR.

CONTROLES NEGATIVOS (los tres, obligatorios)
--------------------------------------------
(a) placebo: los mismos obstáculos desplazados ±0,3 ATR.
(b) DETRÁS del entry: mismo conteo en la banda espejo (dirección contraria, misma
    distancia). NO debería predecir nada. **Si (b) predice, hay fuga y el estudio se
    declara INVÁLIDO.**
(c) aleatorio emparejado por distancia: los conteos se permutan DENTRO de deciles de
    `|tp-entry|/ATR`. Así el conteo permutado conserva toda la información de distancia
    y pierde la del trade. Si predice, lo que medimos era la distancia, no las paredes.

ANTI-LOOK-AHEAD
---------------
- Los POIs vienen de `smc_live.analyze` sobre `htf_map` ya recortado a velas CERRADAS
  al `close_time` de la barra de decisión (`_htf_slice`), igual que el backtest del bot.
- Los niveles vienen de `smc.swing_points`, que sólo emite pivotes con
  `confirm_idx <= n-1` (necesita `lookback` velas a la derecha).
- Los obstáculos se cuentan con la foto del `as_of`, nunca después.
- La simulación forward arranca en `act_idx + 1`, NO en `act_idx`: hubo un bug real en
  este proyecto donde arrancar en `act_idx` costaba 1,5R por trade (la barra de
  activación de un largo tiene su MÁXIMO posiblemente ANTES del mínimo que llenó la
  zona; con OHLC no se sabe el orden intrabarra, así que no se cuenta).
- El régimen usa sólo pasado (ATR y retorno de 200 barras al `as_of`).

Corre:   .venv/bin/python3 research/vacio_disponible.py            (usa caché si existe)
         .venv/bin/python3 research/vacio_disponible.py --recolectar
Escribe: research/vacio_disponible_trades.json   (caché por-trade, ~10 MB, regenerable)
         research/vacio_disponible_results.json  (el entregable)

research_only · execution_enabled: false · validated: false
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import random
import sys
import time

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import smc, smc_live                      # noqa: E402
from modules.trading import run_setup_backtest as rsb          # noqa: E402
from modules.trading.setups_store import _cost_fraction        # noqa: E402

CACHE = os.path.join(WT, "research", "vacio_disponible_trades.json")
OUT_JSON = os.path.join(WT, "research", "vacio_disponible_results.json")

# ---------------------------------------------------------------------------
# DISEÑO PRE-REGISTRADO. Se serializa tal cual en el bloque `meta` del JSON para
# que cualquiera pueda comprobar que los cortes no se movieron después de ver los
# resultados. Si algo acá cambia, tiene que quedar escrito en `desviaciones`.
# ---------------------------------------------------------------------------
DESIGN = {
    "hipotesis": ("obstacle_count_before_target > 0 predice MENOR realizacion del "
                  "objetivo, controlando por RR planificado, par, direccion y regimen"),
    "obstaculo": ("nivel Weak o Strong (ambos) o POI de cualquier POI_TFS, confirmado "
                  "en el as_of, con precio ESTRICTAMENTE entre entry y tp; para POIs "
                  "se usa el BORDE CERCANO (lo si largo, hi si corto)"),
    "universo": ("trades ACTIVADOS del pipeline alineado del bot (smc_live.analyze, "
                 "POIs 1D/4h/1h proyectados sobre TF de planeacion 1h/4h), rr>=5. "
                 "SIN 15m: el bot no opera 15m"),
    "baseline": "el rr planificado actual, solo",
    "controles_negativos": ["a_placebo_+-0.3ATR", "b_detras_del_entry", "c_permutado_por_distancia"],
    "invalidacion": "si el control (b) predice, hay fuga y el estudio se declara INVALIDO",
    "is_oos_corte": "2025-03-19",
    "walk_forward": "por anio 2022-2026",
    "n_minimo_por_celda": 300,
    "celdas": ["0", "1", "2", "3+"],
    "metricas": ["netR medio", "netR mediano", "tasa TP1", "tasa TP", "MAE", "MFE"],
    "ci": "bootstrap de BLOQUES DIARIOS (los trades se agrupan por dia UTC)",
    "correccion_multiple": "Holm sobre la familia de 4 definiciones x 3 desenlaces",
    "decision": {
        "PROMOVER": "sobrevive Holm + control (b) plano + direccion en >=3 de 5 anios",
        "SEGUIR": "signo estable pero el CI cruza cero",
        "DESCARTAR": "control (b) con efecto (fuga) o efecto desaparece controlando por RR",
    },
}

CORTE_OOS_MS = int(dt.datetime(2025, 3, 19, tzinfo=dt.timezone.utc).timestamp() * 1000)
RR_MIN = 5.0
CLUSTER_ATR = 0.25      # de-duplicado de obstáculos: 0,25 x ATR (relativo, no un %)
PLACEBO_ATR = 0.30      # control (a): desplazamiento del placebo
BOOT_B = 2000           # remuestreos para medias/diferencias
BOOT_OLS = 1000         # remuestreos para los coeficientes OLS (más caro)
SEED = 20260726

# Familia de contrastes para Holm (pre-declarada, NO se amplía después).
DEFS = ("obst_all", "obst_valid", "obst_levels", "obst_htf")
DESENLACES = ("netR_real_vivo", "reach_tp1", "reach_tp")


# ===========================================================================
# PARTE 1 — COLECTOR: re-corre el pipeline del bot capturando la foto del as_of
# ===========================================================================

_CAPTURA: list = []


def _instrumentar():
    """Envuelve `smc_live._pois_for_tf` para quedarnos con TODOS los POIs que el
    pipeline vio en cada barra de decisión.

    Por qué envolver y no recalcular: `analyze()` devuelve `pois` ya recortada
    (12 válidos + 6 mitigados + escalera) y `levels` con sólo 2 por lado. Contar
    obstáculos sobre esa lista recortada mediría el recorte, no las paredes.
    Recalcular `detect_pois` aparte duplicaría el costo Y el riesgo de divergir
    de lo que el bot realmente vio. Envolver da la lista EXACTA, gratis.
    No modifica ningún archivo de modules/: es sólo instrumentación en runtime.
    """
    orig = smc_live._pois_for_tf

    def wrapper(candles, tf, last_price):
        out = orig(candles, tf, last_price)
        _CAPTURA.extend(out)
        return out

    wrapper._orig = orig
    smc_live._pois_for_tf = wrapper


def _cands(pois, levels, entry, arriba):
    """Obstáculos candidatos (sin de-duplicar) con su precio de choque, para un
    recorrido hacia ARRIBA (`arriba=True`) o hacia ABAJO.

    Devuelve [{price, kind, tf, valid}] con `kind` ∈ weak/strong/poi.

    Se construye una lista POR DIRECCIÓN, no una sola, porque el borde de choque de
    una zona depende de por dónde viene el precio (subiendo choca con `lo`, bajando
    con `hi`). Reusar la lista del trade para la banda espejo del control (b) metía
    SIEMPRE el propio POI de entrada detrás del entry — el control quedaba con
    flag=1 en el 100% de los trades, o sea sin variación y por lo tanto inútil.

    Por la misma razón se descarta toda zona que CONTIENE la entrada: si el precio
    ya está adentro, esa zona no es una pared en ninguna de las dos direcciones.
    """
    out = []
    for l in levels:
        out.append({"price": float(l["price"]), "kind": l.get("kind") or "weak",
                    "tf": "sel", "valid": True})
    vistos = set()
    for p in pois:
        # Mismo de-duplicado de zona que usa `analyze` para dibujar.
        z = (p["dir"], p["tf"], p["lo"], p["hi"])
        if z in vistos:
            continue
        vistos.add(z)
        if p["lo"] <= entry <= p["hi"]:
            continue          # zona que contiene la entrada: no es pared
        # BORDE CERCANO: el precio choca con el borde que enfrenta, no con el centro.
        price = p["lo"] if arriba else p["hi"]
        out.append({"price": float(price), "kind": "poi", "tf": p["tf"],
                    "valid": bool(p.get("valid"))})
    return out


def _en_banda(price, a, b):
    """ESTRICTAMENTE entre a y b (sin importar el orden). Estricto a propósito:
    el propio TP y el propio POI de entrada no son obstáculos de sí mismos."""
    lo, hi = (a, b) if a <= b else (b, a)
    return lo < price < hi


def _contar(cands, a, b, long, atr, tol_atr=CLUSTER_ATR, solo_validos=False,
            solo_htf=False, solo_levels=False):
    """Cuenta obstáculos en la banda (a,b), de-duplicando paredes vecinas.

    `tol_atr` en unidades de ATR — RELATIVO a la volatilidad del instrumento en el
    as_of, no un porcentaje fijo (defecto #3 de este proyecto). Devuelve
    (n, primer_precio, primer_kind, primer_tf).
    """
    sel = []
    for c in cands:
        if solo_levels and c["kind"] == "poi":
            continue
        if solo_validos and c["kind"] == "poi" and not c["valid"]:
            continue
        if solo_htf and c["kind"] == "poi" and c["tf"] not in ("1D", "4h"):
            continue
        if solo_htf and c["kind"] == "poi" and not c["valid"]:
            continue
        if _en_banda(c["price"], a, b):
            sel.append(c)
    if not sel:
        return 0, None, None, None
    # Orden por CERCANÍA a la entrada `a` en la dirección del trade.
    sel.sort(key=lambda c: (c["price"] - a) if long else (a - c["price"]))
    tol = (atr or 0) * tol_atr
    grupos = [sel[0]]
    for c in sel[1:]:
        if tol > 0 and abs(c["price"] - grupos[-1]["price"]) <= tol:
            continue        # misma pared
        grupos.append(c)
    p = grupos[0]
    return len(grupos), p["price"], p["kind"], p["tf"]


def _mfe_mae(setup, sel, act_idx, end):
    """MFE/MAE en R y banderas de llegada a TP1 (1R) y al TP lejano.

    Camina desde `act_idx + 1` (NUNCA desde act_idx: ver docstring del módulo) y
    respeta la convención intrabar conservadora del proyecto: si una barra toca SL
    y objetivo, gana el SL.
    """
    long = setup["dir"] == "long"
    entry, sl, tp = setup["entry"], setup["sl"], setup["tp"]
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    tp1 = entry + risk if long else entry - risk
    mfe = mae = 0.0
    reach_tp1 = reach_tp = False
    barras = 0
    for j in range(act_idx + 1, end):
        h, l = sel[j]["h"], sel[j]["l"]
        barras += 1
        fav = (h - entry) / risk if long else (entry - l) / risk
        adv = (entry - l) / risk if long else (h - entry) / risk
        mfe = max(mfe, fav)
        mae = max(mae, adv)
        # SL primero (conservador): si la barra pega el stop, lo demás no cuenta.
        if (long and l <= sl) or ((not long) and h >= sl):
            break
        if (long and h >= tp1) or ((not long) and l <= tp1):
            reach_tp1 = True
        if (long and h >= tp) or ((not long) and l <= tp):
            reach_tp = True
            break
    return {"mfe_r": round(mfe, 3), "mae_r": round(mae, 3),
            "reach_tp1": reach_tp1, "reach_tp": reach_tp, "bars_held": barras}


def _pass(symbol, sel_tf, htf_series, htf_ts):
    """Copia FIEL de `run_setup_backtest._run_pass` + la foto de obstáculos.

    Se replica en vez de importarse porque `_run_pass` no expone el `analysis`
    intermedio. Todo lo que decide el universo (dedup por zona, `_simulate`,
    `_simulate_scaled`) se llama del módulo original para que no pueda divergir.
    """
    sel = htf_series[sel_tf]
    if not sel or len(sel) < rsb.WIN + 5:
        return []
    max_fwd = rsb.MAX_FWD.get(sel_tf, 200)
    n_bars = min(rsb.BARS.get(sel_tf, 3000), len(sel) - rsb.WIN - max_fwd)
    if n_bars <= 0:
        return []
    start = len(sel) - max_fwd - n_bars
    sel_ms = rsb.TF_MS[sel_tf]
    atr_arr = smc.atr(sel, 14)          # causal: ATR[i] sólo usa barras <= i
    closes = [c["c"] for c in sel]
    filas = []
    last_res = {}
    for i in range(start, len(sel) - 1):
        close_time = sel[i]["t"] + sel_ms
        htf_map = {tf: rsb._htf_slice(htf_series[tf], htf_ts[tf], rsb.TF_MS[tf],
                                      close_time, rsb.WIN)
                   for tf in rsb.POI_TFS}
        sel_win = sel[max(0, i - rsb.WIN + 1):i + 1]
        last = sel[i]["c"]
        _CAPTURA.clear()
        try:
            analysis = smc_live.analyze(sel_win, htf_map, last, sel_tf)
        except Exception:  # noqa: BLE001
            continue
        plan = analysis.get("tpsl")
        if not plan:
            continue
        key = f"{plan['tf']}:{plan['dir']}:{plan['entry_lo']}"
        if key in last_res and i <= last_res[key]:
            continue
        entry = plan.get("entry") or (plan["entry_lo"] + plan["entry_hi"]) / 2
        setup = {"dir": plan["dir"], "lo": plan["entry_lo"], "hi": plan["entry_hi"],
                 "sl": plan["sl"], "tp": plan["tp"], "rr": plan["rr"], "entry": entry}
        status, r, res_idx, act_idx = rsb._simulate(setup, sel, i, max_fwd)
        last_res[key] = res_idx

        long = plan["dir"] == "long"
        tp = plan["tp"]
        atr = atr_arr[i] or 0.0
        capt = list(_CAPTURA)
        niveles = analysis.get("levels") or []
        cands = _cands(capt, niveles, entry, arriba=long)
        # --- conteos principales (banda entry → tp) --------------------------
        n_all, p1, k1, tf1 = _contar(cands, entry, tp, long, atr)
        n_valid, pv, kv, tfv = _contar(cands, entry, tp, long, atr, solo_validos=True)
        n_lv, _, _, _ = _contar(cands, entry, tp, long, atr, solo_levels=True)
        n_htf, _, _, _ = _contar(cands, entry, tp, long, atr, solo_htf=True)
        # sensibilidad al de-duplicado (0 / 0,25 / 0,50 ATR)
        n_tol0, _, _, _ = _contar(cands, entry, tp, long, atr, tol_atr=0.0)
        n_tol50, _, _, _ = _contar(cands, entry, tp, long, atr, tol_atr=0.50)
        # --- control (a) placebo: obstáculos desplazados ±0,3 ATR -------------
        # Signo alternado de forma determinista (índice par/impar) para que el
        # desplazamiento no sea sistemáticamente hacia el TP ni hacia la entrada.
        d = atr * PLACEBO_ATR
        placebo = [{**c, "price": c["price"] + (d if idx % 2 == 0 else -d)}
                   for idx, c in enumerate(cands)]
        n_placebo, _, _, _ = _contar(placebo, entry, tp, long, atr)
        # --- control (b) DETRÁS del entry: banda espejo -----------------------
        # Misma distancia, dirección contraria, con el borde de choque recalculado
        # para esa dirección. Si esto predice, hay fuga y el estudio es inválido.
        espejo = entry - (tp - entry)
        cands_b = _cands(capt, niveles, entry, arriba=not long)
        n_behind, _, _, _ = _contar(cands_b, entry, espejo, not long, atr)

        dist1 = abs(p1 - entry) if p1 is not None else None
        risk = abs(entry - plan["sl"])
        fila = {
            "pair": symbol, "sel_tf": sel_tf, "poi_tf": plan["tf"], "dir": plan["dir"],
            "t": sel[i]["t"], "rr": plan["rr"], "entry": entry, "sl": plan["sl"],
            "tp": tp, "sl_pct": (risk / entry) if entry else None,
            "sl_capped": plan.get("sl_capped"), "disc_ok": plan.get("disc_ok"),
            "tp_label": plan.get("tp_label"), "status": status, "r": r,
            "atr": atr, "atr_pct": (atr / last) if last else None,
            "trend200": ((last / closes[i - 200] - 1) if i >= 200 and closes[i - 200] else 0.0),
            "band_atr": (abs(tp - entry) / atr) if atr else None,
            "obst_all": n_all, "obst_valid": n_valid, "obst_levels": n_lv,
            "obst_htf": n_htf, "obst_tol0": n_tol0, "obst_tol50": n_tol50,
            "obst_placebo": n_placebo, "obst_behind": n_behind,
            "first_obstacle_kind": k1, "first_obstacle_tf": tf1,
            "distance_to_first_obstacle_atr": (dist1 / atr) if (dist1 and atr) else None,
            "vacuum_rr": (dist1 / risk) if (dist1 and risk) else None,
            "target_beyond_first_reference": n_all > 0,
        }
        if status in ("ganada", "perdida") and act_idx is not None:
            end = min(len(sel), i + 1 + max_fwd)
            esc = rsb._simulate_scaled(setup, sel, act_idx, end,
                                       rsb.SCALE_VARIANTS["real_vivo"]["legs"],
                                       rsb.SCALE_VARIANTS["real_vivo"]["be_after"],
                                       rsb.SCALE_VARIANTS["real_vivo"].get("trail_r"))
            fila["r_real_vivo"] = esc
            ex = _mfe_mae(setup, sel, act_idx, end)
            if ex:
                fila.update(ex)
        filas.append(fila)
    return filas


def recolectar():
    _instrumentar()
    todo = []
    for _live, symbol in rsb.SYMBOLS:
        series = {tf: rsb._load(symbol, tf) for tf in set(rsb.POI_TFS) | set(rsb.SEL_TFS)}
        if any(series[tf] is None for tf in rsb.POI_TFS):
            print(f"  {symbol}: faltan klines, lo salto")
            continue
        ts = {tf: [c["t"] for c in series[tf]] for tf in series}
        for sel_tf in rsb.SEL_TFS:
            t0 = time.time()
            f = _pass(symbol, sel_tf, series, ts)
            todo.extend(f)
            print(f"  {symbol} {sel_tf}: {len(f)} planes en {time.time()-t0:.0f}s")
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(todo, fh)
    print(f"caché: {CACHE} ({len(todo)} planes)")
    return todo


# ===========================================================================
# PARTE 2 — ESTADÍSTICA
# ===========================================================================

def netR(r, sl_pct):
    """R neto con el modelo maker-aware del Diario, escalado por el % del stop.
    El costo se paga sobre el NOCIONAL: en unidades de R pesa más cuando el stop
    es ajustado. Por eso se divide por sl_pct y no se resta un fijo."""
    if r is None or not sl_pct or sl_pct <= 0:
        return None
    return r - _cost_fraction(r > 0) / sl_pct


def dia(ms):
    return dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def bloques_diarios(rows):
    """Agrupa por día UTC. Es la unidad de remuestreo: en este proyecto 39 trades
    del Diario cayeron en 8 días (31 de ellos en 3 días seguidos) y un p-value que
    asumía independencia mintió por 10 órdenes de magnitud."""
    d = {}
    for r in rows:
        d.setdefault(dia(r["t"]), []).append(r)
    return list(d.values())


def boot_stat(rows, fn, rng, B=BOOT_B):
    """CI95 y p bilateral de un estadístico cualquiera, por bloques diarios."""
    base = fn(rows)
    if base is None:
        return None
    bl = bloques_diarios(rows)
    k = len(bl)
    vals = []
    for _ in range(B):
        m = []
        for _ in range(k):
            m.extend(bl[rng.randrange(k)])
        v = fn(m)
        if v is not None:
            vals.append(v)
    if len(vals) < 50:
        return {"punto": round(base, 4), "ci95": None, "p": None, "n_boot": len(vals)}
    vals.sort()
    lo = vals[int(0.025 * len(vals))]
    hi = vals[int(0.975 * len(vals))]
    # p bootstrap bilateral: fracción de remuestreos con signo contrario al punto,
    # x2. Tiene piso 1/B — un p de 0,0005 con B=2000 significa "≤ el piso".
    peor = (sum(1 for v in vals if v <= 0) if base > 0
            else sum(1 for v in vals if v >= 0))
    p = min(1.0, 2.0 * peor / len(vals))
    return {"punto": round(base, 4), "ci95": [round(lo, 4), round(hi, 4)],
            "p": round(p, 5), "cruza_cero": lo <= 0 <= hi, "n_boot": len(vals)}


def _spearman(a, b):
    """Correlación de rangos, a mano (no hay scipy). Con empates usa rangos medios.
    Sirve para una sola pregunta descriptiva: ¿el rr planificado y el vacío
    disponible ordenan los trades igual, o son dos cosas distintas?"""
    if len(a) < 10:
        return None

    def rangos(v):
        orden = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(orden):
            j = i
            while j + 1 < len(orden) and v[orden[j + 1]] == v[orden[i]]:
                j += 1
            medio = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[orden[k]] = medio
            i = j + 1
        return r

    ra, rb = rangos(a), rangos(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return round(num / (da * db), 3) if da and db else None


def holm(pvals: dict):
    """Holm-Bonferroni. Ya nos pasó con fuerza relativa: 5 de 81 variantes se veían
    significativas sin corregir y ninguna sobrevivió."""
    items = sorted(((k, v) for k, v in pvals.items() if v is not None), key=lambda x: x[1])
    m = len(items)
    out, prev = {}, 0.0
    for i, (k, p) in enumerate(items):
        aj = min(1.0, max(prev, (m - i) * p))
        prev = aj
        out[k] = {"p_crudo": p, "p_holm": round(aj, 5), "sobrevive": aj < 0.05}
    for k, v in pvals.items():
        if v is None:
            out[k] = {"p_crudo": None, "p_holm": None, "sobrevive": False}
    return out


# --- OLS pura (no hay numpy/scipy en este venv) -----------------------------

def _resolver(A, b):
    """Gauss con pivoteo parcial. Devuelve None si la matriz es singular (columnas
    colineales: pasa cuando un dummy queda vacío en un remuestreo)."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            return None
        M[c], M[piv] = M[piv], M[c]
        pv = M[c][c]
        for r in range(n):
            if r == c:
                continue
            f = M[r][c] / pv
            if f:
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def _gram(X, y, k):
    """(X'X | X'y) de un bloque, APLANADO en una sola lista de k*k+k floats.

    Se precalcula POR DÍA para que cada remuestreo del bootstrap sea una suma de
    vectores y no un refit sobre miles de filas: con ~1.200 días y 1.000
    remuestreos, refitear sería del orden de 10^9 operaciones en Python puro.
    Aplanado + `map(add, ...)` en vez de bucles anidados por la misma razón.
    """
    g = [0.0] * (k * k + k)
    for row, yy in zip(X, y):
        for a in range(k):
            ra = row[a]
            if ra == 0.0:
                continue
            g[k * k + a] += ra * yy
            base = a * k
            for b in range(k):
                g[base + b] += ra * row[b]
    return g


def _sumar(grams, idxs, k):
    from operator import add
    acc = [0.0] * (k * k + k)
    for i in idxs:
        acc = list(map(add, acc, grams[i]))
    XtX = [acc[a * k:(a + 1) * k] for a in range(k)]
    Xty = acc[k * k:]
    return XtX, Xty


def ols_bloques(rows, ycol, cols, rng, B=BOOT_OLS):
    """OLS de `ycol` sobre `cols` (lista de (nombre, fn)) + CI por bloques diarios.

    Los desenlaces binarios (reach_tp1/reach_tp) se ajustan como modelo lineal de
    probabilidad: el coeficiente se lee directo como diferencia de probabilidad, que
    es lo que interesa acá. No es logit; se declara como limitación.
    """
    nombres = [c[0] for c in cols]
    bl = bloques_diarios(rows)
    Xs, ys = [], []
    for b in bl:
        X = [[1.0] + [f(r) for _, f in cols] for r in b]
        Y = [float(r[ycol]) for r in b]
        Xs.append(X)
        ys.append(Y)
    k = 1 + len(cols)
    grams = [_gram(X, Y, k) for X, Y in zip(Xs, ys)]
    A, bb = _sumar(grams, range(len(grams)), k)
    base = _resolver(A, bb)
    if base is None:
        return None
    muestras = {n: [] for n in nombres}
    nb = len(grams)
    for _ in range(B):
        idxs = [rng.randrange(nb) for _ in range(nb)]
        A, bb = _sumar(grams, idxs, k)
        sol = _resolver(A, bb)
        if sol is None:
            continue
        for j, n in enumerate(nombres):
            muestras[n].append(sol[j + 1])
    out = {}
    for j, n in enumerate(nombres):
        v = sorted(muestras[n])
        if len(v) < 50:
            out[n] = {"coef": round(base[j + 1], 5), "ci95": None, "p": None}
            continue
        lo, hi = v[int(0.025 * len(v))], v[int(0.975 * len(v))]
        pt = base[j + 1]
        peor = sum(1 for x in v if x <= 0) if pt > 0 else sum(1 for x in v if x >= 0)
        out[n] = {"coef": round(pt, 5), "ci95": [round(lo, 5), round(hi, 5)],
                  "p": round(min(1.0, 2.0 * peor / len(v)), 5),
                  "cruza_cero": lo <= 0 <= hi}
    out["_n"] = len(rows)
    out["_dias"] = nb
    return out


# ===========================================================================
# PARTE 3 — AGREGACIÓN
# ===========================================================================

def celda(n):
    return "3+" if n >= 3 else str(n)


def resumen(rows):
    if not rows:
        return {"n": 0}
    net = [r["netR"] for r in rows]
    net_s = sorted(net)
    n = len(net)
    tp1 = [r for r in rows if r.get("reach_tp1") is not None]
    vac = sorted(r["vacuum_rr"] for r in rows if r.get("vacuum_rr"))
    vivo = [r["netR_real_vivo"] for r in rows if r.get("netR_real_vivo") is not None]
    return {
        "n": n,
        "dias": len({dia(r["t"]) for r in rows}),
        "netR_medio": round(sum(net) / n, 3),
        "netR_mediano": round(net_s[n // 2], 3),
        "win_pct": round(100 * sum(1 for r in rows if r["r"] > 0) / n, 1),
        "tp1_pct": round(100 * sum(1 for r in tp1 if r["reach_tp1"]) / len(tp1), 1) if tp1 else None,
        "tp_pct": round(100 * sum(1 for r in rows if r.get("reach_tp")) / n, 1),
        "mfe_r_medio": round(sum(r.get("mfe_r") or 0 for r in rows) / n, 2),
        "mae_r_medio": round(sum(r.get("mae_r") or 0 for r in rows) / n, 2),
        "rr_medio": round(sum(r["rr"] for r in rows) / n, 1),
        "rr_mediano": round(sorted(r["rr"] for r in rows)[n // 2], 1),
        "vacuum_rr_mediano": round(vac[len(vac) // 2], 2) if vac else None,
        "n_con_vacuum_rr": len(vac),
        "netR_real_vivo_medio": round(sum(vivo) / len(vivo), 3) if vivo else None,
        "netR_real_vivo_mediano": (round(sorted(vivo)[len(vivo) // 2], 3)
                                   if vivo else None),
    }


def dif_estratificada(rows, flagcol, ycol, quintiles):
    """Diferencia (flag=1) − (flag=0) promediada DENTRO de estratos de RR × dirección
    y re-ponderada por el tamaño del estrato. Es el control por RR sin suponer forma
    funcional: si el efecto sólo existía porque los trades con obstáculos tienen otro
    RR, acá se muere."""
    est = {}
    for r in rows:
        est.setdefault((r["_rrq"], r["dir"]), []).append(r)
    num = den = 0.0
    for _, g in est.items():
        a = [float(x[ycol]) for x in g if x[flagcol]]
        b = [float(x[ycol]) for x in g if not x[flagcol]]
        if len(a) < 5 or len(b) < 5:
            continue
        w = len(g)
        num += w * (sum(a) / len(a) - sum(b) / len(b))
        den += w
    return (num / den) if den else None


def main():
    rng = random.Random(SEED)
    if "--recolectar" in sys.argv or not os.path.isfile(CACHE):
        print("Recolectando (re-corre el pipeline del bot con instrumentación)...")
        crudos = recolectar()
    else:
        with open(CACHE, encoding="utf-8") as fh:
            crudos = json.load(fh)
        print(f"caché: {len(crudos)} planes ({CACHE})")

    # --- UNIVERSO: activados, rr>=5, con netR calculable ---------------------
    rows = []
    for t in crudos:
        if t["status"] not in ("ganada", "perdida"):
            continue
        if t["rr"] < RR_MIN:
            continue
        nr = netR(t["r"], t.get("sl_pct"))
        if nr is None:
            continue
        t["netR"] = nr
        t["netR_real_vivo"] = netR(t.get("r_real_vivo"), t.get("sl_pct"))
        t["year"] = dt.datetime.utcfromtimestamp(t["t"] / 1000).year
        t["oos"] = t["t"] > CORTE_OOS_MS
        rows.append(t)
    rows.sort(key=lambda r: r["t"])
    if not rows:
        print("sin trades")
        return

    # Quintiles de RR (derivados de los datos, no umbrales inventados).
    rr_ord = sorted(r["rr"] for r in rows)
    qs = [rr_ord[int(len(rr_ord) * k / 5)] for k in range(1, 5)]
    for r in rows:
        r["_rrq"] = sum(1 for q in qs if r["rr"] >= q)

    # Control (c): conteo permutado DENTRO de deciles de |tp-entry|/ATR. Se hace
    # ANTES de binarizar para que el control reciba exactamente la misma regla de
    # corte que el tratamiento (si no, se estaría comparando con otra vara).
    con_band = [r for r in rows if r.get("band_atr")]
    con_band.sort(key=lambda r: r["band_atr"])
    for k in range(10):
        g = con_band[int(len(con_band) * k / 10):int(len(con_band) * (k + 1) / 10)]
        vals = [r["obst_all"] for r in g]
        rng.shuffle(vals)
        for r, v in zip(g, vals):
            r["obst_perm"] = v
    for r in rows:
        r.setdefault("obst_perm", r["obst_all"])

    # BINARIZACIÓN. El pre-registro decía `count > 0`. Si la celda 0 queda casi vacía
    # ese contraste es DEGENERADO (flag=1 para todos → no hay con qué comparar) y no
    # se puede interpretar. En ese caso se cae a `count >= mediana del propio conteo`:
    # un corte RELATIVO derivado de los datos, no un umbral absoluto inventado
    # (defecto #3 del proyecto). Qué regla se usó queda escrito en el JSON.
    reglas = {}
    for d in DEFS + ("obst_behind", "obst_placebo", "obst_perm"):
        vals = sorted(r[d] for r in rows)
        med = vals[len(vals) // 2]
        n0 = sum(1 for r in rows if r[d] == 0)
        usa_med = n0 < 50 or n0 > len(rows) - 50
        corte = max(1, med)
        for r in rows:
            r["flag_" + d] = (r[d] >= corte) if usa_med else (r[d] > 0)
        reglas[d] = {"regla": (f">= {corte} (mediana del propio conteo)"
                               if usa_med else "> 0 (pre-registrado)"),
                     "n_celda_0": n0,
                     "n_flag_1": sum(1 for r in rows if r["flag_" + d]),
                     "motivo": ("celda 0 degenerada: el contraste >0 no tiene grupo de "
                                "comparacion" if usa_med else "pre-registrado")}

    covs = [
        ("log_rr", lambda r: math.log(max(r["rr"], 1e-6))),
        ("is_long", lambda r: 1.0 if r["dir"] == "long" else 0.0),
        ("log_atr_pct", lambda r: math.log(max(r.get("atr_pct") or 1e-6, 1e-6))),
        ("trend200", lambda r: r.get("trend200") or 0.0),
        ("sel_4h", lambda r: 1.0 if r["sel_tf"] == "4h" else 0.0),
        ("poi_4h", lambda r: 1.0 if r["poi_tf"] == "4h" else 0.0),
        ("poi_1D", lambda r: 1.0 if r["poi_tf"] == "1D" else 0.0),
    ]
    pares = sorted({r["pair"] for r in rows})[1:]     # base = el primero (evita colinealidad)
    covs += [(f"par_{p}", (lambda p: (lambda r: 1.0 if r["pair"] == p else 0.0))(p))
             for p in pares]

    res = {
        "meta": {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "aviso": "Research only - No senal - No bot - NO usar para activar live",
            "generado": dt.datetime.now(dt.timezone.utc).isoformat(),
            "diseno_preregistrado": DESIGN,
            "fuente": "re-corrida instrumentada de smc_live.analyze (pipeline del bot)",
            "planes_totales": len(crudos),
            "universo": {"activados_rr>=5": len(rows),
                         "dias": len({dia(r["t"]) for r in rows}),
                         "span": [dia(rows[0]["t"]), dia(rows[-1]["t"])],
                         "sel_tfs": sorted({r["sel_tf"] for r in rows}),
                         "pares": sorted({r["pair"] for r in rows})},
            "quintiles_rr": [round(q, 1) for q in qs],
            "costos": "maker-aware del Diario (_cost_fraction) / sl_pct",
            "reglas_de_binarizacion": reglas,
            "desviaciones_del_diseno": [
                ("La binarizacion pre-registrada era `count > 0`. Donde la celda 0 quedo "
                 "practicamente vacia el contraste es degenerado (flag=1 para todos) y se "
                 "reemplazo por `count >= mediana del propio conteo`, corte relativo "
                 "derivado de los datos. Ver meta.reglas_de_binarizacion: dice para cada "
                 "definicion cual regla se aplico y por que."),
                ("El de-duplicado de paredes vecinas (0,25 x ATR) no estaba en el "
                 "pre-registro; sin el, dos pivotes a 3 puntos de distancia contaban como "
                 "dos paredes. Se reporta sensibilidad a 0 / 0,25 / 0,50 ATR."),
                ("El control (a) placebo resulto poco informativo POR CONSTRUCCION: la "
                 "banda entry->tp es de varios ATR, asi que desplazar +-0,3 ATR casi no "
                 "cambia la pertenencia. Se reporta igual, pero no discrimina."),
            ],
        },
    }

    # --- 1) Descriptivo: distribución de obstáculos y celdas ----------------
    dist = {}
    for d in DEFS + ("obst_behind", "obst_placebo", "obst_tol0", "obst_tol50", "obst_perm"):
        c = {}
        for r in rows:
            c[celda(r[d])] = c.get(celda(r[d]), 0) + 1
        dist[d] = {k: c.get(k, 0) for k in ("0", "1", "2", "3+")}
    res["distribucion_celdas"] = dist
    res["celdas_bajo_minimo"] = {
        d: [k for k, v in dist[d].items() if v < DESIGN["n_minimo_por_celda"]]
        for d in DEFS}

    # --- 2) Por celda de obstáculos (la tabla que responde la hipótesis) ----
    res["por_celda"] = {}
    for d in DEFS:
        res["por_celda"][d] = {k: resumen([r for r in rows if celda(r[d]) == k])
                               for k in ("0", "1", "2", "3+")}
    res["por_celda"]["CONTROL_b_detras"] = {
        k: resumen([r for r in rows if celda(r["obst_behind"]) == k])
        for k in ("0", "1", "2", "3+")}
    res["por_celda"]["CONTROL_c_permutado"] = {
        k: resumen([r for r in rows if celda(r["obst_perm"]) == k])
        for k in ("0", "1", "2", "3+")}

    # --- 3) Contrastes crudos + estratificados por RR, con CI de bloques ----
    print("\nbootstrap de bloques diarios...")
    contrastes, pvals = {}, {}
    familia = [(d, y) for d in DEFS for y in DESENLACES]
    for d, y in familia:
        col = "flag_" + d
        sub = [r for r in rows if r.get(y) is not None]

        def crudo(rr, _c=col, _y=y):
            a = [float(x[_y]) for x in rr if x[_c]]
            b = [float(x[_y]) for x in rr if not x[_c]]
            if len(a) < 10 or len(b) < 10:
                return None
            return sum(a) / len(a) - sum(b) / len(b)

        def estrat(rr, _c=col, _y=y):
            return dif_estratificada(rr, _c, _y, qs)

        key = f"{d}|{y}"
        contrastes[key] = {
            "n_con": sum(1 for r in sub if r[col]),
            "n_sin": sum(1 for r in sub if not r[col]),
            "crudo": boot_stat(sub, crudo, rng),
            "estratificado_rr_dir": boot_stat(sub, estrat, rng),
        }
        st = contrastes[key]["estratificado_rr_dir"]
        pvals[key] = st["p"] if st else None
        print(f"  {key:32} crudo={contrastes[key]['crudo']}")
    res["contrastes"] = contrastes
    res["holm"] = holm(pvals)

    # --- 4) Controles negativos --------------------------------------------
    ctrl = {}
    for nombre, col, comment in (
        ("a_placebo", "flag_obst_placebo",
         "obstaculos desplazados +-0,3 ATR"),
        ("b_detras_del_entry", "flag_obst_behind",
         "conteo en la banda ESPEJO; si predice, hay fuga y el estudio es INVALIDO"),
        ("c_permutado_por_distancia", "flag_obst_perm",
         "conteo permutado dentro de deciles de |tp-entry|/ATR"),
    ):
        blk = {"que_es": comment}
        for y in DESENLACES:
            sub = [r for r in rows if r.get(y) is not None]

            def crudo(rr, _c=col, _y=y):
                a = [float(x[_y]) for x in rr if x[_c]]
                b = [float(x[_y]) for x in rr if not x[_c]]
                if len(a) < 10 or len(b) < 10:
                    return None
                return sum(a) / len(a) - sum(b) / len(b)

            blk[y] = {"crudo": boot_stat(sub, crudo, rng),
                      "estratificado": boot_stat(
                          sub, lambda rr, _c=col, _y=y: dif_estratificada(rr, _c, _y, qs), rng)}
        ctrl[nombre] = blk
    res["controles_negativos"] = ctrl

    # --- 5) OLS: ¿aporta POR ENCIMA de lo que el RR ya dice? ----------------
    print("OLS con CI de bloques...")
    res["ols"] = {}
    for y in DESENLACES:
        sub = [r for r in rows if r.get(y) is not None]
        res["ols"][y] = {
            "baseline_solo_rr": ols_bloques(sub, y, covs, rng),
            "con_obst_all": ols_bloques(
                sub, y, [("obst_flag", lambda r: 1.0 if r["flag_obst_all"] else 0.0),
                         ("obst_n", lambda r: float(min(r["obst_all"], 6)))] + covs, rng),
            "con_obst_valid": ols_bloques(
                sub, y, [("obst_flag", lambda r: 1.0 if r["flag_obst_valid"] else 0.0),
                         ("obst_n", lambda r: float(min(r["obst_valid"], 6)))] + covs, rng),
            "con_vacuum_rr": ols_bloques(
                sub, y, [("log_vacuum_rr",
                          lambda r: math.log(max(r.get("vacuum_rr") or r["rr"], 1e-6)))] + covs, rng),
            "CONTROL_b_detras": ols_bloques(
                sub, y, [("behind_flag", lambda r: 1.0 if r["flag_obst_behind"] else 0.0),
                         ("behind_n", lambda r: float(min(r["obst_behind"], 6)))] + covs, rng),
        }

    # --- 6) Walk-forward por año e IS/OOS ----------------------------------
    res["por_ano"] = {}
    for yr in sorted({r["year"] for r in rows}):
        g = [r for r in rows if r["year"] == yr]
        a = [r["netR_real_vivo"] for r in g if r["obst_all"] > 0 and r.get("netR_real_vivo") is not None]
        b = [r["netR_real_vivo"] for r in g if r["obst_all"] == 0 and r.get("netR_real_vivo") is not None]
        res["por_ano"][str(yr)] = {
            "n": len(g), "n_con_obst": len(a), "n_sin_obst": len(b),
            "netR_con": round(sum(a) / len(a), 3) if a else None,
            "netR_sin": round(sum(b) / len(b), 3) if b else None,
            "dif": round(sum(a) / len(a) - sum(b) / len(b), 3) if (a and b) else None,
            "tp1_con": round(100 * sum(1 for r in g if r["obst_all"] > 0 and r.get("reach_tp1")) /
                             max(1, sum(1 for r in g if r["obst_all"] > 0)), 1),
            "tp1_sin": round(100 * sum(1 for r in g if r["obst_all"] == 0 and r.get("reach_tp1")) /
                             max(1, sum(1 for r in g if r["obst_all"] == 0)), 1),
        }
    res["is_oos"] = {}
    for nombre, sel in (("IS", [r for r in rows if not r["oos"]]),
                        ("OOS", [r for r in rows if r["oos"]])):
        res["is_oos"][nombre] = {
            "con_obst": resumen([r for r in sel if r["obst_all"] > 0]),
            "sin_obst": resumen([r for r in sel if r["obst_all"] == 0]),
        }

    # --- 7) Auditoría del gate rr>=5 (la pregunta de coherencia interna) ---
    vac = [r["vacuum_rr"] for r in rows if r.get("vacuum_rr")]
    vac.sort()
    res["auditoria_gate_rr5"] = {
        "que_mide": ("si el rr planificado y el vacuum_rr (a la PRIMERA pared) "
                     "describen el mismo recorrido"),
        "rr_mediano": round(sorted(r["rr"] for r in rows)[len(rows) // 2], 1),
        "vacuum_rr_mediano": round(vac[len(vac) // 2], 2) if vac else None,
        "pct_con_al_menos_una_pared": round(100 * sum(1 for r in rows if r["obst_all"] > 0) / len(rows), 1),
        "pct_tp_a_mas_de_una_pared": round(100 * sum(1 for r in rows if r["obst_all"] >= 2) / len(rows), 1),
        "dist_tp_pct_mediana": round(sorted(abs(r["tp"] / r["entry"] - 1) * 100
                                            for r in rows)[len(rows) // 2], 2),
        "primer_obstaculo_kind": {
            k: sum(1 for r in rows if r.get("first_obstacle_kind") == k)
            for k in ("weak", "strong", "poi")},
        "primer_obstaculo_tf": {
            k: sum(1 for r in rows if r.get("first_obstacle_tf") == k)
            for k in ("sel", "1h", "4h", "1D")},
        # El plan de salida del bot cobra 75% de la posicion en <=2R. Si la primera
        # pared aparece ANTES de 2R, la ceguera del TP afecta al grueso del tamaño;
        # si aparece despues, solo afecta al runner. Es la pregunta operativa.
        "pct_primera_pared_antes_de_1R": round(
            100 * sum(1 for r in rows if (r.get("vacuum_rr") or 99) < 1) / len(rows), 1),
        "pct_primera_pared_antes_de_2R": round(
            100 * sum(1 for r in rows if (r.get("vacuum_rr") or 99) < 2) / len(rows), 1),
        "correlacion_rango_rr_vs_vacuum_rr": _spearman(
            [r["rr"] for r in rows if r.get("vacuum_rr")],
            [r["vacuum_rr"] for r in rows if r.get("vacuum_rr")]),
        "nota": ("DESCRIPTIVO, sin contraste: no entra en la familia de Holm. "
                 "Mide si el rr planificado y el vacio disponible describen el "
                 "mismo recorrido, no si alguno predice el resultado."),
    }

    # --- 7b) DESCRIPTIVO: ¿discrimina mejor el vacuum_rr que el rr? ---------
    # Hipotesis 1 de la clase 7. Se reporta como tabla, sin p-value: elegir a
    # posteriori la variable que mejor se ve es exactamente como se fabrican
    # hallazgos falsos. Si la tabla sugiere algo, se pre-registra aparte.
    def _quintiles(col):
        vv = sorted(r[col] for r in rows if r.get(col))
        if len(vv) < 50:
            return None
        cortes = [vv[int(len(vv) * k / 5)] for k in range(1, 5)]
        out = {}
        for q in range(5):
            g = [r for r in rows if r.get(col) is not None
                 and sum(1 for c in cortes if r[col] >= c) == q]
            out[f"Q{q + 1}"] = {"corte_desde": round(cortes[q - 1], 2) if q else None,
                                **resumen(g)}
        return out

    res["descriptivo_quintiles"] = {"por_rr": _quintiles("rr"),
                                    "por_vacuum_rr": _quintiles("vacuum_rr")}

    # --- 8) Sensibilidad al de-duplicado (0 / 0,25 / 0,50 ATR) -------------
    res["sensibilidad_dedup"] = {}
    for d in ("obst_tol0", "obst_all", "obst_tol50"):
        sub = [r for r in rows if r.get("netR_real_vivo") is not None]
        a = [r["netR_real_vivo"] for r in sub if r[d] > 0]
        b = [r["netR_real_vivo"] for r in sub if r[d] == 0]
        res["sensibilidad_dedup"][d] = {
            "n_con": len(a), "n_sin": len(b),
            "dif_netR_real_vivo": round(sum(a) / len(a) - sum(b) / len(b), 3) if (a and b) else None}

    # --- 9) VEREDICTO, calculado de los propios números --------------------
    # Se computa en vez de escribirse a mano para que no pueda quedar desalineado
    # con la tabla de arriba si el estudio se re-corre con otros datos.
    sobrevive_holm = sorted(k for k, v in res["holm"].items() if v["sobrevive"])
    ctrl_b = res["controles_negativos"]["b_detras_del_entry"]
    b_plano = all((ctrl_b[y]["estratificado"] or {}).get("cruza_cero", True)
                  for y in DESENLACES)
    # ¿algún efecto crudo con CI fuera de cero se muere al estratificar por RR?
    muere_con_rr = []
    for k, v in contrastes.items():
        cr, es = v["crudo"], v["estratificado_rr_dir"]
        if cr and es and not cr.get("cruza_cero") and es.get("cruza_cero"):
            muere_con_rr.append(k)
    anios = [v["dif"] for v in res["por_ano"].values() if v["dif"] is not None]
    if not b_plano:
        vd = "INVALIDO"
    elif sobrevive_holm and len([d for d in anios if d < 0]) >= 3:
        vd = "PROMOVER"
    elif sobrevive_holm:
        vd = "SEGUIR INVESTIGANDO"
    else:
        vd = "DESCARTAR"
    res["veredicto"] = {
        "decision": vd,
        "sobreviven_holm": sobrevive_holm,
        "control_b_plano": b_plano,
        "contrastes_que_mueren_al_controlar_por_rr": muere_con_rr,
        "anios_en_la_direccion_de_la_hipotesis": len([d for d in anios if d < 0]),
        "anios_totales": len(anios),
        "por_que": ("criterio pre-registrado: PROMOVER exige sobrevivir Holm + control "
                    "(b) plano + direccion en >=3 de 5 anios; DESCARTAR si el control "
                    "(b) muestra efecto (fuga) o si el efecto desaparece al controlar "
                    "por RR"),
    }

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False)
    print(f"\nresultados: {OUT_JSON}")
    print("VEREDICTO:", json.dumps(res["veredicto"], ensure_ascii=False))

    u = res["meta"]["universo"]
    print(f"{u['activados_rr>=5']} trades activados rr>=5 en {u['dias']} dias "
          f"({u['span'][0]} .. {u['span'][1]})")
    print("\ndistribucion obst_all:", dist["obst_all"])
    print("celdas bajo el minimo de 300:", res["celdas_bajo_minimo"]["obst_all"])
    def _tabla(titulo, blk):
        print(f"\n{titulo}")
        for k in ("0", "1", "2", "3+"):
            s = blk.get(k) or {}
            if not s.get("n"):
                continue
            vivo = s.get("netR_real_vivo_medio")
            print(f"  {k:3} n={s['n']:5} netR={s['netR_medio']:+.3f} "
                  f"vivo={vivo if vivo is None else format(vivo, '+.3f')} "
                  f"TP1={s['tp1_pct']}% TP={s['tp_pct']}% rr_med={s['rr_mediano']}")

    _tabla("por celda (obst_all):", res["por_celda"]["obst_all"])
    _tabla("CONTROL (b) detras del entry:", res["por_celda"]["CONTROL_b_detras"])
    _tabla("CONTROL (c) permutado por distancia:", res["por_celda"]["CONTROL_c_permutado"])
    print("\nHolm:")
    for k, v in sorted(res["holm"].items()):
        print(f"  {k:34} p={v['p_crudo']} holm={v['p_holm']} "
              f"{'SOBREVIVE' if v['sobrevive'] else '-'}")


if __name__ == "__main__":
    main()
