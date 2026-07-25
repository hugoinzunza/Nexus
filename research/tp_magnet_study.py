#!/usr/bin/env python3
"""¿Conviene poner el TP en el imán REAL en vez de un objetivo lejano teórico?

Idea de Hugo (2026-07-25): la dirección ya la da la estrategia SMC. Lo que falta
es estimar **hasta dónde puede llegar el precio antes de girar** para poner TP y SL
ahí, en vez de esperar un TP teórico (tipo "TP4") que nunca llega porque el precio
solo iba a buscar una orden en un precio X y se dio la vuelta.

Restricción de datos: el mapa de liquidaciones y la profundidad histórica del libro
NO son descargables con el plan API actual (sondeo 2026-07-25: 401 "Upgrade plan").
Así que el imán se aproxima con estructura de PRECIO —pivotes confirmados y no
barridos, y clústers de pivotes— que es el mismo concepto: dónde hay órdenes
esperando. La versión con niveles reales de CoinGlass solo se podrá validar hacia
adelante, cuando el colector acumule.

VARIANTES DE TP (todas sobre el MISMO universo de setups, comparación pareada):
  lejano        el pivote no barrido más LEJANO dentro del radio -> proxy del "TP4"
  cercano       el pivote no barrido más cercano  (lo que hace el plan hoy)
  cluster       el clúster de pivotes más DENSO   (el imán real: donde hay masa)
  alcance_p35   cap a la distancia que el precio recorre >=35% de las veces
  fijo_2r       control: múltiplo fijo 2R. La evidencia previa (playbook 06-30)
                dice que capar a múltiplo fijo destruye el edge; se incluye para
                verificar que el estudio reproduce ese resultado conocido.

VARIANTES DE SL:
  estructural   stop del POI + buffer (el actual)
  tras_iman     stop apenas MÁS ALLÁ del imán opuesto más cercano, para no morir
                justo antes del nivel que iba a frenar el precio

Métrica clave, la que responde la hipótesis: **tasa de llenado del TP**. Si el TP
lejano se llena 8% de las veces y el cercano 40%, el objetivo teórico es el problema.

Anti-look-ahead: pivotes con confirm_idx, niveles no barridos AL MOMENTO del toque,
resolución intrabar conservadora (SL y TP en la misma vela = SL), costos maker-aware.

Corre:   .venv/bin/python3 research/tp_magnet_study.py
Escribe: research/tp_magnet_study_results.json
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import defaultdict

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading.strategies import detect_pois  # noqa: E402
from research import bta_visual_oos as oos  # noqa: E402

OUT_JSON = os.path.join(WT, "research", "tp_magnet_study_results.json")
RADIO_PCT = 8.0          # radio donde se buscan imanes (más allá no es "alcanzable")
CLUSTER_TOL = 0.0025     # 0,25%: pivotes dentro de esta banda son el mismo imán
ALCANCE_P = 0.35         # el cap "alcance_p35": distancia alcanzada >=35% del tiempo
IS_FRAC = 0.70
MIN_RR = 1.0

VARIANTES_TP = ("lejano", "cercano", "cluster", "alcance_p35", "fijo_2r")
VARIANTES_SL = ("estructural", "tras_iman")


def imanes(pivrows, long, ref, t, precio):
    """Niveles no barridos, visibles en `t`, dentro del radio y en la dirección."""
    lado = "high" if long else "low"
    fuera = []
    for r in pivrows:
        if r["side"] != lado or r["confirm_t"] > t:
            continue
        if r["swept_t"] is not None and r["swept_t"] <= t:
            continue
        if long and r["price"] <= ref:
            continue
        if not long and r["price"] >= ref:
            continue
        if abs(r["price"] / precio - 1) * 100 > RADIO_PCT:
            continue
        fuera.append(r["price"])
    return sorted(fuera) if long else sorted(fuera, reverse=True)


def cluster_mas_denso(niveles, precio):
    """Agrupa niveles cercanos y devuelve el centro del grupo con MÁS pivotes.

    Es el análogo de precio a un clúster de liquidaciones o una pared del libro:
    no importa un nivel suelto, importa dónde se acumula la masa. Ante empate en
    cantidad gana el grupo más cercano al precio (llega antes).
    """
    if not niveles:
        return None
    grupos = []
    actual = [niveles[0]]
    for p in niveles[1:]:
        if abs(p / actual[-1] - 1) <= CLUSTER_TOL:
            actual.append(p)
        else:
            grupos.append(actual)
            actual = [p]
    grupos.append(actual)
    mejor = max(grupos, key=lambda g: (len(g), -abs(g[0] / precio - 1)))
    return sum(mejor) / len(mejor)


def percentil_alcance(candles, h_barras, p):
    """Distancia (en %) que el precio recorre al menos `p` del tiempo en h barras.

    Es la tasa base del propio par, no una constante inventada. Se usa para no
    apuntar más lejos de lo que ese activo suele alcanzar.
    """
    exc = []
    for i in range(len(candles) - h_barras):
        base = candles[i]["c"]
        if not base:
            continue
        tramo = candles[i + 1:i + 1 + h_barras]
        if not tramo:
            continue
        exc.append(max(max(abs(c["h"] / base - 1), abs(c["l"] / base - 1))
                       for c in tramo) * 100)
    if not exc:
        return None
    exc.sort()
    # el valor tal que una fracción p de las observaciones lo supera
    idx = int(len(exc) * (1 - p))
    return exc[min(idx, len(exc) - 1)]


def estudiar(pair, tf, horizonte_barras=12):
    path = os.path.join(oos.DATA_DIR, f"klines_{pair}_{tf}.json")
    candles = json.load(open(path))
    n = len(candles)
    pivrows = oos.pivot_rows(candles, oos.LEG_PIV)
    t_by_idx = [c["t"] for c in candles]
    import bisect

    cap_alcance = percentil_alcance(candles, horizonte_barras, ALCANCE_P)
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
        favor = imanes(pivrows, long, entry, t_tap, entry)
        contra = imanes(pivrows, not long, entry, t_tap, entry)
        if not favor:
            continue

        objetivos = {
            "cercano": favor[0],
            "lejano": favor[-1],
            "cluster": cluster_mas_denso(favor, entry),
        }
        if cap_alcance:
            limite = entry * (1 + cap_alcance / 100) if long else entry * (1 - cap_alcance / 100)
            base = objetivos["cercano"]
            objetivos["alcance_p35"] = min(base, limite) if long else max(base, limite)

        stops = {"estructural": stop_estr}
        if contra:
            # stop apenas más allá del imán opuesto: si ese nivel iba a frenar el
            # precio, morir antes de llegar es perder por colocación, no por tesis.
            stops["tras_iman"] = (min(stop_estr, contra[0] * (1 - oos.BUFFER)) if long
                                  else max(stop_estr, contra[0] * (1 + oos.BUFFER)))
        else:
            stops["tras_iman"] = stop_estr

        fila = {"pair": pair, "tf": tf, "dir": poi["dir"], "t": t_tap}
        for nombre_sl, sl in stops.items():
            riesgo = (entry - sl) if long else (sl - entry)
            if riesgo <= 0:
                continue
            objetivos["fijo_2r"] = entry + 2 * riesgo if long else entry - 2 * riesgo
            for nombre_tp in VARIANTES_TP:
                tp = objetivos.get(nombre_tp)
                if tp is None:
                    continue
                rr = abs(tp - entry) / riesgo
                if rr < MIN_RR:
                    continue
                r, j_fin = oos.resolve(candles, i_tap, long, entry, sl, tp)
                if r is None:
                    continue
                fila[f"{nombre_tp}|{nombre_sl}"] = {
                    "netR": round(oos.netR(r, entry, sl), 3),
                    "rr": round(rr, 2),
                    "gano": r > 0,
                }
        if len(fila) > 4:
            filas.append(fila)
    return filas


def agrega(valores):
    if not valores:
        return {"n": 0}
    n = len(valores)
    netos = [v["netR"] for v in valores]
    tp_llenado = sum(1 for v in valores if v["gano"]) / n
    eq = pico = dd = 0.0
    for v in netos:
        eq += v
        pico = max(pico, eq)
        dd = max(dd, pico - eq)
    return {
        "n": n,
        "tp_llenado_pct": round(100 * tp_llenado, 1),
        "avg_netR": round(sum(netos) / n, 3),
        "total_netR": round(sum(netos), 1),
        "rr_medio": round(sum(v["rr"] for v in valores) / n, 2),
        "dd_R": round(dd, 1),
    }


def main():
    filas = []
    for pair, tf in oos.DATASETS:
        if not os.path.isfile(os.path.join(oos.DATA_DIR, f"klines_{pair}_{tf}.json")):
            continue
        r = estudiar(pair, tf)
        filas.extend(r)
        print(f"  {pair} {tf}: {len(r)} setups")
    filas.sort(key=lambda f: f["t"])
    corte = filas[int(len(filas) * IS_FRAC)]["t"] if filas else 0
    for f in filas:
        f["oos"] = f["t"] > corte
        f["year"] = dt.datetime.utcfromtimestamp(f["t"] / 1000).year

    combos = [f"{tp}|{sl}" for sl in VARIANTES_SL for tp in VARIANTES_TP]
    resultado = {
        "meta": {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "aviso": "Research only - No senal - No bot - NO usar para activar live",
            "idea": ("TP en el iman real en vez de objetivo lejano teorico; el iman "
                     "se aproxima con estructura de precio porque el mapa historico "
                     "de CoinGlass no es descargable con el plan actual"),
            "setups": len(filas),
            "corte_oos": dt.datetime.utcfromtimestamp(corte / 1000).isoformat() if corte else None,
            "radio_pct": RADIO_PCT, "cluster_tol": CLUSTER_TOL, "alcance_p": ALCANCE_P,
        },
        "cortes": {},
    }

    def bloque(sel):
        return {c: agrega([f[c] for f in sel if c in f]) for c in combos}

    resultado["cortes"]["TODO"] = bloque(filas)
    resultado["cortes"]["IS"] = bloque([f for f in filas if not f["oos"]])
    resultado["cortes"]["OOS"] = bloque([f for f in filas if f["oos"]])
    for tf in ("1h", "15m"):
        resultado["cortes"][f"tf_{tf}"] = bloque([f for f in filas if f["tf"] == tf])
        resultado["cortes"][f"tf_{tf}_OOS"] = bloque(
            [f for f in filas if f["tf"] == tf and f["oos"]])
    for y in sorted({f["year"] for f in filas}):
        resultado["cortes"][f"ano_{y}"] = bloque([f for f in filas if f["year"] == y])
    por_par = defaultdict(list)
    for f in filas:
        por_par[f["pair"]].append(f)
    for p, rows in por_par.items():
        resultado["cortes"][f"par_{p}_OOS"] = bloque([f for f in rows if f["oos"]])

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(resultado, fh, indent=1, default=str)
    print(f"\nresultados: {OUT_JSON}\n")
    for nombre in ("TODO", "IS", "OOS", "tf_1h_OOS"):
        print(f"=== {nombre} ===")
        print(f"  {'combo':24} {'n':>5} {'TP lleno':>9} {'avgR':>8} {'rr medio':>9} {'DD':>7}")
        for c in combos:
            d = resultado["cortes"][nombre][c]
            if not d.get("n"):
                continue
            print(f"  {c:24} {d['n']:5} {d['tp_llenado_pct']:8.1f}% "
                  f"{d['avg_netR']:+8.3f} {d['rr_medio']:9.2f} {d['dd_R']:7.1f}")
        print()


if __name__ == "__main__":
    main()
