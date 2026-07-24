"""Tests del indicador de riesgo CoinGlass (research)."""
from __future__ import annotations

import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import coinglass_risk_indicator as ri  # noqa: E402


def _serie(n=200, paso=3_600_000 * 4):
    return [{"time": i * paso, "month": "2026-01", "price": 100.0 + i,
             "funding": 0.01, "oi_change": 0.01, "crowd_long": 55.0,
             "long_liq": 1.0, "short_liq": 1.0, "book_pressure": 0.1,
             "price_change": 0.01} for i in range(n)]


def test_zscore_es_causal_no_mira_el_futuro():
    """El z-score de la barra t no puede cambiar si se agregan barras después."""
    filas = ri.construir_features(_serie(120))
    for i, f in enumerate(filas):
        f["liq_intensity"] = float(i)          # serie creciente y determinista

    completo = ri.zscores_causales(filas, "liq_intensity")
    truncado = ri.zscores_causales(filas[:100], "liq_intensity")

    assert completo[:100] == truncado, "el z-score usó datos posteriores"
    assert all(v is None for v in completo[:ri.MIN_HISTORIA]), \
        "no puede emitirse score sin historia mínima"


def test_objetivo_solo_mira_barras_futuras():
    filas = ri.construir_features(_serie(10))
    ri.objetivos(filas, 2)

    # precio sube 1 por barra desde 100: a 2 barras vista el movimiento es 2/100
    assert abs(filas[0]["absmove_2"] - 0.02) < 1e-9
    assert filas[-1]["absmove_2"] is None, "las últimas barras no tienen futuro"
    assert filas[0]["vol_previa_2"] is None, "las primeras no tienen pasado"


def test_ventanas_no_solapadas():
    filas = list(range(10))
    assert ri.no_solapadas(filas, 1) == filas
    assert ri.no_solapadas(filas, 3) == [0, 3, 6, 9]


def test_spearman_parcial_detecta_redundancia():
    """Si x es casi una copia de z, no puede aportar nada sobre z.

    (Con x == z exacto la parcial es indefinida —colinealidad perfecta— y la
    función devuelve None, que es lo correcto.)
    """
    z = [float(i) for i in range(60)]
    x = [v + (i * 7 % 11) for i, v in enumerate(z)]   # muy correlacionado con z
    y = [v * 2 for v in z]                            # depende SOLO de z

    parcial = ri.spearman_parcial(x, y, z)
    assert parcial is not None and abs(parcial) < 0.3, \
        "x no aporta nada sobre z: la parcial debe ser ~0"

    assert ri.spearman_parcial(list(z), y, z) is None, \
        "colinealidad perfecta debe ser indefinida, no cero"


def test_ablacion_marca_el_cambio_de_signo_como_artefacto():
    """Una variable con signo invertido entre IS y OOS no es un edge."""
    filas = ri.construir_features(_serie(400))
    ri.puntuar(filas)
    ri.objetivos(filas, 1)
    # z_ inventado: negativo respecto al objetivo en IS, positivo en OOS
    corte = int(len(filas) * ri.IS_FRAC)
    for i, f in enumerate(filas):
        f["absmove_1"] = float(i % 7) / 100 if f.get("absmove_1") is not None else None
        f["vol_previa_1"] = 0.01
        f["z_liq_intensity"] = -(i % 7) if i < corte else (i % 7)

    resultado = ri.ablacion(filas, 1)
    assert resultado["liq_intensity"]["signo_estable"] is False
    assert "regimen" in resultado["liq_intensity"]["veredicto"]


def test_resultados_committeados_llevan_marca_research():
    import json
    path = os.path.join(WT, "research", "coinglass_risk_indicator_results.json")
    assert os.path.isfile(path)
    d = json.load(open(path))
    assert d["meta"]["research_only"] is True
    assert d["meta"]["execution_enabled"] is False
    assert d["meta"]["validated"] is False
    assert "NO usar para activar live" in d["meta"]["aviso"]
    assert d["meta"]["hipotesis_pre_registrada"]
