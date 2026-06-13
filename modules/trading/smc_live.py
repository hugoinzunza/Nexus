"""Análisis SMC en vivo para el indicador del dashboard de trading.

Reusa EXACTAMENTE la misma lógica de detección que el backtest (strategies.detect_pois,
smc.swing_points, smc.find_fvgs) para que el indicador en vivo y el backtest sean
consistentes: mismas definiciones de barrido / displacement / FVG / descuento /
mitigación.

Es apoyo visual/contexto: marca ZONAS DE INTERÉS, no señales de compra/venta.

Devuelve, para un instrumento y la temporalidad seleccionada:
  - estructura (strong high / weak low) y rango con equilibrio 50% (premium/discount),
  - FVGs recientes de la TF seleccionada,
  - POIs válidos (sin mitigar) detectados en 1D/4h/1h, proyectados con su TF de origen,
    distancia al precio y si el precio está dentro ahora.
"""
from __future__ import annotations

import bisect
import time
from typing import Dict, List

from . import smc
from . import strategies

PIV = 2          # pivote fino para detectar FVG / order blocks (POIs)
DISP = 1.0
# Pivote para el DEALING RANGE (Strong High / Weak Low) y los niveles Weak/Strong:
# más grande → swings mayores, alineado con el indicador de Bitcoin Traders Academy
# que Hugo ve en BTCUSDT.P 15m (lookback 10, calibrado contra sus niveles).
RANGE_PIV = 10
# El rango y los niveles se calculan sobre las últimas RANGE_WINDOW velas, aunque
# el gráfico cargue mucha más historia: la calibración del dealing range se hizo
# con ~400 velas y un rango sobre meses daría extremos irrelevantes. La historia
# completa sí alimenta POIs, FVGs y CDC.
RANGE_WINDOW = 400
POI_TFS = ["1D", "4h", "1h"]   # temporalidades de detección de POIs

# --- CDC (Cambio De Carácter / CHoCH) como CONFIRMACIÓN del plan -----------
# Validado en research/cdc_backtest_2026-06-12.md: esperar el CDC tras el toque
# del POI gira el OOS de 1h de −0.096R a +0.066R (P(exp>0)=0.81 — probable, NO
# concluyente; en 15m no rescata). Mismos parámetros del backtest, sin tuneo.
CDC_PIV = 2        # pivotes de corto plazo para el CDC (PIV del research)
CDC_WINDOW = 16    # velas de la TF de planeación que esperamos el CDC tras el toque
# Un CDC PENDIENTE (nivel aún no roto) solo se dibuja si está CERCA del precio: el
# indicador del curso marca el nivel overhead/underfoot que está en juego (la línea
# 64.234 a +0,8% sobrevivió 5 días en la captura de Hugo), NO la liquidez ya barrida
# lejos (un mínimo estructural a −5/−7% es el Weak Low, no un CDC). Acortar la ventana
# de selección no basta: SIEMPRE queda algún extremo sin romper → un pendiente espurio
# que solo se reubica; el filtro correcto es la proximidad al último cierre.
CDC_PEND_MAX_DIST_PCT = 2.5

# Duración de una vela por TF (para descartar la vela en formación y para la
# ventana CDC). Claves tal como las usa el selector del módulo.
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
         "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000,
         "12h": 43_200_000, "1D": 86_400_000, "7D": 604_800_000}


def closed_candles(candles: list, tf: str, now_ms: int | None = None) -> list:
    """Solo velas CERRADAS (anti-repaint): descarta la última si aún se está
    formando. El CDC y el régimen se evalúan únicamente sobre cierres."""
    if not candles:
        return candles
    now_ms = now_ms or int(time.time() * 1000)
    dur = TF_MS.get(tf)
    if dur and candles[-1]["t"] + dur > now_ms:
        return candles[:-1]
    return candles


def _conf_prices(points, n):
    """Precio del swing más reciente CONFIRMADO (confirm_idx<=j) en cada vela j.
    Anti-look-ahead: un pivote se conoce recién `lookback` velas después (igual
    que en el backtest del research)."""
    out = [None] * n
    evt = sorted(points, key=lambda p: p["confirm_idx"])
    pi = 0
    cur = None
    for j in range(n):
        while pi < len(evt) and evt[pi]["confirm_idx"] <= j:
            cur = evt[pi]["price"]
            pi += 1
        out[j] = cur
    return out


