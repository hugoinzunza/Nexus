"""Regresión del indicador SMC en vivo (dealing range, zonas profundas, paginación).

Complementa research/cdc_regression_checks.py (que cubre el CDC). Corre contra los
klines persistidos (data/klines_BTCUSDT_*.json) → determinista, sin red. Verifica
invariantes de los cambios de jun-2026:

  RANGE  Dealing range desacoplado del CDC y más ancho: DEALING_RANGE_WINDOW >
         RANGE_WINDOW, y el Weak Low sobre la ventana ancha es <= el de la angosta
         (más historia solo puede bajar el mínimo de la liquidez → llega al ~59k).
  DEEP   Con historia profunda en las HTF, analyze() expone una ESCALERA de POIs
         válidos BAJO y SOBRE el precio (referencia "qué hay si el mercado se va"),
         sin duplicados de zona, y acotada.
  PAGE   La paginación de velas (limit/before/has_more, con clamp de limit) parte
         la serie correctamente para el back-load del gráfico.

Salida: imprime cada check y termina 0 (todo OK) o 1 (alguna falla).
"""
from __future__ import annotations

import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import smc_live  # noqa: E402

DATA = os.path.join(WT, "data")
UI_TO_FILE = {"1D": "1d", "4h": "4h", "1h": "1h", "15m": "15m"}


def _load(sym, ui_tf):
    path = os.path.join(DATA, f"klines_{sym}_{UI_TO_FILE[ui_tf]}.json")
    with open(path) as fh:
        return sorted(json.load(fh), key=lambda c: c["t"])


def _merge(deep, recent):
    by = {c["t"]: c for c in deep}
    by.update({c["t"]: c for c in recent})
    return sorted(by.values(), key=lambda c: c["t"])


def _page(full, limit, before=None):
    """Réplica de la lógica de api/candles (module.py) para testearla aislada."""
    limit = max(1, min(limit, 5000))
    subset = [c for c in full if c["t"] < before] if before else full
    candles = subset[-limit:]
    return candles, len(subset) > len(candles)


def main():
    sym = "BTCUSDT"
    checks = []

    # --- RANGE -------------------------------------------------------------
    d15 = _load(sym, "15m")
    assert smc_live.DEALING_RANGE_WINDOW > smc_live.RANGE_WINDOW
    wl_narrow = smc_live._range(d15[-smc_live.RANGE_WINDOW:])["weak_low"]
    wl_wide = smc_live._range(d15[-smc_live.DEALING_RANGE_WINDOW:])["weak_low"]
    r1 = smc_live.DEALING_RANGE_WINDOW > smc_live.RANGE_WINDOW
    r2 = wl_wide <= wl_narrow
    checks.append(("RANGE ventana del rango desacoplada y > que la del CDC", r1))
    checks.append((f"RANGE Weak Low ancho ({wl_wide:.0f}) <= angosto ({wl_narrow:.0f})", r2))

    # --- DEEP (escalera de zonas con historia profunda en HTF) -------------
    htf = {tf: _merge(_load(sym, tf), _load(sym, tf)) for tf in ("1D", "4h", "1h")}
    sel = d15[-1000:]
    last = sel[-1]["c"]
    res = smc_live.analyze(sel, htf, last, "15m")
    pois = res["pois"]
    below = [p for p in pois if p["hi"] < last]
    above = [p for p in pois if p["lo"] > last]
    # zonas profundas reales (lejos del precio) presentes hacia abajo:
    deep_below = [p for p in below if p["dist_pct"] < -10]
    zkeys = [(p["dir"], p["tf"], round(p["lo"], 2), round(p["hi"], 2)) for p in pois]
    checks.append((f"DEEP hay zonas válidas bajo el precio ({len(below)})", len(below) >= 1))
    checks.append((f"DEEP hay zona profunda <-10% abajo ({len(deep_below)})", len(deep_below) >= 1))
    checks.append((f"DEEP hay zonas sobre el precio ({len(above)})", len(above) >= 1))
    checks.append((f"DEEP sin duplicados de zona ({len(zkeys)} pois)", len(zkeys) == len(set(zkeys))))
    checks.append((f"DEEP set de dibujo acotado ({len(pois)} <= 30)", len(pois) <= 30))

    # --- PAGE (paginación del gráfico) -------------------------------------
    full = d15
    recent, more1 = _page(full, 1500)
    older, more2 = _page(full, 3000, before=recent[0]["t"])
    p1 = len(recent) == 1500 and more1 is True
    p2 = len(older) == 3000 and all(c["t"] < recent[0]["t"] for c in older)
    capped, _ = _page(full, 999999)            # tope MAX_CHART_PAGE
    p3 = len(capped) == 5000
    zero, _ = _page(full, 0)                    # limit<=0 NO devuelve todo
    p4 = len(zero) == 1
    checks.append((f"PAGE recientes=1500 y has_more ({len(recent)})", p1))
    checks.append((f"PAGE older anteriores al cursor ({len(older)})", p2))
    checks.append((f"PAGE limit topado a 5000 ({len(capped)})", p3))
    checks.append((f"PAGE limit<=0 no devuelve todo ({len(zero)})", p4))

    ok = True
    for name, passed in checks:
        print(f"  [{'OK ' if passed else 'FALLA'}] {name}")
        ok = ok and passed
    print(f"\nSUITE SMC LIVE: {'APROBADA' if ok else 'FALLA'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
