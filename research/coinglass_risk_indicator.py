#!/usr/bin/env python3
"""Indicador de RIESGO (no de dirección) desde los datos de CoinGlass.

Motivación honesta: el estudio previo (`coinglass_hobbyist_study`) probó reglas
DIRECCIONALES sobre estas mismas series y ninguna sobrevivió OOS con su IC 95%
sobre cero. Predecir dirección con 6 meses de barras 4h y features de
posicionamiento es, a priori, lo más difícil que se puede intentar.

Este estudio apunta a algo distinto y con mejor fundamento: **expansión de
volatilidad**. La volatilidad se agrupa (clustering) y el posicionamiento extremo
—funding tensionado, OI acumulado, crowding, liquidaciones recientes— es el
combustible documentado de las cascadas. Además un indicador de riesgo es
*seguro* de usar en un bot: modula tamaño o pausa entradas, no elige lado.

HIPÓTESIS PRE-REGISTRADA (fijada antes de mirar resultados):
  H1. El score de riesgo correlaciona positivamente con el movimiento absoluto
      máximo de las siguientes H barras.
  H2. Aporta información INCREMENTAL sobre la volatilidad reciente (el baseline
      tonto). Si no supera a "la vol de las últimas H barras", no sirve.
  H3. Control negativo: NO predice dirección (correlación ~0 con el retorno con
      signo). Si predijera dirección, sospechar del pipeline.

CRITERIO DE DESCARTE (también pre-registrado):
  - Si el IC 95% de la correlación OOS incluye cero -> descartado.
  - Si la correlación parcial (controlando por el baseline) no es positiva con
    IC 95% sobre cero -> el indicador es redundante y se descarta.

Anti-look-ahead:
  - Normalización con ventana EXPANSIVA: el z-score de la barra t usa solo las
    barras < t. Normalizar con media/desvío de toda la muestra sería trampa.
  - El objetivo mira solo barras futuras; la barra t no entra en su propio target.
  - Ventanas NO solapadas por horizonte para los tests (una obs cada H barras).

Corre:   .venv/bin/python3 research/coinglass_risk_indicator.py
Escribe: research/coinglass_risk_indicator_results.json
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from research.coinglass_hobbyist_study import load_bars  # noqa: E402

STORE = ROOT / "data/coinsignals_coinglass.json"
OUT_JSON = ROOT / "research/coinglass_risk_indicator_results.json"
HORIZONTES = (1, 2, 3)          # barras 4h -> 4h, 8h, 12h
IS_FRAC = 0.70
MIN_HISTORIA = 60               # barras mínimas antes de emitir score
BOOTSTRAP = 2000
SEMILLA = 20260724

# Pesos IGUALES y pre-registrados: no se ajustan a los datos.
FEATURES = ("funding_extremity", "oi_buildup", "crowd_extremity",
            "liq_intensity", "book_imbalance")


def construir_features(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Features de tensión de posicionamiento, todas en magnitud (sin signo)."""
    filas = []
    for bar in bars:
        funding = bar.get("funding")
        oi_change = bar.get("oi_change")
        crowd = bar.get("crowd_long")
        liq = (bar.get("long_liq") or 0.0) + (bar.get("short_liq") or 0.0)
        book = bar.get("book_pressure")
        filas.append({
            "time": bar["time"],
            "month": bar["month"],
            "price": bar["price"],
            "price_change": bar.get("price_change"),
            "funding_extremity": abs(funding) if funding is not None else None,
            "oi_buildup": abs(oi_change) if oi_change is not None else None,
            "crowd_extremity": (abs(crowd - 50) / 50) if crowd is not None else None,
            "liq_intensity": liq,
            "book_imbalance": abs(book) if book is not None else None,
        })
    return filas


def zscores_causales(filas: list[dict[str, Any]], campo: str) -> list[float | None]:
    """z-score de cada barra usando SOLO las barras anteriores (ventana expansiva).

    Normalizar con la media/desvío de toda la muestra metería información del
    futuro en el score de cada barra. Es el error silencioso más común en este
    tipo de indicador.
    """
    salida: list[float | None] = []
    vistos: list[float] = []
    for fila in filas:
        valor = fila.get(campo)
        if len(vistos) >= MIN_HISTORIA and valor is not None:
            media = sum(vistos) / len(vistos)
            var = sum((v - media) ** 2 for v in vistos) / max(len(vistos) - 1, 1)
            desvio = math.sqrt(var)
            salida.append((valor - media) / desvio if desvio > 0 else 0.0)
        else:
            salida.append(None)
        if valor is not None:
            vistos.append(valor)
    return salida


def puntuar(filas: list[dict[str, Any]]) -> None:
    """Score de riesgo = promedio de z-scores causales, con pesos iguales."""
    columnas = {campo: zscores_causales(filas, campo) for campo in FEATURES}
    for i, fila in enumerate(filas):
        partes = [columnas[campo][i] for campo in FEATURES]
        disponibles = [p for p in partes if p is not None]
        fila["risk_score"] = (sum(disponibles) / len(disponibles)
                              if len(disponibles) >= 3 else None)
        for campo in FEATURES:
            fila[f"z_{campo}"] = columnas[campo][i]


