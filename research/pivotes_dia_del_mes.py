"""PIVOT-DOM-001 — pivotes de BTC 1D vs día del mes.

Implementa el método congelado en pivotes_dia_del_mes_2026-08-15.md.
Determinista (semilla fija); solo lectura del dataset versionado.
"""
from __future__ import annotations

import datetime
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.trading import smc  # noqa: E402

DATA = Path(__file__).parent / "hypothesis_lab/data/BINANCE_BTCUSDT_DAILY_2017_2026.json"
ROTACIONES = 4000
SEMILLA = 11


def cargar_velas() -> list[dict]:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    return [{"t": r["open_time_ms"], "o": r["open"], "h": r["high"],
             "l": r["low"], "c": r["close"]} for r in payload["rows"]]


def dia_del_mes(t_ms: int) -> int:
    return datetime.datetime.utcfromtimestamp(t_ms / 1000).day


def pivotes(velas: list[dict], piv: int) -> dict[str, list[int]]:
    """Índices de barra de cada pivote confirmado, por tipo."""
    highs, lows = smc.swing_points(velas, piv)
    return {"highs": [p["idx"] for p in highs], "lows": [p["idx"] for p in lows]}


def conteo_por_dia(indices: list[int], velas: list[dict],
                   corrimiento: int = 0) -> Counter:
    n = len(velas)
    return Counter(dia_del_mes(velas[(i + corrimiento) % n]["t"]) for i in indices)


def chi2(observado: Counter, esperado: dict[int, float]) -> float:
    total = 0.0
    for dia, exp in esperado.items():
        if exp > 0:
            total += (observado.get(dia, 0) - exp) ** 2 / exp
    return total


def analizar(velas: list[dict], indices: list[int], etiqueta: str) -> dict:
    n_piv = len(indices)
    obs = conteo_por_dia(indices, velas)
    dias_calendario = Counter(dia_del_mes(v["t"]) for v in velas)
    total_dias = sum(dias_calendario.values())
    esperado = {d: n_piv * dias_calendario[d] / total_dias for d in range(1, 32)}

    rng = random.Random(SEMILLA)
    chi_obs = chi2(obs, esperado)
    chi_null = []
    conteos_null: dict[int, list[int]] = {d: [] for d in range(1, 32)}
    for _ in range(ROTACIONES):
        k = rng.randrange(30, len(velas) - 30)
        rotado = conteo_por_dia(indices, velas, corrimiento=k)
        chi_null.append(chi2(rotado, esperado))
        for d in range(1, 32):
            conteos_null[d].append(rotado.get(d, 0))

    p_global = sum(c >= chi_obs for c in chi_null) / ROTACIONES
    p_por_dia = {}
    for d in range(1, 32):
        nulos = conteos_null[d]
        p_por_dia[d] = sum(c >= obs.get(d, 0) for c in nulos) / ROTACIONES

    # Holm sobre los 31 dias (barrido exploratorio)
    orden = sorted(p_por_dia, key=lambda d: p_por_dia[d])
    holm = {}
    sobrevive = []
    for rank, d in enumerate(orden):
        ajustado = min(1.0, p_por_dia[d] * (31 - rank))
        holm[d] = ajustado
        if ajustado < 0.05 and (not sobrevive or len(sobrevive) == rank):
            sobrevive.append(d)

    return {
        "etiqueta": etiqueta, "n_pivotes": n_piv,
        "chi2_obs": chi_obs, "p_global": p_global,
        "obs": obs, "esperado": esperado, "p_por_dia": p_por_dia,
        "holm": holm, "sobreviven_holm": sobrevive,
        "media_null": {d: sum(conteos_null[d]) / ROTACIONES for d in range(1, 32)},
    }


def imprimir(r: dict) -> None:
    print(f"\n== {r['etiqueta']}  (n pivotes = {r['n_pivotes']}) ==")
    print(f"  GLOBAL: chi2={r['chi2_obs']:.1f}  p_empirico={r['p_global']:.4f}"
          f"  -> {'RECHAZA uniformidad' if r['p_global'] < 0.05 else 'compatible con azar'}")
    d5 = 5
    print(f"  DIA 5 (pre-declarado): obs={r['obs'].get(d5, 0)}  "
          f"esperado(nulo)={r['media_null'][d5]:.1f}  p={r['p_por_dia'][d5]:.4f}"
          f"  -> {'SEÑAL' if r['p_por_dia'][d5] < 0.05 else 'nada'}")
    top = sorted(range(1, 32), key=lambda d: r['p_por_dia'][d])[:5]
    print("  top-5 dias por p crudo (exploratorio):")
    for d in top:
        print(f"    dia {d:2}: obs={r['obs'].get(d, 0):3}  esp={r['media_null'][d]:5.1f}"
              f"  p={r['p_por_dia'][d]:.4f}  p_holm={r['holm'][d]:.4f}")
    print(f"  sobreviven Holm: {r['sobreviven_holm'] or 'NINGUNO'}")


def main() -> None:
    velas = cargar_velas()
    print(f"velas diarias: {len(velas)}  "
          f"({datetime.datetime.utcfromtimestamp(velas[0]['t']/1000).date()} -> "
          f"{datetime.datetime.utcfromtimestamp(velas[-1]['t']/1000).date()})")
    for piv, etiqueta in ((5, "PRIMARIO 5+1+5"), (3, "secundario 3+1+3")):
        pts = pivotes(velas, piv)
        imprimir(analizar(velas, pts["highs"] + pts["lows"], f"{etiqueta} · todos"))
        imprimir(analizar(velas, pts["highs"], f"{etiqueta} · highs"))
        imprimir(analizar(velas, pts["lows"], f"{etiqueta} · lows"))


if __name__ == "__main__":
    main()
