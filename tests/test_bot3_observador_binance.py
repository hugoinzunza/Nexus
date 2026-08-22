"""Observador Bot3.v13 — gates del cliente público (checkpoint 1 del bloque 2).

Diseño rev.8 §10. La red se INYECTA: nada de esto toca Binance.
"""
import json
import os

import pytest

from modules.bot3.observador import binance as B
from modules.bot3.observador import contrato as C
from modules.bot3.v9.contract import TF_MS
from modules.bot3.v9.store import ser_vela

DUR = TF_MS["15m"]
BASE = 1_700_000_000_000 // DUR * DUR


def fila(t, o=1.5, h=2.5, l=0.5, c=2.0, v=10.25, dur=DUR):
    """Fila cruda de Binance: numéricos como CADENA, igual que la API."""
    return [t, str(o), str(h), str(l), str(c), str(v), t + dur - 1,
            "0", 0, "0", "0", "0"]


def fetcher(paginas, reloj=None):
    """`fetch` inyectado. `paginas` es una lista de respuestas sucesivas."""
    estado = {"i": 0, "pedidos": []}

    def fetch(url, params):
        if url == C.ENDPOINT_TIME:
            if isinstance(reloj, Exception):
                raise reloj
            return reloj
        estado["pedidos"].append(params)
        i = estado["i"]
        estado["i"] += 1
        return paginas[i] if i < len(paginas) else []

    fetch.estado = estado
    return fetch


# ------------------------------------------------------------------ reloj
def test_el_reloj_de_elegibilidad_es_el_de_binance():
    assert B.eligibility_time(fetcher([], {"serverTime": BASE})) == BASE


def test_sin_serverTime_no_se_ingiere_y_no_hay_fallback_al_mac():
    """Nunca se cae en silencio al reloj local: sin reloj del exchange, el
    ciclo no ingiere nada."""
    for reloj in (None, {}, {"serverTime": "123"}, {"serverTime": 0},
                  {"serverTime": -1}, {"serverTime": 1.5},
                  RuntimeError("timeout")):
        with pytest.raises(B.RelojIndisponible):
            B.eligibility_time(fetcher([], reloj))
    fuente = open(B.__file__, encoding="utf-8").read()
    for prohibido in ("time.time", "datetime.now", "utcnow"):
        assert prohibido not in fuente, prohibido


def test_la_deriva_del_reloj_local_se_ve_pero_no_decide():
    assert B.deriva(BASE, BASE) is None
    assert B.deriva(BASE, BASE + C.DERIVA_MAX_MS) is None
    inc = B.deriva(BASE, BASE + C.DERIVA_MAX_MS + 1)
    assert inc["tipo"] == "deriva_de_reloj"
    assert inc["delta_ms"] == C.DERIVA_MAX_MS + 1
    # y en el otro sentido: un Mac atrasado también se ve
    assert B.deriva(BASE, BASE - C.DERIVA_MAX_MS - 1)["delta_ms"] > 0


# ------------------------------------------------------------ elegibilidad
def test_la_vela_en_curso_se_descarta_siempre():
    cierre = BASE + DUR - 1                        # último ms del intervalo
    assert not B.es_elegible(BASE, cierre, cierre)          # aún abierta
    assert not B.es_elegible(BASE, cierre, cierre + 1)      # cerró, sin margen
    assert not B.es_elegible(BASE, cierre, cierre + C.MARGEN_CIERRE_MS)
    assert B.es_elegible(BASE, cierre, cierre + 1 + C.MARGEN_CIERRE_MS)


# -------------------------------------------------------------- normalización
def test_el_mapeo_es_explicito_y_valida_la_forma():
    v = B.normalizar_fila(fila(BASE, o=1.25, h=3.5, l=0.75, c=2.5, v=9.5),
                          "15m")
    assert v == {"t": BASE, "o": 1.25, "h": 3.5, "l": 0.75, "c": 2.5,
                 "v": 9.5, "close_time": BASE + DUR - 1}
    with pytest.raises(B.PaginaInvalida, match="incompleta"):
        B.normalizar_fila([BASE, "1"], "15m")
    with pytest.raises(B.PaginaInvalida, match="no numérica"):
        B.normalizar_fila(fila(BASE, o="x"), "15m")
    with pytest.raises(B.PaginaInvalida, match="desalineado"):
        B.normalizar_fila(fila(BASE + 1), "15m")
    with pytest.raises(B.PaginaInvalida, match="intervalo distinto"):
        B.normalizar_fila(fila(BASE, dur=TF_MS["4h"]), "15m")


def test_el_push_serializa_igual_que_el_snapshot():
    """El gate que evita la tormenta: re-ingerir por push una vela ya sellada
    desde el snapshot NO puede producir incidencia, así que las dos rutas
    tienen que dar los MISMOS bytes canónicos."""
    ruta = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "klines_BTCUSDT_15m.json")
    if not os.path.exists(ruta):
        pytest.skip("sin klines versionadas")
    del_snapshot = json.load(open(ruta, encoding="utf-8"))[:200]
    for fila_snap in del_snapshot:
        # la misma vela, tal como la devolvería Binance: numéricos en CADENA
        crudo = [fila_snap["t"], repr(fila_snap["o"]), repr(fila_snap["h"]),
                 repr(fila_snap["l"]), repr(fila_snap["c"]),
                 repr(fila_snap["v"]), fila_snap["t"] + DUR - 1,
                 "0", 0, "0", "0", "0"]
        del_push = B.normalizar_fila(crudo, "15m")
        del_push.pop("close_time")
        assert ser_vela(del_push) == ser_vela(fila_snap), fila_snap["t"]


