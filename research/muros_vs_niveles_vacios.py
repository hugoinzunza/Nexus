#!/usr/bin/env python3
"""¿El precio reacciona distinto en un muro REAL que en un nivel vacío igual de lejos?

Es la premisa de toda la idea del imán, y hasta ahora nunca se probó directamente.
El estudio del imán (2026-07-25) aproximó los imanes con estructura de precio porque
el histórico de CoinGlass no es descargable; y el estudio de niveles reales quedó
atado a los setups del Diario, que produce ~2,6 setups de BTC por semana — años para
juntar muestra.

**El error de diseño era atarlo a los setups.** La pregunta no los necesita: cada
captura del libro trae ~40 muros, y hay 288 capturas al día. Son ~11.000
observaciones diarias en vez de 2,6 semanales.

DISEÑO PAREADO POR DISTANCIA. El confusor obvio es la distancia: los niveles cercanos
se tocan mucho más que los lejanos, y los muros no se reparten uniformemente. Así que
no se compara "con muro" contra "sin muro" a secas, sino **dentro del mismo bucket de
distancia y del mismo lado**: entre todas las capturas donde el precio tenía algo a
1,0-1,5% hacia arriba, ¿se comportó distinto cuando ahí había un muro?

DOS PREGUNTAS SEPARADAS, porque miden cosas opuestas:
  alcance   ¿el precio LLEGA al nivel? Un muro real debería frenarlo -> alcance MENOR.
  reaccion  si llega, ¿se devuelve? Es la afirmación del imán -> rebote MAYOR.
Si el muro subiera las dos, sería sospechoso: no se puede frenar más y ser tocado más.

INDEPENDENCIA. Las capturas consecutivas comparten los mismos muros (duran horas),
así que 11.000 observaciones NO son 11.000 datos. El CI se saca con bootstrap por
bloques contiguos de capturas, y aun así hay que leerlo con cuidado.

ANTI-LOOK-AHEAD: el resultado de una captura se mide sólo con capturas POSTERIORES.

Corre:   .venv/bin/python3 research/muros_vs_niveles_vacios.py
Escribe: research/muros_vs_niveles_vacios_results.json
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from core.paths import persist_dir  # noqa: E402

DATA = persist_dir(WT)
ARCHIVO = os.path.join(DATA, "coinglass_visual_book_archive.jsonl")
CALIENTE = os.path.join(DATA, "coinglass_visual_book_history.json")
OUT_JSON = os.path.join(WT, "research", "muros_vs_niveles_vacios_results.json")

# Bordes de los buckets de distancia, en % sobre el precio de la captura.
BUCKETS = ((0.25, 0.5), (0.5, 0.75), (0.75, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 3.0))
HORIZONTES = (12, 36)          # capturas de 5 min -> 1 h y 3 h
REBOTE_PCT = 0.3               # cuánto tiene que devolverse para contar como reacción
BLOQUE = 24                    # bloques de 2 h para el bootstrap
REMUESTREOS = 2000
MIN_USD = 500_000              # un "muro" por debajo de esto es ruido del scraping


def cargar_capturas():
    """Archivo histórico + ventana caliente, deduplicado y ordenado por tiempo."""
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
                    continue
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
    out = []
    for fila in por_stamp.values():
        try:
            when = dt.datetime.fromisoformat(
                str(fila["captured_at"]).replace("Z", "+00:00"))
        except (ValueError, TypeError, KeyError):
            continue
        if when.tzinfo is None or not fila.get("price"):
            continue
        out.append((when.timestamp(), fila))
    out.sort(key=lambda x: x[0])
    return [f for _, f in out]


def observaciones(capturas, horizonte):
    """Una fila por (captura, lado, bucket): si había muro y qué hizo el precio.

    El nivel evaluado es SIEMPRE el centro del bucket, tenga muro o no. Así el
    tratamiento es "había un muro cerca de este precio" y no "el muro estaba en un
    precio distinto del control", que sería comparar niveles diferentes.
    """
    filas = []
    for i, cap in enumerate(capturas):
        futuro = capturas[i + 1: i + 1 + horizonte]
        if len(futuro) < horizonte:
            break                          # sin futuro completo no se evalúa
        precio = float(cap["price"])
        if precio <= 0:
            continue
        muros = {
            "arriba": [(p, u) for p, u in (cap.get("asks") or [])
                       if p and u and u >= MIN_USD and p > precio],
            "abajo": [(p, u) for p, u in (cap.get("bids") or [])
                      if p and u and u >= MIN_USD and p < precio],
        }
        for lado in ("arriba", "abajo"):
            signo = 1 if lado == "arriba" else -1
            for lo, hi in BUCKETS:
                centro = precio * (1 + signo * (lo + hi) / 200)
                en_bucket = [
                    (p, u) for p, u in muros[lado]
                    if lo <= abs(p / precio - 1) * 100 < hi
                ]
                # ¿llegó el precio al centro del bucket?
                alcanzado, j_toque = False, None
                for j, f in enumerate(futuro):
                    p = float(f.get("price") or 0)
                    if not p:
                        continue
                    if (p >= centro) if lado == "arriba" else (p <= centro):
                        alcanzado, j_toque = True, j
                        break
                rebote = None
                if alcanzado:
                    # tras tocar, ¿se devolvió REBOTE_PCT en lo que queda de ventana?
                    objetivo = centro * (1 - signo * REBOTE_PCT / 100)
                    rebote = False
                    for f in futuro[j_toque + 1:]:
                        p = float(f.get("price") or 0)
                        if not p:
                            continue
                        if (p <= objetivo) if lado == "arriba" else (p >= objetivo):
                            rebote = True
                            break
                filas.append({
                    "i": i,
                    "lado": lado,
                    "bucket": f"{lo}-{hi}",
                    "hay_muro": bool(en_bucket),
                    "usd": sum(u for _, u in en_bucket),
                    "alcanzado": alcanzado,
                    "rebote": rebote,
                })
    return filas


def tasa(filas, campo):
    vals = [f[campo] for f in filas if f[campo] is not None]
    if not vals:
        return None
    return round(100 * sum(1 for v in vals if v) / len(vals), 1)


def bootstrap_dif(filas, campo, rng):
    """CI95 de la diferencia (con muro − sin muro), por bloques contiguos."""
    con = [f for f in filas if f["hay_muro"] and f[campo] is not None]
    sin = [f for f in filas if not f["hay_muro"] and f[campo] is not None]
    if len(con) < BLOQUE * 3 or len(sin) < BLOQUE * 3:
        return None

    def bloques(rows):
        rows = sorted(rows, key=lambda f: f["i"])
        return [rows[k:k + BLOQUE] for k in range(0, len(rows), BLOQUE)] or [[]]

    bc, bs = bloques(con), bloques(sin)
    difs = []
    for _ in range(REMUESTREOS):
        a = [x for _ in bc for x in bc[rng.randrange(len(bc))]]
        b = [x for _ in bs for x in bs[rng.randrange(len(bs))]]
        if not a or not b:
            continue
        difs.append(100 * (sum(1 for x in a if x[campo]) / len(a)
                           - sum(1 for x in b if x[campo]) / len(b)))
    if not difs:
        return None
    difs.sort()
    lo, hi = difs[int(.025 * len(difs))], difs[int(.975 * len(difs))]
    return {"dif_pp": round(sum(difs) / len(difs), 2),
            "ci95": [round(lo, 2), round(hi, 2)],
            "cruza_cero": lo <= 0 <= hi}


def main():
    rng = random.Random(20260725)
    capturas = cargar_capturas()

    salida = {
        "meta": {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "aviso": "Research only - No senal - No bot - NO usar para activar live",
            "pregunta": ("el precio reacciona distinto en un muro real que en un "
                         "nivel vacio a la misma distancia"),
            "diseno": ("pareado por bucket de distancia y lado; el nivel evaluado es "
                       "el centro del bucket tenga muro o no"),
            "min_usd_para_contar_como_muro": MIN_USD,
            "rebote_pct": REBOTE_PCT,
            "capturas": len(capturas),
            "independencia": ("capturas consecutivas comparten muros: el CI es por "
                              "bloques contiguos y aun asi hay que leerlo con cuidado"),
        },
        "por_horizonte": {},
    }

    if len(capturas) < max(HORIZONTES) + BLOQUE * 6:
        salida["meta"]["sin_datos_suficientes"] = True
        with open(OUT_JSON, "w", encoding="utf-8") as fh:
            json.dump(salida, fh, indent=1)
        faltan = max(HORIZONTES) + BLOQUE * 6 - len(capturas)
        print(f"capturas disponibles: {len(capturas)} — insuficientes.\n"
              f"Se necesitan al menos {max(HORIZONTES) + BLOQUE * 6}: faltan {faltan},\n"
              f"o sea ~{faltan * 5 / 60:.1f} horas de colector a 5 min por captura.\n\n"
              "El archivo local del VPS acumula solo; esto no es un error, es que\n"
              "todavia no hay historia suficiente. Vuelve a correrlo mas tarde.")
        return

    for h in HORIZONTES:
        filas = observaciones(capturas, h)
        bloque = {"n": len(filas), "global": {}, "por_bucket": {}}
        for campo in ("alcanzado", "rebote"):
            bloque["global"][campo] = {
                "con_muro": tasa([f for f in filas if f["hay_muro"]], campo),
                "sin_muro": tasa([f for f in filas if not f["hay_muro"]], campo),
                "bootstrap": bootstrap_dif(filas, campo, rng),
            }
        for lo, hi in BUCKETS:
            b = f"{lo}-{hi}"
            sel = [f for f in filas if f["bucket"] == b]
            bloque["por_bucket"][b] = {
                campo: {
                    "n_con": sum(1 for f in sel if f["hay_muro"]),
                    "n_sin": sum(1 for f in sel if not f["hay_muro"]),
                    "con_muro": tasa([f for f in sel if f["hay_muro"]], campo),
                    "sin_muro": tasa([f for f in sel if not f["hay_muro"]], campo),
                }
                for campo in ("alcanzado", "rebote")
            }
        salida["por_horizonte"][str(h)] = bloque

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, indent=1)

    print(f"resultados: {OUT_JSON}")
    print(f"capturas: {len(capturas)}\n")
    for h in HORIZONTES:
        b = salida["por_horizonte"][str(h)]
        print(f"=== horizonte {h} capturas ({h*5} min) · n={b['n']} ===")
        for campo in ("alcanzado", "rebote"):
            g = b["global"][campo]
            bs = g["bootstrap"]
            ci = (f"dif {bs['dif_pp']:+.2f} pp CI95 [{bs['ci95'][0]:+.2f}, "
                  f"{bs['ci95'][1]:+.2f}]"
                  + ("  cruza cero" if bs["cruza_cero"] else "  NO cruza cero")
                  ) if bs else "sin CI"
            print(f"  {campo:10} con muro {g['con_muro']}%  sin muro {g['sin_muro']}%   {ci}")
        print(f"  {'bucket':12} {'alc con':>8} {'alc sin':>8} {'reb con':>8} {'reb sin':>8}")
        for lo, hi in BUCKETS:
            d = b["por_bucket"][f"{lo}-{hi}"]
            print(f"  {f'{lo}-{hi}%':12} {str(d['alcanzado']['con_muro']):>8} "
                  f"{str(d['alcanzado']['sin_muro']):>8} "
                  f"{str(d['rebote']['con_muro']):>8} "
                  f"{str(d['rebote']['sin_muro']):>8}")
        print()


if __name__ == "__main__":
    main()
