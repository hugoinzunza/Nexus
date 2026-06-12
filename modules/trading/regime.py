"""Filtro de RÉGIMEN para los planes SMC POI multi-TF — capa de PERMISO/CONTEXTO.

Hallazgo de la investigación (research/estrategias_2026-06-12.md): las entradas POI
rinden mucho mejor en (a) calma de mercado —VIX bajo— y (b) con tendencia en la TF de
planeación —ADX alto—. Con costos, la base de 7 pares queda break-even OOS (PF 0.98);
el filtro VIX<25 + ADX>25 la lleva a +0.77R OOS / PF 1.74 (7 pares) y +2.07R / PF 3.07
(BTC+ETH). Es la ÚNICA variante cuyo IC90 bootstrap excluye el 0. NO es garantía: sigue
siendo una hipótesis a validar en vivo (forward-test).

Esto NO toca la detección SMC. Es un SEMÁFORO que se envuelve alrededor del plan que ya
produce smc_live.analyze: marca cada setup como "régimen favorable" o "desfavorable",
con VIX y ADX visibles. El frontend atenúa/etiqueta el plan fuera de régimen, pero NO lo
oculta (la zona sigue siendo contexto válido).

Regla: VIX < 25 (ideal < 20) Y ADX(14) de la TF de planeación > 25.

Anti-repaint: el ADX usa solo velas cerradas; el VIX usa el último cierre diario conocido.
Degradación elegante: si el VIX no es accesible (geobloqueo/red), NO se veta por macro
(conservador) y se reporta vix=None → la UI muestra "s/d".
"""
from __future__ import annotations

import bisect
import json
import os
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
VIX_CACHE_PATH = os.path.join(DATA_DIR, "vix_1d.json")

_DAY_MS = 86_400_000
_VIX_TTL_MS = 6 * 3_600_000      # refrescar el VIX como máximo cada 6 h
_MARKET_CLOSE_UTC_H = 21         # ~cierre NYSE en UTC (anti-repaint)
_VIX_MAX = 25.0
_ADX_MIN = 25.0

_lock = threading.Lock()


# --- ADX de Wilder (mismas velas cerradas que smc_live) ------------------
def adx(candles, period: int = 14):
    """ADX de Wilder. Lista alineada (None hasta tener datos)."""
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


def adx_last(candles, period: int = 14):
    arr = adx(candles, period)
    for i in range(len(arr) - 1, -1, -1):
        if arr[i] is not None:
            return round(arr[i], 1)
    return None


# --- VIX (último cierre diario), cacheado en disco -----------------------
def _fetch_vix():
    """Descarga el VIX diario de Yahoo (público, sin clave). Prueba dos hosts."""
    last_err = None
    for host in ("query1", "query2"):
        url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/"
               f"%5EVIX?range=3mo&interval=1d")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.load(r)
            res = d["chart"]["result"][0]
            ts = res["timestamp"]
            cl = res["indicators"]["quote"][0]["close"]
            out = []
            for t, c in zip(ts, cl):
                if c is None:
                    continue
                day0 = (int(t) * 1000 // _DAY_MS) * _DAY_MS
                out.append({"t": day0 + _MARKET_CLOSE_UTC_H * 3_600_000, "c": float(c)})
            out.sort(key=lambda x: x["t"])
            if out:
                return out
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    if last_err:
        raise last_err
    return []


def vix_now(now_ms: int | None = None) -> float | None:
    """Último cierre del VIX ya conocido (anti-repaint), con caché en disco.
    Si no se puede traer y no hay caché, devuelve None (la UI muestra 's/d')."""
    now_ms = now_ms or int(time.time() * 1000)
    with _lock:
        data = None
        if os.path.isfile(VIX_CACHE_PATH):
            try:
                with open(VIX_CACHE_PATH, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:  # noqa: BLE001
                data = None
        fresh = data and (now_ms - data[-1]["t"]) < (_VIX_TTL_MS + _DAY_MS)
        if not fresh:
            try:
                fetched = _fetch_vix()
                if fetched:
                    data = fetched
                    os.makedirs(DATA_DIR, exist_ok=True)
                    tmp = VIX_CACHE_PATH + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as fh:
                        json.dump(data, fh)
                    os.replace(tmp, VIX_CACHE_PATH)
            except Exception:  # noqa: BLE001 - sin red/geobloqueo: usamos lo cacheado si hay
                if not data:
                    return None
        if not data:
            return None
        ts = [r["t"] for r in data]
        idx = bisect.bisect_right(ts, now_ms) - 1
        return round(data[idx]["c"], 1) if idx >= 0 else None


# --- Gate de régimen (semáforo) ------------------------------------------
def regime_gate(sel_candles, now_ms: int | None = None,
                vix_max: float = _VIX_MAX, adx_min: float = _ADX_MIN) -> dict:
    """Semáforo de régimen para el plan. NO bloquea nada: informa ok + valores.

    sel_candles: velas YA CERRADAS de la TF de planeación (las mismas de smc_live.analyze).
    Devuelve {ok, vix, adx, reason}. Si falta el VIX, no se veta por macro (conservador)
    y vix=None → la UI muestra 's/d'.
    """
    adx_v = adx_last(sel_candles, 14)
    vix_v = vix_now(now_ms)
    adx_ok = adx_v is not None and adx_v > adx_min
    vix_ok = (vix_v is None) or (vix_v < vix_max)   # sin dato → no veta por macro
    ok = bool(adx_ok and vix_ok)
    reasons = []
    if not adx_ok:
        reasons.append(f"ADX {adx_v if adx_v is not None else '—'} ≤ {adx_min:g} (sin tendencia)")
    if vix_v is not None and not vix_ok:
        reasons.append(f"VIX {vix_v} ≥ {vix_max:g} (mercado estresado)")
    return {
        "ok": ok,
        "vix": vix_v,
        "adx": adx_v,
        "reason": "régimen favorable" if ok else ("; ".join(reasons) or "régimen desfavorable"),
    }
