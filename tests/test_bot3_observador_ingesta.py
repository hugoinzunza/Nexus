"""Observador Bot3.v13 — gates de ingesta, lag y precondición H4.

Checkpoint 2 del bloque 2. La red se inyecta; los almacenes son reales.
"""
import pytest

from modules.bot3.observador import binance as B
from modules.bot3.observador import contrato as C
from modules.bot3.observador import ingesta as I
from modules.bot3.v9 import store as S
from modules.bot3.v9.contract import GENESIS_H4, TF_MS

DUR = TF_MS["15m"]
DUR4 = TF_MS["4h"]
BASE = 1_700_000_000_000 // DUR * DUR
# Alineada a la grilla H4 y CONTEMPORÁNEA de BASE: si las dos series
# vivieran en épocas distintas, el lag mediría otra cosa.
BASE4 = BASE // DUR4 * DUR4


def fila(t, dur=DUR):
    return [t, "1.5", "2.5", "0.5", "2.0", "10.25", t + dur - 1,
            "0", 0, "0", "0", "0"]


def fetch_de(paginas_por_stream, registro=None):
    """`fetch` inyectado que sirve páginas por (símbolo, intervalo)."""
    estado = {}

    def fetch(url, params):
        if registro is not None:
            registro.append((url, params))
        if url == C.ENDPOINT_TIME:
            raise AssertionError("la ingesta NO puede muestrear el reloj")
        k = (params["symbol"], params["interval"])
        i = estado.get(k, 0)
        estado[k] = i + 1
        paginas = paginas_por_stream.get(k, [])
        return paginas[i] if i < len(paginas) else []

    return fetch


def almacen(mercado, tf, velas, ancla=None):
    dur = TF_MS[tf]
    a = S.Almacen(mercado, tf)
    a.nacer_en(ancla if ancla is not None else velas[0])
    a.ofrecer([{"t": t, "o": 1.5, "h": 2.5, "l": 0.5, "c": 2.0, "v": 10.25}
               for t in velas], "push")
    a.drenar()
    return a


# ------------------------------------------------------------------- lag
def test_el_lag_se_evalua_por_mercado_Y_por_timeframe():
    """14 evaluaciones, no una: un fallo en H4 no puede quedar oculto por un
    M15 fresco."""
    m15 = {m: almacen(m, "15m", [BASE + i * DUR for i in range(100)])
           for m in ("BTCUSDT", "ETHUSDT")}
    ahora = BASE + 100 * DUR                        # M15 justo al día
    h4 = {m: almacen(m, "4h", [BASE4 - (3 - i) * DUR4 for i in range(3)])
          for m in ("BTCUSDT", "ETHUSDT")}          # H4 varios cierres atrás
    # M15 al día, H4 muy atrasado
    stale = I.streams_stale(m15, h4, ahora)
    assert [(m, tf) for m, tf, _ in stale] == [("BTCUSDT", "4h"),
                                               ("ETHUSDT", "4h")]
    assert all(atraso > C.LAG_MAX_MS["4h"] for _, _, atraso in stale)


def test_el_lag_cuenta_desde_el_ultimo_instante_resuelto():
    a = almacen("BTCUSDT", "15m", [BASE + i * DUR for i in range(5)])
    fin = BASE + 5 * DUR                            # cierre de la última vela
    assert I.lag(a, "15m", fin) == 0
    assert I.lag(a, "15m", fin + 1234) == 1234
    assert I.lag(a, "15m", fin - 999) == 0          # nunca negativo
    vacio = S.Almacen("X", "15m")
    assert I.lag(vacio, "15m", fin) == 0            # sin nacer: no hay atraso


