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

from typing import Dict, List

from . import smc
from . import strategies

PIV = 2          # pivote fino para detectar FVG / order blocks (POIs)
DISP = 1.0
# Pivote para el DEALING RANGE (Strong High / Weak Low) y los niveles Weak/Strong:
# más grande → swings mayores, alineado con el indicador de Bitcoin Traders Academy
# que Hugo ve en BTCUSDT.P 15m (lookback 10, calibrado contra sus niveles).
RANGE_PIV = 10
POI_TFS = ["1D", "4h", "1h"]   # temporalidades de detección de POIs


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

    Dibuja el PLAN del POI válido en zona correcta MÁS CERCANO para poder PLANEAR la
    entrada, no solo en el instante exacto del toque:
      - POI válido (✓, sin mitigar), en zona correcta del rango (descuento para largo,
        premium para corto) y CERCA (dentro del dealing range o <= 5% del precio),
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
    eq = rng.get("eq") if rng else None
    rhi = rng.get("strong_high") if rng else None
    rlo = rng.get("weak_low") if rng else None
    tol = last_price * TOUCH_TOL

    # 1) Candidatos: POI válido, en su zona correcta del rango, y CERCA (cap de distancia).
    cands = []
    for p in pois:
        if not p["valid"]:
            continue
        long = p["dir"] == "long"
        mid = (p["lo"] + p["hi"]) / 2
        if eq is not None:
            if long and mid >= eq:        # largo solo si el POI está en DESCUENTO
                continue
            if (not long) and mid <= eq:  # corto solo si el POI está en PREMIUM
                continue
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
    result = {
        "timeframe": sel_tf,
        "last_price": last_price,
        "range": _range(sel_candles) if sel_candles else None,
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
    result["pois"] = valids[:12] + mitig[:6]
    result["active_pois"] = valids[:12]   # para el panel "POIs activos"
    # Capas estilo LuxAlgo (aditivas): niveles Weak/Strong con % y proyección TP/SL.
    result["levels"] = _levels(sel_candles, result["range"], len(sel_candles)) if sel_candles else []
    result["tpsl"] = _tpsl(valids, result["levels"], last_price, result["range"])
    return result
