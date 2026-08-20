#!/usr/bin/env python3
"""Auditoría READ-ONLY de los snapshots versionados de Bot3.v13.

Paso 2 del gate de despliegue: continuidad, hashes y provenance ANTES de
congelar `bootstrap_hasta`. No escribe nada, no toca el estado ni el libro.

    python3 tools/auditar_snapshots_bot3.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.bot3.v9 import runner as R                       # noqa: E402
from modules.bot3.v9.contract import GENESIS_H4, MERCADOS, TF_MS  # noqa: E402

CAMPOS = ("t", "o", "h", "l", "c", "v")


def f(ms: int) -> str:
    return dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def auditar(mercado: str, tf: str) -> dict:
    ruta = R.ruta_snapshot(R.ROOT, mercado, tf)
    r = {"mercado": mercado, "tf": tf, "ruta": ruta, "problemas": []}
    if not os.path.exists(ruta):
        r["problemas"].append("AUSENTE")
        return r
    filas = json.load(open(ruta, encoding="utf-8"))
    dur = TF_MS[tf]
    ts = [int(x["t"]) for x in filas]
    r.update(n=len(filas), desde=min(ts), hasta=max(ts),
             sha256=R.sha_snapshot(ruta),
             blob_git=R.blob_del_archivo(R.ROOT, ruta))

    if ts != sorted(ts):
        r["problemas"].append("no viene ordenado por `t`")
    if len(set(ts)) != len(ts):
        r["problemas"].append(f"{len(ts) - len(set(ts))} `t` duplicados")
    desalineadas = [t for t in ts if t % dur]
    if desalineadas:
        r["problemas"].append(f"{len(desalineadas)} velas fuera de la grilla")
    if tf == "4h" and min(ts) > GENESIS_H4:
        r["problemas"].append(f"empieza después de GENESIS_H4 ({f(GENESIS_H4)})")

    # continuidad: huecos respecto de la grilla del TF
    orden = sorted(set(ts))
    huecos = [(a + dur, b - dur) for a, b in zip(orden, orden[1:])
              if b - a != dur]
    r["huecos"] = huecos
    r["velas_faltantes"] = sum((b - a) // dur + 1 for a, b in huecos)

    for x in filas:                       # forma de cada vela
        if not all(k in x for k in CAMPOS):
            r["problemas"].append("velas sin todos los campos OHLCV")
            break
        if not (float(x["l"]) <= float(x["o"]) <= float(x["h"])
                and float(x["l"]) <= float(x["c"]) <= float(x["h"])):
            r["problemas"].append(f"OHLC incoherente en t={x['t']}")
            break

    # provenance: ¿el commit HEAD contiene ESTOS bytes?
    head = R.commit_actual(R.ROOT)
    if head:
        en_commit = R.blob_en_commit(R.ROOT, head, ruta)
        r["en_head"] = en_commit == r["blob_git"]
        if not r["en_head"]:
            r["problemas"].append(
                "los bytes en disco no son los del HEAD: sin commitear")
    return r


def main() -> int:
    head = R.commit_actual(R.ROOT)
    print(f"HEAD: {head}")
    sucio = subprocess.run(["git", "-C", R.ROOT, "status", "--porcelain", "--",
                            "data"], capture_output=True, text=True).stdout
    print(f"árbol de data/: {'SUCIO' if sucio.strip() else 'limpio'}\n")
    filas, malos = [], 0
    for mercado in MERCADOS:
        for tf in ("15m", "4h"):
            r = auditar(mercado, tf)
            filas.append(r)
            malos += bool(r["problemas"])
    ancho = "{:<10} {:<4} {:>7} {:>17} {:>17} {:>7} {:>9}"
    print(ancho.format("mercado", "tf", "velas", "desde", "hasta",
                       "huecos", "faltantes"))
    for r in filas:
        if "n" not in r:
            print(f"{r['mercado']:<10} {r['tf']:<4}  AUSENTE"); continue
        print(ancho.format(r["mercado"], r["tf"], r["n"], f(r["desde"]),
                           f(r["hasta"]), len(r["huecos"]),
                           r["velas_faltantes"]))
    print()
    for r in filas:
        if r["problemas"]:
            print(f"⚠ {r['mercado']} {r['tf']}: " + "; ".join(r["problemas"]))
        for a, b in r.get("huecos", [])[:3]:
            print(f"    hueco {f(a)} → {f(b)}")
        if len(r.get("huecos", [])) > 3:
            print(f"    … y {len(r['huecos']) - 3} huecos más")
    print("\nSHA-256 de cada snapshot (provenance del despliegue):")
    for r in filas:
        if "sha256" in r:
            print(f"  {r['mercado']:<10} {r['tf']:<4} {r['sha256']}")
    # el último cierre M15 COMÚN a los siete mercados: candidato a frontera
    finales = [r["hasta"] + TF_MS["15m"] for r in filas
               if r["tf"] == "15m" and "hasta" in r]
    if len(finales) == len(MERCADOS):
        print(f"\núltimo cierre M15 común a los {len(MERCADOS)} mercados: "
              f"{min(finales)}  ({f(min(finales))})")
    print(f"\n{'TODO EN ORDEN' if not malos else f'{malos} snapshots con problemas'}")
    return 1 if malos else 0


if __name__ == "__main__":
    raise SystemExit(main())