def _conf_points(points, n):
    """Como _conf_prices pero devuelve el PIVOTE completo (precio + idx) más
    reciente confirmado en cada vela j (para dibujar desde dónde viene el CDC)."""
    out = [None] * n
    evt = sorted(points, key=lambda p: p["confirm_idx"])
    pi = 0
    cur = None
    for j in range(n):
        while pi < len(evt) and evt[pi]["confirm_idx"] <= j:
            cur = evt[pi]
            pi += 1
        out[j] = cur
    return out


def _cdc_events(closed: list, max_events: int = 3) -> List[Dict]:
    """CDC (cambios de carácter) para DIBUJAR, replicando el indicador de
    referencia (iterado con los ejemplos M15 de Hugo, 2026-06-12):

    - Un swing solo CALIFICA como nivel de CDC cuando después de él confirma un
      pivote OPUESTO (ya produjo reversión). El extremo del movimiento en curso
      (el Strong High/Weak Low recién hechos) NO califica: "los strong no son
      CDC" — romperlos a favor es continuación, no cambio de carácter.
    - Cada lado es independiente (sin alternancia forzada).
    - El nivel vigente es PEGAJOSO: elegido el candidato (el extremo calificado
      de la ventana), la línea vive hasta que un CIERRE la rompe — aunque su
      origen envejezca (la línea 64.234 del ejemplo sobrevivió 5 días y todo un
      rally que nunca cerró sobre ella). Expira solo si supera 2× la ventana.
    - HISTÓRICOS: al romperse, la línea queda congelada en la vela del quiebre.

    Anti-repaint: solo velas cerradas y swings con confirm_idx.
    Devuelve [{dir, price, t_from, t_to, pending}]."""
    n = len(closed)
    if n < 2 * RANGE_PIV + 3:
        return []
    sh, sl = smc.swing_points(closed, RANGE_PIV)
    closes = [c["c"] for c in closed]
    last = closes[-1]
    INF = 10 ** 9
    events = []

    def mk(cur, jto, is_high, pending):
        return {"dir": "up" if is_high else "down",
                "price": round(cur["price"], 6),
                "idx_from": cur["idx"], "idx_to": jto,
                "t_from": closed[cur["idx"]]["t"], "t_to": closed[jto]["t"],
                "pending": pending}

    def availability(own, opp, is_high):
        """Barra en que cada swing propio queda DISPONIBLE como nivel CDC, con la
        calificación ENDURECIDA (regla confirmada por Hugo, 2026-06-13): el
        movimiento que sale del swing debe ROMPER ESTRUCTURA con CUERPO — un
        cierre más allá del swing OPUESTO confirmado previo (la mecha no vale).
        Un extremo cuyo retroceso fue solo un pivote menor NO califica: los
        Strong vigentes dejan de marcar CDC hasta que de verdad se rompan.
        Además se descarta el swing cuyo propio nivel fue cerrado-atravesado
        antes de calificar (nunca llegó a ser un nivel CDC conocido)."""
        opp_sorted = sorted(opp, key=lambda p: p["idx"])
        opp_idx = [p["idx"] for p in opp_sorted]
        out = []
        for p in own:
            k = bisect.bisect_right(opp_idx, p["idx"]) - 1
            if k < 0:
                continue
            ref = opp_sorted[k]          # el swing opuesto previo (estructura)
            qual = next((j for j in range(p["idx"] + 1, n)
                         if ((closes[j] < ref["price"]) if is_high
                             else (closes[j] > ref["price"]))), None)
            if qual is None:
                continue
            a = max(p["confirm_idx"], ref["confirm_idx"], qual)
            crossed = next((j for j in range(p["idx"] + 1, min(a + 1, n))
                            if ((closes[j] > p["price"]) if is_high
                                else (closes[j] < p["price"]))), None)
            if crossed is not None:
                continue
            out.append((a, p))
        out.sort(key=lambda t: t[0])
        return out

    def run(own, opp, is_high):
        avail = availability(own, opp, is_high)

        out = []
        floor = -1      # tras un quiebre, solo cuentan swings posteriores
        cur = None
        pool = []
        pi = 0
        for j in range(n):
            added = False
            while pi < len(avail) and avail[pi][0] <= j:
                pool.append(avail[pi][1])
                pi += 1
                added = True
            if cur is not None and (cur["idx"] <= floor or j - cur["idx"] > 2 * RANGE_WINDOW):
                cur = None
            if cur is None or added:
                cands = [p for p in pool if p["idx"] > floor and p["idx"] >= j - RANGE_WINDOW]
                if cur is not None:
                    # Solo un calificado MÁS extremo puede reemplazar al vigente.
                    cands = [p for p in cands
                             if (p["price"] > cur["price"]) == is_high
                             and p["price"] != cur["price"]] + [cur]
                if cands:
                    cur = max(cands, key=lambda p: p["price"]) if is_high \
                        else min(cands, key=lambda p: p["price"])
            if cur is None:
                continue
            if (closes[j] > cur["price"]) if is_high else (closes[j] < cur["price"]):
                out.append(mk(cur, j, is_high, False))
                floor = j
                cur = None
        if cur is not None:
            out.append(mk(cur, n - 1, is_high, True))
        return out

    def run_internal(own, opp, is_high, max_keep=2):
        """Estructura INTERNA (la 2ª escala del indicador, ejemplos 61.19/61.55
        de Hugo): el nivel es el swing calificado MÁS RECIENTE de cada lado (no
        el extremo); al romperlo con un cierre, CDC interno congelado ahí.
        Usa la MISMA calificación endurecida (ruptura de estructura con cuerpo)."""
        avail = availability(own, opp, is_high)
        out = []
        floor = -1
        cur = None
        pi = 0
        for j in range(n):
            while pi < len(avail) and avail[pi][0] <= j:
                p = avail[pi][1]
                pi += 1
                # El calificado más reciente pasa a ser el nivel interno vigente.
                if p["idx"] > floor and (cur is None or p["idx"] > cur["idx"]):
                    cur = p
            if cur is None:
                continue
            if (closes[j] > cur["price"]) if is_high else (closes[j] < cur["price"]):
                out.append(mk(cur, j, is_high, False))
                floor = j
                cur = None
        return out[-max_keep:]

    # 1) Estructura MAYOR de ambos lados. Los PENDIENTES (nivel aún sin romper) se
    # filtran por proximidad: solo el nivel en juego cerca del precio (la línea
    # 64.234 overhead de la captura), no la liquidez ya barrida lejos (el mínimo
    # estructural a −5/−7% que es Weak Low, no CDC). Así desaparece el pendiente
    # espurio ~59 sin afectar el dealing range ni el pendiente 64.234.
    majors = []
    for own, opp, is_high in ((sh, sl, True), (sl, sh, False)):
        majors.extend(run(own, opp, is_high))
    majors = [e for e in majors if (not e["pending"])
              or (last and abs(e["price"] - last) / last * 100 <= CDC_PEND_MAX_DIST_PCT)]

    def covered_by_major(e):
        """Un CDC interno es CONTINUACIÓN (no cambio de carácter) cuando rompe en la
        MISMA dirección de un nivel MAYOR activo que lo domina: el rally hacia el
        Strong High overhead (64.234/64.250) hace que cada quiebre interno al alza
        sea continuación, no CDC (la queja de Hugo del rally del 06-12 y del interno
        63.843). El interno a la BAJA 61.18 va EN CONTRA del mayor (no hay un nivel
        mayor bajista que lo cubra: el pendiente ~59 se filtró por lejano) → se
        mantiene. La cobertura incluye la pierna de FORMACIÓN del nivel mayor
        (origen hasta 2·RANGE_PIV velas después del quiebre interno)."""
        for m in majors:
            if m["dir"] != e["dir"]:
                continue
            beyond = (m["price"] >= e["price"]) if e["dir"] == "up" else (m["price"] <= e["price"])
            if beyond and m["idx_to"] >= e["idx_to"] and m["idx_from"] <= e["idx_to"] + 2 * RANGE_PIV:
                return True
        return False

    for is_high in (True, False):
        d = "up" if is_high else "down"
        side = [e for e in majors if e["dir"] == d]
        pend = [e for e in side if e["pending"]]
        hist = [e for e in side if not e["pending"]][-max_events:]
        events.extend(hist + pend)
    # 2) Capa interna, deduplicada contra la mayor y sin los quiebres de continuación.
    seen = {(e["price"], e["t_to"]) for e in events}
    for own, opp, is_high in ((sh, sl, True), (sl, sh, False)):
        for e in run_internal(own, opp, is_high):
            if (e["price"], e["t_to"]) in seen:
                continue
            if covered_by_major(e):
                continue
            events.append(e)
    events.sort(key=lambda e: e["t_to"])
    for e in events:                       # campos internos de cálculo, fuera del payload
        e.pop("idx_from", None)
        e.pop("idx_to", None)
    return events


