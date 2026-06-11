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

PIV = 2
DISP = 1.0
POI_TFS = ["1D", "4h", "1h"]   # temporalidades de detección de POIs (Crypto.com)


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
    """Dealing range = swing alto (Strong High) y swing bajo (Weak Low) recientes,
    con equilibrio al 50%."""
    n = len(candles)
    sh, sl = smc.swing_points(candles, 3)
    hi = _last_confirmed(sh, n)
    lo = _last_confirmed(sl, n)
    if not hi or not lo:
        # Respaldo: extremos de las últimas velas.
        window = candles[-60:]
        h = max(c["h"] for c in window)
        l = min(c["l"] for c in window)
        return {"strong_high": h, "weak_low": l, "eq": (h + l) / 2,
                "strong_high_t": window[-1]["t"], "weak_low_t": window[0]["t"]}
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
    return result
