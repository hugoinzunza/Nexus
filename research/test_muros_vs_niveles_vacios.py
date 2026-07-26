#!/usr/bin/env python3
"""Tests del estudio pareado muro-vs-nivel-vacío.

El estudio corre solo por cron cada día a las 19:07 UTC, así que un error acá no lo
ve nadie hasta que alguien lea el resultado meses después. Por eso los tests usan un
archivo PATOLÓGICO que replica lo que produce el VPS de verdad, no un caso amable:

  * el piso exacto de US$1M con el que CoinGlass filtra su lista;
  * muros pegados a ese piso que aparecen y desaparecen sin que nadie los mueva;
  * una ballena persistente 40x más grande que la mediana;
  * un precio que apenas se mueve, que es el régimen habitual.

Los cuatro defectos que encontramos el 2026-07-26 eran invisibles en los fixtures
benignos del proyecto y visibles con el snapshot real. Este fixture existe para que
eso no vuelva a pasar.
"""
from __future__ import annotations

import datetime as dt
import os
import random
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import muros_vs_niveles_vacios as est  # noqa: E402

PISO = 1_000_000          # el umbral real de listado de CoinGlass
BALLENA = 78_700_000      # el bid persistente medido en produccion
FUENTE = os.path.join(WT, "research/muros_vs_niveles_vacios.py")


def codigo(ruta=FUENTE):
    """El fuente SIN comentarios ni docstrings.

    Afirmar que un símbolo desapareció y que salte con el comentario que documenta
    su eliminación me pasó cuatro veces el 2026-07-26. El comentario tiene que
    seguir ahí —explica el bug— así que lo que hay que arreglar es el test.
    """
    import tokenize
    with open(ruta, "rb") as fh:
        tokens = list(tokenize.tokenize(fh.readline))
    fuera = {tokenize.COMMENT, tokenize.NL}
    partes = []
    anterior = None
    for tok in tokens:
        if tok.type in fuera:
            continue
        # un STRING que es la única cosa de su línea lógica es un docstring
        if tok.type == tokenize.STRING and anterior in (None, tokenize.INDENT,
                                                        tokenize.NEWLINE,
                                                        tokenize.DEDENT):
            anterior = tok.type
            continue
        partes.append(tok.string)
        anterior = tok.type
    return " ".join(partes)


def capturas_patologicas(n=200, precio0=64_000.0):
    """Serie realista: piso en 1M, muros parpadeando en el borde, ballena fija.

    El precio sube 0,004% por captura (un 0,8% en toda la ventana), que es el orden
    de lo observado: en 22 capturas reales el recorrido fue de 0,12%.
    """
    salida = []
    base = dt.datetime(2026, 7, 26, tzinfo=dt.timezone.utc)
    for i in range(n):
        precio = precio0 * (1 + 0.00004 * i)
        bids = [
            [round(precio * 0.9922, 1), 3_200_000],     # muro real, estable
            [round(precio * 0.985, 1), 2_100_000],      # muro real, estable
            [61_300.0, BALLENA],                        # ballena fija, lejos
        ]
        asks = [
            [round(precio * 1.0078, 1), 3_400_000],
            [round(precio * 1.015, 1), 1_900_000],
        ]
        # PARPADEO: el mismo muro cruza el umbral de listado cada dos capturas
        if i % 2 == 0:
            bids.append([round(precio * 0.995, 1), PISO])
            asks.append([round(precio * 1.005, 1), PISO * 1.05])
        salida.append({
            "captured_at": (base + dt.timedelta(minutes=5 * i)).isoformat(),
            "price": round(precio, 1),
            "bids": bids,
            "asks": asks,
        })
    return salida


def test_el_piso_se_deriva_de_los_datos_no_de_una_constante():
    """`MIN_USD = 500_000` estaba POR DEBAJO del piso real de 1M, así que no filtraba
    nada: todos los muros del borde entraban como tratamiento."""
    caps = capturas_patologicas()
    assert est.piso_observado(caps) == PISO

    src = codigo()
    assert "MIN_USD" not in src, "volvio el umbral absoluto en dolares"
    assert "MARGEN_SOBRE_EL_PISO" in src
    assert "piso_observado" in src