def _cdc_state(closed: list, direction: str, zone_lo: float, zone_hi: float) -> Dict:
    """Estado del CDC para el plan: tras el TOQUE de la zona del POI, ¿hubo un
    cierre que rompa el último swing relevante en la dirección del plan?
    (descuento → CDC alcista para largos; premium → CDC bajista para cortos).

    Solo velas cerradas (cero look-ahead); los swings usan confirm_idx. Estados:
      sin_toque  → el precio todavía no toca la zona (no aplica CDC aún),
      esperando  → tocó la zona, sin CDC dentro de la ventana todavía,
      confirmado → apareció el CDC en la dirección correcta dentro de la ventana,
      vencido    → la ventana (16 velas) pasó sin CDC.
    """
    n = len(closed)
    none = {"status": "sin_toque", "tap_t": None, "cdc_t": None, "bars_since_tap": None}
    if n < 2 * CDC_PIV + 2:
        return none
    # Toque: primera vela que solapa la zona, mirando solo el tramo reciente
    # (más allá de ~3 ventanas el setup ya no es "este" toque).
    scan_from = max(0, n - 3 * CDC_WINDOW)
    tap = None
    for j in range(scan_from, n):
        if closed[j]["l"] <= zone_hi and closed[j]["h"] >= zone_lo:
            tap = j
            break
    if tap is None:
        return none
    sh, sl = smc.swing_points(closed, CDC_PIV)
    ref = _conf_prices(sh if direction == "long" else sl, n)
    closes = [c["c"] for c in closed]
    end = min(n - 1, tap + CDC_WINDOW)
    for j in range(tap, end + 1):
        r = ref[j]
        if r is None:
            continue
        if (direction == "long" and closes[j] > r) or \
           (direction == "short" and closes[j] < r):
            return {"status": "confirmado", "tap_t": closed[tap]["t"],
                    "cdc_t": closed[j]["t"], "bars_since_tap": n - 1 - tap}
    if n - 1 - tap >= CDC_WINDOW:
        return {"status": "vencido", "tap_t": closed[tap]["t"], "cdc_t": None,
                "bars_since_tap": n - 1 - tap}
    return {"status": "esperando", "tap_t": closed[tap]["t"], "cdc_t": None,
            "bars_since_tap": n - 1 - tap}


