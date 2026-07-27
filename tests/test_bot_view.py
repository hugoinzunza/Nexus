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
    # "Riesgo" cedio su lugar a "R total" y "P&L", que lo subsumen: P&L = R x riesgo.
    for col in ("Entrada", "Precio", "SL", "TP", "RR", "Vivo", "Parciales",
                "R total", "Tiempo"):
        assert f"<th>{col}</th>" in src, f"falta la columna {col}"
    assert "<th>P&L</th>" in src


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


def test_el_resultado_vivo_pondera_los_parciales_ya_tomados():
    """No basta con precio contra entrada: si ya se cerro la mitad en TP1, esa mitad
    esta REALIZADA y solo el resto sigue expuesto.

    Verificado contra el SOL real del 2026-07-27: entrada 75,34, SL 74,857 (R=0,483),
    qty 18,633 -> qty_open 9,317 tras TP1. A precio 75,86 el tramo vivo da 1,077R por
    unidad x 50% = 0,538, mas 0,50 ya realizado = 1,038 -> +1,04 en pantalla, y
    1,038 x $9 de riesgo = $9,34. Ambos coincidieron.
    """
    bloque = js().split("function resultadoVivo(t, precio) {")[1].split("\n}")[0]
    assert "qty_open" in bloque and "qo / q" in bloque, "no pondera el tramo vivo"
    assert "realized_r" in bloque, "ignora los parciales ya realizados"
    assert "realizado + rVivo" in bloque, "el total no suma realizado y vivo"
    # R por unidad = |entrada - SL|, no una constante ni el TP
    assert "Math.abs(entry - sl)" in bloque


def test_el_signo_respeta_la_direccion():
    """En un short el precio BAJANDO gana. Sin el signo, la tabla pintaria en rojo un
    trade ganador."""
    bloque = js().split("function resultadoVivo(t, precio) {")[1].split("\n}")[0]
    assert 'const signo = t.dir === "long" ? 1 : -1' in bloque
    assert "* signo" in bloque


def test_sin_precio_no_se_pinta_ganando_ni_perdiendo():
    """Si Binance no responde y no hay respaldo, la fila muestra "—" sin color. Pintar
    verde o rojo sin dato sugiere un resultado que no se conoce."""
    bloque = js().split("function resultadoVivo(t, precio) {")[1].split("\n}")[0]
    assert "!Number.isFinite(precio)" in bloque
    assert "precio: null" in bloque
    fila = js().split("function abiertosHtml")[1].split("\n}")[0]
    assert "r === null ? \"\"" in fila, "sin dato no puede asignarse clase pos/neg"


def test_la_fuente_del_precio_se_declara():
    """Binance en vivo, ingesta del VPS o nada: el que mira tiene que saber cual, sobre
    todo si el respaldo esta viejo."""
    src = js()
    assert "preciosVivos.fuente" in src
    assert "Binance en vivo" in src and "ingesta VPS" in src
    assert "precio: ${preciosVivos.fuente}" in src


def test_el_precio_lo_pide_el_NAVEGADOR_y_no_el_servidor():
    """Railway responde 451 desde Binance; el navegador no. Pedirlo del lado del
    servidor habria obligado a tocar la ingesta del VPS para algo de solo lectura."""
    src = js()
    assert "fapi.binance.com/fapi/v1/ticker/price" in src
    py = open(os.path.join(ROOT, "modules/bot/module.py"), encoding="utf-8").read()
    assert "ticker/price" not in py, "el precio se movio al servidor, que esta bloqueado"
