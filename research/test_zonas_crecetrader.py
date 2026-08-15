"""Tests del harness ZONAS-001 sobre datos sintéticos."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.zonas_crecetrader import (
    construir_zonas, medir_toques, bandas_placebo, _bordes_en)
from modules.bot2.strategy import atr_values


def _velas_con_pivotes(precios_pivote, tf_gap=3_600_000):
    """Serie sintética: sube y baja para crear pivotes en precios controlados."""
    velas = []
    t = 0
    nivel = 100.0
    def empujar(destino, pasos=7):
        nonlocal nivel, t
        delta = (destino - nivel) / pasos
        for _ in range(pasos):
            nivel += delta
            # mechas ancladas SOLO al cierre: los extremos quedan estrictos y
            # swing_points (que exige > estricto) puede confirmarlos
            velas.append({"t": t, "o": nivel - delta, "h": nivel + 0.05,
                          "l": nivel - 0.05, "c": nivel})
            t += tf_gap
    for p in precios_pivote:
        empujar(p)
    return velas


def test_cluster_agrupa_pivotes_cercanos_y_separa_lejanos():
    # pivotes bajos ~100 (dos veces) y altos ~140: el par cercano debe fundirse
    velas = _velas_con_pivotes([100, 140, 101, 141, 100.5, 139, 99.5, 140.5, 100.2, 139.5])
    zonas = construir_zonas(velas, "1h", k=0.50, piv=2)
    formadas = [z for z in zonas if z["formed_idx"] is not None]
    assert formadas, "debe existir al menos una zona con 2+ miembros"
    assert all(z["high"] - z["low"] < 10 for z in formadas), "una zona no puede abarcar 100 y 140"


def test_bordes_vigentes_son_causales():
    velas = _velas_con_pivotes([100, 140, 101, 141, 100.5, 139, 99.5, 140.5, 100.2, 139.5])
    zonas = construir_zonas(velas, "1h", k=0.50, piv=2)
    z = next(z for z in zonas if z["members"] >= 2)
    # en el idx de cada registro rige el ULTIMO registro con ese confirm_idx
    ultimos = {}
    for confirm_idx, lo, hi, miembros in z["bounds_log"]:
        ultimos[confirm_idx] = (lo, hi, miembros)
    for confirm_idx, esperado in ultimos.items():
        assert _bordes_en(z, confirm_idx) == esperado
    assert _bordes_en(z, z["bounds_log"][0][0] - 1) is None


def test_toque_y_reaccion_basicos():
    zona = {"low": 99.0, "high": 101.0, "bounds_log": [(0, 99.0, 101.0, 2)]}
    velas = [{"t": i * 1000, "o": 110, "h": 111, "l": 109, "c": 110} for i in range(20)]
    velas += [{"t": 20000, "o": 110, "h": 110, "l": 100.5, "c": 103}]      # toque desde arriba
    velas += [{"t": 21000, "o": 103, "h": 115, "l": 102, "c": 114}]        # reacción > 1 ATR
    velas += [{"t": 22000 + i * 1000, "o": 114, "h": 115, "l": 113, "c": 114} for i in range(14)]
    atrs = atr_values(velas)
    eventos = medir_toques(velas, zona, atrs, 14)
    assert len(eventos) == 1
    assert eventos[0]["reaccion"] is True and eventos[0]["desde"] == "arriba"


def test_ruptura_congela_los_toques_hasta_reclamo():
    zona = {"low": 99.0, "high": 101.0, "bounds_log": [(0, 99.0, 101.0, 2)]}
    velas = [{"t": i * 1000, "o": 110, "h": 111, "l": 109, "c": 110} for i in range(16)]
    velas += [{"t": 16000, "o": 110, "h": 110, "l": 90, "c": 90}]           # cierre MUY por debajo: rota
    velas += [{"t": 17000 + i * 1000, "o": 90, "h": 100.5, "l": 89, "c": 92} for i in range(6)]
    atrs = atr_values(velas)
    eventos = medir_toques(velas, zona, atrs, 14)
    assert eventos == [], "una zona rota no registra toques mientras siga rota"


def test_placebo_no_solapa_zonas_reales():
    velas = _velas_con_pivotes([100, 140, 101, 141, 100.5, 139, 99.5, 140.5])
    zonas = construir_zonas(velas, "1h", k=0.50, piv=2)
    for pb in bandas_placebo(zonas, velas):
        for z in zonas:
            if z["formed_idx"] is None:
                continue
            assert pb["high"] < z["low"] or pb["low"] > z["high"], \
                "el placebo no puede pisar una zona real"