def _last_confirmed(points, n):
    """Último pivote confirmado (precio, índice) — el más reciente ya válido."""
    if not points:
        return None
    p = sorted(points, key=lambda x: x["confirm_idx"])
    last = None
    for pt in p:
        if pt["confirm_idx"] < n:
            last = pt
    return last


def _range(candles) -> Dict:
    """Dealing range = el swing alto MÁS ALTO (Strong High) y el swing bajo MÁS BAJO
    (Weak Low) de la ventana visible, con equilibrio al 50%. Esto bracketa la
    estructura mayor, igual que el indicador de Bitcoin Traders Academy (no el
    último swing pequeño). Calibrado contra BTCUSDT.P 15m con RANGE_PIV=10 y
    candle_count≈400 → Strong High/Weak Low cercanos a los que ve Hugo."""
    sh, sl = smc.swing_points(candles, RANGE_PIV)
    if not sh or not sl:
        # Respaldo: extremos de las últimas velas.
        window = candles[-60:]
        h = max(c["h"] for c in window)
        l = min(c["l"] for c in window)
        return {"strong_high": h, "weak_low": l, "eq": (h + l) / 2,
                "strong_high_t": window[-1]["t"], "weak_low_t": window[0]["t"]}
    hi = max(sh, key=lambda x: x["price"])
    lo = min(sl, key=lambda x: x["price"])
    return {"strong_high": hi["price"], "weak_low": lo["price"],
            "eq": (hi["price"] + lo["price"]) / 2,
            "strong_high_t": candles[hi["idx"]]["t"],
            "weak_low_t": candles[lo["idx"]]["t"]}


