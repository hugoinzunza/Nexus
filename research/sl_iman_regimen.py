#!/usr/bin/env python3
"""¿Por qué el SL "tras el imán opuesto" ayuda en OOS y falla en 2024 y en 1h?

Viene de `tp_magnet_study.py` (2026-07-25). Ahí quedó que la mitad TP de la idea
está refutada y que la mitad SL —correr el stop apenas más allá del imán opuesto
más cercano— baja el drawdown entre 22% y 54% pero cambia de signo según el corte.
El informe dejó escrito el próximo paso: si eso es régimen, la mejora es prestada.

Este estudio no busca confirmar nada; busca romperlo. Tres ataques:

1. IDENTIDAD CONTABLE. Ensanchar el stop no puede convertir un ganador en perdedor
   (el camino de precios es el mismo y el stop nuevo está más lejos), así que toda
   la diferencia de P&L se descompone EXACTAMENTE en tres términos:
     rescate    el stop estructural moría y el ancho aguanta hasta el TP  -> gana
     dilucion   los dos ganan, pero el ancho arriesga más y cobra menos R -> pierde
     ahorro     los dos mueren; el ancho paga menos costo relativo (el costo
                se divide por el % de SL, y el % es mayor)                -> gana poco
   Si el balance falla en 2024, tiene que ser porque dilucion > rescate. Eso es
   medible, no opinable. El script verifica que la identidad cierre.

2. PLACEBO. El control que puede matar la idea entera: quizá el imán no aporta nada
   y lo único que pasa es que un stop más ancho aguanta más. Se construye un stop
   con la MISMA distribución de ensanche pero barajada entre setups (mismo par y
   timeframe), o sea mismo riesgo típico y misma dilución, pero puesto en un precio
   que no es el imán de ese setup. Si el placebo empata con `tras_iman`, el nivel
   es decorativo.

3. RÉGIMEN. Se mide, corte por corte, si el signo del efecto es función de la tasa
   base de stop-out del baseline. Si la correlación es alta, `tras_iman` no es una
   mejora: es una apuesta a que el régimen siga siendo el de los cortes buenos.

Asimetría real que hay que declarar: con el stop más ancho un trade puede tardar
más en resolver y quedar fuera de SIM_MAX donde el estrecho sí resolvía. Se cuenta
aparte (`sin_resolver`) y la comparación pareada usa solo setups donde resuelven
los tres stops.

Anti-look-ahead: heredado de tp_magnet_study (pivotes con confirm_idx, niveles no
barridos al momento del toque, SL y TP en la misma vela = SL, costos maker-aware).

Corre:   .venv/bin/python3 research/sl_iman_regimen.py
Escribe: research/sl_iman_regimen_results.json
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import os
import random
import sys
from collections import defaultdict

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading.strategies import detect_pois  # noqa: E402
from research import bta_visual_oos as oos  # noqa: E402
from research import tp_magnet_study as magnet  # noqa: E402

OUT_JSON = os.path.join(WT, "research", "sl_iman_regimen_results.json")
SEMILLA = 20260725       # placebo reproducible
BLOQUE = 30              # bootstrap por bloques contiguos de setups
REMUESTREOS = 2000
VARIANTES_SL = ("estructural", "tras_iman", "placebo")
VARIANTES_TP = ("lejano", "cercano")


def recolectar(pair, tf):
    """Setups con entry, TPs y los dos stops candidatos, sin resolver todavía.

    Se separa de la resolución porque el placebo necesita conocer la distribución
    completa de ensanches del par antes de poder asignar los factores barajados.
    """
    path = os.path.join(oos.DATA_DIR, f"klines_{pair}_{tf}.json")
    candles = json.load(open(path))
    n = len(candles)
    pivrows = oos.pivot_rows(candles, oos.LEG_PIV)
    t_by_idx = [c["t"] for c in candles]
    filas = []

    for poi in detect_pois(candles, oos.POI_PIV, oos.POI_DISP):
        long = poi["dir"] == "long"
        lo, hi = poi["lo"], poi["hi"]
        stop_estr = (poi["stop"] * (1 - oos.BUFFER) if long
                     else poi["stop"] * (1 + oos.BUFFER))
        i_conf = bisect.bisect_left(t_by_idx, poi["t_conf"])

        i_tap = None
        for j in range(i_conf + 1, min(i_conf + 1 + oos.TAP_MAX, n)):
            c = candles[j]
            if (c["c"] < stop_estr) if long else (c["c"] > stop_estr):
                break
            if c["l"] <= hi and c["h"] >= lo:
                i_tap = j
                break
        if i_tap is None:
            continue

        entry = hi if long else lo
        t_tap = candles[i_tap]["t"]
        favor = magnet.imanes(pivrows, long, entry, t_tap, entry)
        contra = magnet.imanes(pivrows, not long, entry, t_tap, entry)
        if not favor:
            continue

        riesgo_estr = (entry - stop_estr) if long else (stop_estr - entry)
        if riesgo_estr <= 0:
            continue

        if contra:
            sl_iman = (min(stop_estr, contra[0] * (1 - oos.BUFFER)) if long
                       else max(stop_estr, contra[0] * (1 + oos.BUFFER)))
        else:
            sl_iman = stop_estr
        riesgo_iman = (entry - sl_iman) if long else (sl_iman - entry)

        filas.append({
            "pair": pair, "tf": tf, "dir": poi["dir"], "t": t_tap, "i_tap": i_tap,
            "entry": entry, "long": long,
            "tp": {"lejano": favor[-1], "cercano": favor[0]},
            "sl": {"estructural": stop_estr, "tras_iman": sl_iman},
            # >1 significa stop más ancho; ==1 significa que el imán no movió nada
            "ensanche": riesgo_iman / riesgo_estr,
        })
    return candles, filas


def asignar_placebo(filas, rng):
    """Stop con la misma distribución de ensanche pero desacoplada del setup.

    Solo se barajan los ensanches que efectivamente movieron el stop: si se
    incluyeran los 1.0 el placebo quedaría más estrecho en promedio que
    `tras_iman` y la comparación mediría el ancho, no la ubicación.
    """
    factores = [f["ensanche"] for f in filas if f["ensanche"] > 1.0]
    if not factores:
        for f in filas:
            f["sl"]["placebo"] = f["sl"]["estructural"]
        return 0
    barajados = list(factores)
    rng.shuffle(barajados)
    k = 0
    for f in filas:
        if f["ensanche"] <= 1.0:
            f["sl"]["placebo"] = f["sl"]["estructural"]
            continue
        factor = barajados[k % len(barajados)]
        k += 1
        entry, estr = f["entry"], f["sl"]["estructural"]
        riesgo = (entry - estr) if f["long"] else (estr - entry)
        f["sl"]["placebo"] = (entry - riesgo * factor if f["long"]
                              else entry + riesgo * factor)
    return k


def resolver(candles, filas):
    """Resuelve cada setup con las 3 variantes de stop x 2 de TP."""
    for f in filas:
        f["res"] = {}
        f["falta"] = {}
        for nombre_tp in VARIANTES_TP:
            tp = f["tp"][nombre_tp]
            for nombre_sl in VARIANTES_SL:
                sl = f["sl"][nombre_sl]
                clave = f"{nombre_tp}|{nombre_sl}"
                riesgo = (f["entry"] - sl) if f["long"] else (sl - f["entry"])
                if riesgo <= 0:
                    f["falta"][clave] = "riesgo_invalido"
                    continue
                rr = abs(tp - f["entry"]) / riesgo
                if rr < magnet.MIN_RR:
                    # ensanchar el stop achica el rr: este setup se cae del universo
                    # por el filtro, no por no haber resuelto. Se cuenta aparte.
                    f["falta"][clave] = "descartado_rr"
                    continue
                r, _ = oos.resolve(candles, f["i_tap"], f["long"], f["entry"], sl, tp)
                if r is None:
                    f["falta"][clave] = "sin_resolver"
                    continue
                f["res"][clave] = {
                    "netR": oos.netR(r, f["entry"], sl),
                    "rr": rr,
                    "gano": r > 0,
                }


def clasificar(f, nombre_tp, variante):
    """Etiqueta el par (estructural, variante) para la identidad contable."""
    a = f["res"].get(f"{nombre_tp}|estructural")
    b = f["res"].get(f"{nombre_tp}|{variante}")
    if a is None or b is None:
        # el motivo importa: "descartado_rr" es selección (el ensanche mata el rr),
        # "sin_resolver" es truncamiento de la simulación. Conflatearlos esconde sesgo.
        motivo = (f["falta"].get(f"{nombre_tp}|{variante}")
                  or f["falta"].get(f"{nombre_tp}|estructural") or "sin_resolver")
        return motivo, 0.0
    delta = b["netR"] - a["netR"]
    if f["ensanche"] <= 1.0 and variante == "tras_iman":
        return "sin_cambio", delta
    if not a["gano"] and b["gano"]:
        return "rescate", delta
    if a["gano"] and b["gano"]:
        return "dilucion", delta
    if not a["gano"] and not b["gano"]:
        return "ahorro", delta
    # ensanchar el stop no puede convertir ganador en perdedor: si esto aparece,
    # el modelo de resolución tiene un error y hay que mirarlo, no promediarlo.
    return "imposible", delta


def agrega(valores):
    if not valores:
        return {"n": 0}
    n = len(valores)
    netos = [v["netR"] for v in valores]
    eq = pico = dd = 0.0
    for v in netos:
        eq += v
        pico = max(pico, eq)
        dd = max(dd, pico - eq)
    return {
        "n": n,
        "gana_pct": round(100 * sum(1 for v in valores if v["gano"]) / n, 1),
        "avg_netR": round(sum(netos) / n, 3),
        "dd_R": round(dd, 1),
        "rr_medio": round(sum(v["rr"] for v in valores) / n, 2),
    }


def bootstrap_pareado(deltas, rng):
    """CI del delta medio por bloques contiguos (los setups no son independientes)."""
    if len(deltas) < BLOQUE * 2:
        return None
    bloques = [deltas[i:i + BLOQUE] for i in range(0, len(deltas), BLOQUE)]
    bloques = [b for b in bloques if b]
    medias = []
    for _ in range(REMUESTREOS):
        muestra = []
        for _ in range(len(bloques)):
            muestra.extend(bloques[rng.randrange(len(bloques))])
        medias.append(sum(muestra) / len(muestra))
    medias.sort()
    lo = medias[int(0.025 * len(medias))]
    hi = medias[int(0.975 * len(medias))]
    return {
        "delta_medio": round(sum(deltas) / len(deltas), 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "cruza_cero": lo <= 0 <= hi,
    }


def spearman(xs, ys):
    """Correlación de rangos. Suficiente para "el signo sigue al régimen"."""
    n = len(xs)
    if n < 4:
        return None

    def rangos(v):
        orden = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[orden[j + 1]] == v[orden[i]]:
                j += 1
            medio = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[orden[k]] = medio
            i = j + 1
        return r

    rx, ry = rangos(xs), rangos(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx * dy < 1e-9:
        return None
    return round(num / (dx * dy), 3)


def main():
    rng = random.Random(SEMILLA)
    todas = []
    cambiados_total = 0
    for pair, tf in oos.DATASETS:
        if not os.path.isfile(os.path.join(oos.DATA_DIR, f"klines_{pair}_{tf}.json")):
            continue
        candles, filas = recolectar(pair, tf)
        # el placebo se baraja DENTRO de cada par+tf: los ensanches de BTC 1h no son
        # comparables con los de DOGE 15m
        cambiados_total += asignar_placebo(filas, rng)
        resolver(candles, filas)
        todas.extend(filas)
        print(f"  {pair} {tf}: {len(filas)} setups")

    todas.sort(key=lambda f: f["t"])
    corte = todas[int(len(todas) * magnet.IS_FRAC)]["t"] if todas else 0
    for f in todas:
        f["oos"] = f["t"] > corte
        f["year"] = dt.datetime.utcfromtimestamp(f["t"] / 1000).year

    cortes = {"TODO": todas, "IS": [f for f in todas if not f["oos"]],
              "OOS": [f for f in todas if f["oos"]]}
    for tf in ("1h", "15m"):
        cortes[f"tf_{tf}"] = [f for f in todas if f["tf"] == tf]
        cortes[f"tf_{tf}_OOS"] = [f for f in todas if f["tf"] == tf and f["oos"]]
    for y in sorted({f["year"] for f in todas}):
        cortes[f"ano_{y}"] = [f for f in todas if f["year"] == y]

    salida = {
        "meta": {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "aviso": "Research only - No senal - No bot - NO usar para activar live",
            "pregunta": ("por que el SL tras el iman opuesto ayuda en OOS y falla "
                         "en 2024 y en 1h: rescate vs dilucion, placebo y regimen"),
            "viene_de": "research/tp_magnet_study_2026-07-25.md",
            "setups": len(todas),
            "stops_movidos_por_el_iman": cambiados_total,
            "corte_oos": (dt.datetime.utcfromtimestamp(corte / 1000).isoformat()
                          if corte else None),
            "semilla_placebo": SEMILLA,
            "bloque_bootstrap": BLOQUE,
        },
        "cortes": {},
        "regimen": {},
    }

    anomalias = 0
    for nombre, sel in cortes.items():
        bloque = {}
        for nombre_tp in VARIANTES_TP:
            for nombre_sl in VARIANTES_SL:
                clave = f"{nombre_tp}|{nombre_sl}"
                bloque[clave] = agrega([f["res"][clave] for f in sel
                                        if clave in f["res"]])
            # descomposición pareada contra el estructural
            for variante in ("tras_iman", "placebo"):
                conteo = defaultdict(int)
                suma = defaultdict(float)
                deltas = []
                for f in sel:
                    etiqueta, delta = clasificar(f, nombre_tp, variante)
                    conteo[etiqueta] += 1
                    suma[etiqueta] += delta
                    if etiqueta == "imposible":
                        anomalias += 1
                    if etiqueta in ("rescate", "dilucion", "ahorro", "sin_cambio"):
                        deltas.append(delta)
                bloque[f"{nombre_tp}|{variante}|desglose"] = {
                    "conteo": dict(conteo),
                    "aporte_R": {k: round(v, 2) for k, v in suma.items()},
                    "delta_total_R": round(sum(deltas), 2),
                    "bootstrap": bootstrap_pareado(deltas, rng),
                }
            # EFECTO UBICACIÓN: imán contra placebo del mismo ancho típico. Esto
            # aísla lo que aporta el NIVEL, sin el efecto de "stop más ancho aguanta
            # más" que ya está en los dos. Acá no aplica rescate/dilución porque el
            # placebo puede caer más cerca o más lejos que el imán, no es monótono.
            ka, kb = f"{nombre_tp}|placebo", f"{nombre_tp}|tras_iman"
            ubic = [f["res"][kb]["netR"] - f["res"][ka]["netR"] for f in sel
                    if ka in f["res"] and kb in f["res"]]
            bloque[f"{nombre_tp}|ubicacion"] = {
                "n_pareado": len(ubic),
                "delta_total_R": round(sum(ubic), 2),
                "bootstrap": bootstrap_pareado(ubic, rng),
            }
        salida["cortes"][nombre] = bloque

    # ¿el signo del efecto sigue a la tasa base de stop-out?
    puntos = []
    for nombre, sel in cortes.items():
        if nombre in ("TODO", "IS", "OOS"):
            continue          # cortes anidados: sesgarían la correlación
        base = agrega([f["res"]["lejano|estructural"] for f in sel
                       if "lejano|estructural" in f["res"]])
        if not base.get("n") or base["n"] < 50:
            continue
        des = salida["cortes"][nombre]["lejano|tras_iman|desglose"]
        ubic = salida["cortes"][nombre]["lejano|ubicacion"]
        movidos = [f["ensanche"] for f in sel if f["ensanche"] > 1.0]
        c = des["conteo"]
        puntos.append({
            "corte": nombre,
            "n": base["n"],
            "stopout_pct": round(100 - base["gana_pct"], 1),
            "ensanche_medio": round(sum(movidos) / len(movidos), 3) if movidos else 1.0,
            "frac_movidos": round(len(movidos) / len(sel), 3) if sel else 0.0,
            "rescate_por_dilucion": round(c.get("rescate", 0)
                                          / max(1, c.get("dilucion", 0)), 2),
            "delta_avg_R": round(des["delta_total_R"] / max(1, base["n"]), 4),
            "ubicacion_avg_R": round(ubic["delta_total_R"]
                                     / max(1, ubic["n_pareado"]), 4),
        })
    salida["regimen"] = {
        "puntos": puntos,
        "spearman_stopout_vs_delta": spearman([p["stopout_pct"] for p in puntos],
                                              [p["delta_avg_R"] for p in puntos]),
        "spearman_ensanche_vs_delta": spearman([p["ensanche_medio"] for p in puntos],
                                               [p["delta_avg_R"] for p in puntos]),
        "spearman_frac_movidos_vs_delta": spearman([p["frac_movidos"] for p in puntos],
                                                   [p["delta_avg_R"] for p in puntos]),
        # la pregunta que decide todo: el efecto del NIVEL, ¿también es régimen?
        "spearman_stopout_vs_ubicacion": spearman([p["stopout_pct"] for p in puntos],
                                                  [p["ubicacion_avg_R"] for p in puntos]),
    }
    salida["meta"]["anomalias_ganador_a_perdedor"] = anomalias

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, indent=1, default=str)

    print(f"\nresultados: {OUT_JSON}")
    print(f"setups: {len(todas)} · stops movidos por el iman: {cambiados_total}")
    print(f"anomalias ganador->perdedor: {anomalias} (deben ser 0)\n")

    for nombre in ("TODO", "OOS", "tf_1h", "tf_1h_OOS", "ano_2024", "ano_2026"):
        if nombre not in salida["cortes"]:
            continue
        b = salida["cortes"][nombre]
        print(f"=== {nombre} ===")
        print(f"  {'combo':26} {'n':>5} {'gana':>7} {'avgR':>8} {'DD':>7}")
        for clave in (f"{tp}|{sl}" for tp in VARIANTES_TP for sl in VARIANTES_SL):
            d = b[clave]
            if not d.get("n"):
                continue
            print(f"  {clave:26} {d['n']:5} {d['gana_pct']:6.1f}% "
                  f"{d['avg_netR']:+8.3f} {d['dd_R']:7.1f}")
        for variante in ("tras_iman", "placebo"):
            des = b[f"lejano|{variante}|desglose"]
            c, a = des["conteo"], des["aporte_R"]
            bs = des["bootstrap"]
            ci = (f"CI95 [{bs['ci95'][0]:+.3f}, {bs['ci95'][1]:+.3f}]"
                  + ("  cruza cero" if bs["cruza_cero"] else "  NO cruza cero")
                  ) if bs else "sin CI"
            print(f"  lejano vs {variante}: total {des['delta_total_R']:+.1f}R · {ci}")
            print(f"    rescate {c.get('rescate', 0)} ({a.get('rescate', 0):+.1f}R) · "
                  f"dilucion {c.get('dilucion', 0)} ({a.get('dilucion', 0):+.1f}R) · "
                  f"ahorro {c.get('ahorro', 0)} ({a.get('ahorro', 0):+.1f}R) · "
                  f"sin_cambio {c.get('sin_cambio', 0)}")
            print(f"    excluidos: descartado_rr {c.get('descartado_rr', 0)} · "
                  f"sin_resolver {c.get('sin_resolver', 0)}")
        u = b["lejano|ubicacion"]
        bs = u["bootstrap"]
        ci = (f"CI95 [{bs['ci95'][0]:+.3f}, {bs['ci95'][1]:+.3f}]"
              + ("  cruza cero" if bs["cruza_cero"] else "  NO cruza cero")
              ) if bs else "sin CI"
        print(f"  UBICACION (iman - placebo, mismo ancho): "
              f"{u['delta_total_R']:+.1f}R en {u['n_pareado']} pareados · {ci}")
        print()

    print("=== regimen (el signo sigue a la tasa de stop-out?) ===")
    print(f"  {'corte':16} {'n':>5} {'stopout':>8} {'ensanche':>9} "
          f"{'resc/dil':>9} {'deltaR':>8} {'ubicR':>8}")
    for p in sorted(puntos, key=lambda p: p["delta_avg_R"]):
        print(f"  {p['corte']:16} {p['n']:5} {p['stopout_pct']:7.1f}% "
              f"{p['ensanche_medio']:9.3f} {p['rescate_por_dilucion']:9.2f} "
              f"{p['delta_avg_R']:+8.4f} {p['ubicacion_avg_R']:+8.4f}")
    r = salida["regimen"]
    print(f"\n  spearman stopout vs delta:       {r['spearman_stopout_vs_delta']}")
    print(f"  spearman ensanche vs delta:      {r['spearman_ensanche_vs_delta']}")
    print(f"  spearman %movidos vs delta:      {r['spearman_frac_movidos_vs_delta']}")
    print(f"  spearman stopout vs UBICACION:   {r['spearman_stopout_vs_ubicacion']}")


if __name__ == "__main__":
    main()
