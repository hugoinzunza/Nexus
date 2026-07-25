#!/usr/bin/env python3
"""Tests del cruce entre los niveles reales de CoinGlass y los setups del Diario.

Lo que se protege es la causalidad. Este script va a correr dentro de meses, cuando
nadie recuerde cómo se armó, y la tentación de tomar "la captura más cercana" en vez
de "la última anterior" produce un resultado precioso y falso.
"""
from __future__ import annotations

import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import coinglass_imanes_forward as fwd  # noqa: E402


def test_los_imanes_se_toman_del_lado_correcto_del_precio():
    fila = {
        "bids": [[63_750, 1_800_000], [61_300, 78_600_000], [65_000, 999]],
        "asks": [[64_750, 1_630_000], [65_500, 1_290_000], [60_000, 999]],
    }
    abajo, arriba = fwd.imanes_reales(fila, 64_238)

    # el bid de 65.000 esta ARRIBA del precio: no es soporte, se ignora
    assert abajo["precio"] == 63_750
    # y el ask de 60.000 esta ABAJO: tampoco es resistencia
    assert arriba["precio"] == 64_750

    # el mas cercano de cada lado, no el mas grande: el de 61.300 es 43x mayor
    assert abajo["usd"] == 1_800_000
    assert abajo["distancia_pct"] > 0    # se reporta como magnitud, con signo aparte
    assert arriba["distancia_pct"] > 0


def test_sin_muros_de_un_lado_devuelve_none():
    abajo, arriba = fwd.imanes_reales({"bids": [], "asks": []}, 64_000)
    assert abajo is None and arriba is None


def test_solo_se_usan_capturas_ANTERIORES_a_la_activacion(tmp_path, monkeypatch):
    """El corazon del asunto: usar una captura posterior al toque seria mirar el
    libro del futuro, que es exactamente el error que ya cometimos en active_leg().
    """
    archivo = tmp_path / "archivo.jsonl"
    caliente = tmp_path / "caliente.json"
    setups = tmp_path / "setups.json"

    # el setup se activa a las 12:00:00Z
    activacion = 1_781_000_000
    import datetime as dt
    f = lambda off: dt.datetime.fromtimestamp(activacion + off, dt.timezone.utc).isoformat()

    caliente.write_text(json.dumps([
        {"captured_at": f(-300), "price": 64_000,      # 5 min ANTES -> es la buena
         "bids": [[63_500, 1_000_000]], "asks": [[64_500, 2_000_000]]},
        {"captured_at": f(+60), "price": 70_000,       # 1 min DESPUES -> prohibida
         "bids": [[69_000, 9_000_000]], "asks": [[71_000, 9_000_000]]},
    ]), encoding="utf-8")
    archivo.write_text("", encoding="utf-8")
    setups.write_text(json.dumps([
        {"key": "BTC_USDT:1h:long:1", "pair": "BTC_USDT", "dir": "long",
         "ts_activated": activacion, "entry": 64_000, "sl": 63_000, "rr": 9.0,
         "result_r": -1.0},
    ]), encoding="utf-8")

    monkeypatch.setattr(fwd, "ARCHIVO", str(archivo))
    monkeypatch.setattr(fwd, "CALIENTE", str(caliente))
    monkeypatch.setattr(fwd, "SETUPS", str(setups))
    monkeypatch.setattr(fwd, "OUT_JSON", str(tmp_path / "out.json"))
    fwd.main()

    salida = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert salida["meta"]["con_cobertura"] == 1
    fila = salida["filas"][0]
    assert fila["precio_captura"] == 64_000, "uso la captura POSTERIOR"
    assert fila["desfase_seg"] == 300


def test_una_captura_demasiado_vieja_no_cuenta(tmp_path, monkeypatch):
    """Mejor sin dato que con un libro de hace horas: los muros se mueven."""
    import datetime as dt
    activacion = 1_781_000_000
    viejo = dt.datetime.fromtimestamp(
        activacion - 3 * 3600, dt.timezone.utc).isoformat()

    caliente = tmp_path / "c.json"
    caliente.write_text(json.dumps([
        {"captured_at": viejo, "price": 64_000, "bids": [], "asks": []}]),
        encoding="utf-8")
    setups = tmp_path / "s.json"
    setups.write_text(json.dumps([
        {"key": "k", "pair": "BTC_USDT", "dir": "long", "ts_activated": activacion}]),
        encoding="utf-8")

    monkeypatch.setattr(fwd, "ARCHIVO", str(tmp_path / "no_existe.jsonl"))
    monkeypatch.setattr(fwd, "CALIENTE", str(caliente))
    monkeypatch.setattr(fwd, "SETUPS", str(setups))
    monkeypatch.setattr(fwd, "OUT_JSON", str(tmp_path / "out.json"))
    fwd.main()

    salida = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert salida["meta"]["con_cobertura"] == 0
    assert salida["meta"]["sin_cobertura"] == 1


def test_una_linea_cortada_no_invalida_el_archivo(tmp_path, monkeypatch):
    """Es append-only sobre un proceso que puede morir a media escritura."""
    archivo = tmp_path / "a.jsonl"
    archivo.write_text(
        '{"captured_at":"2026-07-01T00:00:00+00:00","price":1,"bids":[],"asks":[]}\n'
        '{"captured_at":"2026-07-01T00:05:00+00:00","pri\n'          # cortada
        '{"captured_at":"2026-07-01T00:10:00+00:00","price":3,"bids":[],"asks":[]}\n',
        encoding="utf-8")
    monkeypatch.setattr(fwd, "ARCHIVO", str(archivo))
    monkeypatch.setattr(fwd, "CALIENTE", str(tmp_path / "no.json"))
    assert len(fwd.cargar_capturas()) == 2


def test_declara_que_esto_no_responde_pronto():
    """Un archivo nuevo puede generar la ilusion de que la respuesta esta cerca. El
    colector captura solo BTC y el Diario da ~15 setups de BTC cada 43 dias."""
    src = open(os.path.join(WT, "research/coinglass_imanes_forward.py"),
               encoding="utf-8").read()
    assert "anos, no meses" in src