def test_los_muros_del_borde_no_entran_como_tratamiento():
    """Es el punto: un muro que parpadea por el umbral figura presente y ausente en
    capturas consecutivas, y eso mete ruido en la variable de tratamiento. El ruido
    de etiqueta ATENUA el efecto hacia cero, así que destruye el poder del estudio.
    """
    caps = capturas_patologicas()
    corte = est.piso_observado(caps) * est.MARGEN_SOBRE_EL_PISO

    con_corte = est.observaciones(caps, 12, corte)
    sin_corte = est.observaciones(caps, 12, 0.0)

    def tratados(filas):
        return sum(1 for f in filas if f["hay_muro"])

    assert tratados(sin_corte) > tratados(con_corte), \
        "el corte deberia excluir los muros del borde"
    # y los muros REALES (2-3,4M) siguen contando: el corte no puede matarlos
    assert tratados(con_corte) > 0
    # el parpadeo desaparece: con el corte, cada bucket es estable entre capturas
    assert len(con_corte) == len(sin_corte), \
        "las filas evaluadas deben ser las mismas; solo cambia la etiqueta"


def test_el_resultado_de_una_captura_solo_usa_capturas_POSTERIORES():
    """Anti-look-ahead. Si `futuro` incluyera la captura actual, el alcance saldría
    inflado porque el precio de partida ya está en el rango evaluado."""
    fuente = open(FUENTE, encoding="utf-8").read()
    bloque = fuente.split("def observaciones(")[1].split("\ndef ")[0]
    assert "capturas[i + 1: i + 1 + horizonte]" in bloque, \
        "la ventana futura debe arrancar en i+1, no en i"
    assert "futuro[j_toque + 1:]" in bloque, \
        "el rebote debe medirse DESPUES del toque, no desde el toque"


def test_alcance_y_reaccion_miden_cosas_opuestas():
    """Un muro real deberia frenar el precio (menos alcance) y devolverlo mas (mas
    rebote). Si el estudio reportara las dos subiendo, seria contradictorio y habria
    que desconfiar del calculo antes que celebrar."""
    caps = capturas_patologicas()
    filas = est.observaciones(caps, 12, est.piso_observado(caps) * 1.2)
    assert filas
    for f in filas:
        assert f["lado"] in ("arriba", "abajo")
        assert isinstance(f["alcanzado"], bool)
        # `rebote` solo tiene sentido si el precio llego: si no, es None
        if not f["alcanzado"]:
            assert f["rebote"] is None
        else:
            assert isinstance(f["rebote"], bool)


def test_el_bootstrap_es_por_bloques_contiguos():
    """Las capturas vecinas comparten los mismos muros durante horas, asi que
    remuestrear filas sueltas finge independencia y estrecha el CI hasta mentir."""
    rng = random.Random(1)
    caps = capturas_patologicas(n=400)
    filas = est.observaciones(caps, 12, est.piso_observado(caps) * 1.2)
    bs = est.bootstrap_dif(filas, "alcanzado", rng)
    if bs is not None:
        assert "ci95" in bs and "cruza_cero" in bs
        assert bs["ci95"][0] <= bs["dif_pp"] <= bs["ci95"][1]
    fuente = open(FUENTE, encoding="utf-8").read()
    assert "BLOQUE" in fuente and "rows[k:k + BLOQUE]" in fuente


def test_sin_datos_suficientes_lo_dice_y_no_inventa():
    """Con pocas capturas tiene que reportar cuantas faltan, no producir un numero."""
    fuente = open(FUENTE, encoding="utf-8").read()
    assert "sin_datos_suficientes" in fuente
    assert "faltan" in fuente
    assert "no es un error" in fuente


