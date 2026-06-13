"""Suite de regresión del CDC dibujado contra las capturas de Hugo (M15 BTC).

Hechos extraídos de sus 7 capturas (2026-06-12/13) que toda regla nueva debe
respetar. Se corre sobre dos datasets:
  - CACHE: data/klines_BTCUSDT_15m.json recortado al 2026-06-12 ~13:30 UTC
    (el momento de sus capturas, ANTES del quiebre del 64.23), y
  - VIVO: las 1000 velas actuales de Binance (si hay red).

Checks:
  A (cache) Pendiente alcista ≈ 64.234 existe (su línea, viva 5 días).
  B (cache) NINGÚN CDC alcista histórico en 63.000–64.200 después del 06-11
            (el rally no rompió carácter bajo la línea — su queja clave).
  C (cache) CDC bajista (interno o mayor) en 61.000–61.250 entre 06-09 y 06-10
            (su quiebre hacia el Discount POI).
  D (cache) CDC alcista interno ≈ 61.4–61.7 alrededor del 06-06/07 (su ejemplo
            del lower high roto). SOFT: se reporta, no falla la suite.
  E (vivo)  El quiebre con cuerpo del 64.23–64.30 del 06-12 aparece como CDC
            histórico ("un Strong roto pasa a ser CDC").
  F (vivo)  Reporte de pendientes vigentes (¿64.403? ¿59.13?) — el árbitro
            final es la captura actual de Hugo.
"""
from __future__ import annotations

import json
import os
import sys
import time

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import smc_live  # noqa: E402

CUT_MS = 1781271000000   # 2026-06-12 ~13:30 UTC (momento de las capturas)


def ts(ms):
    return time.strftime("%m-%d %H:%M", time.gmtime(ms / 1000))


def events_for(candles):
    return smc_live._cdc_events(candles)


def fmt(e):
    tag = "PEND" if e["pending"] else "hist"
    return f"{tag} {e['dir']} @ {e['price']:.1f} (origen {ts(e['t_from'])} → {ts(e['t_to'])})"


def main():
    with open(os.path.join(WT, "data", "klines_BTCUSDT_15m.json")) as fh:
        data = sorted(json.load(fh), key=lambda c: c["t"])
    cache = [c for c in data if c["t"] <= CUT_MS][-1000:]
    ev = events_for(cache)
    print("== CACHE (recortado al 06-12 13:30, momento de las capturas) ==")
    for e in ev:
        print("  ", fmt(e))
    okA = any(e["pending"] and e["dir"] == "up" and abs(e["price"] - 64234) < 120 for e in ev)
    okB = not any((not e["pending"]) and e["dir"] == "up" and 63000 < e["price"] < 64200
                  and e["t_to"] > 1781136000000 for e in ev)   # después del 06-11 00:00
    okC = any(e["dir"] == "down" and 61000 <= e["price"] <= 61250
              and 1781000000000 < e["t_to"] < 1781200000000 for e in ev)
    okD = any(e["dir"] == "up" and 61400 <= e["price"] <= 61700 for e in ev)
    print(f"A pendiente 64.234: {'OK' if okA else 'FALLA'}")
    print(f"B sin CDC alcista interior en el rally: {'OK' if okB else 'FALLA'}")
    print(f"C quiebre bajista 61.0-61.25 (06-09/10): {'OK' if okC else 'FALLA'}")
    print(f"D (soft) CDC alcista ~61.5 (06-06/07): {'OK' if okD else 'no aparece'}")

    try:
        from modules.trading import binance
        live = binance.recent_klines("BTCUSDT", "15m", limit=1000)
        ev2 = events_for(live)
        print("\n== VIVO (ahora) ==")
        for e in ev2:
            print("  ", fmt(e))
        okE = any((not e["pending"]) and e["dir"] == "up"
                  and 64150 < e["price"] < 64350 for e in ev2)
        print(f"E Strong 64.23-64.30 roto con cuerpo = CDC histórico: {'OK' if okE else 'FALLA'}")
        pends = [(e["dir"], round(e["price"])) for e in ev2 if e["pending"]]
        print(f"F pendientes vigentes (validar con captura de Hugo): {pends}")
        hard_ok = okA and okB and okC and okE
    except Exception as exc:  # noqa: BLE001 - sin red igual corre el cache
        print(f"\n(VIVO no disponible: {exc})")
        hard_ok = okA and okB and okC
    print(f"\nSUITE: {'APROBADA' if hard_ok else 'FALLA'}")
    sys.exit(0 if hard_ok else 1)


if __name__ == "__main__":
    main()
