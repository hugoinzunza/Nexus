#!/usr/bin/env python3
"""Re-lee TODOS los estudios sobre el universo que el bot realmente opera.

El detector del Diario (`modules/trading/smc_live.py`) usa POI_TFS = 1D/4h/1h.
**No hay 15m.** Y el bot es espejo del Diario. Pero el universo de research son 7
datasets de 1h y 3 de 15m, y como 15m genera ~2,5x más setups por par, la cuenta
real quedó 5.648 de 15m contra 2.257 de 1h: 71% contra 29%.

O sea los titulares que veníamos citando —los cortes ALL/OOS de cada estudio— son
promedios dominados por un timeframe que el bot no opera.

Importante, para no exagerar el problema: los datos SIEMPRE estuvieron. Casi todos
los estudios guardan el desglose por timeframe. Lo que estaba mal era la LECTURA,
no la validez, y la config del bot nunca estuvo equivocada. Este script no
recalcula nada: sólo vuelve a leer lo que ya se calculó, con el corte correcto.

Corre:   .venv/bin/python3 research/universo_operable.py
Escribe: research/universo_operable_results.json
"""
from __future__ import annotations

import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

RES = os.path.join(WT, "research")
OUT_JSON = os.path.join(RES, "universo_operable_results.json")

# Tres familias de estructura, porque los estudios se escribieron en momentos
# distintos. No las unifico: tocar los JSON viejos para que calcen sería reescribir
# resultados ya publicados.
FAMILIA_TABLES = (      # tables[tf][variante]["con_costos"]["OOS"]
    ("liq_tp", "liq_tp_results.json", ("tables",)),
    ("cdc", "cdc_results.json", ("modes", "fixed", "tables")),
    ("cdc_struct", "cdc_struct_results.json", ("tables",)),
    ("dealing_range", "dealing_range_results.json", ("tables",)),
    ("fractal_piv", "fractal_piv_results.json", ("tables",)),
)
FAMILIA_CORTES = (      # cortes["tf_1h_OOS"][combo]["avg_netR"]
    ("tp_magnet", "tp_magnet_study_results.json", "avg_netR"),
    ("sl_iman", "sl_iman_regimen_results.json", "avg_netR"),
    ("abort", "bta_visual_abort_results.json", "avg"),
)
FAMILIA_POR_TF = (      # cortes[modo]["por_tf"][tf]["avg"]
    ("replay_visual", "bta_visual_oos_results.json"),
)


def _cargar(nombre):
    with open(os.path.join(RES, nombre), encoding="utf-8") as fh:
        return json.load(fh)


def _bajar(d, ruta):
    for k in ruta:
        d = d[k]
    return d


def _norm(v):
    """Los estudios usan claves distintas para lo mismo. Devuelve (n, exp, dd)."""
    if not isinstance(v, dict):
        return None
    n = v.get("n") or v.get("trades")
    exp = v.get("avg_netR", v.get("expectancy_R", v.get("avg")))
    dd = v.get("dd_R", v.get("max_drawdown_R"))
    if n is None or exp is None:
        return None
    return {"n": n, "exp": round(float(exp), 3),
            "dd": round(float(dd), 1) if dd is not None else None}


def leer_tables(nombre_estudio, archivo, ruta):
    d = _bajar(_cargar(archivo), ruta)
    filas = []
    variantes = sorted({v for tf in d for v in d[tf]})
    for var in variantes:
        fila = {"estudio": nombre_estudio, "variante": var}
        for tf in ("1h", "15m"):
            o = d.get(tf, {}).get(var, {}).get("con_costos", {}).get("OOS")
            fila[tf] = _norm(o)
        if fila.get("1h") or fila.get("15m"):
            filas.append(fila)
    return filas


def leer_cortes(nombre_estudio, archivo, clave_exp):
    d = _cargar(archivo)["cortes"]
    a, b = d.get("tf_1h_OOS", {}), d.get("tf_15m_OOS", {})
    filas = []
    for var in sorted(set(a) | set(b)):
        if var.endswith("|desglose") or var.endswith("|ubicacion"):
            continue
        fila = {"estudio": nombre_estudio, "variante": var,
                "1h": _norm(a.get(var)), "15m": _norm(b.get(var))}
        if fila["1h"] or fila["15m"]:
            filas.append(fila)
    return filas


def leer_por_tf(nombre_estudio, archivo):
    d = _cargar(archivo)["cortes"]
    filas = []
    for modo, v in d.items():
        pt = v.get("por_tf") if isinstance(v, dict) else None
        if not pt:
            continue
        filas.append({"estudio": nombre_estudio, "variante": modo,
                      "1h": _norm(pt.get("1h")), "15m": _norm(pt.get("15m"))})
    return filas


def main():
    filas = []
    for nombre, archivo, ruta in FAMILIA_TABLES:
        filas += leer_tables(nombre, archivo, ruta)
    for nombre, archivo, clave in FAMILIA_CORTES:
        filas += leer_cortes(nombre, archivo, clave)
    for nombre, archivo in FAMILIA_POR_TF:
        filas += leer_por_tf(nombre, archivo)

    # el conteo que decide si el patrón es una regularidad o un corte afortunado
    pares = [f for f in filas if f["1h"] and f["15m"]]
    mejor_1h = sum(1 for f in pares if f["1h"]["exp"] > f["15m"]["exp"])
    pos_1h = sum(1 for f in pares if f["1h"]["exp"] > 0)
    pos_15m = sum(1 for f in pares if f["15m"]["exp"] > 0)

    salida = {
        "meta": {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "aviso": "Research only - No senal - No bot - NO usar para activar live",
            "pregunta": ("re-leer los estudios sobre el universo que el bot opera "
                         "(POI_TFS = 1D/4h/1h, sin 15m); no recalcula nada"),
            "universo_bot": ["1D", "4h", "1h"],
            "universo_research": "7 datasets 1h + 3 datasets 15m (71% de los setups son 15m)",
            "variantes_comparadas": len(pares),
        },
        "resumen": {
            "variantes_donde_1h_supera_a_15m": mejor_1h,
            "de_un_total_de": len(pares),
            "variantes_con_expectativa_positiva_en_1h": pos_1h,
            "variantes_con_expectativa_positiva_en_15m": pos_15m,
        },
        "filas": filas,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, indent=1)

    print(f"resultados: {OUT_JSON}\n")
    print(f"{'estudio':16} {'variante':22} {'n 1h':>6} {'exp 1h':>8} "
          f"{'n 15m':>6} {'exp 15m':>8}  {'':2}")
    ultimo = None
    for f in filas:
        if f["estudio"] != ultimo:
            print()
            ultimo = f["estudio"]
        a, b = f["1h"], f["15m"]
        marca = ""
        if a and b:
            marca = "1h mejor" if a["exp"] > b["exp"] else "15m mejor"
        print(f"{f['estudio']:16} {f['variante']:22} "
              f"{a['n'] if a else '-':>6} {a['exp'] if a else '-':>8} "
              f"{b['n'] if b else '-':>6} {b['exp'] if b else '-':>8}  {marca}")

    r = salida["resumen"]
    print(f"\n1h supera a 15m en {mejor_1h} de {len(pares)} variantes comparables")
    print(f"expectativa positiva: {pos_1h} variantes en 1h, {pos_15m} en 15m")


if __name__ == "__main__":
    main()
