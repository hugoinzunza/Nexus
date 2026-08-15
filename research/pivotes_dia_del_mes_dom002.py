"""PIVOT-DOM-002 — confirmación del día 25 en mínimos, rotación conjunta.

Implementa el método congelado en pivotes_dia_del_mes_dom002_prereg.md.
"""
from __future__ import annotations

import datetime
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.inteligencia import precio as P  # noqa: E402
from modules.trading import smc               # noqa: E402

ACTIVOS = ("ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT")
DIA = 25
ROTACIONES = 4000
SEMILLA = 13
DIA_MS = 86_400_000


def cargar(sym: str) -> list[dict]:
    rows = json.loads((Path(__file__).parent.parent / "data" /
                       f"klines_{sym}_1d.json").read_text())
    return P.velas_cerradas(rows, "1d", int(rows[-1]["t"]) + 2 * DIA_MS)


def dia_de(t_ms: int) -> int:
    return datetime.datetime.utcfromtimestamp(t_ms / 1000).day


def lows_por_activo(piv: int) -> dict[str, list[int]]:
    """Timestamps (ms) del extremo de cada pivote low confirmado."""
    salida = {}
    for sym in ACTIVOS:
        velas = cargar(sym)
        _, lows = smc.swing_points(velas, piv)
        salida[sym] = [int(velas[p["idx"]]["t"]) for p in lows]
    return salida


def conteo_dia(tss: list[int], corrimiento_dias: int = 0) -> int:
    return sum(1 for t in tss if dia_de(t + corrimiento_dias * DIA_MS) == DIA)


def correr(piv: int, etiqueta: str) -> None:
    lows = lows_por_activo(piv)
    obs_por_activo = {s: conteo_dia(ts) for s, ts in lows.items()}
    total_obs = sum(obs_por_activo.values())

    rng = random.Random(SEMILLA)
    totales_null = []
    medias = {s: 0.0 for s in ACTIVOS}
    for _ in range(ROTACIONES):
        k = rng.randrange(30, 1400)  # MISMO corrimiento para los 6: co-movimiento intacto
        tot = 0
        for s, ts in lows.items():
            c = conteo_dia(ts, k)
            tot += c
            medias[s] += c
        totales_null.append(tot)
    p = sum(t >= total_obs for t in totales_null) / ROTACIONES
    elevados = sum(1 for s in ACTIVOS
                   if obs_por_activo[s] > medias[s] / ROTACIONES)

    print(f"\n== {etiqueta} ==")
    for s in ACTIVOS:
        print(f"  {s:9} lows={len(lows[s]):4}  dia{DIA}={obs_por_activo[s]:3}  "
              f"esperado={medias[s] / ROTACIONES:5.1f}  "
              f"{'↑' if obs_por_activo[s] > medias[s] / ROTACIONES else '↓'}")
    print(f"  TOTAL: obs={total_obs}  esperado={sum(medias.values()) / ROTACIONES:.1f}  "
          f"p_conjunta={p:.4f}  activos_elevados={elevados}/6")
    pasa = p < 0.05 and elevados >= 4
    print(f"  CRITERIO CONGELADO (p<0,05 y >=4/6 elevados): "
          f"{'SUPERA la replicacion debil' if pasa else 'NO replica'}")


def main() -> None:
    correr(5, "PRIMARIO 5+1+5 · lows · día 25")
    correr(3, "secundario 3+1+3 · lows · día 25")


if __name__ == "__main__":
    main()
