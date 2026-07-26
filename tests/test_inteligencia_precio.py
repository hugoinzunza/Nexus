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


def test_la_apertura_semanal_no_entrega_una_semana_vieja_como_actual():
    """A diferencia de la anual, esta SI envejece. Con datos que no alcanzan la
    semana en curso debe decir que no hay, no servir la de hace un mes."""
    viejas = velas_diarias(desde="2024-01-01", n=30)
    ahora = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    assert P.apertura_semanal(viejas, ahora) is None


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


def _serie(n=5, t0=1_700_000_000_000, paso=3_600_000):
    return [{"t": t0 + i * paso, "o": 100.0 + i, "h": 101.0 + i,
             "l": 99.0 + i, "c": 100.5 + i, "v": 1.0} for i in range(n)]


def test_la_ingesta_exige_token(monkeypatch, tmp_path):
    """El endpoint se salta la sesion del navegador (lo llama un colector), asi que
    el token es lo UNICO que lo protege."""
    m, mod = _modulo()
    monkeypatch.setattr(mod, "KLINES_PATH", str(tmp_path / "k.json"))
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
    monkeypatch.setattr(mod, "KLINES_PATH", str(tmp_path / "k.json"))
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
    monkeypatch.setattr(mod, "KLINES_PATH", str(ruta))

    ruta.write_text(_json.dumps({
        "empujado_ts": _time.time() - (mod.MAX_EDAD_PUSH_S + 60),
        "series": {"BTCUSDT:1h": _serie()}}))
    assert m._velas_empujadas("BTCUSDT", "1h", 500) == [], "sirvio un push vencido"

    ruta.write_text(_json.dumps({
        "empujado_ts": _time.time(),
        "series": {"BTCUSDT:1h": _serie()}}))
    assert len(m._velas_empujadas("BTCUSDT", "1h", 500)) == 5


def test_el_orden_de_respaldos_es_push_binance_versionadas():
    """El respaldo bueno primero. Si esto se invierte, Railway seguiria mostrando
    datos de hace 41 dias aunque el VPS este empujando en vivo."""
    fuente = open(os.path.join(ROOT, "modules/inteligencia/module.py"),
                  encoding="utf-8").read()
    bloque = fuente.split("def _velas(")[1].split("\n    @staticmethod")[0]
    assert bloque.index("_velas_empujadas") < bloque.index("bc.public_get")
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
    assert "no se pisa lo que ya está servido" in fuente
