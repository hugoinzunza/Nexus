"""Tests de la vista Accion del precio (curso CreceTrader).

El modulo dibuja niveles que NO estan validados. Por eso los tests cuidan dos cosas
distintas: que la aritmetica sea la del curso, y que la pantalla no pueda mentir
—ni presentandose como senal, ni escondiendo lo que no sabe—.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.inteligencia import precio as P  # noqa: E402

APP_JS = os.path.join(ROOT, "modules/inteligencia/public/app.js")
INDEX = os.path.join(ROOT, "modules/inteligencia/public/index.html")
MODULE = os.path.join(ROOT, "modules/inteligencia/module.py")


def velas_diarias(desde="2024-01-01", n=800, px0=40_000.0):
    base = dt.datetime.fromisoformat(desde).replace(tzinfo=dt.timezone.utc)
    out = []
    for i in range(n):
        p = px0 * (1 + 0.0006 * i)
        t = int((base + dt.timedelta(days=i)).timestamp() * 1000)
        out.append({"t": t, "o": p, "h": p * 1.01, "l": p * 0.99, "c": p * 1.002, "v": 1})
    return out


# --- aritmetica del curso -------------------------------------------


def test_la_rejilla_es_lineal_y_no_compuesta():
    """+20% es `ancla*1.20`, NO `ancla*1.10^2`. La intuicion financiera dice lo
    contrario y por eso es facil equivocarse; el apunte lo confirma contra la
    planilla del curso."""
    filas = P.rejilla(100.0, 100.0)
    arriba = {f["k"]: f["precio"] for f in filas if f["dir"] == "arriba"}
    assert abs(arriba[1] - 110.0) < 1e-9
    assert abs(arriba[2] - 120.0) < 1e-9   # y NO 121.0, que es lo compuesto
    assert abs(arriba[2] - 121.0) > 0.9
    assert abs(arriba[3] - 130.0) < 1e-9


def test_la_rejilla_nunca_produce_precios_cero_o_negativos():
    """Con `k >= 10` hacia abajo la formula del curso da cero y luego negativo, que
    no significa nada para un activo. El tope de K_MAX existe para eso."""
    assert P.K_MAX < 10
    for ancla in (100.0, 87_608.3, 0.05):
        for f in P.rejilla(ancla, ancla):
            assert f["precio"] > 0


def test_la_apertura_anual_no_se_inventa_si_falta_el_comienzo_del_anio():
    """Si el par se listo en marzo, su "apertura anual" seria una ficcion con cara
    de dato. Tiene que devolver None, no la primera vela que haya."""
    velas = velas_diarias(desde="2024-03-15", n=100)
    assert P.apertura_anual(velas, 2024) is None
    completo = velas_diarias(desde="2024-01-01", n=100)
    ancla = P.apertura_anual(completo, 2024)
    assert ancla and ancla["fecha"] == "2024-01-01"
    empieza_el_2 = velas_diarias(desde="2024-01-02", n=100)
    assert P.apertura_anual(empieza_el_2, 2024) is None


def test_la_apertura_semanal_no_entrega_una_semana_vieja_como_actual():
    """A diferencia de la anual, esta SI envejece. Con datos que no alcanzan la
    semana en curso debe decir que no hay, no servir la de hace un mes."""
    viejas = velas_diarias(desde="2024-01-01", n=30)
    ahora = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    assert P.apertura_semanal(viejas, ahora) is None


def test_la_apertura_semanal_exige_el_lunes_exacto():
    lunes = dt.datetime(2026, 7, 20, tzinfo=dt.timezone.utc)
    ahora = int((lunes + dt.timedelta(days=2)).timestamp() * 1000)
    desde_una = [{
        "t": int((lunes + dt.timedelta(hours=1)).timestamp() * 1000),
        "o": 100, "h": 101, "l": 99, "c": 100, "v": 1,
    }]
    assert P.apertura_semanal(desde_una, ahora) is None


# --- causalidad ------------------------------------------------------


def test_un_pivote_no_existe_antes_de_sus_velas_de_la_derecha():
    """Es el candado central. Fechar un pivote en su extremo en vez de en su
    confirmacion es look-ahead, y es el error mas caro que cometimos en este
    proyecto: un bucle que arrancaba una vela antes costaba 1,5R por trade."""
    velas = velas_diarias(n=300)
    # ruido para que existan pivotes de verdad
    for i in range(20, 280, 17):
        velas[i]["h"] *= 1.05
        velas[i + 3]["l"] *= 0.95
    completo = P.estructura(velas, piv=5)
    for p in completo["highs"] + completo["lows"]:
        assert p["confirm_idx"] >= p["idx"] + 5

    # el observador de una vela intermedia NO puede ver pivotes que confirman despues
    corte = 150
    parcial = P.estructura(velas, piv=5, as_of_idx=corte)
    for p in parcial["highs"] + parcial["lows"]:
        assert p["confirm_idx"] <= corte


def test_agregar_velas_futuras_no_cambia_un_pivote_ya_confirmado():
    """Replay: anexar futuro no puede alterar decisiones pasadas. Si esto falla, todo
    lo que la pantalla muestre como historico es reconstruccion, no observacion."""
    velas = velas_diarias(n=300)
    for i in range(20, 280, 17):
        velas[i]["h"] *= 1.05
    corte = 200
    antes = P.estructura(velas[:corte], piv=5)
    despues = P.estructura(velas, piv=5, as_of_idx=corte - 1)
    clave = lambda e: [(p["idx"], p["confirm_idx"]) for p in e["highs"]]  # noqa: E731
    assert clave(antes) == clave(despues)


def test_agregar_futuro_no_reescribe_una_pierna_ya_confirmada():
    paso = P.TF_MS["1h"]
    patron = (100, 104, 109, 104, 100, 96, 91, 96)
    velas = []
    for i in range(96):
        px = patron[i % len(patron)]
        velas.append({"t": i * paso, "o": px, "h": px + 1,
                      "l": px - 1, "c": px, "v": 1})
    corte = 64
    antes = P.piernas_confirmadas(velas[:corte], "1h", piv=2)
    despues = [
        p for p in P.piernas_confirmadas(velas, "1h", piv=2)
        if p["confirm_idx"] < corte
    ]
    clave = lambda p: (p["direccion"], p["inicio_idx"], p["fin_idx"],  # noqa: E731
                       p["confirm_idx"], p["confirmed_at"])
    assert antes
    assert [clave(p) for p in antes] == [clave(p) for p in despues]


def test_una_vela_abierta_no_puede_confirmar_un_pivote():
    velas = []
    for i in range(14):
        velas.append({"t": i * P.TF_MS["1h"], "o": 5, "h": 5 + i * .01,
                      "l": 4 - i * .01, "c": 5, "v": 1})
    velas[8]["h"] = 10
    velas[13]["h"] = 9
    assert any(p["idx"] == 8 for p in P.estructura(velas, 5)["highs"])

    as_of = velas[13]["t"] + P.TF_MS["1h"] // 2
    cerradas = P.velas_cerradas(velas, "1h", as_of)
    assert not any(p["idx"] == 8 for p in P.estructura(cerradas, 5)["highs"])


def test_mapa_de_precios_es_simetrico_y_aritmetico():
    alcista = P.mapa_precios({"inicio": 100, "fin": 200}, 160)
    bajista = P.mapa_precios({"inicio": 200, "fin": 100}, 140)
    ra = {x["ratio"]: x["precio"] for x in alcista["retrocesos"]}
    rb = {x["ratio"]: x["precio"] for x in bajista["retrocesos"]}
    ea = {x["ratio"]: x["precio"] for x in alcista["extensiones"]}
    eb = {x["ratio"]: x["precio"] for x in bajista["extensiones"]}
    assert ra[.40] == 160 and rb[.40] == 140
    assert ea[1.50] == 250 and eb[1.50] == 50
    assert alcista["estado"] == "correccion"
    assert bajista["estado"] == "correccion"
    assert P.mapa_precios({"inicio": 200, "fin": 100}, 210)["estado"] == "invalidada"


def test_la_tendencia_dice_indefinida_en_vez_de_inventar():
    """Con menos de dos pivotes por lado no hay como hablar de creciente. Forzar una
    lectura ahi es exactamente la discrecionalidad que el curso no resuelve."""
    planas = velas_diarias(n=60)
    e = P.estructura(planas, piv=5)
    assert e["tendencia"] in ("indefinida", "lateral", "sin_datos")


# --- el vacio disponible --------------------------------------------


def test_el_vacio_toma_el_primer_obstaculo_y_no_el_conveniente():
    """El punto entero del concepto: elegir el "primer" referente despues de ver el
    recorrido es la trampa que viene a denunciar."""
    refs = [{"precio": 105.0}, {"precio": 120.0}, {"precio": 95.0}]
    v = P.vacio_disponible(100.0, "long", 98.0, refs)
    assert v["primer_obstaculo"]["precio"] == 105.0
    assert v["n_adelante"] == 2
    assert v["vacuum_rr"] == 2.5          # (105-100)/(100-98)


def test_los_obstaculos_intermedios_se_cuentan():
    """Un RR alto medido a traves de tres paredes es aritmeticamente correcto y
    operativamente ilusorio. Contar es lo unico que lo hace visible."""
    refs = [{"precio": 105.0}, {"precio": 110.0}, {"precio": 130.0}]
    o = P.obstaculos_entre(100.0, 120.0, "long", refs)
    assert o["obstacle_count"] == 2       # 130 queda fuera del tramo
    assert o["target_atraviesa_referencias"] is True
    assert P.obstaculos_entre(100.0, 104.0, "long", refs)["obstacle_count"] == 0


# --- la pantalla no puede mentir -------------------------------------


def test_la_vista_se_declara_research_y_sin_ejecucion():
    fuente = open(MODULE, encoding="utf-8").read()
    assert '"research_only": True' in fuente
    assert '"execution_enabled": False' in fuente
    assert '"validated": False' in fuente
    html = open(INDEX, encoding="utf-8").read()
    assert "SIN VALIDAR" in html


def test_el_resultado_que_refuta_la_rejilla_esta_en_la_pantalla():
    """La rejilla anual se midio el 2026-07-26 y NO se distingue de un placebo:
    24,00% de reaccion contra 23,86% de niveles aleatorios, CI [-5,3; +5,8], y
    ninguno de los seis controles sobrevive a Holm.

    Sigue dibujada porque es un marco de referencia legible. Pero si el numero que la
    refuta vive solo en un informe de research, la pantalla sigue vendiendo el metodo
    igual que la masterclass. Por eso la medicion va EN la vista, y este test la fija
    ahi.
    """
    html = open(INDEX, encoding="utf-8").read()
    assert "no funciona" in html, "el titular tiene que decir el resultado"
    assert "23,86" in html and "24,00" in html, "faltan las dos tasas comparadas"
    assert "6.675" in html, "falta el tamano de la muestra"
    # el 11,3% incondicional es el numero que el curso nunca publica
    assert "11,3" in html and "denominador" in html
    # y el limite honesto: no se probo efecto cero
    assert "no prueba que el efecto sea cero" in html
    # el control que desarma la unica celda que sobrevivia
    assert "ancla corrida" in html or "corrida tres d" in html


def test_el_gate_de_entrada_del_curso_tambien_esta_medido_en_pantalla():
    """El gate central del curso —dos cierres consecutivos— tiene los cuatro brazos
    medidos sobre 8.440 setups pareados, y ninguno convierte la informacion de la
    confirmacion en expectativa: el RR realizado cae de 4,25 (toque) a 1,15 (CDC), y
    el retest recupera solo hasta 1,30.

    Va en la vista por la misma razon que la rejilla: un usuario que opere mirando
    esta pantalla tiene que ver que esperar la confirmacion le cuesta el precio.
    """
    html = open(INDEX, encoding="utf-8").read()
    assert "4,25" in html and "1,15" in html and "1,30" in html
    assert "8.440" in html
    # el control que cierra el caso: esperar sin condicion de precio empata
    assert "sin condición de precio" in html or "sin condicion de precio" in html
    assert "0,42" in html


def test_la_rejilla_placebo_viaja_siempre_al_lado_de_la_del_curso():
    """Una rejilla sola SIEMPRE parece funcionar: con suficientes niveles el precio
    reacciona en alguno. El placebo de 7,5% y 12,5% es lo que convierte la pantalla
    en algo honesto en vez de una demostracion."""
    assert P.PASOS_PLACEBO == (0.075, 0.125)
    fuente = open(MODULE, encoding="utf-8").read()
    assert "rejilla_placebo" in fuente
    js = open(APP_JS, encoding="utf-8").read()
    assert "ver-placebo" in js and "rejilla_placebo" in js


def test_ningun_nivel_desaparece_en_silencio_del_grafico():
    """En 1h la rejilla anual queda casi entera fuera del encuadre. Esconderla hace
    que la pantalla parezca decir "no hay nada cerca" cuando lo que pasa es que no
    estamos mirando tan lejos. Es la misma familia de defecto que ya corregimos seis
    veces: una franja no declarada haciendose pasar por una medicion completa."""
    js = open(APP_JS, encoding="utf-8").read()
    assert "fuera del encuadre" in js
    assert "fuera.length" in js, "hay que contar los que quedaron afuera"
    # y el encuadre lo fijan las VELAS, no los niveles: si un nivel a +90% mandara en
    # el eje, aplastaria todo el grafico en una franja
    bloque = js.split("function pintarNiveles()")[1].split("\nfunction ")[0]
    assert "state.velas.flatMap" in bloque


def test_el_modulo_no_puede_tocar_la_cuenta():
    """Solo klines publicas. Si aparece una llamada firmada aca, el modulo dejo de
    ser una vista de lectura."""
    fuente = open(MODULE, encoding="utf-8").read()
    assert "signed_get" not in fuente
    assert "BINANCE_API" not in fuente
    assert "public_get" in fuente


def test_la_medicion_del_vacio_disponible_esta_en_pantalla():
    """El vacio disponible era la unica idea del curso que NexUX no tenia, y se midio
    el 2026-07-26 sobre 5.289 trades del bot. Resultado en dos partes, y las dos
    tienen que estar visibles porque juntas dicen algo distinto que cada una sola:

      1. la ceguera EXISTE y es grande: rr planificado mediano 11,6 contra 1,52 de
         distancia a la primera pared; 97,9% de los planes tiene al menos una pared
         entre entrada y objetivo;
      2. y aun asi contar paredes NO predice: 0 de 12 contrastes sobreviven Holm, y
         un conteo permutado al azar predice igual o mejor.

    Publicar solo la (1) haria pensar que hay algo que arreglar; solo la (2), que no
    habia nada que mirar. Las dos juntas es lo unico honesto.
    """
    html = open(INDEX, encoding="utf-8").read()
    assert "5.289" in html
    assert "11,6" in html and "1,52" in html, "falta la magnitud de la ceguera"
    assert "97,9" in html
    assert "Cero de" in html and "Holm" in html, "falta el resultado negativo"
    assert "permutado al azar" in html
    # el control de fuga: sin el, un resultado negativo no es creible
    assert "control de fuga" in html


# --- ingesta de klines desde el VPS ----------------------------------

def _modulo(tmp_path=None):
    import threading
    from modules.inteligencia import module as mod
    m = mod.InteligenciaModule.__new__(mod.InteligenciaModule)
    m._lock = threading.Lock()
    m._cache = {}
    m.config = {"pares": ["BTCUSDT", "ETHUSDT"]}

    class Ctx:
        def log(self, _m):
            pass
    m.context = Ctx()
    return m, mod


def _serie(n=5, t0=None, paso=3_600_000):
    if t0 is None:
        import time
        t0 = int((time.time() // (paso / 1000) - n + 1) * paso)
    return [{"t": t0 + i * paso, "o": 100.0 + i, "h": 101.0 + i,
             "l": 99.0 + i, "c": 100.5 + i, "v": 1.0} for i in range(n)]


def test_la_ingesta_exige_token(monkeypatch, tmp_path):
    """El endpoint se salta la sesion del navegador (lo llama un colector), asi que
    el token es lo UNICO que lo protege."""
    m, mod = _modulo()
    from core import klines_push
    monkeypatch.setattr(klines_push, "_ruta", lambda _root: str(tmp_path / "k.json"))
    monkeypatch.setenv("NEXUS_INGEST_TOKEN", "secreto")
    cuerpo = {"series": {"BTCUSDT:1h": _serie()}}

    st, _, _ = m.api_post("klines-ingest", cuerpo, {}, None)
    assert st == 401
    st, _, _ = m.api_post("klines-ingest", cuerpo, {"x-nexus-token": "otro"}, None)
    assert st == 401
    st, _, _ = m.api_post("klines-ingest", cuerpo, {"x-nexus-token": "secreto"}, None)
    assert st == 200


def test_la_ingesta_no_cree_lo_que_le_manden(monkeypatch, tmp_path):
    """Que el colector mande algo no significa que el servidor deba creerlo: par y
    temporalidad se validan contra las listas blancas del modulo."""
    m, mod = _modulo()
    from core import klines_push
    monkeypatch.setattr(klines_push, "_ruta", lambda _root: str(tmp_path / "k.json"))
    monkeypatch.setenv("NEXUS_INGEST_TOKEN", "secreto")
    cab = {"x-nexus-token": "secreto"}

    st, _, _ = m.api_post("klines-ingest", {"series": {"HACKUSDT:1h": _serie()}}, cab, None)
    assert st == 400, "acepto un par fuera de la lista"
    st, _, _ = m.api_post("klines-ingest", {"series": {"BTCUSDT:3m": _serie()}}, cab, None)
    assert st == 400, "acepto una temporalidad fuera de la lista"
    st, _, _ = m.api_post("klines-ingest", {"series": {}}, cab, None)
    assert st == 400
    # y este modulo no expone ningun otro POST
    assert m.api_post("cualquier-otra-cosa", {}, cab, None) is None


def test_un_push_viejo_NO_se_sirve_como_si_fuera_en_vivo(monkeypatch, tmp_path):
    """Klines empujadas hace horas son PEOR que las versionadas, porque parecen en
    vivo. Pasada la ventana se cae al siguiente respaldo y la pantalla lo dice."""
    import json as _json
    import time as _time
    m, mod = _modulo()
    ruta = tmp_path / "k.json"
    from core import klines_push
    monkeypatch.setattr(klines_push, "_ruta", lambda _root: str(ruta))

    ruta.write_text(_json.dumps({
        "empujado_ts": _time.time() - (klines_push.MAX_EDAD_S + 60),
        "series": {"BTCUSDT:1h": _serie()}}))
    assert m._velas_empujadas("BTCUSDT", "1h", 500) == [], "sirvio un push vencido"

    ruta.write_text(_json.dumps({
        "empujado_ts": _time.time(),
        "series": {"BTCUSDT:1h": _serie(
            t0=int((_time.time() // 3600 - 4) * 3_600_000))}}))
    assert len(m._velas_empujadas("BTCUSDT", "1h", 500)) == 5


def test_el_orden_de_respaldos_es_push_binance_versionadas():
    """El respaldo bueno primero. Si esto se invierte, Railway seguiria mostrando
    datos de hace 41 dias aunque el VPS este empujando en vivo."""
    fuente = open(os.path.join(ROOT, "modules/inteligencia/module.py"),
                  encoding="utf-8").read()
    bloque = fuente.split("def _velas(")[1].split("\n    @staticmethod")[0]
    assert bloque.index("klines_push.serie_con_meta") < bloque.index("bc.public_get")
    assert bloque.index("bc.public_get") < bloque.index("_velas_versionadas")
    for etiqueta in ("vps_binance", "binance_publico", "klines_versionados"):
        assert f'"{etiqueta}"' in bloque


def test_el_colector_del_vps_no_puede_tocar_la_cuenta():
    """Solo GET publicos y un POST con token. Si aparece una firma aca, el colector
    dejo de ser lo que dice ser."""
    fuente = open(os.path.join(ROOT, "deploy/klines_collector.py"), encoding="utf-8").read()
    assert "BINANCE_API" not in fuente and "hmac" not in fuente
    assert "signed" not in fuente
    assert "X-Nexus-Token" in fuente
    # el 1d tiene que traer historia suficiente para anclar la rejilla anual
    assert '("1d", 1_500)' in fuente
    # y no publica vacio: pisaria lo que ya esta servido
    assert "snapshot incompleto" in fuente and "no se pisa lo que ya" in fuente


def test_el_modulo_aparece_en_el_menu_compartido():
    """El landing de NexUX es un HTML ESTATICO: no arma las tarjetas desde los modulos
    cargados. Un modulo nuevo puede estar corriendo, responder 200 y ser invisible,
    que es exactamente lo que paso el 2026-07-26 — Hugo no lo encontraba.

    La navegacion de verdad vive en `static/nexux-shell.js`, y hay que anotarse ahi.
    """
    shell = open(os.path.join(ROOT, "static/nexux-shell.js"), encoding="utf-8").read()
    assert '"/m/inteligencia/"' in shell
    assert "Acción del precio" in shell

    # y la pagina tiene que CARGAR el shell, o queda sin barra compartida
    html = open(INDEX, encoding="utf-8").read()
    assert "nexux-shell.js" in html


def test_el_shell_se_versiona_igual_en_todas_las_paginas():
    """El shell va cacheado con `?v=N`. Si una pagina queda en una version vieja, su
    menu no muestra los modulos nuevos y el sintoma es invisible: la pagina anda, solo
    que le falta un enlace."""
    import glob
    import re
    versiones = set()
    for ruta in glob.glob(os.path.join(ROOT, "modules/*/public/*.html")):
        for m in re.finditer(r"nexux-shell\.js\?v=(\d+)", open(ruta, encoding="utf-8").read()):
            versiones.add(m.group(1))
    assert len(versiones) == 1, f"hay paginas con versiones distintas del shell: {versiones}"


# --- el grafico de Trading y el feed de las senales ------------------

TRADING = os.path.join(ROOT, "modules/trading/module.py")


def test_el_grafico_de_trading_usa_binance_pero_las_senales_NO_cambian():
    """La costura que Codex encontro: el bot ejecuta en Binance Futuros y el grafico
    mostraba Crypto.com. Peor: `_deep_history` lee los klines de BINANCE de `data/`,
    asi que el grafico venia siendo un EMPALME de dos exchanges pegados en el borde.

    Medido el 2026-07-26 sobre 200 velas 1h: los extremos difieren 0,045% en la
    mediana y 0,183% en el peor caso — el 6% y el 23% de la distancia a TP1.

    Y el candado que importa: el ANALISIS sigue con `_candles_cached` a proposito.
    Cambiarle el feed a las senales a mitad del dry-run haria incomparables los trades
    de antes y despues, y la Fase 1 esta juntando muestra con criterio pre-registrado.
    """
    fuente = open(TRADING, encoding="utf-8").read()

    grafico = fuente.split("def _full_candles")[1].split("def _fuente_grafico")[0]
    assert "klines_push.serie" in grafico, "el grafico no toma el push de Binance"
    assert '"binance_vps"' in grafico

    analisis = fuente.split("def _smc_analysis")[1].split("\n    def ")[0]
    assert "_candles_cached" in analisis, "el analisis debe seguir con su feed"
    assert "klines_push" not in analisis, \
        "el analisis cambio de feed: eso invalida la muestra de la Fase 1 en curso"


def test_1m_y_5m_no_pueden_venir_del_push():
    """Un push cada 10 min deja una vela de 1m mas atrasada que la vela misma. Servir
    eso como si fuera en vivo es peor que mostrar otro exchange declarado."""
    from core import klines_push
    assert "1m" not in klines_push.TFS_SERVIBLES
    assert "5m" not in klines_push.TFS_SERVIBLES
    assert set(klines_push.TFS_SERVIBLES) == {"15m", "1h", "4h", "1d", "1w"}


def test_un_envelope_nuevo_no_disfraza_una_serie_vieja(monkeypatch, tmp_path):
    import json as _json
    import time as _time
    from core import klines_push
    ruta = tmp_path / "k.json"
    monkeypatch.setattr(klines_push, "_ruta", lambda _root: str(ruta))
    ruta.write_text(_json.dumps({
        "empujado_ts": _time.time(),
        "series": {"BTCUSDT:1h": _serie(t0=1_700_000_000_000)}}))
    filas, meta = klines_push.serie_con_meta(str(tmp_path), "BTCUSDT", "1h")
    assert filas == []
    assert meta["error"] == "serie vencida"


def test_la_fuente_del_grafico_se_declara_en_pantalla():
    fuente = open(TRADING, encoding="utf-8").read()
    assert '"fuente": self._fuente_grafico(instrument, timeframe)' in fuente
    js = open(os.path.join(ROOT, "modules/trading/public/app.js"), encoding="utf-8").read()
    assert "marcarFuente(card, j.fuente)" in js
    assert "Binance Futuros" in js and "Crypto.com" in js


def test_la_vista_expone_horizontes_y_mapa_sin_habilitar_ejecucion():
    html = open(INDEX, encoding="utf-8").read()
    js = open(APP_JS, encoding="utf-8").read()
    modulo = open(MODULE, encoding="utf-8").read()
    for horizonte in ("corto", "medio", "largo"):
        assert f'data-horizonte="{horizonte}"' in html
        assert f'"{horizonte}":' in modulo
    assert 'value="1w"' in html
    assert "/mapa?" in js
    assert '"execution_enabled": False' in modulo
    assert '"validated": False' in modulo


def test_el_lector_del_push_vive_en_un_solo_lugar():
    """Con el lector duplicado, el dia que cambie el formato o la ventana de frescura
    uno de los dos consumidores se queda atras en silencio."""
    for mod in ("modules/inteligencia/module.py", "modules/trading/module.py"):
        src = open(os.path.join(ROOT, mod), encoding="utf-8").read()
        assert "from core import klines_push" in src
        assert "inteligencia_klines.json" not in src, \
            f"{mod} vuelve a abrir el archivo por su cuenta"


def test_un_tick_de_otro_exchange_no_pisa_una_vela_de_binance():
    """Hugo comparo el grafico con TradingView y no cuadraba. Una de las causas era
    esta: el SSE trae el tick de Crypto.com y `rebuildBars`/`liveUpdate` lo escribian
    encima del close/high/low de la ULTIMA vela — que desde el cambio a Binance viene
    de otro instrumento. Mezcla de dos mercados DENTRO de una misma vela, justo en la
    barra que uno mira.

    Medido: el basis ronda 0,045% en la mediana, el 6% de la distancia a TP1.
    """
    js = open(os.path.join(ROOT, "modules/trading/public/app.js"), encoding="utf-8").read()

    # Los DOS lugares que aplican el tick, verificados leyendo el archivo y no de
    # memoria: `_ohlc` lo mete en las series de los indicadores y `liveUpdate` lo
    # escribe en la ultima barra del grafico. `rebuildBars` NO lo aplica -mi primer
    # test miraba ahi y por eso fallaba-.
    ohlc = js.split("function _ohlc(")[1].split("\n  function ")[0]
    assert "tickCompatible" in ohlc
    assert 'card.fuenteVelas === "cryptocom"' in ohlc, \
        "el tick vuelve a entrar a los indicadores sin mirar el exchange"

    vivo = js.split("function liveUpdate(")[1].split("\n  function ")[0]
    assert 'card.fuenteVelas !== "cryptocom"' in vivo, "liveUpdate no se protegio"

    # y donde NO estaba el problema, que quede escrito para no volver a buscar ahi
    barras = js.split("function rebuildBars(")[1].split("\n  function ")[0]
    assert "lastPrice" not in barras


def test_el_atraso_de_la_barra_en_formacion_se_publica():
    """"El precio no coincide" y "la barra tiene 7 minutos" mandan a buscar el problema
    a lugares opuestos. El push llega cada 10 min, asi que el atraso es real y tiene
    que estar a la vista."""
    fuente = open(TRADING, encoding="utf-8").read()
    assert '"push": self._push_meta(instrument, timeframe),' in fuente
    assert "series_lag_seconds" in open(
        os.path.join(ROOT, "modules/trading/public/app.js"), encoding="utf-8").read()


# --- cola en vivo directo desde el navegador --------------------------

def test_el_stream_lo_arma_el_servidor_no_el_javascript():
    """El mapeo 1D->1d vive en `binance.UI_TO_BINANCE`. Duplicarlo en el cliente es el
    mismo problema que tener dos lectores del push: el dia que cambie, uno se queda
    atras en silencio. Por eso el servidor manda el nombre del stream armado."""
    fuente = open(TRADING, encoding="utf-8").read()
    assert "def _stream_vivo" in fuente
    assert '"stream_vivo": self._stream_vivo(instrument, timeframe),' in fuente
    bloque = fuente.split("def _stream_vivo")[1].split("\n    def ")[0]
    assert "binance.UI_TO_BINANCE" in bloque
    assert "kline_" in bloque

    js = open(os.path.join(ROOT, "modules/trading/public/app.js"), encoding="utf-8").read()
    assert "j.stream_vivo" in js
    # el JS no puede estar rearmando el intervalo por su cuenta
    assert "@kline_" not in js.split("const vivoBinance")[1].split("marcarFuente(card, fuente)")[0] \
        or "${stream}" in js


def test_no_se_ofrece_stream_de_binance_si_las_velas_son_de_otro_exchange():
    """Pegarle un tick de Binance a una vela de Crypto.com es la misma mezcla que
    acabamos de corregir, al reves."""
    fuente = open(TRADING, encoding="utf-8").read()
    bloque = fuente.split("def _stream_vivo")[1].split("\n    def ")[0]
    assert '!= "binance_vps"' in bloque and "return None" in bloque


def test_un_stream_caido_o_MUDO_no_se_ve_como_en_vivo():
    """Tres estados y ninguno se puede confundir: en vivo, stream mudo (socket abierto
    que dejo de mandar frames — la falla que se ve igual que estar bien) y sin vivo con
    el atraso del push a la vista.

    Es la septima u octava variante del mismo defecto que corregi hoy: algo degradado
    presentandose como completo.
    """
    js = open(os.path.join(ROOT, "modules/trading/public/app.js"), encoding="utf-8").read()
    estado = js.split("  estado() {")[1].split("\n  },")[0]
    assert "readyState !== 1" in estado, "no chequea que el socket este abierto"
    assert "this.ultimo" in estado, "no chequea que sigan llegando frames"
    assert "vivo mudo" in estado

    # CONECTADO SIN UN SOLO FRAME NO ES "EN VIVO": es conectando. Confundirlos fue mi
    # error, y lo pille comparando el titulo contra el REST de Binance — mostraba
    # 64.820,70 contra 64.998,10, o sea 0,27% de diferencia, con el sello diciendo
    # "en vivo". Mientras no llegue el primer frame, el ticker de respaldo tiene que
    # seguir trabajando.
    assert "conectando" in estado
    assert "if (!this.frames) return" in estado

    # Stream COMBINADO: el de klines se calla con el mercado quieto. Medido hoy:
    # `@kline_1m` y `@aggTrade` sin frame en 10 s mientras `@bookTicker` llego en 0,18 s.
    assert "@bookTicker" in js
    assert "streams=" in js

    assert "Binance Futuros · en vivo" in js
    assert "Binance Futuros · stream mudo" in js
    assert "· sin vivo" in js
    # y el latido que detecta el mudo: nadie dispara un evento cuando los frames PARAN
    assert "vigilar()" in js and "vivoBinance.vigilar()" in js


def test_el_reintento_no_machaca_cuando_el_bloqueo_es_permanente():
    """Si el que mira esta en una jurisdiccion que Binance no atiende, el socket va a
    fallar SIEMPRE. Reintentar cada segundo no lo arregla y quema bateria."""
    js = open(os.path.join(ROOT, "modules/trading/public/app.js"), encoding="utf-8").read()
    bloque = js.split("  reintentar(card, stream) {")[1].split("\n  },")[0]
    assert "Math.pow(2" in bloque, "el reintento debe espaciarse"
    assert "Math.min(60_000" in bloque, "y tener tope"


def test_la_barra_en_formacion_se_mueve_con_bookTicker_y_no_solo_con_klines():
    """La regresion que Hugo vio: el grafico quedo ESTATICO.

    Medido: el stream de klines de 15m manda 0 frames en 10 s mientras `bookTicker`
    manda 5.259. Al desactivar `liveUpdate` para las velas de Binance, deje la barra
    dependiendo de un evento que casi nunca llega — el titulo se movia y el grafico no.
    """
    js = open(os.path.join(ROOT, "modules/trading/public/app.js"), encoding="utf-8").read()
    assert "function extenderBarraViva" in js
    bloque = js.split('d.e === "bookTicker"')[1].split("\n        }")[0]
    assert "extenderBarraViva(card, mid)" in bloque, \
        "bookTicker vuelve a mover solo el titulo y el grafico queda estatico"


def test_el_tick_no_remapea_toda_la_serie():
    """`rebuildBars` remapea TODAS las velas y con la historia profunda son decenas de
    miles. Llamarlo varias veces por segundo colgaba la pestana —lo vi con el panel del
    navegador dejando de responder— y por eso el `liveUpdate` original tampoco lo hacia.
    """
    # Sin comentarios: el assert de "rebuildBars no esta" salta con el comentario que
    # EXPLICA por que no esta. Sexta vez que me pasa hoy, y el helper ya existe.
    from tests.test_coinglass_visual import js_sin_comentarios_trading as limpio
    js = limpio()
    ext = js.split("function extenderBarraViva(card, px) {")[1].split("\n  }")[0]
    assert "rebuildBars" not in ext, "el tick volvio a remapear la serie completa"
    assert "card.bars[card.bars.length - 1]" in ext, "falta la actualizacion O(1)"

    # en el camino de kline, `rebuildBars` solo cuando NACE una barra
    viva = js.split("function aplicarVelaViva(card, k) {")[1].split("\n  }")[0]
    assert viva.index("card.candles.push") < viva.index("rebuildBars(card)"), \
        "rebuildBars debe correr solo al aparecer una barra nueva"


def test_los_frames_se_descartan_ANTES_de_parsearlos():
    """`bookTicker` manda entre 65 y 740 frames por segundo segun la actividad (medido).
    `JSON.parse` en cada uno es el costo real, aunque el repintado este limitado. El
    descarte se hace con un `indexOf` sobre el string crudo, y los frames de KLINE nunca
    se descartan: son escasos y traen la barra autoritativa."""
    from tests.test_coinglass_visual import js_sin_comentarios_trading as limpio
    js = limpio()
    handler = js.split("ws.onmessage = (ev) => {")[1].split("\n      };")[0]
    assert handler.index("indexOf") < handler.index("JSON.parse"), \
        "se parsea antes de decidir si el frame sirve"
    assert '"e":"bookTicker"' in handler
    assert "_ultimoBt" in handler