# --------------------------------------------------------------- paginación
def test_el_inicio_incluye_exactamente_el_solape():
    ultimo = BASE + 10 * DUR
    inicio = B.inicio_paginacion(ultimo, "15m")
    assert inicio == ultimo - (C.RESOLAPE - 1) * DUR
    assert inicio % DUR == 0                       # alineado a la grilla
    assert (ultimo - inicio) // DUR + 1 == C.RESOLAPE
    assert B.inicio_paginacion(0, "15m") == 0      # no se va a negativo


def test_pagina_vacia_termina_la_paginacion():
    f = fetcher([[]])
    assert B.paginar(f, "BTCUSDT", "15m", BASE, BASE + 10 ** 9) == []


def test_backlog_multipagina_con_progreso_estricto():
    ahora = BASE + 5000 * DUR
    pag1 = [fila(BASE + i * DUR) for i in range(3)]
    pag2 = [fila(BASE + (3 + i) * DUR) for i in range(3)]
    f = fetcher([pag1, pag2, []])
    velas = B.paginar(f, "BTCUSDT", "15m", BASE, ahora, limite=3)
    assert [v["t"] for v in velas] == [BASE + i * DUR for i in range(6)]
    inicios = [p["startTime"] for p in f.estado["pedidos"]]
    assert inicios[1] == pag1[-1][0] + DUR         # avance por openTime + dur
    assert inicios[2] == pag2[-1][0] + DUR
    assert inicios == sorted(set(inicios))         # estrictamente creciente


def test_una_pagina_llena_que_no_avanza_falla_cerrado():
    """Sería un loop infinito. Se prefiere el fallo."""
    repetida = [fila(BASE - 5 * DUR)]
    f = fetcher([repetida, repetida, repetida])
    with pytest.raises(B.SinProgreso, match="no avanza"):
        B.paginar(f, "BTCUSDT", "15m", BASE, BASE + 10 ** 9, limite=1)


def test_una_pagina_invalida_se_descarta_entera():
    ahora = BASE + 5000 * DUR
    casos = {
        "fuera de orden": [fila(BASE + DUR), fila(BASE)],
        "duplicada": [fila(BASE), fila(BASE)],
        "desalineado": [fila(BASE), fila(BASE + DUR + 7)],
        "intervalo distinto": [fila(BASE), fila(BASE + DUR, dur=TF_MS["4h"])],
        "incompleta": [fila(BASE), [BASE + DUR, "1"]],
    }
    for nombre, pagina in casos.items():
        f = fetcher([pagina, []])
        with pytest.raises(B.PaginaInvalida):
            B.paginar(f, "BTCUSDT", "15m", BASE, ahora)
    # y la repetición ENTRE páginas también
    f = fetcher([[fila(BASE), fila(BASE + DUR)],
                 [fila(BASE + DUR), fila(BASE + 2 * DUR)]])
    with pytest.raises(B.PaginaInvalida, match="repetida entre páginas"):
        B.paginar(f, "BTCUSDT", "15m", BASE, ahora, limite=2)


def test_solo_vuelven_velas_elegibles():
    """La vela en curso llega en la respuesta y NO puede entrar."""
    cerrada = fila(BASE)
    abierta = fila(BASE + DUR)
    ahora = BASE + DUR + 1 + C.MARGEN_CIERRE_MS    # la segunda aún no cierra
    f = fetcher([[cerrada, abierta], []])
    velas = B.paginar(f, "BTCUSDT", "15m", BASE, ahora, limite=2)
    assert [v["t"] for v in velas] == [BASE]
    assert "close_time" not in velas[0]            # no viaja al almacén


def test_el_simbolo_se_valida_contra_el_universo_congelado():
    for ajeno in ("LTCUSDT", "BTCBUSD", "btcusdt", ""):
        with pytest.raises(B.PaginaInvalida):
            B.validar_simbolo(ajeno)
    for propio in C.UNIVERSO:
        B.validar_simbolo(propio)


def test_la_cadencia_de_red_no_cambia_los_bytes_aceptados():
    """La misma serie repartida en distinto número de páginas da exactamente
    las mismas velas: el troceado de la red no puede alterar el resultado."""
    ahora = BASE + 5000 * DUR
    todas = [fila(BASE + i * DUR) for i in range(9)]
    una = B.paginar(fetcher([todas, []]), "BTCUSDT", "15m", BASE, ahora,
                    limite=9)
    tres = B.paginar(fetcher([todas[0:3], todas[3:6], todas[6:9], []]),
                     "BTCUSDT", "15m", BASE, ahora, limite=3)
    assert [ser_vela(v) for v in una] == [ser_vela(v) for v in tres]


def test_el_cliente_no_abre_sockets_por_su_cuenta():
    """La red se inyecta: por eso se puede probar entero sin tocar Binance."""
    import re
    fuente = open(B.__file__, encoding="utf-8").read()
    # Se mira el CÓDIGO: la cabecera explica por qué no abre sockets.
    codigo = re.sub(r'"""(.|\n)*?"""', "", fuente)
    for prohibido in ("requests", "urllib", "http.client", "socket",
                      "aiohttp", "httpx", "import ssl"):
        assert prohibido not in codigo, prohibido
