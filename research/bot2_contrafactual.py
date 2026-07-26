#!/usr/bin/env python3
"""BOT2: evaluador contrafactual de reglas CoinGlass sobre los setups de BOT1.

NO es un segundo bot. Es un "Diario B" que corre reglas alternativas sobre los
MISMOS setups del bot real, para que la comparación sea pareada: mismos trades,
misma ventana, la única variable es la regla. Cada trade real se vuelve evidencia
doble, en vez de partir en dos una muestra que ya es escasa (~1,3 días
independientes por semana).

Reglas CONGELADAS en `docs/BOT2_REGLAS_CONGELADAS_2026-07-26.md` antes de mirar
ningún resultado. Este script NO debe elegir umbrales; los lee de allí.

  R1  veto por muro opuesto entre la entrada y TP1   (la única con chance)
  R2  TP recortado al muro                            (control negativo esperado)
  R3  SL tras el muro                                 (ya refutada con proxies)

Aislamiento: no importa nada de `modules/bot/` ni de `modules/coinglass/`. El
contexto se une OFFLINE por `captured_at`, leyendo los archivos de datos. Así la
separación research↔ejecución queda intacta y este script no puede, ni por error,
tocar una orden.

Causalidad: para cada setup se usa la captura del libro **anterior o igual** a su
activación. Nunca posterior.

Corre:   .venv/bin/python3 research/bot2_contrafactual.py
Escribe: research/bot2_contrafactual_results.json
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
OUT_JSON = os.path.join(WT, "research", "bot2_contrafactual_results.json")
REGLAS_DOC = os.path.join(WT, "docs", "BOT2_REGLAS_CONGELADAS_2026-07-26.md")

SIMBOLO = "BTC_USDT"        # lo único que captura el colector
TOLERANCIA_MIN = 15         # captura válida si es de hasta 15 min antes del toque
UMBRAL_MURO = 5_000_000     # congelado en el doc; NO se ajusta acá
BUFFER = 0.0005             # para poner TP/SL "justo antes/detrás" del muro


def _epoch(stamp):
    try:
        when = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return when.timestamp() if when.tzinfo else None


def cargar_capturas():
    """Archivo histórico + ventana caliente, deduplicado y ordenado."""
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
                    continue        # una línea cortada no invalida el resto
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
        ts = _epoch(fila.get("captured_at"))
        if ts is not None:
            out.append((ts, fila))
    out.sort(key=lambda x: x[0])
    return out


def captura_previa(capturas, t):
    """La más reciente ANTERIOR o igual a `t`. Nunca posterior: usar el libro del
    futuro sería el mismo error que ya cometimos en `active_leg()`."""
    previa = None
    for ts, fila in capturas:
        if ts <= t:
            previa = (ts, fila)
        else:
            break
    if previa is None or (t - previa[0]) > TOLERANCIA_MIN * 60:
        return None
    return previa


def muros_en_tramo(fila, lo, hi, lado, umbral=UMBRAL_MURO):
    """Muros de `lado` dentro de [lo, hi] que superan el umbral."""
    campo = "asks" if lado == "ask" else "bids"
    return [(p, u) for p, u in (fila.get(campo) or [])
            if u >= umbral and lo <= p <= hi]


def aplicar_reglas(s, fila):
    """Devuelve, para cada regla, qué habría hecho. NO simula el resultado: eso
    requiere el recorrido del precio, que el Diario ya resolvió en `result_r`.

    R1 es la única que puede evaluarse de forma limpia con lo que hay: es un veto,
    así que su efecto es "este trade no se habría tomado" y el contrafactual es
    simplemente excluirlo del promedio.
    """
    long = s.get("dir") == "long"
    entry = float(s["entry"])
    sl = float(s["sl"])
    riesgo = abs(entry - sl)
    tp1 = entry + riesgo if long else entry - riesgo

    lo, hi = (entry, tp1) if long else (tp1, entry)
    opuestos = muros_en_tramo(fila, lo, hi, "ask" if long else "bid")
    r1_veta = bool(opuestos)

    # R2: muro a favor entre entrada y TP original
    tp = float(s["tp"])
    lo2, hi2 = (entry, tp) if long else (tp, entry)
    a_favor = muros_en_tramo(fila, lo2, hi2, "ask" if long else "bid")
    r2_tp = None
    if a_favor:
        objetivo = min(a_favor)[0] if long else max(a_favor)[0]
        r2_tp = round(objetivo * (1 - BUFFER) if long else objetivo * (1 + BUFFER), 2)

    # R3: muro a favor MÁS ALLÁ del SL estructural
    lo3, hi3 = (sl * 0.97, sl) if long else (sl, sl * 1.03)
    detras = muros_en_tramo(fila, lo3, hi3, "bid" if long else "ask")
    r3_sl = None
    if detras:
        nivel = min(detras)[0] if long else max(detras)[0]
        r3_sl = round(nivel * (1 - BUFFER) if long else nivel * (1 + BUFFER), 2)

    return {
        "r1_veta": r1_veta,
        "r1_muros_opuestos": [{"precio": p, "usd": u} for p, u in opuestos],
        "r2_tp": r2_tp,
        "r3_sl": r3_sl,
    }


def main():
    capturas = cargar_capturas()
    setups = []
    if os.path.isfile(SETUPS):
        with open(SETUPS, encoding="utf-8") as fh:
            crudos = json.load(fh)
        setups = [s for s in (crudos if isinstance(crudos, list) else [])
                  if s.get("pair") == SIMBOLO and s.get("ts_activated")
                  and s.get("status") in ("ganada", "perdida")
                  and s.get("result_r") is not None
                  and s.get("entry") and s.get("sl") and s.get("tp")]

    filas, sin_cobertura = [], 0
    for s in setups:
        previa = captura_previa(capturas, float(s["ts_activated"]))
        if previa is None:
            sin_cobertura += 1
            continue
        ts, fila = previa
        filas.append({
            "key": s.get("key"),
            "dir": s.get("dir"),
            "ts_activated": int(s["ts_activated"]),
            "desfase_seg": int(float(s["ts_activated"]) - ts),
            "entry": s["entry"], "sl": s["sl"], "tp": s["tp"],
            "rr": s.get("rr"),
            "result_r": s["result_r"],
            **aplicar_reglas(s, fila),
        })

    # BOT1 vs BOT2 bajo R1: el contrafactual del veto es excluir esos trades
    def promedio(rs):
        return round(sum(rs) / len(rs), 4) if rs else None

    todos = [f["result_r"] for f in filas]
    vetados = [f["result_r"] for f in filas if f["r1_veta"]]
    sobreviven = [f["result_r"] for f in filas if not f["r1_veta"]]

    salida = {
        "meta": {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "aviso": "Research only - No senal - No bot - NO usar para activar live",
            "que_es": ("evaluador contrafactual sobre los MISMOS setups de BOT1; "
                       "NO es un segundo bot con universo propio"),
            "reglas_congeladas_en": "docs/BOT2_REGLAS_CONGELADAS_2026-07-26.md",
            "umbral_muro_usd": UMBRAL_MURO,
            "causalidad": "captura anterior o igual a la activacion, nunca posterior",
            "simbolo": SIMBOLO,
            "capturas_disponibles": len(capturas),
            "setups_cerrados_btc": len(setups),
            "con_cobertura": len(filas),
            "sin_cobertura": sin_cobertura,
            "gate2_n_minimo_afectados": 50,
            "limitacion": ("solo BTCUSDT y ~15 setups BTC cada 43 dias: llegar a "
                           "n>=50 AFECTADOS toma mas de un ano"),
        },
        "r1_veto": {
            "n_total": len(todos),
            "n_vetados": len(vetados),
            "n_sobreviven": len(sobreviven),
            "avgR_bot1": promedio(todos),
            "avgR_bot2": promedio(sobreviven),
            "avgR_de_los_vetados": promedio(vetados),
            "cobertura_pct": (round(100 * len(sobreviven) / len(todos), 1)
                              if todos else None),
        },
        "filas": filas,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, indent=1)

    m, r = salida["meta"], salida["r1_veto"]
    print(f"resultados: {OUT_JSON}\n")
    print(f"capturas del libro : {m['capturas_disponibles']}")
    print(f"setups BTC cerrados: {m['setups_cerrados_btc']}")
    print(f"  con contexto     : {m['con_cobertura']}")
    print(f"  sin contexto     : {m['sin_cobertura']}")
    if not filas:
        print("\nSin cruces todavia. Es lo ESPERADO: el archivo del libro empieza\n"
              "el 2026-07-26 y solo cubre hacia adelante, mientras que los setups\n"
              "cerrados son anteriores. Este script existe para que dentro de meses\n"
              "haya con que, con las reglas ya congeladas de antemano.")
        return
    print(f"\nR1 (veto): {r['n_vetados']} vetados de {r['n_total']} · "
          f"cobertura {r['cobertura_pct']}%")
    print(f"  avgR BOT1 {r['avgR_bot1']} -> BOT2 {r['avgR_bot2']} "
          f"(los vetados promediaban {r['avgR_de_los_vetados']})")
    if r["n_vetados"] < m["gate2_n_minimo_afectados"]:
        print(f"\n  n AFECTADOS = {r['n_vetados']}, muy por debajo del minimo de "
              f"{m['gate2_n_minimo_afectados']} del Gate 2.\n"
              "  Cualquier diferencia de arriba es ruido. NO interpretar.")


if __name__ == "__main__":
    main()