def objetivos(filas: list[dict[str, Any]], h: int) -> None:
    """Objetivo: movimiento absoluto MÁXIMO de las próximas h barras, y el
    retorno con signo (control negativo). Baseline: vol de las h barras previas."""
    n = len(filas)
    for i, fila in enumerate(filas):
        if i + h < n:
            base = fila["price"]
            futuros = [filas[i + k]["price"] for k in range(1, h + 1)]
            fila[f"absmove_{h}"] = max(abs(p / base - 1) for p in futuros)
            fila[f"ret_{h}"] = futuros[-1] / base - 1
        else:
            fila[f"absmove_{h}"] = None
            fila[f"ret_{h}"] = None
        # Baseline tonto: cuánto se movió en las h barras ANTERIORES.
        if i - h >= 0:
            previo = filas[i - h]["price"]
            fila[f"vol_previa_{h}"] = abs(fila["price"] / previo - 1)
        else:
            fila[f"vol_previa_{h}"] = None


# ------------------------------ estadística ------------------------------

def rangos(valores: list[float]) -> list[float]:
    orden = sorted(range(len(valores)), key=lambda i: valores[i])
    rank = [0.0] * len(valores)
    i = 0
    while i < len(orden):
        j = i
        while j + 1 < len(orden) and valores[orden[j + 1]] == valores[orden[i]]:
            j += 1
        promedio = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rank[orden[k]] = promedio
        i = j + 1
    return rank


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 8:
        return None
    rx, ry = rangos(xs), rangos(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return num / (dx * dy) if dx > 0 and dy > 0 else None


def spearman_parcial(xs, ys, zs) -> float | None:
    """Correlación de x con y controlando por z (todo en rangos).

    Responde la pregunta que importa: ¿el score aporta ALGO que la volatilidad
    reciente no tenga ya?
    """
    rxy, rxz, ryz = spearman(xs, ys), spearman(xs, zs), spearman(ys, zs)
    if None in (rxy, rxz, ryz):
        return None
    den = math.sqrt(max(0.0, (1 - rxz ** 2) * (1 - ryz ** 2)))
    # Con colinealidad (casi) perfecta la parcial es indefinida: un denominador
    # diminuto por error de punto flotante devolvía un número inestable en vez
    # de None. Se exige un mínimo antes de dividir.
    return (rxy - rxz * ryz) / den if den > 1e-9 else None


def ic_bootstrap(xs, ys, zs=None, reps=BOOTSTRAP) -> tuple[float, float] | None:
    rng = random.Random(SEMILLA)
    n = len(xs)
    if n < 12:
        return None
    muestras = []
    for _ in range(reps):
        idx = [rng.randrange(n) for _ in range(n)]
        bx = [xs[i] for i in idx]
        by = [ys[i] for i in idx]
        valor = (spearman(bx, by) if zs is None
                 else spearman_parcial(bx, by, [zs[i] for i in idx]))
        if valor is not None:
            muestras.append(valor)
    if len(muestras) < reps * 0.5:
        return None
    muestras.sort()
    return (muestras[int(len(muestras) * 0.025)],
            muestras[int(len(muestras) * 0.975)])


def no_solapadas(filas: list[dict[str, Any]], h: int) -> list[dict[str, Any]]:
    """Una observación cada h barras: las ventanas de h barras no se pisan."""
    return filas[::h]


def evaluar(filas: list[dict[str, Any]], h: int) -> dict[str, Any]:
    usables = [
        f for f in no_solapadas(filas, h)
        if f.get("risk_score") is not None
        and f.get(f"absmove_{h}") is not None
        and f.get(f"vol_previa_{h}") is not None
    ]
    corte = int(len(usables) * IS_FRAC)
    bloques = {"IS": usables[:corte], "OOS": usables[corte:], "TODO": usables}
    salida: dict[str, Any] = {}
    for nombre, filas_b in bloques.items():
        if len(filas_b) < 12:
            salida[nombre] = {"n": len(filas_b)}
            continue
        score = [f["risk_score"] for f in filas_b]
        objetivo = [f[f"absmove_{h}"] for f in filas_b]
        baseline = [f[f"vol_previa_{h}"] for f in filas_b]
        direccion = [f[f"ret_{h}"] for f in filas_b]
        salida[nombre] = {
            "n": len(filas_b),
            "rho_score": spearman(score, objetivo),
            "ic_score": ic_bootstrap(score, objetivo),
            "rho_baseline": spearman(baseline, objetivo),
            "rho_parcial": spearman_parcial(score, objetivo, baseline),
            "ic_parcial": ic_bootstrap(score, objetivo, baseline),
            "rho_direccion_control": spearman(score, direccion),
        }
    # Calibración por deciles sobre OOS
    oos = bloques["OOS"]
    if len(oos) >= 20:
        ordenado = sorted(oos, key=lambda f: f["risk_score"])
        tam = max(len(ordenado) // 5, 1)
        salida["quintiles_OOS"] = [
            {
                "quintil": q + 1,
                "n": len(ordenado[q * tam:(q + 1) * tam]),
                "absmove_medio_pct": round(100 * sum(
                    f[f"absmove_{h}"] for f in ordenado[q * tam:(q + 1) * tam]
                ) / max(len(ordenado[q * tam:(q + 1) * tam]), 1), 3),
            }
            for q in range(5)
        ]
    return salida


def ablacion(filas: list[dict[str, Any]], h: int) -> dict[str, Any]:
    """Cada feature por separado, en IS **y** en OOS.

    Mirar solo el OOS es una trampa: una variable puede lucir fuerte ahí y tener
    el signo CONTRARIO en in-sample, que es la firma de un artefacto de régimen y
    no de una relación estable. Por eso se reportan ambos y se marca
    `signo_estable`; sin eso, elegir la mejor del OOS es cherry-picking.
    """
    usables = [
        f for f in no_solapadas(filas, h)
        if f.get(f"absmove_{h}") is not None and f.get(f"vol_previa_{h}") is not None
    ]
    corte = int(len(usables) * IS_FRAC)
    bloque_is, bloque_oos = usables[:corte], usables[corte:]
    salida = {}
    for campo in FEATURES:
        def columnas(rows):
            validas = [f for f in rows if f.get(f"z_{campo}") is not None]
            return ([f[f"z_{campo}"] for f in validas],
                    [f[f"absmove_{h}"] for f in validas],
                    [f[f"vol_previa_{h}"] for f in validas])
        xi, yi, _ = columnas(bloque_is)
        xo, yo, zo = columnas(bloque_oos)
        if len(xi) < 12 or len(xo) < 12:
            continue
        rho_is, rho_oos = spearman(xi, yi), spearman(xo, yo)
        parcial = spearman_parcial(xo, yo, zo)
        ic = ic_bootstrap(xo, yo, zo)
        estable = (rho_is is not None and rho_oos is not None
                   and rho_is > 0 and rho_oos > 0)
        salida[campo] = {
            "rho_IS": rho_is,
            "rho_OOS": rho_oos,
            "parcial_OOS": parcial,
            "ic_parcial_OOS": ic,
            "signo_estable": estable,
            "veredicto": (
                "candidato" if estable and ic and ic[0] > 0
                else "signo estable, sin significancia" if estable
                else "artefacto de regimen: cambia de signo IS->OOS"
            ),
        }
    return salida


def main() -> None:
    bars = load_bars(STORE)
    filas = construir_features(bars)
    puntuar(filas)
    for h in HORIZONTES:
        objetivos(filas, h)

    resultados = {
        "meta": {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "aviso": "Research only - No senal - No bot - NO usar para activar live",
            "objetivo": "riesgo/volatilidad, NO direccion",
            "barras": len(filas),
            "hipotesis_pre_registrada": [
                "H1 el score correlaciona con el movimiento absoluto futuro",
                "H2 aporta informacion incremental sobre la volatilidad reciente",
                "H3 control negativo: no predice direccion",
            ],
            "criterio_descarte": (
                "IC 95% de la correlacion OOS que incluya cero, o correlacion "
                "parcial no positiva con IC sobre cero"
            ),
            "pesos": "iguales, pre-registrados, sin ajuste a los datos",
            "normalizacion": "z-score con ventana expansiva (solo pasado)",
        },
        "horizontes": {},
    }
    for h in HORIZONTES:
        resultados["horizontes"][f"{h*4}h"] = {
            "evaluacion": evaluar(filas, h),
            "ablacion_OOS": ablacion(filas, h),
        }

    OUT_JSON.write_text(json.dumps(resultados, indent=1, default=str), encoding="utf-8")
    print(f"resultados: {OUT_JSON}\n")
    for etiqueta, bloque in resultados["horizontes"].items():
        ev = bloque["evaluacion"]
        print(f"=== {etiqueta} ===")
        for nombre in ("IS", "OOS"):
            d = ev.get(nombre, {})
            if d.get("rho_score") is None:
                print(f"  {nombre}: n={d.get('n')} (insuficiente)")
                continue
            ic = d.get("ic_score") or (None, None)
            icp = d.get("ic_parcial") or (None, None)
            print(f"  {nombre}: n={d['n']:4} "
                  f"rho_score={d['rho_score']:+.3f} IC[{ic[0]:+.3f},{ic[1]:+.3f}] | "
                  f"baseline={d['rho_baseline']:+.3f} | "
                  f"parcial={d['rho_parcial']:+.3f} IC[{icp[0]:+.3f},{icp[1]:+.3f}] | "
                  f"control_dir={d['rho_direccion_control']:+.3f}")
        if ev.get("quintiles_OOS"):
            resumen = " ".join(f"Q{q['quintil']}={q['absmove_medio_pct']:.2f}%"
                               for q in ev["quintiles_OOS"])
            print(f"  quintiles OOS (movimiento medio): {resumen}")
        for campo, d in bloque["ablacion_OOS"].items():
            print(f"    {campo:18} IS={d['rho_IS']:+.3f} OOS={d['rho_OOS']:+.3f} "
                  f"parcial={d['parcial_OOS']:+.3f} -> {d['veredicto']}")
        print()


if __name__ == "__main__":
    main()
