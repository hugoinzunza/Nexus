#!/usr/bin/env python3
"""Tasas históricas de ALCANCE: ¿cuán seguido el precio recorre X% en N horas?

Esto es lo que sí se puede afirmar con los datos y sin inventar dirección. En vez
de decir "el precio va a subir", responde la pregunta operativa real:

  "El clúster de liquidez de arriba está a 1,2%. ¿Cuántas veces, históricamente,
   el precio recorrió 1,2% hacia arriba dentro de 4 horas?"

Es una **tasa base empírica**, no una predicción: se mide sobre la distribución de
excursiones máximas de BTC en la propia historia 4h del store. Dos números
separados por lado (arriba y abajo), porque la distribución no es simétrica.

Lo que NO es: una probabilidad condicionada al estado actual del mercado. Es la
tasa incondicional. Si alguna vez se valida que un componente del Radar la
desplaza, entonces sí habría un condicionamiento — hoy no está demostrado y por
eso se publica como tasa base.

Corre:   .venv/bin/python3 research/coinglass_touch_rates.py
Escribe: modules/coinglass/touch_rates.json (lo consume el indicador visual)
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from research.coinglass_hobbyist_study import load_bars  # noqa: E402

STORE = ROOT / "data/coinsignals_coinglass.json"
OUT = ROOT / "modules/coinglass/touch_rates.json"
HORIZONTES = (1, 2, 3)                 # barras 4h
# Distancias en % sobre las que se tabula la tasa base.
BUCKETS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)


def excursiones(bars: list[dict], h: int) -> list[tuple[float, float]]:
    """Por cada barra: (excursión máxima hacia arriba, hacia abajo) en las
    próximas h barras, en %. Solo mira el futuro de esa barra."""
    salida = []
    for i in range(len(bars) - h):
        base = bars[i]["price"]
        if not base:
            continue
        futuros = [bars[i + k]["price"] for k in range(1, h + 1)]
        arriba = max((p / base - 1) * 100 for p in futuros)
        abajo = min((p / base - 1) * 100 for p in futuros)
        salida.append((max(arriba, 0.0), abs(min(abajo, 0.0))))
    return salida


def tabla(bars: list[dict]) -> dict:
    resultado = {"buckets_pct": list(BUCKETS), "horizontes": {}}
    for h in HORIZONTES:
        datos = excursiones(bars, h)
        n = len(datos)
        arriba = [a for a, _ in datos]
        abajo = [b for _, b in datos]
        resultado["horizontes"][f"{h*4}h"] = {
            "n": n,
            # P(la excursión hacia ese lado alcanzó al menos `bucket`%)
            "p_arriba": {str(b): round(sum(1 for v in arriba if v >= b) / n, 4)
                         for b in BUCKETS},
            "p_abajo": {str(b): round(sum(1 for v in abajo if v >= b) / n, 4)
                        for b in BUCKETS},
            "mediana_arriba_pct": round(sorted(arriba)[n // 2], 3),
            "mediana_abajo_pct": round(sorted(abajo)[n // 2], 3),
        }
    return resultado


def main() -> None:
    bars = load_bars(STORE)
    datos = tabla(bars)
    datos["meta"] = {
        "research_only": True,
        "que_es": ("tasa base historica de alcance: P(el precio recorrio X% hacia "
                   "ese lado dentro del horizonte). NO es prediccion ni esta "
                   "condicionada al estado actual del mercado."),
        "fuente": "historia 4h del store CoinGlass (origen backfill)",
        "barras": len(bars),
    }
    OUT.write_text(json.dumps(datos, indent=1), encoding="utf-8")
    print(f"tabla: {OUT}  ({len(bars)} barras)\n")
    for etiqueta, bloque in datos["horizontes"].items():
        print(f"=== {etiqueta} (n={bloque['n']}) ===")
        print("  dist%   P(arriba)  P(abajo)")
        for b in BUCKETS:
            print(f"  {b:>5.2f}    {100*bloque['p_arriba'][str(b)]:5.1f}%    "
                  f"{100*bloque['p_abajo'][str(b)]:5.1f}%")
        print(f"  mediana: arriba {bloque['mediana_arriba_pct']}% / "
              f"abajo {bloque['mediana_abajo_pct']}%\n")


if __name__ == "__main__":
    main()