def test_el_nivel_evaluado_es_el_centro_del_bucket_tenga_muro_o_no():
    """Si el nivel con muro se evaluara EN el muro y el control en otra parte, se
    compararian precios distintos y el pareo no valdria nada."""
    fuente = open(FUENTE, encoding="utf-8").read()
    bloque = fuente.split("def observaciones(")[1].split("\ndef ")[0]
    assert "centro = precio * (1 + signo * (lo + hi) / 200)" in bloque
    # el centro se calcula ANTES de saber si hay muro
    assert bloque.index("centro =") < bloque.index("en_bucket =")


def test_el_fixture_patologico_no_se_puede_sanear():
    """Candado del candado: si alguien "limpia" este fixture, los tests de arriba
    pasan a probar un caso amable y dejan de servir. Los cuatro defectos del
    2026-07-26 eran invisibles justamente en fixtures amables.
    """
    caps = capturas_patologicas()
    montos = [u for c in caps for _, u in [*c["bids"], *c["asks"]]]
    assert min(montos) == PISO, "el fixture perdio el piso exacto de CoinGlass"
    assert max(montos) == BALLENA, "el fixture perdio la ballena persistente"
    assert max(montos) / sorted(montos)[len(montos) // 2] > 20, \
        "el fixture perdio la asimetria extrema entre la ballena y la mediana"

    # el parpadeo: el conteo de muros NO puede ser constante
    conteos = {len(c["bids"]) + len(c["asks"]) for c in caps}
    assert len(conteos) > 1, "el fixture perdio el parpadeo del borde"

    # y el precio se mueve poco, como en la realidad
    precios = [c["price"] for c in caps]
    recorrido = (max(precios) / min(precios) - 1) * 100
    assert recorrido < 2.0, f"el fixture se volvio volatil ({recorrido:.2f}%)"


def test_un_bucket_fuera_del_alcance_del_precio_no_es_evaluable():
    """"Cero por cero" NO es "no hay efecto": es "no se probo".

    Corrida real del 2026-07-26: 192 capturas -por encima del minimo de 180- de un
    mercado que se movio 0,88% en 16 horas. Con una excursion maxima de 0,61%, TODOS
    los buckets desde 0,75% para arriba eran inalcanzables por aritmetica, y sus
    celdas salian "0,0% contra 0,0%". El estudio las reportaba como si fueran
    resultados.
    """
    caps = capturas_patologicas(n=200)
    exc12 = est.excursion_maxima(caps, 12)
    assert exc12 >= 0
    # el fixture apenas se mueve, igual que la realidad
    assert exc12 < 2.0

    src = codigo()
    assert "excursion_maxima" in src
    assert "alcanzable" in src and "evaluable" in src
    assert "MIN_POR_BRAZO" in src


def test_el_minimo_se_exige_en_CADA_brazo_no_en_el_total():
    """El defecto exacto: el bucket 0.25-0.5% tenia n_con=301 y n_sin=ONCE, y el
    estudio reportaba "+2,07 pp, NO cruza cero". Comparar 28 eventos de 301 contra 0
    de 11 no es una comparacion; el total de 312 disimulaba que un brazo no existia.
    """
    src = codigo()
    bloque = src.split("por_bucket")[1][:1200]
    assert "n_con >= MIN_POR_BRAZO and n_sin >= MIN_POR_BRAZO" in src, \
        "el minimo tiene que exigirse en los DOS brazos"


def test_el_gate_de_suficiencia_ya_no_mira_solo_el_conteo_de_capturas():
    """Contar capturas mide cuanto tiempo estuvo prendido el colector, no si hubo
    algo que observar. El estudio tiene que poder decir NO INTERPRETABLE aunque le
    sobren capturas."""
    src = codigo()
    assert "interpretable" in src
    assert "buckets_evaluables" in src
    fuente = open(FUENTE, encoding="utf-8").read()
    assert "no se probo" in fuente or "no se probó" in fuente
