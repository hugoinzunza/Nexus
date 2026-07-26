#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests del estudio de Refugios de Mediano Plazo.

Cada test protege un defecto concreto que ya se cometio (aqui o en estudios
anteriores de este repo). No prueban "que la funcion hace lo que dice": prueban
que el estudio no puede mentir de la forma clasica.

    python3 -m pytest research/test_refugios_anuales.py -q
"""

import datetime as dt
import json
import os
import random
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import refugios_anuales as R  # noqa: E402


# --------------------------------------------------------------------------
# Helpers de datos sinteticos: sin tocar data/ (que es solo lectura)
# --------------------------------------------------------------------------
def synth_bars(start_year=2023, n_days=800, price0=100.0, seed=7):
    rng = random.Random(seed)
    t0 = R.utc_ms(start_year, 1, 1)
    t, o, h, l, c = [], [], [], [], []
    px = price0
    for i in range(n_days):
        op = px
        move = op * rng.uniform(-0.05, 0.05)
        cl = max(op + move, op * 0.5)
        hi = max(op, cl) * (1 + abs(rng.gauss(0, 0.01)))
        lo = min(op, cl) * (1 - abs(rng.gauss(0, 0.01)))
        t.append(t0 + i * R.DAY_MS)
        o.append(op); h.append(hi); l.append(lo); c.append(cl)
        px = cl
    return {
        "t": np.array(t, dtype=np.int64),
        "o": np.array(o), "h": np.array(h), "l": np.array(l), "c": np.array(c),
    }


# --------------------------------------------------------------------------
# CAUSALIDAD — el test que el enunciado pide explicitamente
# --------------------------------------------------------------------------
def test_la_rejilla_de_un_anio_no_existe_antes_del_1_de_enero():
    """La rejilla del anio y solo puede evaluarse desde el 1-ene de y.

    Si la ventana empezara antes, el ancla de 2025 "explicaria" 2024 y todo el
    estudio seria circular. Se verifica que la ventana arranca exactamente en
    la vela del 1-ene y que ningun episodio cae antes de esa fecha.
    """
    bars = synth_bars(start_year=2022, n_days=1000)
    atrp = R.atr_prev(bars, R.PREREG["atr_period"])
    built = R.build_year_families("SYNTH", bars, atrp, 2023, random.Random(1))
    assert built is not None

    jan1 = R.utc_ms(2023, 1, 1)
    assert int(bars["t"][built["i_anchor"]]) == jan1
    assert int(bars["t"][built["i_anchor"]]) >= jan1  # nunca antes

    for lv in built["families"]["rmp_10"]:
        eps = R.find_episodes(
            lv["level"], bars, atrp, built["i_anchor"], built["i_end"],
            R.PREREG["touch_tolerance_atr"], R.PREREG["episode_gap_bars"],
        )
        for i in eps:
            assert int(bars["t"][i]) >= jan1, "episodio anterior al nacimiento de la rejilla"
            assert int(bars["t"][i]) < R.utc_ms(2024, 1, 1), "episodio fuera del anio de validez"


def test_anio_sin_vela_del_1_de_enero_se_excluye_y_no_se_inventa_ancla():
    """Si el snapshot no tiene el 1-ene, el anio se excluye. Usar la primera
    vela disponible (23-feb en los datos reales) seria fabricar un ancla."""
    bars = synth_bars(start_year=2023, n_days=400)  # empieza el 1-ene-2023
    atrp = R.atr_prev(bars, R.PREREG["atr_period"])
    assert R.build_year_families("SYNTH", bars, atrp, 2022, random.Random(1)) is None
    assert R.build_year_families("SYNTH", bars, atrp, 2023, random.Random(1)) is not None


def test_atr_es_causal():
    """atr_prev[i] no puede contener informacion de la vela i."""
    bars = synth_bars(n_days=200)
    a_full = R.atr_prev(bars, 14)
    i = 120
    truncado = {k: v[: i + 1].copy() for k, v in bars.items()}
    # se altera la ULTIMA vela; el ATR usado para evaluarla no debe cambiar
    truncado["h"][i] *= 3.0
    truncado["l"][i] /= 3.0
    a_trunc = R.atr_prev(truncado, 14)
    assert np.isclose(a_full[i], a_trunc[i]), "el ATR usado en la vela i miro dentro de la vela i"


# --------------------------------------------------------------------------
# NIVELES NEGATIVOS — el otro test que el enunciado pide explicitamente
# --------------------------------------------------------------------------
def test_niveles_no_positivos_se_excluyen_y_se_cuentan():
    """Con paso 0.10 y k>=10 hacia abajo el precio es 0 o negativo.

    Un activo spot no tiene precio negativo: esos niveles se descartan y se
    reportan, no se dejan colar como "soportes profundos".
    """
    levels, dropped = R.rmp_levels(100.0, 0.10, 15)
    assert dropped == 6, "deben excluirse k=10..15 en direccion bajista"
    assert all(lv["level"] > 0 for lv in levels)
    assert not any(lv["dir"] == -1 and lv["k"] >= 10 for lv in levels)
    # el nivel exactamente cero tampoco pasa
    assert all(abs(lv["level"]) > 1e-12 for lv in levels)


def test_conteo_de_excluidos_depende_del_paso():
    """Cada paso placebo excluye una cantidad distinta: 7.5% excluye k>=14,
    12.5% excluye k>=8. Si el conteo fuera constante habria un bug."""
    _, d075 = R.rmp_levels(100.0, 0.075, 15)
    _, d125 = R.rmp_levels(100.0, 0.125, 15)
    assert d075 == 2
    assert d125 == 8


def test_pasos_lineales_no_compuestos():
    """+20% es O*1.20, NO O*1.10^2. El curso es explicito y componer moveria
    todos los niveles altos."""
    levels, _ = R.rmp_levels(1000.0, 0.10, 3)
    up = {lv["k"]: lv["level"] for lv in levels if lv["dir"] == 1}
    assert up[1] == pytest.approx(1100.0)
    assert up[2] == pytest.approx(1200.0)
    assert up[2] != pytest.approx(1000.0 * 1.1 ** 2)
    assert up[3] == pytest.approx(1300.0)


# --------------------------------------------------------------------------
# ESCALA — el error cometido seis veces en este proyecto
# --------------------------------------------------------------------------
def test_tolerancia_de_toque_escala_con_el_atr_y_no_es_un_porcentaje_fijo():
    """Dos activos identicos en forma pero de distinta volatilidad deben
    producir el MISMO resultado de contacto. Un umbral fijo en % los separaria."""
    bars = synth_bars(n_days=120, price0=100.0)
    atrp = R.atr_prev(bars, 14)
    i = 100
    nivel_apenas_fuera = float(bars["h"][i]) + 0.5 * float(atrp[i])
    nivel_dentro = float(bars["h"][i]) + 0.1 * float(atrp[i])
    assert R.find_episodes(nivel_dentro, bars, atrp, i, i + 1, 0.25, 5) == [i]
    assert R.find_episodes(nivel_apenas_fuera, bars, atrp, i, i + 1, 0.25, 5) == []

    # el mismo activo escalado x1000 se comporta identico: escala-invariante
    big = {k: (v * 1000.0 if k in ("o", "h", "l", "c") else v) for k, v in bars.items()}
    atrb = R.atr_prev(big, 14)
    assert R.find_episodes(nivel_dentro * 1000.0, big, atrb, i, i + 1, 0.25, 5) == [i]
    assert R.find_episodes(nivel_apenas_fuera * 1000.0, big, atrb, i, i + 1, 0.25, 5) == []


def test_paso_de_numeros_redondos_se_deriva_de_los_datos():
    """Codificar 'multiplos de 1000' seria un umbral absoluto sobre una
    cantidad de escala variable: sirve para BTC y es absurdo para ADA."""
    _, r_btc = R.round_number_levels(np.array([55000.0, 70000.0]))
    _, r_ada = R.round_number_levels(np.array([0.30, 0.90]))
    assert r_btc == pytest.approx(1000.0)
    assert r_ada == pytest.approx(0.01)
    assert r_btc > r_ada


def test_reaccion_se_mide_en_atr():
    """La magnitud de reaccion debe ser invariante a la escala del activo."""
    bars = synth_bars(n_days=200, price0=50.0)
    atrp = R.atr_prev(bars, 14)
    i = 150
    nivel = float(bars["c"][i - 1]) * 0.99
    m1 = R.episode_metrics(nivel, bars, atrp, i, 5, 0.5, 1.0, 20)
    big = {k: (v * 777.0 if k in ("o", "h", "l", "c") else v) for k, v in bars.items()}
    m2 = R.episode_metrics(nivel * 777.0, big, R.atr_prev(big, 14), i, 5, 0.5, 1.0, 20)
    assert m1 is not None and m2 is not None
    assert m1["reaction_atr"] == pytest.approx(m2["reaction_atr"], rel=1e-9)
    assert m1["hit"] == m2["hit"]


# --------------------------------------------------------------------------
# EPISODIOS — no inflar n
# --------------------------------------------------------------------------
def test_contactos_cercanos_son_un_solo_episodio():
    """Una consolidacion de 5 dias contra el nivel es UN evento. Contar cada
    vela como observacion independiente infla n y estrecha el CI hasta mentir."""
    n = 60
    bars = {
        "t": np.arange(n, dtype=np.int64) * R.DAY_MS,
        "o": np.full(n, 100.0), "c": np.full(n, 100.0),
        "h": np.full(n, 101.0), "l": np.full(n, 99.0),
    }
    atrp = np.full(n, 2.0)
    # el nivel 100 esta dentro del rango de TODAS las velas
    eps = R.find_episodes(100.0, bars, atrp, 0, n, 0.25, 5)
    assert eps == [0], "60 velas en contacto continuo deben ser un unico episodio"

    # dos toques separados por mas de gap velas son dos episodios
    bars2 = {k: v.copy() for k, v in bars.items()}
    bars2["h"][5:40] = 90.0
    bars2["l"][5:40] = 80.0
    eps2 = R.find_episodes(100.0, bars2, atrp, 0, n, 0.25, 5)
    assert len(eps2) == 2 and eps2[0] == 0 and eps2[1] == 40


def test_episodio_sin_ventana_completa_se_descarta():
    """Sin las H velas siguientes no se puede medir la reaccion. Rellenar con
    lo que haya sesgaria el final de la muestra."""
    bars = synth_bars(n_days=100)
    atrp = R.atr_prev(bars, 14)
    assert R.episode_metrics(float(bars["c"][97]), bars, atrp, 97, 5, 0.5, 1.0, 20) is None
    assert R.episode_metrics(float(bars["c"][50]) * 0.999, bars, atrp, 50, 5, 0.5, 1.0, 20) is not None


def test_direccion_de_aproximacion_usa_la_vela_previa():
    """Decidir soporte/resistencia con la propia vela de contacto seria elegir
    la direccion sabiendo el resultado."""
    n = 40
    bars = {
        "t": np.arange(n, dtype=np.int64) * R.DAY_MS,
        "o": np.full(n, 100.0), "c": np.full(n, 100.0),
        "h": np.full(n, 101.0), "l": np.full(n, 99.0),
    }
    atrp = np.full(n, 1.0)
    bars["c"][19] = 105.0  # venia por arriba
    m = R.episode_metrics(100.0, bars, atrp, 20, 5, 0.5, 1.0, 10)
    assert m is not None and m["support"] is True
    bars["c"][19] = 95.0  # venia por abajo
    m = R.episode_metrics(100.0, bars, atrp, 20, 5, 0.5, 1.0, 10)
    assert m is not None and m["support"] is False


# --------------------------------------------------------------------------
# CONTROLES
# --------------------------------------------------------------------------
def test_control_aleatorio_nunca_coincide_con_el_nivel_real():
    """Si el 'aleatorio' pudiera caer encima del nivel real, el control estaria
    contaminado y la comparacion siempre daria empate por construccion."""
    base, _ = R.rmp_levels(100.0, 0.10, 5)
    rnd = R.random_levels(base, random.Random(3), 20, 100.0)
    reales = {round(lv["level"], 9) for lv in base}
    for lv in rnd:
        assert round(lv["level"], 9) not in reales
        assert abs(lv["rel"] - round(lv["rel"] / 0.10) * 0.10) >= 0.0199 - 1e-9
        assert lv["level"] > 0


def test_ancla_desplazada_produce_niveles_distintos():
    """El control (b) solo sirve si el ancla desplazada cambia los niveles."""
    bars = synth_bars(start_year=2022, n_days=900)
    atrp = R.atr_prev(bars, 14)
    built = R.build_year_families("SYNTH", bars, atrp, 2023, random.Random(1))
    a = {round(x["level"], 6) for x in built["families"]["rmp_10"]}
    b = {round(x["level"], 6) for x in built["families"]["shift_-3"]}
    assert built["shift_anchors"]["shift_-3"] is not None
    assert a != b


# --------------------------------------------------------------------------
# ESTADISTICA
# --------------------------------------------------------------------------
def test_holm_es_mas_conservador_que_crudo_y_monotono():
    p = [0.001, 0.01, 0.02, 0.04, 0.30]
    adj = R.holm(p)
    assert all(a >= x for a, x in zip(adj, p))
    orden = sorted(range(len(p)), key=lambda i: p[i])
    vals = [adj[i] for i in orden]
    assert vals == sorted(vals), "Holm debe ser monotono en el orden de los p"
    assert all(a <= 1.0 for a in adj)


def test_holm_mata_un_falso_positivo_aislado():
    """Reproduce el caso real del repo: 1 de 81 variantes con p=0.03 no debe
    sobrevivir."""
    p = [0.03] + [0.5] * 80
    assert R.holm(p)[0] > 0.05


def test_bootstrap_por_bloques_no_es_iid():
    """Con bloques internamente correlacionados, el CI por bloques tiene que
    ser MAS ancho que uno iid; si no, el bootstrap no esta bloqueando nada."""
    rs = np.random.RandomState(0)
    A, B = {}, {}
    for b in range(30):
        shift = rs.normal(0, 1.0)  # efecto de bloque (regimen)
        A[f"b{b}"] = list(rs.normal(shift + 0.05, 0.1, 40))
        B[f"b{b}"] = list(rs.normal(shift, 0.1, 40))
    res = R.block_bootstrap_diff(A, B, 1500, 11)
    ancho_bloques = res["ci95"][1] - res["ci95"][0]

    flatA = {f"x{i}": [v] for i, v in enumerate(x for xs in A.values() for x in xs)}
    flatB = {f"x{i}": [v] for i, v in enumerate(x for xs in B.values() for x in xs)}
    res_iid = R.block_bootstrap_diff(flatA, flatB, 1500, 11)
    assert ancho_bloques > (res_iid["ci95"][1] - res_iid["ci95"][0])


def test_binomial_dos_colas_sano():
    assert R.binom_two_sided(5, 10, 0.5) == pytest.approx(1.0, abs=1e-9)
    assert R.binom_two_sided(10, 10, 0.5) == pytest.approx(2 / 1024, abs=1e-9)
    assert 0.0 <= R.binom_two_sided(7, 9, 0.24) <= 1.0


# --------------------------------------------------------------------------
# CONTRATO DEL ENTREGABLE
# --------------------------------------------------------------------------
def test_resultados_marcados_como_research_only():
    """Nada de este estudio puede leerse como habilitado para ejecutar."""
    path = os.path.join(R.ROOT, "research", "refugios_anuales_results.json")
    if not os.path.exists(path):
        pytest.skip("aun no se genero el JSON de resultados")
    with open(path) as fh:
        d = json.load(fh)
    assert d["meta"]["research_only"] is True
    assert d["meta"]["execution_enabled"] is False
    assert d["meta"]["validated"] is False
    assert d["meta"]["prereg"]["venue"] == "binance"
    assert d["meta"]["prereg"]["timezone"] == "UTC"
    assert d["meta"]["prereg"]["quote_asset"] == "USDT"
    # cada ancla declara venue/quote/timezone: sin eso no es reproducible
    for a in d["meta"]["anchors"]:
        assert a["venue"] and a["quote_asset"] and a["timezone"]
        assert a["annual_open_date"].endswith("-01-01")
    assert d["meta"]["non_positive_levels_dropped"]["rmp_10"] > 0


def test_semana_binance_es_lunes_00_utc():
    """El estudio semanal no puede mezclar la semana de Londres del curso, que
    ademas se mueve con DST."""
    t = np.array([R.utc_ms(2026, 1, 5, h) for h in range(0, 24)], dtype=np.int64)  # lunes
    wid = ((t // R.HOUR_MS) + 24 * 3) // (24 * 7)
    assert len(set(wid.tolist())) == 1
    dom = np.array([R.utc_ms(2026, 1, 4, 23)], dtype=np.int64)  # domingo previo
    wid_dom = ((dom // R.HOUR_MS) + 24 * 3) // (24 * 7)
    assert wid_dom[0] == wid[0] - 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