def _fvgs(candles, lookback=80) -> List[Dict]:
    """FVGs recientes de la TF seleccionada (alcistas y bajistas), con marca de si
    ya se rellenaron (mitigaron)."""
    n = len(candles)
    start = max(2, n - lookback)
    out = []
    for bullish in (True, False):
        for f in smc.find_fvgs(candles, start, n - 1, bullish):
            idx = f["idx"]
            filled = False
            for k in range(idx + 1, n):
                if candles[k]["l"] <= f["hi"] and candles[k]["h"] >= f["lo"]:
                    filled = True
                    break
            out.append({"lo": round(f["lo"], 6), "hi": round(f["hi"], 6),
                        "t": candles[idx - 2]["t"], "bullish": bullish, "filled": filled})
    out.sort(key=lambda x: x["t"])
    return out[-10:]


def _pois_for_tf(candles, tf, last_price) -> List[Dict]:
    """POIs detectados en una TF, con estado de mitigación y relación con el precio."""
    n = len(candles)
    pois = strategies.detect_pois(candles, PIV, DISP)
    out = []
    for poi in pois:
        lo, hi = poi["lo"], poi["hi"]
        # Mitigado: alguna vela posterior al FVG volvió a entrar a la caja del OB.
        mitigated = False
        mit_t = None
        for k in range(poi["idx"] + 1, n):
            if candles[k]["l"] <= hi and candles[k]["h"] >= lo:
                mitigated = True
                mit_t = candles[k]["t"]
                break
        # Invalidado: el precio rompió el stop (atravesó la zona en contra).
        invalid = (last_price < poi["stop"]) if poi["dir"] == "long" else (last_price > poi["stop"])
        mid = (lo + hi) / 2
        out.append({
            "tf": tf, "dir": poi["dir"], "lo": round(lo, 6), "hi": round(hi, 6),
            "stop": round(poi["stop"], 6), "t_conf": poi["t_conf"],
            "mitigated": mitigated, "mit_t": mit_t, "invalid": invalid,
            "valid": (not mitigated) and (not invalid),
            "discount": poi["dir"] == "long",
            "in_zone": lo <= last_price <= hi,
            "dist_pct": round((mid - last_price) / last_price * 100, 2) if last_price else 0.0,
        })
    return out


# Cuántos niveles Weak/Strong recientes mostrar por lado (de la TF seleccionada).
# Pocos y RECIENTES para no saturar: los swings viejos/lejanos parecen de otra TF.
LEVELS_PER_SIDE = 2


def _levels(sel_candles, rng, n) -> List[Dict]:
    """Etiqueta los swings RECIENTES de la temporalidad seleccionada como Weak/Strong
    y su % en el dealing range. Solo los más recientes (locales) por lado, para que
    no aparezcan extremos viejos que parecen de otras temporalidades.
    Weak = liquidez AÚN no barrida (probable objetivo). Strong = ya barrida/defendida.
    % = posición del nivel dentro del rango (0% = Weak Low, 100% = Strong High)."""
    sh, sl = smc.swing_points(sel_candles, RANGE_PIV)
    rlo = rng["weak_low"] if rng else None
    rhi = rng["strong_high"] if rng else None
    valid_range = rlo is not None and rhi is not None and rhi > rlo

    def pct(p):
        if not valid_range:
            return None
        return round(max(0.0, min(100.0, (p - rlo) / (rhi - rlo) * 100)), 0)

    out = []
    for s in sorted(sh, key=lambda x: x["confirm_idx"])[-LEVELS_PER_SIDE:]:
        price, idx = s["price"], s["idx"]
        swept = any(sel_candles[k]["h"] > price for k in range(idx + 1, n))
        out.append({"type": "high", "price": round(price, 2), "t": sel_candles[idx]["t"],
                    "kind": "strong" if swept else "weak",
                    "label": ("Strong" if swept else "Weak") + " High", "pct": pct(price)})
    for s in sorted(sl, key=lambda x: x["confirm_idx"])[-LEVELS_PER_SIDE:]:
        price, idx = s["price"], s["idx"]
        swept = any(sel_candles[k]["l"] < price for k in range(idx + 1, n))
        out.append({"type": "low", "price": round(price, 2), "t": sel_candles[idx]["t"],
                    "kind": "strong" if swept else "weak",
                    "label": ("Strong" if swept else "Weak") + " Low", "pct": pct(price)})
    return out


