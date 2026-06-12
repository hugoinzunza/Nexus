"""Filtro de RÉGIMEN para las entradas SMC POI multi-TF (prototipo integrable).

Hallazgo del backtest (research/estrategias_2026-06-12.md): las entradas POI rinden
mucho mejor cuando hay (a) calma de mercado —VIX bajo— y (b) tendencia presente en la
TF de planeación —ADX alto—. Este módulo entrega un "permiso" (gate) que se puede
ENVOLVER alrededor del plan que ya produce smc_live.analyze, sin cambiar la detección:
si el régimen no es favorable, se marca el setup como "vetado por régimen" (no se
opera / se reduce tamaño), pero NO se altera la lógica SMC.

Regla recomendada (la más robusta del estudio, OOS PF 1.74, bootstrap P(exp>0)=0.97):
    operar el POI solo si  VIX < 25  Y  ADX(14) de la TF de planeación > 25.
Variantes:
    - Estricta (más calidad, menos trades): VIX < 20.
    - Solo confluencia técnica (sin dato macro): ADX > 25.

Anti-repaint: el ADX usa solo velas cerradas; el VIX usa el último cierre diario ya
conocido. NADA de esto mira el futuro.

Este archivo es un PROTOTIPO de research/: no toca el frontend ni el live. Para
integrarlo, ver las notas al final.
"""
from __future__ import annotations

import bisect
import json
import os
import time
import urllib.request

# --- ADX (Wilder), igual que en research/collect_trades.py ---------------
def adx(candles, period: int = 14):
    """ADX de Wilder. Devuelve lista alineada (None hasta tener datos)."""
    n = len(candles)
    out = [None] * n
    if n < 2 * period + 1:
        return out
    tr = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        h, l = candles[i]["h"], candles[i]["l"]
        ph, pl, pc = candles[i - 1]["h"], candles[i - 1]["l"], candles[i - 1]["c"]
        up, dn = h - ph, pl - l
        plus_dm[i] = up if (up > dn and up > 0) else 0.0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = sum(tr[1:period + 1])
    pdm = sum(plus_dm[1:period + 1])
    mdm = sum(minus_dm[1:period + 1])
    dxs = []
    for i in range(period + 1, n):
        atr = atr - atr / period + tr[i]
        pdm = pdm - pdm / period + plus_dm[i]
        mdm = mdm - mdm / period + minus_dm[i]
        if atr <= 0:
            continue
        pdi, mdi = 100 * pdm / atr, 100 * mdm / atr
        denom = pdi + mdi
        dx = 100 * abs(pdi - mdi) / denom if denom > 0 else 0.0
        dxs.append(dx)
        if len(dxs) >= period:
            out[i] = sum(dxs[-period:]) / period
    return out


# --- VIX (último cierre diario conocido), cacheado -----------------------
_VIX_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "data_macro", "vix_1d.json")
_DAY_MS = 86_400_000
_VIX_TTL_MS = 6 * 3_600_000   # refrescar como máximo cada 6 h


def _fetch_vix():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=3mo&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.load(r)
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    cl = res["indicators"]["quote"][0]["close"]
    out = []
    for t, c in zip(ts, cl):
        if c is None:
            continue
        day0 = (int(t) * 1000 // _DAY_MS) * _DAY_MS
        out.append({"t": day0 + 21 * 3_600_000, "c": float(c)})  # ~cierre NYSE UTC
    out.sort(key=lambda x: x["t"])
    return out


def vix_now(now_ms: int | None = None) -> float | None:
    """Último cierre del VIX ya conocido (anti-repaint). Usa caché en disco."""
    now_ms = now_ms or int(time.time() * 1000)
    data = None
    if os.path.isfile(_VIX_CACHE_PATH):
        try:
            with open(_VIX_CACHE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:  # noqa: BLE001
            data = None
    fresh = data and (now_ms - data[-1]["t"]) < (_VIX_TTL_MS + _DAY_MS)
    if not fresh:
        try:
            data = _fetch_vix()
            os.makedirs(os.path.dirname(_VIX_CACHE_PATH), exist_ok=True)
            with open(_VIX_CACHE_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
        except Exception:  # noqa: BLE001
            if not data:
                return None
    ts = [r["t"] for r in data]
    idx = bisect.bisect_right(ts, now_ms) - 1
    return data[idx]["c"] if idx >= 0 else None


# --- Gate de régimen -----------------------------------------------------
def regime_gate(sel_candles, now_ms: int | None = None,
                vix_max: float = 25.0, adx_min: float = 25.0,
                require_vix: bool = True) -> dict:
    """¿El régimen permite operar el POI? Devuelve dict con ok/reason/valores.

    sel_candles: velas YA CERRADAS de la TF de planeación (1h/4h), la misma ventana
                 que usa smc_live.analyze.
    """
    adx_arr = adx(sel_candles, 14)
    adx_v = next((adx_arr[i] for i in range(len(adx_arr) - 1, -1, -1)
                  if adx_arr[i] is not None), None)
    vix_v = vix_now(now_ms)

    adx_ok = adx_v is not None and adx_v > adx_min
    if require_vix:
        # Si no hay dato de VIX, no vetamos por macro (conservador: no bloquear por falta de dato).
        vix_ok = (vix_v is None) or (vix_v < vix_max)
    else:
        vix_ok = True
    ok = adx_ok and vix_ok

    reasons = []
    if not adx_ok:
        reasons.append(f"ADX {round(adx_v,1) if adx_v is not None else '—'} ≤ {adx_min} (sin tendencia)")
    if require_vix and not vix_ok:
        reasons.append(f"VIX {round(vix_v,1) if vix_v is not None else '—'} ≥ {vix_max} (mercado estresado)")
    return {
        "ok": ok,
        "adx": round(adx_v, 1) if adx_v is not None else None,
        "vix": round(vix_v, 1) if vix_v is not None else None,
        "reason": "régimen favorable" if ok else "; ".join(reasons),
    }


if __name__ == "__main__":
    # Demo: VIX actual y ejemplo de gate con velas BTC 1h.
    print("VIX ahora:", vix_now())
    p = os.path.join("/Users/hugh/Nexus/data", "klines_BTCUSDT_1h.json")
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as fh:
            c = json.load(fh)
        print("Gate (VIX<25 + ADX>25):", regime_gate(c[-400:]))
        print("Gate estricto (VIX<20):", regime_gate(c[-400:], vix_max=20.0))

# --- NOTAS DE INTEGRACIÓN (cuando Hugo decida sumarlo al live) ------------
# En modules/trading/smc_live.analyze, después de construir result["tpsl"]:
#
#     from research.regime_filter import regime_gate   # o mover este archivo a modules/trading/
#     if result.get("tpsl"):
#         gate = regime_gate(sel_candles)               # mismas velas cerradas de la TF
#         result["tpsl"]["regime_ok"] = gate["ok"]
#         result["tpsl"]["regime_reason"] = gate["reason"]
#         result["tpsl"]["adx"] = gate["adx"]
#         result["tpsl"]["vix"] = gate["vix"]
#
# El frontend puede pintar el setup atenuado / con etiqueta "vetado por régimen"
# cuando regime_ok es False, sin eliminar la zona (sigue siendo contexto válido).
# Opción tamaño: operar tamaño completo si ok, medio o nada si no. NO cambia la
# detección SMC: es una capa de permiso por encima.