# --------------------------------------------------------- precondición H4
def test_la_grilla_h4_se_resuelve_en_O1_por_el_avance_contiguo():
    """El almacén solo avanza contiguamente —`drenar` appendea el prefijo
    continuo y un marcador de hueco mueve `ultimo_t`—, así que basta comparar
    `ultimo_t` con el último cierre esperado."""
    a = almacen("BTCUSDT", "4h", [BASE4 + i * DUR4 for i in range(10)])
    ultimo = BASE4 + 9 * DUR4
    assert I.grilla_h4_resuelta(a, ultimo + DUR4) is None      # justo al día
    assert I.grilla_h4_resuelta(a, ultimo + DUR4 + 1) is None
    assert I.grilla_h4_resuelta(a, ultimo + 2 * DUR4) == ultimo + DUR4
    # y todo `t <= ultimo_t` está resuelto, sin barrer la grilla
    for k in range(10):
        assert I.grilla_h4_resuelta(a, BASE4 + (k + 1) * DUR4) is None


def test_un_hueco_sellado_tambien_resuelve_la_grilla():
    """Ausencia declarada causalmente cuenta como resuelta: el marcador mueve
    `ultimo_t` igual que una vela."""
    a = S.Almacen("BTCUSDT", "4h")
    a.nacer_en(BASE4)
    faltante = BASE4 + DUR4
    a.ofrecer([{"t": BASE4, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1}],
              "push")
    a.drenar()
    # el hueco se declara con el watermark local (N cierres propios después)
    a.ofrecer([{"t": faltante + (i + 1) * DUR4, "o": 1, "h": 2, "l": 0.5,
                "c": 1.5, "v": 1} for i in range(3)], "push")
    a.drenar()
    assert I.grilla_h4_resuelta(a, faltante + DUR4) == faltante   # bloquea
    assert a.declarar_hueco_local() is not None
    assert I.grilla_h4_resuelta(a, faltante + DUR4) is None       # resuelto


def test_no_se_procesa_ningun_lote_con_h4_sin_resolver():
    """`lote_finalizable` solo mira M15: sin esta precondición el motor
    decidiría con un rector congelado."""
    ahora = BASE4 + 12 * DUR4
    m15 = {"BTCUSDT": almacen("BTCUSDT", "15m",
                              [BASE + i * DUR for i in range(400)])}
    h4 = {"BTCUSDT": almacen("BTCUSDT", "4h",
                             [BASE4 + i * DUR4 for i in range(10)])}
    faltan = I.precondicion_h4(h4, ahora)
    assert faltan == [("BTCUSDT", BASE4 + 10 * DUR4)]
    decision = I.puede_procesar(m15, h4, ahora, ahora)
    assert decision["procesar"] is False
    assert decision["h4_sin_resolver"] == faltan


def test_con_todo_al_dia_el_lote_se_procesa():
    m15 = {"BTCUSDT": almacen("BTCUSDT", "15m",
                              [BASE + i * DUR for i in range(20)])}
    h4 = {"BTCUSDT": almacen("BTCUSDT", "4h",
                             [BASE4 + i * DUR4 for i in range(10)])}
    T = BASE + 20 * DUR
    decision = I.puede_procesar(m15, h4, T, T)
    assert decision == {"procesar": True, "catch_up": False,
                        "streams_stale": [], "h4_sin_resolver": []}


def test_catch_up_ingiere_pero_no_procesa():
    """Con cualquier stream stale se sella, pero no se procesa ningún lote."""
    m15 = {"BTCUSDT": almacen("BTCUSDT", "15m",
                              [BASE + i * DUR for i in range(20)])}
    h4 = {"BTCUSDT": almacen("BTCUSDT", "4h",
                             [BASE4 + i * DUR4 for i in range(10)])}
    T = BASE + 20 * DUR
    muy_tarde = BASE4 + 10 * DUR4 + 10 * C.LAG_MAX_MS["4h"]
    decision = I.puede_procesar(m15, h4, T, muy_tarde)
    assert decision["procesar"] is False
    assert decision["catch_up"] is True
    assert [(m, tf) for m, tf, _ in decision["streams_stale"]] == [
        ("BTCUSDT", "15m"), ("BTCUSDT", "4h")]