# R:R mínimo para que un escenario valga la pena mostrarse (filtro 1:2).
MIN_RR = 2.0
# SL estructural con TECHO: se coloca apenas PASADO el nivel estructural que protege
# el setup (al otro lado del barrido), pero su distancia nunca supera MAX_SL_PCT del
# precio de entrada. Si la estructura exige más, se topa y se marca "SL excede estructura".
MAX_SL_PCT = 0.015        # tope de 1,5% del precio de entrada
SWEEP_BUFFER_PCT = 0.0015  # buffer ~0,15% más allá del extremo para sobrevivir un sweep
# Tolerancia para considerar que el precio ya está DENTRO de la zona (estado activo).
TOUCH_TOL = 0.0015
# Cap de distancia: solo planeamos POIs dentro del dealing range o a <= 5% del precio,
# para no dibujar order blocks irrelevantes (p. ej. un OB de 1D a +90%).
DIST_CAP_PCT = 5.0


def _opposite_liquidity(levels, long, ref, rhi, rlo):
    """TP = la siguiente liquidez SIN BARRER (Weak) en la dirección del trade y más
    allá del precio de referencia (Weak High arriba para largo / Weak Low abajo para
    corto). Respaldo: el extremo del dealing range. Devuelve (precio, etiqueta) o None.
    Apuntar a liquidez weak (no barrida) evita el bug de tomar un nivel ya barrido o
    por detrás del precio, que daba un R:R falso."""
    if long:
        weak = [l["price"] for l in levels
                if l["type"] == "high" and l["kind"] == "weak" and l["price"] > ref]
        if weak:
            return round(min(weak), 2), "Weak High"
        if rhi and rhi > ref:
            return round(rhi, 2), "Strong High"   # respaldo: techo del rango
        return None
    weak = [l["price"] for l in levels
            if l["type"] == "low" and l["kind"] == "weak" and l["price"] < ref]
    if weak:
        return round(max(weak), 2), "Weak Low"
    if rlo and rlo < ref:
        return round(rlo, 2), "Weak Low"          # respaldo: piso del rango
    return None


