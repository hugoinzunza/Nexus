"""Estudio "ruptura + retest" — el cuarto brazo del evento de entrada.

CONTEXTO Y POR QUE EXISTE ESTE ESTUDIO
--------------------------------------
El estudio del abort (`bta_visual_abort.py`, informe 2026-07-05) dejó medidos
tres de los cuatro brazos posibles del evento de entrada: `toque`, `un cierre` y
`dos cierres` (CDC). El hallazgo fue: las zonas que LUEGO confirman CDC rinden
+0.68R contra -0.16R las que no (la confirmación SI contiene información), pero
entrar EN el CDC pierde, porque la entrada es tardía y el RR realizado se
destruye. Clásico "la confirmación mejora la precisión y mata el RR".

Queda un brazo sin medir: **ruptura + retest**. Hipótesis pre-registrada: el
retest conserva la información del CDC (hubo ruptura confirmada por cierre) pero
recupera el precio de entrada (entra cuando el precio vuelve al nivel roto, no en
la vela expansiva). Si el problema del CDC es el PRECIO y no la INFORMACION, este
brazo debería mejorar el RR realizado. Si falla, el hallazgo es que la
información del CDC no es explotable en ninguna forma de entrada — resultado
negativo, igualmente entregable.

DISEÑO PRE-REGISTRADO (congelado antes de mirar resultados)
-----------------------------------------------------------
* Universo: EXACTAMENTE los 8.440 trades pareados del estudio del abort. Mismos
  POIs, mismo toque, mismo stop, mismo target, mismos costos maker-aware, misma
  resolución intrabar conservadora. Si el universo cambia, la comparación contra
  los brazos ya medidos deja de valer.
* Ruptura = CIERRE de vela más allá del último swing confirmado (piv=2) en la
  dirección del plan. Es el mismo CDC del estudio previo: no vale la mecha.
* Retest = el precio vuelve al nivel roto dentro de N velas posteriores a la
  ruptura. N ∈ {4, 8, 12}, pre-registrados. NO se agrega un N nuevo después de
  ver cuál gana (defecto #2 del proyecto: cherry-picking por subconjunto).
* Buffer del nivel: RELATIVO, `TOL_ATR * ATR(14)` medido causalmente en la vela
  de ruptura. NUNCA un porcentaje fijo: es el defecto que apareció SEIS veces en
  este proyecto — 0.3% es ruido en DOGE y movimiento real en BTC. El fill es al
  precio del gatillo (nivel + tolerancia en contra), no al extremo de la vela.
* Protocolo de aislamiento: TODOS los brazos comparten stop y target del plan
  original del toque. Lo único que cambia entre brazos es la ENTRADA. Así el
  contraste mide el mecanismo (precio/tiempo de entrada) y no una mezcla de
  entrada + target recalculado.
* Costo de esperar: mientras el brazo espera (CDC y luego retest), si el SL o el
  TP originales se tocan, el brazo NO opera. Los setups que rompen y nunca
  vuelven, y los que se van directo al target sin dar retest, son un COSTO del
  brazo y se cuentan explícitamente (`desaparecidos`).

CONTROLES NEGATIVOS (obligatorios, sin ellos el estudio no vale)
----------------------------------------------------------------
(a) `up_N` / `dn_N`: mismo timing y misma mecánica, pero con el nivel DESPLAZADO
    ±SHIFT_ATR·ATR. Se corren los DOS lados a propósito: un desplazamiento de un
    solo lado confunde "el nivel importa" con "el precio de fill es mejor". Si el
    nivel real no tiene contenido, el retest verdadero debe quedar interpolado
    entre los dos desplazados (puro efecto de precio).
(b) `lvl`: mismo nivel y MISMO precio de fill, pero sin exigir ruptura confirmada
    ni vuelta: orden en el nivel que se ejecuta la primera vez que el precio
    llega ahí. Aísla "estructura ruptura+vuelta" de "entrar en ese precio". El
    nivel se toma de `lh2/ll2` en la vela del TOQUE (causal en ese instante); usar
    el nivel de la vela de ruptura sería look-ahead.
(c) `del_N`: retraso fijo de L velas desde el toque, sin ninguna condición de
    precio, donde L = retraso medio observado del retest_N. Separa "esperar" de
    "esperar A QUE PASE ALGO". Si el retest no supera a este control, el efecto es
    el tiempo, no el retest, y el brazo se DESCARTA.

METRICA PRIMARIA Y TRAMPA CONOCIDA
-----------------------------------
Primaria: netR promedio POR TRADE TOMADO, pareado 1:1 contra el mismo setup en
los otros brazos. Es lo que afirma la hipótesis ("mejor RR realizado").
Secundaria/guardarraíl: netR promedio POR SETUP del universo (0 si el brazo no
dispara). Se reporta para exponer la trampa obvia: con expectativa base negativa,
NO OPERAR le gana a operar. Una mejora que venga solo de disparar poco NO cuenta
como promoción.

Corre:   .venv/bin/python3 research/ruptura_retest.py
Escribe: research/ruptura_retest_results.json  (el informe MD se redacta aparte)
Research only · execution_enabled: false · no toca bot, dry-run ni credenciales.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import os
import random
import sys
from collections import defaultdict

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import bta_visual_abort as ab  # noqa: E402
from research import bta_visual_model2 as v2  # noqa: E402
from research import bta_visual_oos as oos  # noqa: E402
from modules.trading.strategies import detect_pois  # noqa: E402

OUT_JSON = os.path.join(WT, "research", "ruptura_retest_results.json")

# --- parámetros pre-registrados (no se tocan después de ver resultados) -------
RETEST_N = (4, 8, 12)     # velas tras la ruptura para aceptar el retest
CDC_WINDOW = 16           # v2.CONFIRM_WINDOW: ventana canónica del proyecto
ATR_LEN = 14
TOL_ATR = 0.25            # tolerancia del nivel, EN ATR (nunca % fijo)
SHIFT_ATR = 0.5           # desplazamiento del control (a), EN ATR
IS_FRAC = 0.70            # reproduce el corte del estudio del abort (2025-06-01)
SPLIT_ALT = "2025-03-19"  # corte alternativo usado en otros estudios del repo
BOOT_ITERS = 2000
BOOT_SEED = 20260726
ABORT_ARMS = ("cap03_8", "mkt_4")   # los mejores brazos del estudio previo
PAIRS7 = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "BNBUSDT",
          "DOGEUSDT")


# ------------------------------ utilidades ------------------------------

def atr_array(candles, n=ATR_LEN):
    """ATR simple (media de TR) CAUSAL: atr[j] usa solo velas <= j.

    Se usa para normalizar la tolerancia del nivel. El defecto que evita: un
    umbral absoluto (0.3%) sobre una cantidad de escala variable trata igual a
    DOGE y a BTC, y en este proyecto ya se cometió seis veces.
    """
    out = [None] * len(candles)
    trs = []
    prev_c = None
    acc = 0.0
    for j, c in enumerate(candles):
        tr = (c["h"] - c["l"]) if prev_c is None else max(
            c["h"] - c["l"], abs(c["h"] - prev_c), abs(c["l"] - prev_c))
        trs.append(tr)
        acc += tr
        if len(trs) > n:
            acc -= trs[-n - 1]
        if j >= n - 1:
            out[j] = acc / n
        prev_c = c["c"]
    return out


def walk_resolve(candles, j0, long, entry, sl, tp, include_j0):
    """Resuelve un trade desde j0 devolviendo (r_bruto, j_exit, mae_R, mfe_R).

    `include_j0=True` para fills INTRABAR (retest, controles de nivel): la vela
    del fill puede matarte, así que se revisa el SL en esa misma vela, pero NO se
    permite el TP en ella (regla conservadora de la casa: ante ambigüedad
    intrabar, manda la pérdida).
    `include_j0=False` para fills al CIERRE de j0 (toque, CDC, control de
    retraso): la vela ya terminó y no puede resolverse en ella.

    Anti-look-ahead: el barrido posterior SIEMPRE arranca en j0+1. Este es
    exactamente el bug que en este proyecto costó 1.5R por trade cuando un bucle
    arrancó en `act_idx` en vez de `act_idx + 1` (ver test_ruptura_retest.py).
    """
    risk = (entry - sl) if long else (sl - entry)
    if risk <= 0:
        return None
    mae = mfe = 0.0

    def upd(c):
        nonlocal mae, mfe
        if long:
            mae = min(mae, (c["l"] - entry) / risk)
            mfe = max(mfe, (c["h"] - entry) / risk)
        else:
            mae = min(mae, (entry - c["h"]) / risk)
            mfe = max(mfe, (entry - c["l"]) / risk)

    if include_j0:
        c = candles[j0]
        upd(c)
        if (c["l"] <= sl) if long else (c["h"] >= sl):
            return -1.0, j0, mae, mfe
    for j in range(j0 + 1, min(j0 + 1 + oos.SIM_MAX, len(candles))):
        c = candles[j]
        upd(c)
        if (c["l"] <= sl) if long else (c["h"] >= sl):
            return -1.0, j, mae, mfe
        if (c["h"] >= tp) if long else (c["l"] <= tp):
            return abs(tp - entry) / risk, j, mae, mfe
    return None


def find_cdc(candles, i_tap, long, stop, tp, lh2, ll2, window, atr=None,
             clear_atr=0.0):
    """Primera RUPTURA por cierre tras el toque. Devuelve (i_cdc, ref, motivo).

    `clear_atr` exige que el cierre despeje el nivel por al menos ese múltiplo de
    ATR. POR QUE existe: con `clear_atr=0` (definición publicada del CDC) un
    cierre que supera el nivel por un tick cuenta como ruptura, y entonces el
    "retest" se llena en la vela siguiente SIN que el precio haya vuelto a
    ninguna parte — el gatillo queda por encima del precio y deja de ser una
    orden límite. Con despeje mínimo relativo (ATR, nunca % fijo) la ruptura es
    real y el retest es un retest. Se corren las dos definiciones: `clear=0` para
    poder comparar con el brazo CDC ya publicado, y `clear=TOL_ATR` como evento
    que alimenta el retest.

    Motivos de no-ruptura: 'sl' (el plan murió antes), 'tp' (se fue al target sin
    romper: el brazo se pierde un ganador — costo real de esperar), 'sin_cdc'.
    """
    for j in range(i_tap + 1, min(i_tap + 1 + window, len(candles))):
        c = candles[j]
        if (c["l"] <= stop) if long else (c["h"] >= stop):
            return None, None, "sl"
        if (c["h"] >= tp) if long else (c["l"] <= tp):
            return None, None, "tp"
        ref = lh2[j] if long else ll2[j]
        if ref is None:
            continue
        cl = clear_atr * (atr[j] or 0.0) if (atr and clear_atr) else 0.0
        if (long and c["c"] > ref + cl) or (not long and c["c"] < ref - cl):
            return j, ref, "ok"
    return None, None, "sin_cdc"


def find_trigger(candles, j_start, j_end, long, trig, stop, tp, from_above):
    """Primera vela en [j_start, j_end] que toca `trig`. (j_fill, motivo).

    `from_above=True` (retest de un long: el precio ya está ARRIBA del nivel y
    vuelve a bajar) mira el mínimo; `False` (control de nivel: el precio viene
    desde abajo) mira el máximo. El gatillo se chequea ANTES que SL/TP dentro de
    la misma vela: si la vela toca gatillo y stop, se opera y se pierde (no se
    esquiva la pérdida).
    """
    for j in range(j_start, min(j_end + 1, len(candles))):
        c = candles[j]
        if long:
            hit = (c["l"] <= trig) if from_above else (c["h"] >= trig)
        else:
            hit = (c["h"] >= trig) if from_above else (c["l"] <= trig)
        if hit:
            return j, "ok"
        if (c["l"] <= stop) if long else (c["h"] >= stop):
            return None, "sl"
        if (c["h"] >= tp) if long else (c["l"] <= tp):
            return None, "tp"
    return None, "sin_retest"


# ------------------------------ estudio por dataset ------------------------------

def study_dataset(pair, tf):
    """Reconstruye el universo pareado del abort y le agrega los brazos nuevos.

    El bucle de POIs es una COPIA EXACTA del de `bta_visual_abort.study_dataset`
    (mismos filtros, mismo orden, mismos cortes). No se refactoriza para no
    arriesgar que el universo se mueva: la comparación pareada 1:1 contra los
    brazos ya publicados depende de que estos 8.440 trades sean los mismos.
    """
    path = os.path.join(oos.DATA_DIR, f"klines_{pair}_{tf}.json")
    candles = json.load(open(path))
    n = len(candles)
    legs = v2.build_swing_legs_v2(candles, piv=oos.LEG_PIV)
    pivrows = oos.pivot_rows(candles, oos.LEG_PIV)
    lh2, ll2 = oos.last_confirmed_arrays(candles, oos.POI_PIV)
    atr = atr_array(candles)
    t_by_idx = [c["t"] for c in candles]

    rows = []
    for k, poi in enumerate(detect_pois(candles, oos.POI_PIV, oos.POI_DISP)):
        long = poi["dir"] == "long"
        lo, hi = poi["lo"], poi["hi"]
        stop = poi["stop"] * (1 - oos.BUFFER) if long else poi["stop"] * (1 + oos.BUFFER)
        z = v2.zone_from_poi_v2(poi, legs, f"{pair}_{tf}_{k}")
        i_conf = bisect.bisect_left(t_by_idx, poi["t_conf"])

        i_tap = None
        for j in range(i_conf + 1, min(i_conf + 1 + oos.TAP_MAX, n)):
            c = candles[j]
            if (c["c"] < stop) if long else (c["c"] > stop):
                break
            if c["l"] <= hi and c["h"] >= lo:
                i_tap = j
                break
        if i_tap is None:
            continue
        entry = hi if long else lo
        t_tap = candles[i_tap]["t"]
        tp = oos.liquidity_target(pivrows, long, entry, t_tap)
        risk = (entry - stop) if long else (stop - entry)
        if tp is None or risk <= 0:
            continue
        rr = abs(tp - entry) / risk
        if rr < 1.0:
            continue
        r_base, _ = oos.resolve(candles, i_tap, long, entry, stop, tp)
        if r_base is None:
            continue                       # mismo universo que el baseline OOS

        # --- brazos ya medidos, recalculados con la misma maquinaria ---
        i_cdc_ab = None                    # CDC "estilo abort" (ventana max)
        for j in range(i_tap + 1, min(i_tap + 1 + max(ab.WINDOWS), n)):
            c = candles[j]
            if (c["l"] <= stop) if long else (c["h"] >= stop):
                break
            ref = lh2[j] if long else ll2[j]
            if ref is not None and ((long and c["c"] > ref) or
                                    (not long and c["c"] < ref)):
                i_cdc_ab = j
                break
        row = dict(pair=pair, tf=tf, dir=poi["dir"], side=z.leg_side_at_birth,
                   rr=round(rr, 1), t=t_tap,
                   base=round(oos.netR(r_base, entry, stop), 3),
                   # crudos para la 2a pasada (control de retraso); se descartan
                   # antes de serializar: el JSON solo lleva agregados.
                   _i_tap=i_tap, _entry=entry, _stop=stop, _tp=tp)
        bres = walk_resolve(candles, i_tap, long, entry, stop, tp, False)
        row["base_mae"] = round(bres[2], 2) if bres else None
        row["base_mfe"] = round(bres[3], 2) if bres else None
        row["base_rr"] = round(rr, 2)
        for abarm in ABORT_ARMS:
            mode, N = abarm.rsplit("_", 1)
            r = ab.sim_trade(candles, i_tap, long, entry, stop, tp, i_cdc_ab,
                             int(N), mode)
            row[abarm] = round(oos.netR(r if r is not None else r_base,
                                        entry, stop), 3)

        # --- ruptura (CDC) bajo el protocolo de aislamiento ---
        # `cdc0`: definición publicada (cierre más allá, sin despeje mínimo) para
        # que el brazo CDC sea comparable con el estudio previo.
        # `i_cdc`: ruptura con despeje >= TOL_ATR·ATR, el evento que alimenta el
        # retest y sus controles.
        i_cdc0, _ref0, mot0 = find_cdc(candles, i_tap, long, stop, tp, lh2, ll2,
                                       CDC_WINDOW)
        i_cdc, ref, motivo = find_cdc(candles, i_tap, long, stop, tp, lh2, ll2,
                                      CDC_WINDOW, atr, TOL_ATR)
        row["cdc0_motivo"] = mot0
        row["cdc_motivo"] = motivo
        a_cdc = atr[i_cdc] if i_cdc is not None else None

        def arm(j_fill, px, tag, lag_from):
            """Escribe columnas de un brazo que llenó en `px` en la vela j_fill."""
            res = walk_resolve(candles, j_fill, long, px, stop, tp, True)
            if res is None:
                row[tag] = None
                return
            r, j_ex, mae, mfe = res
            rsk = (px - stop) if long else (stop - px)
            row[tag] = round(oos.netR(r, px, stop), 3)
            row[tag + "_rr"] = round(abs(tp - px) / rsk, 2)
            row[tag + "_lag"] = j_fill - lag_from
            row[tag + "_mae"] = round(mae, 2)
            row[tag + "_mfe"] = round(mfe, 2)

        # brazos CDC: entrada al cierre de la vela de ruptura, mismo stop/target
        for tag, idx in (("cdc", i_cdc0), ("cdcx", i_cdc)):
            if idx is None:
                continue
            c = candles[idx]
            res = walk_resolve(candles, idx, long, c["c"], stop, tp, False)
            if res is None:
                continue
            rsk = (c["c"] - stop) if long else (stop - c["c"])
            if rsk <= 0:
                continue
            row[tag] = round(oos.netR(res[0], c["c"], stop), 3)
            row[tag + "_rr"] = round(abs(tp - c["c"]) / rsk, 2)
            row[tag + "_lag"] = idx - i_tap
            row[tag + "_mae"] = round(res[2], 2)
            row[tag + "_mfe"] = round(res[3], 2)

        # --- retest y controles (a) desplazado ---
        if i_cdc is not None and a_cdc:
            tol = TOL_ATR * a_cdc
            sh = SHIFT_ATR * a_cdc
            px_brk = candles[i_cdc]["c"]
            niveles = {"rt": ref,
                       "up": ref + sh if long else ref - sh,
                       "dn": ref - sh if long else ref + sh}
            for tag, lvl in niveles.items():
                trig = lvl + tol if long else lvl - tol   # limit "no seas codo"
                if (trig <= stop) if long else (trig >= stop):
                    continue                # riesgo <= 0: el brazo no existe
                # El gatillo tiene que ser una orden LIMITE válida: por debajo
                # del precio de la ruptura en un long (encima en un short). Si
                # no, no hay vuelta que esperar y el "retest" sería un market
                # disfrazado — que es justo el sesgo que arruinaría el estudio.
                if (trig >= px_brk) if long else (trig <= px_brk):
                    row[f"{tag}_invalido"] = True
                    continue
                for N in RETEST_N:
                    j_fill, mot = find_trigger(candles, i_cdc + 1, i_cdc + N,
                                               long, trig, stop, tp, True)
                    row[f"{tag}{N}_motivo"] = mot
                    if j_fill is not None:
                        arm(j_fill, trig, f"{tag}{N}", i_tap)

        # --- control (b): MISMO nivel y MISMO precio de fill, sin ruptura ---
        # Orden STOP en el nivel, refrescada cada vela con el último swing
        # confirmado ESTRICTAMENTE antes de esa vela (lh2[j-1] / ll2[j-1]): usar
        # lh2[j] sería look-ahead si el swing se confirma en la misma vela j.
        # Llena al llegar al nivel, sin esperar el cierre que lo rompe ni la
        # vuelta. Aísla "estructura ruptura+retest" de "entrar en ese precio".
        j_fill = None
        mot_lvl = "sin_nivel"
        for j in range(i_tap + 1, min(i_tap + 1 + CDC_WINDOW + max(RETEST_N), n)):
            lvl_j = lh2[j - 1] if long else ll2[j - 1]
            a_j = atr[j - 1]
            c = candles[j]
            if lvl_j is not None and a_j:
                trig_j = lvl_j + TOL_ATR * a_j if long else lvl_j - TOL_ATR * a_j
                if (trig_j > stop) if long else (trig_j < stop):
                    if (c["h"] >= trig_j) if long else (c["l"] <= trig_j):
                        # stop order: si abre pasada, se llena PEOR (en el open)
                        px = max(trig_j, c["o"]) if long else min(trig_j, c["o"])
                        j_fill, mot_lvl = j, "ok"
                        break
            if (c["l"] <= stop) if long else (c["h"] >= stop):
                mot_lvl = "sl"
                break
            if (c["h"] >= tp) if long else (c["l"] <= tp):
                mot_lvl = "tp"
                break
        else:
            mot_lvl = "sin_nivel_alcanzado"
        row["lvl_motivo"] = mot_lvl
        if j_fill is not None:
            arm(j_fill, px, "lvl", i_tap)
        rows.append(row)
    return rows


def add_delay_arm(rows, candles, L_by_N):
    """Control (c): entrada al cierre de la vela i_tap+L, sin condición de precio.

    L se fija con el retraso MEDIO observado del retest (por eso corre en una
    segunda pasada, dataset por dataset para no tener 10 series en memoria).
    Mismas reglas de desaparición: si el SL o el TP originales se tocan antes de
    la vela L, el brazo no opera — igual que el retest.
    """
    for r in rows:
        i_tap, long = r["_i_tap"], r["dir"] == "long"
        entry, stop, tp = r["_entry"], r["_stop"], r["_tp"]
        for N, L in L_by_N.items():
            if L <= 0:
                continue
            j_end = i_tap + L
            dead = False
            for j in range(i_tap + 1, min(j_end, len(candles))):
                c = candles[j]
                if ((c["l"] <= stop) if long else (c["h"] >= stop)) or \
                        ((c["h"] >= tp) if long else (c["l"] <= tp)):
                    dead = True
                    break
            if dead or j_end >= len(candles):
                r[f"del{N}_motivo"] = "muerto"
                continue
            px = candles[j_end]["c"]
            rsk = (px - stop) if long else (stop - px)
            if rsk <= 0:
                r[f"del{N}_motivo"] = "riesgo<=0"
                continue
            res = walk_resolve(candles, j_end, long, px, stop, tp, False)
            if res is None:
                r[f"del{N}_motivo"] = "sin_resolver"
                continue
            r[f"del{N}_motivo"] = "ok"
            r[f"del{N}"] = round(oos.netR(res[0], px, stop), 3)
            r[f"del{N}_rr"] = round(abs(tp - px) / rsk, 2)
            r[f"del{N}_lag"] = L
            r[f"del{N}_mae"] = round(res[2], 2)
            r[f"del{N}_mfe"] = round(res[3], 2)


# ------------------------------ estadística ------------------------------

def agg(vals):
    if not vals:
        return {"n": 0}
    n = len(vals)
    w = sum(1 for v in vals if v > 0)
    losers = [v for v in vals if v <= 0]
    eq = peak = mdd = 0.0
    for v in vals:
        eq += v
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {"n": n, "wr": round(100 * w / n, 1), "avg": round(sum(vals) / n, 3),
            "tot": round(sum(vals), 1),
            "avg_loser": round(sum(losers) / len(losers), 3) if losers else 0.0,
            "dd_R": round(mdd, 1)}


def block_boot(pairs_d, iters=BOOT_ITERS, seed=BOOT_SEED):
    """Bootstrap POR BLOQUES sobre las diferencias pareadas.

    `pairs_d` es {episodio: [d1, d2, ...]}. Se remuestrean EPISODIOS completos
    (par × tf × mes), no trades sueltos: trades vecinos comparten régimen y
    episodio, y remuestrear trades sueltos finge independencia e infla la
    significancia (defecto #3 del proyecto).
    Devuelve (media, lo95, hi95, p_dos_colas).
    """
    keys = list(pairs_d)
    if not keys:
        return None
    allv = [v for k in keys for v in pairs_d[k]]
    if not allv:
        return None
    m = sum(allv) / len(allv)
    rnd = random.Random(seed)
    means = []
    K = len(keys)
    for _ in range(iters):
        s = c = 0
        for _ in range(K):
            blk = pairs_d[keys[rnd.randrange(K)]]
            s += sum(blk)
            c += len(blk)
        if c:
            means.append(s / c)
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[int(0.975 * len(means)) - 1]
    ge = sum(1 for x in means if x >= 0) / len(means)
    le = sum(1 for x in means if x <= 0) / len(means)
    return (round(m, 4), round(lo, 4), round(hi, 4),
            round(min(1.0, 2 * min(ge, le)), 4))


def holm(pvals):
    """Holm-Bonferroni. Se aplica sobre TODA la familia pre-registrada.

    Motivo: en este proyecto ya pasó que 5 de 81 variantes se veían
    significativas sin corregir y ninguna sobrevivió a la corrección.
    """
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, prev = {}, 0.0
    for i, (k, p) in enumerate(items):
        adj = min(1.0, max(prev, (m - i) * p))
        out[k] = round(adj, 4)
        prev = adj
    return out


def episode(r):
    d = dt.datetime.utcfromtimestamp(r["t"] / 1000)
    return f"{r['pair']}_{r['tf']}_{d.year}-{d.month:02d}"


def paired(rows, a, b):
    """Diferencias pareadas a-b SOLO sobre setups donde AMBOS brazos operaron."""
    d = defaultdict(list)
    n = 0
    for r in rows:
        if r.get(a) is None or r.get(b) is None:
            continue
        d[episode(r)].append(r[a] - r[b])
        n += 1
    return d, n


# ------------------------------ main ------------------------------

def main(datasets=None):
    datasets = datasets or oos.DATASETS
    rows, usados = [], []
    for pair, tf in datasets:
        path = os.path.join(oos.DATA_DIR, f"klines_{pair}_{tf}.json")
        if not os.path.isfile(path):
            continue
        rs = study_dataset(pair, tf)
        rows.extend(rs)
        usados.append((pair, tf))
        print(f"  {pair} {tf}: {len(rs)} trades pareados")
    return finish(rows, usados)


def finish(rows, datasets):
    rows.sort(key=lambda r: r["t"])
    ts = [r["t"] for r in rows]
    split = ts[int(len(ts) * IS_FRAC)]
    alt_ms = int(dt.datetime.strptime(SPLIT_ALT, "%Y-%m-%d").timestamp() * 1000)
    for r in rows:
        r["oos"] = r["t"] > split
        r["oos_alt"] = r["t"] > alt_ms
        r["year"] = dt.datetime.utcfromtimestamp(r["t"] / 1000).year

    # retraso medio del retest -> L del control (c)
    L_by_N = {}
    for N in RETEST_N:
        lags = [r[f"rt{N}_lag"] for r in rows if r.get(f"rt{N}_lag") is not None]
        L_by_N[N] = int(round(sum(lags) / len(lags))) if lags else 0
    for pair, tf in datasets:
        sub = [r for r in rows if r["pair"] == pair and r["tf"] == tf]
        if not sub:
            continue
        cand = json.load(open(os.path.join(oos.DATA_DIR,
                                           f"klines_{pair}_{tf}.json")))
        add_delay_arm(sub, cand, L_by_N)
        del cand

    arms = ["base", "cdc", "cdcx"] + list(ABORT_ARMS) + \
           [f"rt{N}" for N in RETEST_N] + \
           [f"up{N}" for N in RETEST_N] + [f"dn{N}" for N in RETEST_N] + \
           [f"del{N}" for N in RETEST_N] + ["lvl"]
    NU = len(rows)

    def cell(rs, a):
        vals = [r[a] for r in rs if r.get(a) is not None]
        g = agg(vals)
        g["cobertura_pct"] = round(100 * len(vals) / max(len(rs), 1), 1)
        g["avg_por_setup"] = round(sum(vals) / max(len(rs), 1), 4)
        for m in ("rr", "lag", "mae", "mfe"):
            xs = [r[f"{a}_{m}"] for r in rs if r.get(f"{a}_{m}") is not None]
            if xs:
                g[m] = round(sum(xs) / len(xs), 2)
        return g

    res = {"meta": {
        "research_only": True,
        "execution_enabled": False,
        "validated": False,
        "aviso": "Research only - No senal - No bot - NO usar para activar live",
        "fecha": "2026-07-26",
        "hipotesis": ("el retest tras ruptura da mejor RR realizado que el toque "
                      "y que el CDC, porque confirma sin pagar la entrada tardia"),
        "universo": "trades touch del estudio del abort (pareado 1:1)",
        "n_universo": NU,
        "datasets": [f"{p}_{t}" for p, t in datasets],
        "prereg": {
            "ruptura": "cierre de vela mas alla del ultimo swing confirmado piv=2",
            "retest": "vuelta al nivel dentro de N velas tras la ruptura",
            "N": list(RETEST_N),
            "cdc_window": CDC_WINDOW,
            "buffer_nivel": f"{TOL_ATR} x ATR({ATR_LEN}) causal (RELATIVO, no % fijo)",
            "shift_control_a": f"+-{SHIFT_ATR} x ATR({ATR_LEN})",
            "stop_target": "identicos al plan del toque en TODOS los brazos",
            "vanish": "si SL o TP originales se tocan mientras el brazo espera, no opera",
            "metrica_primaria": "netR promedio por trade tomado, pareado 1:1",
            "metrica_guardarrail": "netR por setup del universo (expone el sesgo de no operar)",
            "split_oos": dt.datetime.utcfromtimestamp(split / 1000).isoformat(),
            "split_oos_motivo": ("mismo IS_FRAC=0.70 del estudio del abort: si se "
                                 "cambia el corte, los brazos previos dejan de ser "
                                 "comparables"),
            "split_alt": SPLIT_ALT,
            "n_min_retests": 500,
            "cobertura_minima": "10% del universo, si no COBERTURA INSUFICIENTE",
            "bootstrap": f"por bloques par x tf x mes, {BOOT_ITERS} iters, seed {BOOT_SEED}",
            "correccion_multiple": "Holm sobre toda la familia pre-registrada",
            "decision": {
                "promover": "supera al mejor brazo actual en OOS Y en >=5 de 7 pares",
                "seguir": "mejora perfil de riesgo (colas, DD) aunque no la expectativa",
                "descartar": "no supera al control (c) de retraso fijo",
            },
        },
        "L_control_retraso": L_by_N,
    }}

    # --- cobertura y desaparecidos ---
    mot_cdc, mot_cdc0 = defaultdict(int), defaultdict(int)
    for r in rows:
        mot_cdc[r.get("cdc_motivo", "?")] += 1
        mot_cdc0[r.get("cdc0_motivo", "?")] += 1
    res["cobertura"] = {
        "setups": NU,
        "cdc_publicado": dict(mot_cdc0),
        "cdc_publicado_pct": round(100 * mot_cdc0["ok"] / max(NU, 1), 1),
        "ruptura_con_despeje": dict(mot_cdc),
        "cdc_pct": round(100 * mot_cdc["ok"] / max(NU, 1), 1),
        "invalidos_limite": {t: sum(1 for r in rows if r.get(f"{t}_invalido"))
                             for t in ("rt", "up", "dn")},
        "por_N": {},
    }
    for N in RETEST_N:
        m = defaultdict(int)
        for r in rows:
            if r.get("cdc_motivo") == "ok":
                m[r.get(f"rt{N}_motivo", "sin_nivel")] += 1
        fired = sum(1 for r in rows if r.get(f"rt{N}") is not None)
        res["cobertura"]["por_N"][N] = {
            "rupturas": mot_cdc["ok"],
            "motivos_tras_ruptura": dict(m),
            "retests_operados": fired,
            "cobertura_universo_pct": round(100 * fired / max(NU, 1), 2),
            "retest_dado_ruptura_pct": round(100 * fired / max(mot_cdc["ok"], 1), 1),
            "rompen_y_no_vuelven_pct": round(
                100 * m["sin_retest"] / max(mot_cdc["ok"], 1), 1),
            "mueren_esperando_pct": round(
                100 * (m["sl"] + m["tp"]) / max(mot_cdc["ok"], 1), 1),
            "fills_con_rr_menor_1": sum(
                1 for r in rows if (r.get(f"rt{N}_rr") or 9) < 1),
        }
    mot_lvl = defaultdict(int)
    for r in rows:
        mot_lvl[r.get("lvl_motivo", "?")] += 1
    res["cobertura"]["control_b_lvl"] = dict(mot_lvl)

    # --- cortes ---
    C = res["cortes"] = {}
    cortes = {"ALL": rows,
              "IS": [r for r in rows if not r["oos"]],
              "OOS": [r for r in rows if r["oos"]],
              "OOS_alt": [r for r in rows if r["oos_alt"]],
              "rr_5p": [r for r in rows if r["rr"] >= 5],
              "rr_5p_OOS": [r for r in rows if r["rr"] >= 5 and r["oos"]]}
    for tf in ("1h", "15m"):
        cortes[f"tf_{tf}"] = [r for r in rows if r["tf"] == tf]
    for y in sorted({r["year"] for r in rows}):
        cortes[f"ano_{y}"] = [r for r in rows if r["year"] == y]
    for p in PAIRS7:
        cortes[f"par_{p}"] = [r for r in rows if r["pair"] == p]
        cortes[f"par_{p}_OOS"] = [r for r in rows if r["pair"] == p and r["oos"]]
    for name, rs in cortes.items():
        C[name] = {a: cell(rs, a) for a in arms}

    # --- perfil de riesgo SOBRE EL MISMO SUBCONJUNTO ---
    # Comparar DD entre brazos con coberturas distintas es tramposo: el que opera
    # menos tiene menos DD por construcción. Acá se fija el subconjunto (los
    # setups donde el retest_N operó) y se mira a todos los brazos ahí mismo, y
    # además con 0 en los setups donde el brazo no opera (curva de capital real).
    res["perfil_riesgo"] = {}
    for N in RETEST_N:
        sub = [r for r in rows if r.get(f"rt{N}") is not None]
        blk = {}
        for a in arms:
            vals = [r[a] for r in sub if r.get(a) is not None]
            g = cell(sub, a)
            eq = peak = mdd = 0.0
            for r in sub:                       # curva con 0 cuando no opera
                eq += r.get(a) or 0.0
                peak = max(peak, eq)
                mdd = max(mdd, peak - eq)
            g["dd_R_con_ceros"] = round(mdd, 1)
            g["opera_en_subconj"] = len(vals)
            blk[a] = g
        res["perfil_riesgo"][f"subconj_rt{N}"] = {"n_setups": len(sub), "brazos": blk}

    # --- comparaciones pareadas 1:1 + bootstrap por bloques ---
    comps = ["base", "cdc", "cdcx", "cap03_8", "mkt_4", "lvl"]
    fam, det = {}, {}
    for cut in ("ALL", "OOS"):
        rs = cortes[cut]
        for N in RETEST_N:
            a = f"rt{N}"
            for b in comps + [f"del{N}", f"up{N}", f"dn{N}"]:
                d, n = paired(rs, a, b)
                bb = block_boot(d)
                if bb is None or n == 0:
                    continue
                key = f"{cut}:{a}_vs_{b}"
                det[key] = {"n_pareado": n, "dif_media": bb[0],
                            "ci95": [bb[1], bb[2]], "p": bb[3]}
                fam[key] = bb[3]
    res["pareados"] = det
    res["holm"] = holm(fam)
    res["significativos_holm"] = {k: v for k, v in res["holm"].items() if v < 0.05}

    # --- criterio "≥5 de 7 pares" en OOS, contra cada brazo de referencia ---
    res["pares_ganados_OOS"] = {}
    for N in RETEST_N:
        for b in ("base", "cdc", "cap03_8", "mkt_4", f"del{N}"):
            win = []
            for p in PAIRS7:
                rs = [r for r in rows if r["pair"] == p and r["oos"]]
                d, n = paired(rs, f"rt{N}", b)
                if n == 0:
                    continue
                m = sum(v for k in d for v in d[k]) / n
                win.append((p, round(m, 3), n))
            res["pares_ganados_OOS"][f"rt{N}_vs_{b}"] = {
                "pares_con_datos": len(win),
                "pares_ganados": sum(1 for _, m, _ in win if m > 0),
                "detalle": {p: [m, n] for p, m, n in win}}

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)

    print(f"\nuniverso: {NU} setups | rupturas: {res['cobertura']['cdc_pct']}%")
    for N in RETEST_N:
        cv = res["cobertura"]["por_N"][N]
        print(f"  N={N:2}: retests={cv['retests_operados']:5} "
              f"({cv['cobertura_universo_pct']}% universo, "
              f"{cv['retest_dado_ruptura_pct']}% de las rupturas)")
    print(f"\n{'brazo':8} {'ALL n':>6} {'cob%':>6} {'avg':>8} {'/setup':>8} "
          f"{'RRreal':>7} {'OOS avg':>8} {'OOSdd':>7}")
    for a in arms:
        x, o = C["ALL"][a], C["OOS"][a]
        if not x.get("n"):
            continue
        print(f"{a:8} {x['n']:6} {x['cobertura_pct']:6.1f} {x['avg']:+8.3f} "
              f"{x['avg_por_setup']:+8.4f} {x.get('rr', 0):7.1f} "
              f"{o.get('avg', 0):+8.3f} {o.get('dd_R', 0):7.1f}")
    print(f"\nresultados: {OUT_JSON}")
    return res


if __name__ == "__main__":
    main()
