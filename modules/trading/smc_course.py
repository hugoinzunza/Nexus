"""Estrategia del curso Bitcoin Traders (playbook course-study.v1) como capa
PARALELA del gráfico — solo lectura/contexto.

Implementa la lectura que enseña el profe (congelada en
nexux/research/bitcoin_traders_course_2026-08-17/BITCOIN_TRADERS_SMC_PLAYBOOK.md
y validada en CLAUDE_INDEPENDENT_REVIEW.md):

  dirección por ruptura CON CUERPO → rango operativo causal (toma de liquidez →
  strong extreme → weak target → 50%) → zonas admitidas (OB/FVG) con frescura →
  mapa de liquidez delante/detrás (bloque trampa) → retroceso ≥50% del fractal.

REGLAS DE AISLAMIENTO (ECON-COHORT-001 congelada hasta su cierre):
  - Este módulo NO produce `tpsl` ni ningún plan: no puede alimentar el diario
    ni el bot. El camino smc_live → tpsl → setups_store queda intacto.
  - Solo lo consume el endpoint del gráfico con `strategy=course` (toggle UI).

Parámetros de dibujo: son DEFAULTS VISUALES tomados del semáforo amarillo del
playbook (el curso no fija umbrales); no están validados estadísticamente y no
deben migrar al bot sin pasar por el laboratorio.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from . import smc

# Swings ESTRUCTURALES de la TF vista: constante en barras → cada temporalidad
# lee su propia escala (la corrección al bug de calibración única detectado en
# la auditoría vs LuxAlgo 2026-08-17: una sola ventana en barras NO es una sola
# escala temporal).
STRUCT_PIV = 8
# Estructura INTERNA (iBOS / finalización del rango).
INT_PIV = 3
# Barras analizadas de la TF vista.
WINDOW = 500
# Tolerancia relativa para agrupar equal highs/lows (liquidez).
EQ_TOL_PCT = 0.0012
# Liquidez DETRÁS de la zona: se considera trampa si el pool está a menos de
# este % del alto del rango más allá de la invalidación de la zona.
TRAP_MAX_FRAC = 0.35
# FVGs recientes a evaluar.
FVG_LOOKBACK = 140
MAX_ZONES = 10
MAX_POOLS = 8

# ESTRUCTURA RECTORA (jerarquía del curso: D, H4 y M15 — tabla zona→confirmación).
# El rango que el profe dibuja en M15 es el de la estructura PRINCIPAL (H4/D),
# no el de 500 velas de la TF vista: en su gráfico real de M15 el Strong High y
# el Weak Low abarcan semanas. La TF vista aporta la estructura interna
# (BOS/iBOS, zonas de entrada); el rango rector viene de esta tabla.
RECTOR_TF = {"1m": "1h", "5m": "4h", "15m": "4h", "30m": "4h", "1h": "4h",
             "2h": "1D", "4h": "1D", "6h": "1D", "12h": "1D",
             "1D": "1D", "7D": "1D"}


def _q(x):
    if not x:
        return x
    ax = abs(x)
    if ax >= 100:
        return round(x, 2)
    if ax >= 1:
        return round(x, 4)
    if ax >= 0.01:
        return round(x, 6)
    return round(x, 8)


def _bos_events(candles: List[dict], piv: int) -> List[Dict]:
    """Rupturas de estructura CON CUERPO (regla del curso: la mecha no vale).

    Referencia = el swing confirmado más RECIENTE de cada lado aún no roto;
    cuando un CIERRE lo cruza se emite el evento y se espera el siguiente swing
    confirmado DESPUÉS de la ruptura (así una misma ruptura no se re-emite).
    Anti-look-ahead: swings por confirm_idx. Devuelve [{j, dir, swing}]."""
    n = len(candles)
    closes = [c["c"] for c in candles]
    sh, sl = smc.swing_points(candles, piv)
    hi_evt = sorted(sh, key=lambda p: p["confirm_idx"])
    lo_evt = sorted(sl, key=lambda p: p["confirm_idx"])
    hi_i = lo_i = 0
    cur_hi: Optional[dict] = None
    cur_lo: Optional[dict] = None
    floor_hi = floor_lo = -1          # tras romper, solo swings posteriores
    out = []
    for j in range(n):
        while hi_i < len(hi_evt) and hi_evt[hi_i]["confirm_idx"] <= j:
            p = hi_evt[hi_i]; hi_i += 1
            if p["idx"] > floor_hi and (cur_hi is None or p["idx"] > cur_hi["idx"]):
                cur_hi = p
        while lo_i < len(lo_evt) and lo_evt[lo_i]["confirm_idx"] <= j:
            p = lo_evt[lo_i]; lo_i += 1
            if p["idx"] > floor_lo and (cur_lo is None or p["idx"] > cur_lo["idx"]):
                cur_lo = p
        if cur_hi is not None and closes[j] > cur_hi["price"]:
            out.append({"j": j, "dir": "up", "swing": cur_hi})
            floor_hi = j
            cur_hi = None
        if cur_lo is not None and closes[j] < cur_lo["price"]:
            out.append({"j": j, "dir": "down", "swing": cur_lo})
            floor_lo = j
            cur_lo = None
    return out


def _rango(candles: List[dict], bos: List[Dict]) -> Optional[Dict]:
    """Rango operativo causal del curso (S03): la última ruptura estructural con
    cuerpo define la dirección; el STRONG extreme es el origen de la pierna que
    la produjo (idealmente una toma de liquidez); el WEAK extreme es el extremo
    alcanzado después, aún sin barrer — el target."""
    if not bos:
        return None
    n = len(candles)
    e = bos[-1]
    j = e["j"]
    up = e["dir"] == "up"
    # Origen de la pierna: desde la ruptura opuesta previa (o media ventana).
    prev_opp = [b for b in bos if b["dir"] != e["dir"] and b["j"] < j]
    start = prev_opp[-1]["j"] if prev_opp else max(0, j - WINDOW // 2)
    seg = range(start, j + 1)
    if up:
        k0 = min(seg, key=lambda k: candles[k]["l"])
        strong, strong_t = candles[k0]["l"], candles[k0]["t"]
        kw = max(range(j, n), key=lambda k: candles[k]["h"])
        weak, weak_t = candles[kw]["h"], candles[kw]["t"]
    else:
        k0 = max(seg, key=lambda k: candles[k]["h"])
        strong, strong_t = candles[k0]["h"], candles[k0]["t"]
        kw = min(range(j, n), key=lambda k: candles[k]["l"])
        weak, weak_t = candles[kw]["l"], candles[kw]["t"]
    # ¿El strong tomó liquidez? (mecha del origen más allá de un swing previo)
    sh_prev, sl_prev = smc.swing_points(candles[:k0 + 1], INT_PIV)
    if up:
        sweep = any(candles[k0]["l"] < p["price"] for p in sl_prev[-6:]) if sl_prev else False
    else:
        sweep = any(candles[k0]["h"] > p["price"] for p in sh_prev[-6:]) if sh_prev else False
    # El WEAK del curso es LIQUIDEZ PENDIENTE, no el extremo reciente: si más
    # allá del extremo post-BOS queda un swing SIN BARRER más profundo dentro de
    # la ventana, el target es ESE (el Weak Low de Ago/1 del profe sigue vigente
    # aunque el mínimo del 15/Ago no llegara a barrerlo).
    # Se toma la MÁS CERCANA al extremo (el Weak Low del profe es el bajo
    # pendiente inmediato, no el fondo histórico de la ventana).
    sh_all, sl_all = smc.swing_points(candles, STRUCT_PIV)
    if up:
        cands = [p for p in sh_all if p["price"] > weak and p["confirm_idx"] < n
                 and not any(candles[k]["h"] > p["price"] for k in range(p["idx"] + 1, n))]
        if cands:
            best = min(cands, key=lambda p: p["price"])
            weak, weak_t = best["price"], candles[best["idx"]]["t"]
    else:
        cands = [p for p in sl_all if p["price"] < weak and p["confirm_idx"] < n
                 and not any(candles[k]["l"] < p["price"] for k in range(p["idx"] + 1, n))]
        if cands:
            best = max(cands, key=lambda p: p["price"])
            weak, weak_t = best["price"], candles[best["idx"]]["t"]
    # Finalización: después del extremo weak, ¿hubo giro interno (iBOS opuesto)?
    fin = "en_desarrollo"
    tail = candles[kw:]
    if len(tail) > 2 * INT_PIV + 2:
        ib = _bos_events(tail, INT_PIV)
        if any(b["dir"] != e["dir"] for b in ib):
            fin = "finalizado"
    if strong == weak:
        return None
    lo, hi = (strong, weak) if up else (weak, strong)
    return {
        "dir": "alcista" if up else "bajista",
        "strong": _q(strong), "strong_t": strong_t, "sweep": bool(sweep),
        "weak": _q(weak), "weak_t": weak_t,
        "eq": _q((strong + weak) / 2), "lo": _q(lo), "hi": _q(hi),
        "state": fin, "bos_t": candles[j]["t"], "bos_price": _q(e["swing"]["price"]),
    }


def _fractal(candles: List[dict]) -> Optional[Dict]:
    """Última pierna estructural + estado del retroceso ≥50% (regla del curso,
    verificada: el TOQUE del 50% vale con cuerpo o mecha; el ANCLAJE va en los
    extremos del swing — mechas)."""
    sh, sl = smc.swing_points(candles, STRUCT_PIV)
    n = len(candles)
    hs = [p for p in sh if p["confirm_idx"] < n]
    ls = [p for p in sl if p["confirm_idx"] < n]
    if not hs or not ls:
        return None
    h, l = hs[-1], ls[-1]
    up = l["idx"] < h["idx"]           # pierna al alza: low → high
    a, b = (l, h) if up else (h, l)
    if a["idx"] >= b["idx"]:
        return None
    fib50 = (a["price"] + b["price"]) / 2
    # Retroceso tras completarse la pierna (desde el extremo b en adelante).
    after = candles[b["idx"] + 1:]
    if up:
        reached = min((c["l"] for c in after), default=None)
        ok = reached is not None and reached <= fib50
        pct = None
        if reached is not None and b["price"] != a["price"]:
            pct = (b["price"] - reached) / (b["price"] - a["price"]) * 100
    else:
        reached = max((c["h"] for c in after), default=None)
        ok = reached is not None and reached >= fib50
        pct = None
        if reached is not None and a["price"] != b["price"]:
            pct = (reached - b["price"]) / (a["price"] - b["price"]) * 100
    return {"dir": "alcista" if up else "bajista",
            "from": _q(a["price"]), "from_t": candles[a["idx"]]["t"],
            "to": _q(b["price"]), "to_t": candles[b["idx"]]["t"],
            "fib50": _q(fib50), "retrace_ok": bool(ok),
            "retrace_pct": round(pct, 0) if pct is not None else None}


def _pools(candles: List[dict], last_price: float) -> List[Dict]:
    """Mapa de liquidez: swings internos SIN BARRER y clusters de equal
    highs/lows (dos o más swings al mismo nivel dentro de la tolerancia)."""
    n = len(candles)
    sh, sl = smc.swing_points(candles, INT_PIV)
    out = []
    for pts, is_high in ((sh, True), (sl, False)):
        # Sin barrer: ninguna vela posterior cruzó el nivel.
        fresh = []
        for p in pts:
            if p["confirm_idx"] >= n:
                continue
            i = p["idx"]
            swept = any((candles[k]["h"] > p["price"]) if is_high
                        else (candles[k]["l"] < p["price"])
                        for k in range(i + 1, n))
            if not swept:
                fresh.append(p)
        used = set()
        for i, p in enumerate(fresh):
            if i in used:
                continue
            grp = [p]
            for k in range(i + 1, len(fresh)):
                if k in used:
                    continue
                if abs(fresh[k]["price"] - p["price"]) <= p["price"] * EQ_TOL_PCT:
                    grp.append(fresh[k]); used.add(k)
            price = sum(g["price"] for g in grp) / len(grp)
            kind = ("EQH" if is_high else "EQL") if len(grp) > 1 else \
                   ("high" if is_high else "low")
            out.append({"type": "high" if is_high else "low", "kind": kind,
                        "price": _q(price), "t": candles[grp[0]["idx"]]["t"],
                        "count": len(grp)})
    # Los más cercanos al precio primero (los pools lejanos son ruido visual).
    out.sort(key=lambda p: abs(p["price"] - last_price))
    return out[:MAX_POOLS]


def _zones(candles: List[dict], rng: Optional[Dict], pools: List[Dict],
           last_price: float) -> List[Dict]:
    """Zonas admitidas del curso: OB (última vela opuesta antes del impulso que
    deja FVG) y FVG. Cada zona lleva frescura, tipo (extremo/decisional/interna),
    liquidez delante (inducement) y liquidez DETRÁS (bloque trampa)."""
    n = len(candles)
    start = max(2, n - FVG_LOOKBACK)
    range_h = (rng["hi"] - rng["lo"]) if rng else None
    out = []
    for bullish in (True, False):
        for f in smc.find_fvgs(candles, start, n - 1, bullish):
            i = f["idx"]
            # FVG (imbalance) como zona propia si sigue abierto.
            filled = any(candles[k]["l"] <= f["hi"] and candles[k]["h"] >= f["lo"]
                         for k in range(i + 1, n))
            if not filled:
                out.append({"kind": "fvg", "dir": "long" if bullish else "short",
                            "lo": f["lo"], "hi": f["hi"], "t": candles[i - 2]["t"],
                            "born": i, "fresh": True})
            # OB tradicional: última vela opuesta antes del FVG (vela i-2 hacia atrás).
            ob = smc.find_order_block(candles, max(0, i - 6), i - 2, bullish)
            if ob:
                k0 = ob["idx"]
                touched = any(candles[k]["l"] <= ob["hi"] and candles[k]["h"] >= ob["lo"]
                              for k in range(i + 1, n))
                out.append({"kind": "ob", "dir": "long" if bullish else "short",
                            "lo": ob["lo"], "hi": ob["hi"], "t": candles[k0]["t"],
                            "born": i, "fresh": not touched})
    # Dedup por caja (los FVG en cadena repiten OB) conservando la más reciente.
    seen, dedup = set(), []
    for z in sorted(out, key=lambda z: -z["born"]):
        key = (z["kind"], z["dir"], _q(z["lo"]), _q(z["hi"]))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(z)
    zones = dedup[:MAX_ZONES]
    for z in zones:
        z["lo"], z["hi"] = _q(z["lo"]), _q(z["hi"])
        z.pop("born", None)
        # Lado respecto al EQ RECTOR, como rotula el profe (Premium/Discount POI).
        z["lado"] = None
        if rng:
            z["lado"] = "premium" if (z["lo"] + z["hi"]) / 2 > rng["eq"] else "discount"
        # Tipo según el rango: EXTREMO si la caja toca el strong extreme;
        # DECISIONAL si vive del lado del strong (origen del movimiento);
        # interna en el resto. Etiqueta descriptiva, no un juicio de calidad.
        z["tipo"] = "interna"
        if rng and range_h:
            near_strong = abs(((z["lo"] + z["hi"]) / 2) - rng["strong"]) <= 0.2 * range_h
            contains = z["lo"] <= rng["strong"] <= z["hi"]
            if contains or near_strong:
                z["tipo"] = "extremo"
            elif (rng["dir"] == "alcista") == (z["dir"] == "long"):
                z["tipo"] = "decisional"
        # Liquidez DELANTE (inducement): un pool entre el precio y la zona.
        # Liquidez DETRÁS: un pool más allá de la invalidación, cerca (trampa).
        z["liq_delante"] = False
        z["trampa"] = False
        far = z["lo"] if z["dir"] == "long" else z["hi"]
        near = z["hi"] if z["dir"] == "long" else z["lo"]
        for p in pools:
            price = p["price"]
            if z["dir"] == "long":
                if near < price < last_price:
                    z["liq_delante"] = True
                behind = far - price
                if 0 < behind and range_h and behind <= TRAP_MAX_FRAC * range_h \
                        and p["type"] == "low":
                    z["trampa"] = True
            else:
                if last_price < price < near:
                    z["liq_delante"] = True
                behind = price - far
                if 0 < behind and range_h and behind <= TRAP_MAX_FRAC * range_h \
                        and p["type"] == "high":
                    z["trampa"] = True
    return zones


def _structure_events(candles: List[dict], bos: List[Dict]) -> List[Dict]:
    """Marcas de estructura para DIBUJAR como las traza el profe: un segmento
    horizontal en el swing roto, desde su origen hasta la vela cuyo CIERRE lo
    rompió, con etiqueta BOS (estructura de la TF vista) o iBOS (interna).

    Un evento interno que coincide con uno estructural (misma vela de quiebre y
    mismo nivel) se omite: es la misma ruptura vista dos veces."""
    ib = _bos_events(candles, INT_PIV)
    out = []
    seen = set()
    for e in bos[-4:]:
        sw = e["swing"]
        key = (round(sw["price"], 6), e["j"])
        seen.add(key)
        out.append({"label": "BOS", "dir": e["dir"], "price": _q(sw["price"]),
                    "t_from": candles[sw["idx"]]["t"], "t_to": candles[e["j"]]["t"]})
    for e in ib[-6:]:
        sw = e["swing"]
        key = (round(sw["price"], 6), e["j"])
        if key in seen:
            continue
        out.append({"label": "iBOS", "dir": e["dir"], "price": _q(sw["price"]),
                    "t_from": candles[sw["idx"]]["t"], "t_to": candles[e["j"]]["t"]})
    out.sort(key=lambda x: x["t_to"])
    return out[-8:]


def _entradas(candles: List[dict], zones: List[Dict], keep: int = 6) -> List[Dict]:
    """Marcas de ENTRADA del curso (modelo por confirmación, S06/S08): zona
    tocada y luego iBOS de la TF vista en la dirección de la zona → ✓ entrada;
    si un cierre atraviesa la invalidación antes de confirmar → ✗ invalidada.

    Son marcas DESCRIPTIVAS del método sobre el gráfico (como los ✓/✗ del
    indicador del profe). No llevan entry/SL/TP y no alimentan nada."""
    n = len(candles)
    ib = _bos_events(candles, INT_PIV)
    out = []
    for z in zones:
        start = next((i for i in range(n) if candles[i]["t"] > z["t"]), None)
        if start is None:
            continue
        touch = next((i for i in range(start, n)
                      if candles[i]["l"] <= z["hi"] and candles[i]["h"] >= z["lo"]), None)
        if touch is None:
            continue
        long = z["dir"] == "long"
        far = z["lo"] if long else z["hi"]
        conf = next((e for e in ib
                     if e["j"] > touch and e["dir"] == ("up" if long else "down")), None)
        inval = next((i for i in range(touch, n)
                      if ((candles[i]["c"] < far) if long else (candles[i]["c"] > far))),
                     None)
        zona = (z["kind"].upper() + " " + z.get("tf", "")).strip()
        if inval is not None and (conf is None or inval < conf["j"]):
            out.append({"t": candles[inval]["t"], "price": _q(far), "dir": z["dir"],
                        "estado": "invalidada", "zona": zona})
        elif conf is not None and conf["j"] - touch <= 30:
            out.append({"t": candles[conf["j"]]["t"],
                        "price": _q(candles[conf["j"]]["c"]), "dir": z["dir"],
                        "estado": "confirmada", "zona": zona})
    # Dedup por vela (varias zonas confirman en el mismo iBOS) y las más recientes.
    seen, uniq = set(), []
    for m in sorted(out, key=lambda x: x["t"]):
        if (m["t"], m["estado"]) in seen:
            continue
        seen.add((m["t"], m["estado"]))
        uniq.append(m)
    return uniq[-keep:]


def _checklist(rng, fractal, zones, last_price) -> Dict:
    """Semáforo de lectura del profe (checklist del playbook §Checklist):
    puro estado descriptivo — NO es señal ni recomendación."""
    out = {"direccion": rng["dir"] if rng else None,
           "rector": rng.get("tf") if rng else None,
           "rango_estado": rng["state"] if rng else None,
           "toma_liquidez": rng["sweep"] if rng else None,
           "retroceso_50": fractal["retrace_ok"] if fractal else None,
           "precio_zona": None, "zona_fresca": None, "trampa_cerca": None,
           "target": None, "target_dist_pct": None}
    if rng and last_price:
        eq = rng["eq"]
        if rng["dir"] == "alcista":
            out["precio_zona"] = "descuento" if last_price < eq else "premium"
        else:
            out["precio_zona"] = "premium" if last_price > eq else "descuento"
        out["target"] = rng["weak"]
        out["target_dist_pct"] = round((rng["weak"] - last_price) / last_price * 100, 2)
    if rng:
        side = [z for z in zones if z["fresh"]
                and ((z["dir"] == "long") == (rng["dir"] == "alcista"))]
        out["zona_fresca"] = bool(side)
        out["trampa_cerca"] = any(z["trampa"] for z in side) if side else None
    return out


def analyze(sel_candles: List[dict], htf_map: Optional[Dict[str, list]],
            last_price: float, sel_tf: str) -> Dict:
    """Análisis 'curso.v1'. Sin tpsl, sin señales.

    El RANGO viene de la estructura RECTORA (RECTOR_TF: H4 para intradía, 1D
    para TFs altas), como el mapa real del profe en M15; la TF vista aporta la
    estructura interna (BOS/iBOS), el fractal y las zonas de entrada. Si no hay
    velas de la rectora disponibles, cae a la TF vista."""
    candles = sel_candles[-WINDOW:] if sel_candles else []
    rector_tf = RECTOR_TF.get(sel_tf, sel_tf)
    rector = (htf_map or {}).get(rector_tf) or []
    rector = rector[-WINDOW:]
    if len(rector) < 2 * STRUCT_PIV + 5 or rector_tf == sel_tf:
        rector, rector_tf = candles, sel_tf
    base = {"version": "curso.v1", "timeframe": sel_tf, "last_price": last_price,
            "range": None, "fractal": None, "zones": [], "liquidity": [],
            "structure": [], "entradas": [], "checklist": {},
            "note": ("Estrategia del curso (playbook course-study.v1): contexto "
                     "visual, no señales; no alimenta diario ni bot.")}
    if len(candles) < 2 * STRUCT_PIV + 5:
        return base
    rng = _rango(rector, _bos_events(rector, STRUCT_PIV))
    if rng:
        rng["tf"] = rector_tf
    bos = _bos_events(candles, STRUCT_PIV)
    fractal = _fractal(candles)
    pools = _pools(candles, last_price)
    zones = _zones(candles, rng, pools, last_price)
    for z in zones:
        z["tf"] = sel_tf
    # Zonas del RECTOR (las cajas Premium/Discount POI grandes del mapa del
    # profe nacen en H4/D, no en la TF vista). Frescura y trampa evaluadas en
    # su propia escala.
    if rector_tf != sel_tf:
        pools_r = _pools(rector, last_price)
        for z in _zones(rector, rng, pools_r, last_price):
            if not z["fresh"]:
                continue
            z["tf"] = rector_tf
            zones.append(z)
    base.update({"range": rng, "fractal": fractal, "zones": zones,
                 "liquidity": pools,
                 "structure": _structure_events(candles, bos),
                 "entradas": _entradas(candles, zones),
                 "checklist": _checklist(rng, fractal, zones, last_price)})
    return base
