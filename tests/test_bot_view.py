"""Vista del bot: los trades ABIERTOS de la fase, no solo su cantidad."""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "modules/bot/public/app.js")
HTML = os.path.join(ROOT, "modules/bot/public/index.html")


def js():
    return open(APP, encoding="utf-8").read()


def test_los_abiertos_se_listan_y_no_solo_se_cuentan():
    """`open` se usaba UNICAMENTE para el contador "Dry abiertos: 2": se sabia que
    habia dos y no cuales. Con datos reales del VPS son SOL (rr 19,3, mitad tomada en
    TP1) y XRP (rr 5,2, entera) — informacion que el contador no daba."""
    src = js()
    assert "function abiertosHtml" in src
    assert "abiertosHtml(open)" in src, "la tabla no se inserta en la seccion"
    for col in ("Entrada", "SL", "TP", "RR", "Vivo", "Parciales", "Riesgo", "Tiempo"):
        assert f"<th>{col}</th>" in src, f"falta la columna {col}"


def test_se_declara_que_son_papel_y_no_posiciones_reales():
    """El bloque `#position` de mas abajo muestra posiciones REALES de Binance y esta
    vacio porque `live=false`. Poner los de papel al lado sin rotularlos diria que hay
    exposicion donde no la hay."""
    src = js()
    assert "papel, no son posiciones reales" in src


def test_el_tamano_vivo_sale_de_qty_open_y_no_de_qty():
    """Si hubo parciales, `qty_open` baja y `qty` deja de describir lo expuesto. En el
    caso real de SOL: qty 18,633 -> qty_open 9,317 tras TP1, o sea 50% vivo."""
    src = js()
    bloque = src.split("function abiertosHtml")[1].split("\n}")[0]
    assert "qty_open" in bloque
    assert "t.partials" in bloque, "los parciales tomados deben verse"


def test_el_RR_alto_se_marca_pero_no_se_filtra():
    """El estudio del 2026-07-26 encontro que DENTRO de rr>=5 mas RR predice PEOR
    (Q2 rr~8 -> +0,815R y 21,1% de TP; Q5 rr>=21,2 -> +0,142R y 4,8%). NO esta
    pre-registrado ni confirmado, asi que marcarlo es lo maximo que corresponde:
    filtrar por un hallazgo in-sample seria actuar sobre ruido."""
    src = js()
    bloque = src.split("function abiertosHtml")[1].split("\n}")[0]
    assert "rrAlto" in bloque
    assert "rr-alto" in bloque
    # y no se excluye ninguna fila por RR
    assert ".filter(" not in bloque.split("const filas")[1].split(".map(")[0]


def test_los_estaticos_llevan_version_para_no_servirse_cacheados():
    html = open(HTML, encoding="utf-8").read()
    assert "app.js?v=" in html and "styles.css?v=" in html