def _tpsl(pois, levels, last_price, rng) -> Dict:
    """Escenario de contexto (NO una orden ni recomendación automática).

    Dibuja el PLAN del POI válido MÁS CERCANO para poder PLANEAR la entrada, no
    solo en el instante exacto del toque:
      - POI válido (✓, sin mitigar) y CERCA (dentro del dealing range o <= 5% del
        precio). La zona correcta (descuento largo / premium corto) ya se valida
        al FORMARSE el POI contra el EQ local de su swing (detect_pois); el filtro
        de EQ global se eliminó por el research de dealing range (empeoraba OOS),
      - Entrada = la zona del POI,
      - SL ESTRUCTURAL CON TECHO: apenas pasado el nivel que protege el setup (al otro
        lado del barrido, con un pequeño buffer para sobrevivir un sweep), PERO sin que
        su distancia supere MAX_SL_PCT (1,5%) del precio de entrada. Si la estructura
        exige más, se topa en 1,5% y se marca `sl_capped` ("SL excede estructura").
      - TP = la siguiente liquidez SIN BARRER (Weak) en la dirección del trade más allá
        del precio; respaldo: el extremo del dealing range.
      - filtro R:R real (dist entrada→TP / dist entrada→SL real) >= 2.0.
    Estado: "activo" si el precio ya está dentro de la zona; "pendiente" (en
    vigilancia) si todavía no la toca. Devuelve None si no hay un plan que valga."""
    if not pois or not last_price:
        return None
    rhi = rng.get("strong_high") if rng else None
    rlo = rng.get("weak_low") if rng else None
    tol = last_price * TOUCH_TOL

    # 1) Candidatos: POI válido y CERCA (cap de distancia). La corrección de zona
    # (descuento para largos / premium para cortos) ya viene validada en la
    # FORMACIÓN del POI contra el EQ LOCAL de su swing (detect_pois, fib 0.5 del
    # último swing high/low). El filtro extra de EQ global (ventana de 400 velas)
    # se ELIMINÓ: research/dealing_range_2026-06-12.md mostró que empeoraba el
    # OOS de 1h (−0.096R → −0.130R) y descartaba justo los mejores toques.
    cands = []
    for p in pois:
        # Candidato: POI válido (sin mitigar) o recién tocado en fase CDC (la
        # mitigación del toque no mata el plan mientras se espera la confirmación).
        if not (p["valid"] or p.get("cdc_phase")):
            continue
        long = p["dir"] == "long"
        mid = (p["lo"] + p["hi"]) / 2
        in_range = rlo is not None and rhi is not None and rlo <= mid <= rhi
        near = abs(p.get("dist_pct", 0.0)) <= DIST_CAP_PCT
        if not (in_range or near):
            continue                       # POI lejano/irrelevante → no se planea
        cands.append((p, long, mid))
    if not cands:
        return None
    cands.sort(key=lambda c: abs(c[2] - last_price))  # el más cercano = el próximo a vigilar

    # 2) Del más cercano al más lejano: SL estructural con techo, TP y filtro R:R >= 2.
    for p, long, mid in cands:
        entry = round(mid, 2)
        # SL estructural = apenas pasado el extremo del barrido (stop del POI) + buffer.
        buf = entry * SWEEP_BUFFER_PCT
        sl_struct = (p["stop"] - buf) if long else (p["stop"] + buf)
        risk_struct = abs(entry - sl_struct)
        cap = entry * MAX_SL_PCT
        if risk_struct > cap:               # la estructura exige más de 1,5% → se topa
            risk = cap
            sl = round(entry - cap if long else entry + cap, 2)
            sl_capped = True
        else:
            risk = risk_struct
            sl = round(sl_struct, 2)
            sl_capped = False
        if risk <= 0:
            continue
        # TP = siguiente liquidez sin barrer; filtro R:R sobre la distancia de SL REAL.
        ref = max(entry, last_price) if long else min(entry, last_price)
        target = _opposite_liquidity(levels, long, ref, rhi, rlo)
        if not target:
            continue
        tp, tp_label = target
        rr = abs(tp - entry) / risk
        if rr < MIN_RR:
            continue                       # no llega a 2R con el SL real → no vale
        # Etiqueta más precisa si el TP coincide con un nivel concreto.
        for l in levels:
            if round(l["price"], 2) == tp:
                tp_label = l["label"]
                break
        # Estado: activo si el precio ya está dentro de la zona, sino en vigilancia.
        active = (p["lo"] - tol) <= last_price <= (p["hi"] + tol)
        return {
            "dir": p["dir"], "tf": p["tf"], "state": "activo" if active else "pendiente",
            "entry": entry, "entry_lo": round(p["lo"], 2), "entry_hi": round(p["hi"], 2),
            "sl": sl, "tp": tp, "rr": round(rr, 1), "tp_label": tp_label,
            "sl_pct": round(risk / entry * 100, 2), "sl_capped": sl_capped,
            "dist_pct": p.get("dist_pct", 0.0),
        }
    return None


def active_pois(htf_map: Dict[str, list], last_price: float) -> List[Dict]:
    """POIs válidos (sin mitigar) de 1D/4h/1h. Versión liviana para las alertas."""
    out = []
    for tf in POI_TFS:
        hc = htf_map.get(tf)
        if hc:
            out.extend(p for p in _pois_for_tf(hc, tf, last_price) if p["valid"])
    return out