# ---------------------------------------------------------------- ingesta
def test_la_ingesta_ofrece_drena_y_sella():
    a = almacen("BTCUSDT", "15m", [BASE + i * DUR for i in range(3)])
    nuevas = [fila(BASE + (3 + i) * DUR) for i in range(4)]
    fetch = fetch_de({("BTCUSDT", "15m"): [nuevas, []]})
    parte = I.ingerir(fetch, "BTCUSDT", "15m", a, BASE + 100 * DUR)
    assert parte["velas"] == len(nuevas)
    assert a.ultimo_t == BASE + 6 * DUR
    assert parte["observacion_probatoria"] is False
    assert parte["huecos"] == []


def test_el_solape_no_produce_incidencia_sobre_datos_identicos():
    """Las velas re-pedidas son idénticas: reofrecerlas no puede ensuciar el
    libro con `vela_revisada`."""
    a = almacen("BTCUSDT", "15m", [BASE + i * DUR for i in range(5)])
    fetch = fetch_de({("BTCUSDT", "15m"): [
        [fila(BASE + i * DUR) for i in range(2, 6)], []]})
    I.ingerir(fetch, "BTCUSDT", "15m", a, BASE + 100 * DUR)
    assert a.incidencias == []


def test_una_vela_que_no_llega_es_observacion_probatoria():
    """La señal para la máquina de silencio: paginación válida y COMPLETA que
    no trajo la vela esperada."""
    a = almacen("BTCUSDT", "4h", [BASE4 + i * DUR4 for i in range(3)])
    esperada = BASE4 + 3 * DUR4
    # la respuesta trae el solape y la SIGUIENTE, pero no la esperada
    fetch = fetch_de({("BTCUSDT", "4h"): [
        [fila(BASE4 + 2 * DUR4, DUR4), fila(esperada + DUR4, DUR4)], []]})
    parte = I.ingerir(fetch, "BTCUSDT", "4h", a, BASE4 + 10 * DUR4)
    assert parte["esperada"] == esperada
    assert parte["observacion_probatoria"] is True


def test_un_error_de_red_no_es_evidencia_de_silencio():
    """Si la paginación falla, NO hay observación probatoria: el mercado no
    enmudeció, se cayó la consulta."""
    a = almacen("BTCUSDT", "4h", [BASE4 + i * DUR4 for i in range(3)])

    def fetch(url, params):
        raise B.PaginaInvalida("página rota")

    with pytest.raises(B.PaginaInvalida):
        I.ingerir(fetch, "BTCUSDT", "4h", a, BASE4 + 10 * DUR4)


def test_un_ciclo_usa_UN_solo_serverTime_para_los_14_streams():
    """El módulo no muestrea el reloj: lo recibe. Por eso un ciclo no puede
    terminar usando dos `serverTime` distintos."""
    pedidos = []
    m15 = {m: almacen(m, "15m", [BASE + i * DUR for i in range(3)])
           for m in ("BTCUSDT", "ETHUSDT")}
    h4 = {m: almacen(m, "4h", [BASE4 + i * DUR4 for i in range(3)])
          for m in ("BTCUSDT", "ETHUSDT")}
    fetch = fetch_de({}, registro=pedidos)          # el reloj lanzaría
    partes = I.ingerir_ciclo(fetch, m15, h4, BASE + 100 * DUR)
    assert [(p["mercado"], p["tf"]) for p in partes] == [
        ("BTCUSDT", "15m"), ("ETHUSDT", "15m"),
        ("BTCUSDT", "4h"), ("ETHUSDT", "4h")]
    assert all(url == C.ENDPOINT_KLINES for url, _ in pedidos)
    fuente = open(I.__file__, encoding="utf-8").read()
    assert "ENDPOINT_TIME" not in fuente
    assert "eligibility_time(" not in fuente
