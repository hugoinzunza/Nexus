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
# "Tocando o entrando" a la zona: tolerancia chica alrededor del POI (0.15%).
TOUCH_TOL = 0.0015


def _tpsl(pois, levels, last_price, rng) -> Dict:
    """Escenario de contexto (NO una orden ni recomendación automática).

    Solo arma un setup cuando hay CONFLUENCIA real de SMC, no un TP/SL que flota:
      - POI válido (✓, sin mitigar) que el precio está TOCANDO/ENTRANDO ahora,
      - en la zona correcta del rango: descuento (bajo EQ) para LARGO,
        premium (sobre EQ) para CORTO,
      - Entrada = la zona del POI,
      - SL = más allá del extremo del barrido que invalidaría el setup (stop del POI),
      - TP = la SIGUIENTE liquidez opuesta más cercana (Weak High arriba para largo /
        Weak Low abajo para corto; respaldo: el extremo del dealing range),
      - y el R:R real (dist entrada→TP / dist entrada→SL) es >= 2.0.
    Si el TP más cercano no da 2R, o no hay confluencia, devuelve None (no se dibuja)."""
    if not pois or not last_price:
        return None
    eq = rng.get("eq") if rng else None
    rhi = rng.get("strong_high") if rng else None
    rlo = rng.get("weak_low") if rng else None
    tol = last_price * TOUCH_TOL

    # 1) Candidatos: POI válido, en su zona correcta del rango, que el precio toca/entra.
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
        if not ((p["lo"] - tol) <= last_price <= (p["hi"] + tol)):
            continue                       # el precio no está tocando/entrando la zona
        cands.append((p, long, mid))
    if not cands:
        return None
    cands.sort(key=lambda c: abs(c[2] - last_price))  # el que el precio interactúa ahora

    # 2) Para cada candidato, TP = liquidez opuesta MÁS CERCANA y filtro R:R >= 2.
    for p, long, mid in cands:
        entry = round(mid, 2)
        sl = round(p["stop"], 2)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        if long:
            ups = [l["price"] for l in levels if l["type"] == "high" and l["price"] > entry]
            if rhi and rhi > entry:
                ups.append(rhi)
            if not ups:
                continue
            tp = round(min(ups), 2)       # la primera liquidez que el precio buscaría
        else:
            dns = [l["price"] for l in levels if l["type"] == "low" and l["price"] < entry]
            if rlo and rlo < entry:
                dns.append(rlo)
            if not dns:
                continue
            tp = round(max(dns), 2)
        rr = abs(tp - entry) / risk
        if rr < MIN_RR:
            continue                       # el TP más cercano no da 2R → no es setup
        # Etiqueta de la liquidez objetivo (Weak/Strong High/Low si está en niveles).
        tp_label = "Liquidez opuesta"
        for l in levels:
            if round(l["price"], 2) == tp:
                tp_label = l["label"]
                break
        return {
            "dir": p["dir"], "tf": p["tf"],
            "entry": entry, "entry_lo": round(p["lo"], 2), "entry_hi": round(p["hi"], 2),
            "sl": sl, "tp": tp, "rr": round(rr, 1), "tp_label": tp_label,
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