def analyze(sel_candles, htf_map: Dict[str, list], last_price: float, sel_tf: str) -> Dict:
    """Construye el análisis SMC completo para el frontend."""
    rng_candles = sel_candles[-RANGE_WINDOW:] if sel_candles else sel_candles
    result = {
        "timeframe": sel_tf,
        "last_price": last_price,
        "range": _range(rng_candles) if sel_candles else None,
        "fvgs": _fvgs(sel_candles) if sel_candles else [],
        "pois": [],
        "note": "Zonas de interés (contexto), no recomendaciones de compra/venta.",
    }
    all_pois = []
    for tf in POI_TFS:
        hc = htf_map.get(tf)
        if not hc:
            continue
        all_pois.extend(_pois_for_tf(hc, tf, last_price))
    # Para dibujar: válidos (sin mitigar) recientes + algunos mitigados para atenuar.
    valids = [p for p in all_pois if p["valid"]]
    valids.sort(key=lambda p: abs(p["dist_pct"]))
    mitig = [p for p in all_pois if not p["valid"]]
    mitig.sort(key=lambda p: -p["t_conf"])
    draw = valids[:12] + mitig[:6]
    # ESCALERA PROFUNDA: con años de historia hay POIs/OB válidos lejos del precio
    # (p. ej. los <58k que pregunta Hugo). Los más cercanos ya entran en valids[:12];
    # acá sumamos los siguientes válidos BAJO y SOBRE el precio aunque estén lejos,
    # como referencia de "qué hay si el mercado se va" (el gráfico los dibuja cuando
    # el precio entra en su rango). Acotado para no saturar.
    drawn = {id(p) for p in draw}
    below = sorted((p for p in valids if p["hi"] < last_price and id(p) not in drawn),
                   key=lambda p: last_price - (p["lo"] + p["hi"]) / 2)
    above = sorted((p for p in valids if p["lo"] > last_price and id(p) not in drawn),
                   key=lambda p: (p["lo"] + p["hi"]) / 2 - last_price)
    # Deduplicado por valor (la historia larga repite el mismo OB) preservando orden.
    seen_z, pois = set(), []
    for p in draw + below[:8] + above[:4]:
        zkey = (p["dir"], p["tf"], round(p["lo"], 2), round(p["hi"], 2))
        if zkey in seen_z:
            continue
        seen_z.add(zkey)
        pois.append(p)
    result["pois"] = pois
    # Panel "POIs activos": solo los CERCANOS al precio. Con la historia larga
    # aparecen POIs de 1D válidos pero a −40% o más (BTC de otra era) que son
    # ruido para operar hoy; el gráfico igual los dibuja si entran en rango.
    near = [p for p in valids if abs(p.get("dist_pct", 0.0)) <= 15.0]
    result["active_pois"] = near[:12]
    # Capas estilo LuxAlgo (aditivas): niveles Weak/Strong con % y proyección TP/SL.
    result["levels"] = _levels(rng_candles, result["range"], len(rng_candles)) if sel_candles else []
    # Fase CDC: un POI recién TOCADO se mitiga (deja de ser "válido"), pero el plan
    # no debe desaparecer en el toque — es justo cuando se espera el CDC. Lo mantenemos
    # como candidato mientras dure la ventana (16 velas de la TF de planeación),
    # siempre que el stop no se haya roto.
    now_ms = int(time.time() * 1000)
    sel_ms = TF_MS.get(sel_tf, 3_600_000)
    cdc_phase = [dict(p, cdc_phase=True) for p in all_pois
                 if p["mitigated"] and not p["invalid"] and p.get("mit_t")
                 and now_ms - p["mit_t"] <= (CDC_WINDOW + 1) * sel_ms]
    result["tpsl"] = _tpsl(valids + cdc_phase, result["levels"], last_price, result["range"])
    # CDC: eventos de cambio de carácter para DIBUJAR (capa del gráfico) y, si
    # hay plan, la CONFIRMACIÓN del plan (anti-repaint: solo velas cerradas de la
    # TF de planeación). Hipótesis del research: aporta en 1h; forward-test.
    closed = closed_candles(sel_candles, sel_tf, now_ms) if sel_candles else []
    result["cdc_events"] = _cdc_events(closed) if closed else []
    plan = result["tpsl"]
    if plan and closed:
        cdc = _cdc_state(closed, plan["dir"], plan["entry_lo"], plan["entry_hi"])
        plan["cdc_status"] = cdc["status"]
        plan["cdc_ok"] = cdc["status"] == "confirmado"
        plan["cdc_t"] = cdc["cdc_t"]
        plan["cdc_tf"] = sel_tf
    return result
