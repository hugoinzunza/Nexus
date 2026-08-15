"""ZONAS-001 — harness del estudio de grados de zona.

Implementa EXACTAMENTE la definición congelada en
`zonas_crecetrader_prereg_2026-08-15.md`. Solo lectura de klines versionadas;
no toca módulos productivos, señales ni bots. Determinista: sin reloj, sin RNG
fuera del bootstrap sembrado.
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.bot2.strategy import atr_values  # noqa: E402  (media de TR, ya testeada)
from modules.inteligencia import fases as F   # noqa: E402
from modules.inteligencia import precio as P  # noqa: E402

PIV = 5
K_CLUSTER_PRIMARIO = 0.50
K_CLUSTER_SECUNDARIO = 0.25
UMBRAL_RUPTURA_ATR = 0.25
REACCION_ATR = 1.0
HORIZONTE = 12
CORTE_OOS_MS = 1735689600000  # 2025-01-01, congelado en el pre-registro
BOOTSTRAP_N = 5000
BOOTSTRAP_SEED = 7


def construir_zonas(velas: list[dict], tf: str, k: float,
                    piv: int = PIV) -> list[dict]:
    """Zonas causales por clúster de pivotes confirmados.

    Cada zona registra su historia de bordes (`bounds_log`) para que cualquier
    evaluación posterior use los bordes vigentes en ese momento, nunca los
    finales."""
    puntos = F.pivotes_confirmados(velas, tf, piv)
    atrs = atr_values(velas)
    zonas: list[dict] = []
    for punto in sorted(puntos["eventos"], key=lambda p: (p["confirm_idx"], p["idx"])):
        precio = float(punto["price"])
        confirm_idx = punto["confirm_idx"]
        atr = atrs[confirm_idx] if confirm_idx < len(atrs) else None
        if atr is None or atr <= 0:
            continue
        tolerancia = k * atr
        candidata = None
        for zona in zonas:
            lo, hi = zona["low"], zona["high"]
            distancia = 0.0 if lo <= precio <= hi else min(abs(precio - lo), abs(precio - hi))
            if distancia <= tolerancia:
                candidata = zona
                break
        if candidata is None:
            zonas.append({
                "low": precio, "high": precio, "members": 1,
                "formed_idx": None,  # nace recién con el segundo miembro
                "first_confirm_idx": confirm_idx,
                "bounds_log": [(confirm_idx, precio, precio, 1)],
            })
            continue
        candidata["low"] = min(candidata["low"], precio)
        candidata["high"] = max(candidata["high"], precio)
        candidata["members"] += 1
        if candidata["members"] == 2:
            candidata["formed_idx"] = confirm_idx
        candidata["bounds_log"].append(
            (confirm_idx, candidata["low"], candidata["high"], candidata["members"])
        )
    return zonas


def _bordes_en(zona: dict, idx: int) -> tuple[float, float, int] | None:
    """Bordes y grado vigentes en `idx` (el último registro con confirm_idx <= idx)."""
    vigente = None
    for confirm_idx, lo, hi, miembros in zona["bounds_log"]:
        if confirm_idx <= idx:
            vigente = (lo, hi, miembros)
        else:
            break
    return vigente


def medir_toques(velas: list[dict], zona_like: dict, atrs: list[float | None],
                 desde_idx: int) -> list[dict]:
    """Toques causales y su reacción según la métrica congelada.

    `zona_like` necesita `bounds_log` (las bandas placebo llevan uno estático).
    Estados: activa → rota (cierre más allá del borde lejano por 0,25 ATR) →
    reclamada (cierre de vuelta dentro)."""
    eventos = []
    rota = False
    lado = None  # de qué lado de la zona vive el precio; None = dentro o aún sin dato
    i = desde_idx + 1
    while i < len(velas) - 1:
        vigente = _bordes_en(zona_like, i)
        if vigente is None:
            i += 1
            continue
        lo, hi, miembros = vigente
        atr = atrs[i]
        if atr is None or atr <= 0:
            i += 1
            continue
        close = float(velas[i]["c"])
        if rota:
            if lo <= close <= hi:
                rota = False  # reclamada
                lado = None
            i += 1
            continue
        # Rota = ATRAVESADA: el precio vivía de un lado y cierra del otro con
        # margen de 0,25 ATR. Estar lejos de un solo lado es el estado normal
        # de un soporte o una resistencia, no una ruptura.
        if close > hi:
            nuevo_lado = "arriba"
        elif close < lo:
            nuevo_lado = "abajo"
        else:
            nuevo_lado = lado  # dentro: conserva el lado de procedencia
        if lado is not None and nuevo_lado is not None and nuevo_lado != lado:
            margen = (close > hi + UMBRAL_RUPTURA_ATR * atr if nuevo_lado == "arriba"
                      else close < lo - UMBRAL_RUPTURA_ATR * atr)
            if margen:
                rota = True
                i += 1
                continue
        lado = nuevo_lado
        prev_close = float(velas[i - 1]["c"])
        solapa = float(velas[i]["l"]) <= hi and float(velas[i]["h"]) >= lo
        desde_arriba = prev_close > hi
        desde_abajo = prev_close < lo
        if not solapa or not (desde_arriba or desde_abajo):
            i += 1
            continue
        borde_cercano = hi if desde_arriba else lo
        borde_lejano = lo if desde_arriba else hi
        reaccion = False
        for j in range(i, min(i + HORIZONTE, len(velas))):
            atr_j = atrs[j] or atr
            close_j = float(velas[j]["c"])
            if desde_arriba and close_j < borde_lejano - UMBRAL_RUPTURA_ATR * atr_j:
                break
            if desde_abajo and close_j > borde_lejano + UMBRAL_RUPTURA_ATR * atr_j:
                break
            alejamiento = (float(velas[j]["h"]) - borde_cercano if desde_arriba
                           else borde_cercano - float(velas[j]["l"]))
            if alejamiento >= REACCION_ATR * atr:
                reaccion = True
                break
        eventos.append({
            "idx": i, "t": int(velas[i]["t"]), "reaccion": reaccion,
            "members": miembros, "desde": "arriba" if desde_arriba else "abajo",
        })
        i += HORIZONTE  # un toque por ventana; evita contar la misma visita dos veces
    return eventos


def bandas_placebo(zonas: list[dict], velas: list[dict]) -> list[dict]:
    """Bandas del mismo ancho, centradas en el punto medio entre zonas reales
    consecutivas (por precio), excluyendo solapes. Determinista."""
    formadas = [z for z in zonas if z["formed_idx"] is not None]
    orden = sorted(formadas, key=lambda z: (z["low"] + z["high"]) / 2)
    placebos = []
    for a, b in zip(orden, orden[1:]):
        centro = ((a["low"] + a["high"]) / 2 + (b["low"] + b["high"]) / 2) / 2
        ancho = (a["high"] - a["low"] + b["high"] - b["low"]) / 2 or (
            (b["low"] - a["high"]) * 0.05)
        lo, hi = centro - ancho / 2, centro + ancho / 2
        if hi >= b["low"] or lo <= a["high"]:
            continue  # solaparía una zona real
        formed = max(a["formed_idx"], b["formed_idx"])
        placebos.append({
            "low": lo, "high": hi, "members": 0, "formed_idx": formed,
            "bounds_log": [(formed, lo, hi, 0)],
        })
    return placebos


def _tasa(eventos: list[dict]) -> float | None:
    return sum(e["reaccion"] for e in eventos) / len(eventos) if eventos else None


def _bootstrap_delta(reales: list[dict], placebo: list[dict]) -> tuple[float, float] | None:
    """IC95 del Δ tasa de reacción con bloques mensuales, semilla fija."""
    if not reales or not placebo:
        return None
    def bloques(evs):
        por_mes: dict[str, list[int]] = {}
        for e in evs:
            mes = time.strftime("%Y-%m", time.gmtime(e["t"] / 1000))
            por_mes.setdefault(mes, []).append(1 if e["reaccion"] else 0)
        return list(por_mes.values())
    br, bp = bloques(reales), bloques(placebo)
    rng = random.Random(BOOTSTRAP_SEED)
    deltas = []
    for _ in range(BOOTSTRAP_N):
        sr = [x for _ in br for x in rng.choice(br)]
        sp = [x for _ in bp for x in rng.choice(bp)]
        if sr and sp:
            deltas.append(sum(sr) / len(sr) - sum(sp) / len(sp))
    deltas.sort()
    return (deltas[int(len(deltas) * 0.025)], deltas[int(len(deltas) * 0.975)])


def correr_mercado(sym: str, tf: str, k: float) -> dict:
    rows = json.loads(Path(f"data/klines_{sym}_{tf}.json").read_text())
    ahora = int(rows[-1]["t"]) + P.TF_MS[tf] * 2
    velas = P.velas_cerradas(rows, tf, ahora)
    atrs = atr_values(velas)
    zonas = construir_zonas(velas, tf, k)
    brazos = {"grado1": [], "grado2": [], "puntual": [], "placebo": []}
    for z in zonas:
        if z["formed_idx"] is None:
            eventos = medir_toques(velas, {
                **z, "bounds_log": [(z["first_confirm_idx"], z["low"], z["high"], 1)],
            }, atrs, z["first_confirm_idx"])
            brazos["puntual"].extend(eventos)
            continue
        for e in medir_toques(velas, z, atrs, z["formed_idx"]):
            brazos["grado1" if e["members"] >= 3 else "grado2"].append(e)
    for pb in bandas_placebo(zonas, velas):
        brazos["placebo"].extend(medir_toques(velas, pb, atrs, pb["formed_idx"]))
    return {"zonas": len([z for z in zonas if z["formed_idx"] is not None]),
            "brazos": brazos}


def main() -> None:
    for k, etiqueta in ((K_CLUSTER_PRIMARIO, "PRIMARIO"), (K_CLUSTER_SECUNDARIO, "secundario")):
        print(f"\n{'='*86}\nk = {k} ATR ({etiqueta})\n{'='*86}")
        agregado: dict[str, dict[str, list]] = {}
        for tf in ("1h", "4h", "1d"):
            todos = {"grado1": [], "grado2": [], "puntual": [], "placebo": []}
            for sym in ("BTCUSDT", "ETHUSDT"):
                r = correr_mercado(sym, tf, k)
                for brazo, evs in r["brazos"].items():
                    todos[brazo].extend(evs)
            agregado[tf] = todos
            fila = f"  {tf:3}"
            for brazo in ("grado1", "grado2", "puntual", "placebo"):
                evs = todos[brazo]
                tasa = _tasa(evs)
                fila += f" | {brazo} n={len(evs):4} r={tasa:.3f}" if tasa is not None else f" | {brazo} n=0"
            print(fila)
            oos = {b: [e for e in evs if e["t"] >= CORTE_OOS_MS] for b, evs in todos.items()}
            ic = _bootstrap_delta(oos["grado1"], oos["placebo"])
            t1, tp = _tasa(oos["grado1"]), _tasa(oos["placebo"])
            if ic and t1 is not None and tp is not None:
                veredicto = "POSITIVO (borde inferior > 0)" if ic[0] > 0 else "no separa de cero"
                print(f"      OOS grado1 n={len(oos['grado1'])} r={t1:.3f} vs placebo n={len(oos['placebo'])} "
                      f"r={tp:.3f}  Δ={t1-tp:+.3f}  IC95=[{ic[0]:+.3f},{ic[1]:+.3f}]  -> {veredicto}")
            ic_p = _bootstrap_delta(oos["grado1"], oos["puntual"])
            t_pu = _tasa(oos["puntual"])
            if ic_p and t1 is not None and t_pu is not None:
                print(f"      OOS grado1 vs PUNTUAL: Δ={t1-t_pu:+.3f}  IC95=[{ic_p[0]:+.3f},{ic_p[1]:+.3f}]")


if __name__ == "__main__":
    main()
