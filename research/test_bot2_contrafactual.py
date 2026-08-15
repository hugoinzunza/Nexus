#!/usr/bin/env python3
"""Tests de BOT2.

Lo que se protege no es un número —todavía no hay ninguno— sino las propiedades que
hacen que este experimento valga algo cuando por fin haya datos: causalidad, reglas
congeladas de antemano, y aislamiento total de la ejecución.
"""
from __future__ import annotations

import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import bot2_contrafactual as bot2  # noqa: E402

DOC = os.path.join(WT, "docs", "BOT2_MUROS_COINGLASS_REGLAS_CONGELADAS_2026-07-26.md")


def _fila(**kw):
    base = {"captured_at": "2026-07-26T00:00:00+00:00", "price": 64_000,
            "bids": [], "asks": []}
    base.update(kw)
    return base


def test_solo_se_usan_capturas_ANTERIORES_a_la_activacion():
    """Usar el libro del futuro seria el mismo error que ya cometimos en
    `active_leg()` y en la barra de activacion del backtest."""
    t = 1_781_000_000
    capturas = [
        (t - 300, _fila(price=64_000)),      # 5 min antes -> es la buena
        (t + 60, _fila(price=70_000)),       # 1 min despues -> prohibida
    ]
    previa = bot2.captura_previa(capturas, t)
    assert previa is not None
    assert previa[1]["price"] == 64_000, "uso una captura POSTERIOR a la activacion"


def test_una_captura_demasiado_vieja_no_cuenta():
    """Mejor sin contexto que con un libro de hace horas: los muros se mueven."""
    t = 1_781_000_000
    capturas = [(t - 3 * 3600, _fila())]
    assert bot2.captura_previa(capturas, t) is None


def test_r1_veta_solo_con_muro_OPUESTO_dentro_del_camino_a_TP1():
    """Un long se veta por un ASK entre la entrada y +1R. Un muro del mismo lado
    (bid) no estorba, y uno mas alla de TP1 tampoco: no esta en el camino."""
    largo = {"dir": "long", "entry": 64_000.0, "sl": 63_000.0, "tp": 70_000.0}

    # ask a mitad de camino a TP1 (65.000) -> veta
    dentro = _fila(asks=[[64_500, 9_000_000]])
    assert bot2.aplicar_reglas(largo, dentro)["r1_veta"] is True

    # ask mas alla de TP1 -> NO veta
    fuera = _fila(asks=[[66_000, 9_000_000]])
    assert bot2.aplicar_reglas(largo, fuera)["r1_veta"] is False

    # bid en el camino: es del mismo lado, no es un obstaculo
    mismo = _fila(bids=[[64_500, 9_000_000]])
    assert bot2.aplicar_reglas(largo, mismo)["r1_veta"] is False

    # y un short se veta con BID, no con ask
    corto = {"dir": "short", "entry": 64_000.0, "sl": 65_000.0, "tp": 58_000.0}
    assert bot2.aplicar_reglas(corto, _fila(bids=[[63_500, 9_000_000]]))["r1_veta"] is True
    assert bot2.aplicar_reglas(corto, _fila(asks=[[63_500, 9_000_000]]))["r1_veta"] is False


def test_el_umbral_del_muro_no_se_ajusta_en_el_codigo():
    """Esta congelado en el doc. Cambiarlo despues de ver resultados convierte la
    hipotesis en decoracion; si se prueban varios, se publican TODOS."""
    largo = {"dir": "long", "entry": 64_000.0, "sl": 63_000.0, "tp": 70_000.0}
    chico = _fila(asks=[[64_500, bot2.UMBRAL_MURO - 1]])
    justo = _fila(asks=[[64_500, bot2.UMBRAL_MURO]])
    assert bot2.aplicar_reglas(largo, chico)["r1_veta"] is False
    assert bot2.aplicar_reglas(largo, justo)["r1_veta"] is True

    doc = open(DOC, encoding="utf-8").read()
    assert "5.000.000 USD" in doc, "el umbral del codigo y el del doc deben calzar"
    assert str(bot2.UMBRAL_MURO) == "5000000"


def test_r2_recorta_el_TP_justo_ANTES_del_muro():
    largo = {"dir": "long", "entry": 64_000.0, "sl": 63_000.0, "tp": 70_000.0}
    r = bot2.aplicar_reglas(largo, _fila(asks=[[66_000, 9_000_000]]))
    assert r["r2_tp"] is not None and r["r2_tp"] < 66_000


def test_r3_corre_el_SL_DETRAS_del_muro():
    largo = {"dir": "long", "entry": 64_000.0, "sl": 63_000.0, "tp": 70_000.0}
    r = bot2.aplicar_reglas(largo, _fila(bids=[[62_500, 9_000_000]]))
    assert r["r3_sl"] is not None and r["r3_sl"] < 62_500


def test_bot2_no_puede_tocar_una_orden():
    """Aislamiento por construccion: no importa modules/bot ni modules/coinglass, y
    el join con el contexto se hace OFFLINE leyendo archivos."""
    src = open(os.path.join(WT, "research/bot2_contrafactual.py"), encoding="utf-8").read()
    assert "modules.bot" not in src
    assert "modules.coinglass" not in src
    assert "modules.trading" not in src
    for peligro in ("place_order", "create_order", "requests.post", "urlopen"):
        assert peligro not in src


def test_las_reglas_estan_congeladas_con_predicciones_escritas():
    """Escribir la prediccion ANTES evita el sesgo de retrospectiva. R2 y R3 se
    declaran como controles que se espera que FALLEN: si salieran positivas habria
    que sospechar del pipeline antes que celebrar."""
    doc = open(DOC, encoding="utf-8").read()
    assert "antes de mirar resultados" in doc.lower()
    assert "control negativo" in doc
    assert "Predicciones registradas" in doc
    # los criterios de exito tambien congelados
    assert "n ≥ 50" in doc
    assert "no cruza cero" in doc
    assert "quitar el 1% mejor" in doc
    assert "corrección por pruebas" in doc
    # y la bitacora para no editar lo original
    assert "Bitácora de cambios" in doc


def test_declara_que_no_responde_pronto():
    """Un evaluador nuevo puede dar la ilusion de que la respuesta esta cerca."""
    doc = open(DOC, encoding="utf-8").read()
    src = open(os.path.join(WT, "research/bot2_contrafactual.py"), encoding="utf-8").read()
    # sin frases que el salto de linea del markdown pueda partir
    assert "no va a responder pronto" in doc
    assert "toma mas de un ano" in src


def test_marcado_como_research():
    ruta = os.path.join(WT, "research", "bot2_contrafactual_results.json")
    if not os.path.isfile(ruta):
        return
    with open(ruta, encoding="utf-8") as fh:
        meta = json.load(fh)["meta"]
    assert meta["research_only"] is True
    assert meta["execution_enabled"] is False
    assert meta["validated"] is False
