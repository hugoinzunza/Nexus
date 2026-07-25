#!/usr/bin/env python3
"""Une los niveles REALES de CoinGlass con los setups del Diario, hacia adelante.

El estudio del imán (2026-07-25) dejó una sola cosa con evidencia a favor: que el
NIVEL aporta algo por encima del puro ancho del stop (+238R en OOS, CI que no cruza
cero). Pero eso se midió con imanes aproximados por estructura de precio, porque la
profundidad histórica del libro y el mapa de liquidaciones **no son descargables**
con el plan actual (401 "Upgrade plan" en todos los rangos).

La versión con niveles reales sólo se puede construir **registrando hacia adelante**.
Hasta hoy no se estaba registrando: el historial del libro era una ventana rodante de
7 días y nada lo cruzaba con los setups. Ahora el módulo archiva append-only lo que se
cae de la ventana; este script hace el cruce, offline y por `captured_at`, sin que
ningún módulo de trading importe CoinGlass.

CAUSALIDAD: para cada setup se usa la captura más reciente **anterior o igual** a su
activación. Nunca una posterior. Un setup sin captura previa dentro de la tolerancia
queda fuera y se cuenta aparte.

EXPECTATIVA REALISTA, para no generar falsas ilusiones con esto:
el colector captura **sólo BTCUSDT**, y el Diario produce ~15 setups de BTC cada 43
días. Aunque el archivo funcione perfecto desde hoy, juntar muestra suficiente para
repetir la comparación imán-vs-placebo toma **años**, no meses. El archivo vale
porque preserva la opción y cuesta casi nada, no porque vaya a responder pronto.

Corre:   .venv/bin/python3 research/coinglass_imanes_forward.py
Escribe: research/coinglass_imanes_forward_results.json
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from core.paths import persist_dir  # noqa: E402

DATA = persist_dir(WT)
ARCHIVO = os.path.join(DATA, "coinglass_visual_book_archive.jsonl")
CALIENTE = os.path.join(DATA, "coinglass_visual_book_history.json")
SETUPS = os.path.join(DATA, "setups.json")
OUT_JSON = os.path.join(WT, "research", "coinglass_imanes_forward_results.json")

SIMBOLO = "BTC_USDT"        # lo único que captura el colector
TOLERANCIA_MIN = 15         # captura válida si es de hasta 15 min antes del toque


def _epoch(stamp):
    try:
        when = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if when.tzinfo is None:
        return None
    return when.timestamp()


def cargar_capturas():
    """Archivo histórico + ventana caliente, deduplicado por `captured_at`.

    Los dos se solapan a propósito: el archivo se escribe cuando una captura se cae
    de la ventana, así que la ventana tiene lo más nuevo y el archivo lo viejo. Si
    una escritura se repitiera (reintento tras un fallo de disco), la dedup lo tapa.
    """
    por_stamp = {}
    if os.path.isfile(ARCHIVO):
        with open(ARCHIVO, encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    fila = json.loads(linea)
                except json.JSONDecodeError:
                    continue          # una línea cortada no invalida el resto
                if isinstance(fila, dict) and fila.get("captured_at"):
                    por_stamp[fila["captured_at"]] = fila
    if os.path.isfile(CALIENTE):
        try:
            with open(CALIENTE, encoding="utf-8") as fh:
                for fila in json.load(fh) or []:
                    if isinstance(fila, dict) and fila.get("captured_at"):
                        por_stamp[fila["captured_at"]] = fila
        except (OSError, json.JSONDecodeError):
            pass
    capturas = []
    for fila in por_stamp.values():
        ts = _epoch(fila.get("captured_at"))
        if ts is not None:
            capturas.append((ts, fila))
    capturas.sort(key=lambda x: x[0])
    return capturas


def imanes_reales(fila, precio):
    """Muro de compra más cercano por debajo y de venta por encima, con su monto."""
    bids = [(p, u) for p, u in (fila.get("bids") or []) if p and p < precio]
    asks = [(p, u) for p, u in (fila.get("asks") or []) if p and p > precio]
    abajo = max(bids, default=None, key=lambda x: x[0])
    arriba = min(asks, default=None, key=lambda x: x[0])
    def fmt(m, signo):
        if not m:
            return None
        return {"precio": m[0], "usd": m[1],
                "distancia_pct": round(signo * (m[0] / precio - 1) * 100, 3)}
    return fmt(abajo, -1), fmt(arriba, 1)


def main():
    capturas = cargar_capturas()
    setups = []
    if os.path.isfile(SETUPS):
        with open(SETUPS, encoding="utf-8") as fh:
            crudos = json.load(fh)
        setups = [s for s in (crudos if isinstance(crudos, list) else [])
                  if s.get("pair") == SIMBOLO and s.get("ts_activated")]

    filas, sin_cobertura = [], 0
    for s in setups:
        t = float(s["ts_activated"])
        previa = None
        for ts, fila in capturas:
            if ts <= t:
                previa = (ts, fila)
            else:
                break                  # capturas ordenadas: nada posterior sirve
        if previa is None or (t - previa[0]) > TOLERANCIA_MIN * 60:
            sin_cobertura += 1
            continue
        ts, fila = previa
        precio = fila.get("price") or s.get("entry")
        abajo, arriba = imanes_reales(fila, precio)
        filas.append({
            "key": s.get("key"),
            "dir": s.get("dir"),
            "ts_activated": int(t),
            "desfase_seg": int(t - ts),
            "entry": s.get("entry"),
            "sl": s.get("sl"),
            "rr": s.get("rr"),
            "result_r": s.get("result_r"),
            "precio_captura": precio,
            "iman_abajo": abajo,
            "iman_arriba": arriba,
        })

    salida = {
        "meta": {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "aviso": "Research only - No senal - No bot - NO usar para activar live",
            "proposito": ("registrar hacia adelante los imanes REALES en el momento "
                          "del toque; es la unica via, el historico no es descargable"),
            "causalidad": "captura anterior o igual a la activacion, nunca posterior",
            "simbolo": SIMBOLO,
            "tolerancia_min": TOLERANCIA_MIN,
            "capturas_disponibles": len(capturas),
            "setups_btc_activados": len(setups),
            "con_cobertura": len(filas),
            "sin_cobertura": sin_cobertura,
            "expectativa": ("~15 setups de BTC cada 43 dias: juntar muestra para "
                            "repetir iman-vs-placebo toma anos, no meses"),
        },
        "filas": filas,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, indent=1)

    m = salida["meta"]
    print(f"resultados: {OUT_JSON}\n")
    print(f"capturas del libro disponibles : {m['capturas_disponibles']}")
    print(f"setups BTC activados           : {m['setups_btc_activados']}")
    print(f"  con captura previa (<={TOLERANCIA_MIN} min): {m['con_cobertura']}")
    print(f"  sin cobertura                : {m['sin_cobertura']}")
    if not filas:
        print("\nSin cruces todavia. Es lo ESPERADO: el archivo empieza hoy y sólo\n"
              "cubre hacia adelante. Este script existe para que dentro de meses\n"
              "haya con que, no para dar una respuesta ahora.")
        return
    print(f"\n{'setup':28} {'dir':6} {'iman abajo':>22} {'iman arriba':>22} {'R':>6}")
    for f in filas[-20:]:
        a = f["iman_abajo"]
        b = f["iman_arriba"]
        fa = f"{a['precio']:.0f} ({a['distancia_pct']:+.2f}%)" if a else "-"
        fb = f"{b['precio']:.0f} ({b['distancia_pct']:+.2f}%)" if b else "-"
        print(f"{str(f['key'])[:28]:28} {str(f['dir']):6} {fa:>22} {fb:>22} "
              f"{str(f['result_r']):>6}")


if __name__ == "__main__":
    main()
