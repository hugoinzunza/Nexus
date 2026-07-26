#!/usr/bin/env python3
"""Tests del estudio del "vacío disponible".

Lo que se protege acá no es el veredicto —sea cual sea— sino las propiedades que lo
hacen creíble. En este proyecto ya pasó dos veces que un número se cayó por debajo:
un bucle que arrancaba en `act_idx` en vez de `act_idx + 1` costaba 1,5R por trade, y
un p-value calculado sobre trades sueltos (39 de ellos en 8 días) mintió por 10
órdenes de magnitud. Un resultado negativo mal medido no sirve para descartar nada.

Los dos tests obligatorios del encargo son:
  - `test_no_hay_look_ahead_en_los_obstaculos`
  - `test_control_b_esta_implementado_de_verdad`

Corre:  .venv/bin/python3 -m pytest research/test_vacio_disponible.py -q
"""
from __future__ import annotations

import json
import os
import random
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

import research.vacio_disponible as V                          # noqa: E402
from modules.trading import smc, smc_live                      # noqa: E402
from modules.trading import run_setup_backtest as rsb          # noqa: E402

RESULTS = V.OUT_JSON
CACHE = V.CACHE
SCRIPT = os.path.join(WT, "research", "vacio_disponible.py")
INFORME = os.path.join(WT, "research", "vacio_disponible_2026-07-26.md")


def _res():
    with open(RESULTS, encoding="utf-8") as fh:
        return json.load(fh)


def _cache():
    with open(CACHE, encoding="utf-8") as fh:
        return json.load(fh)


def _fuente():
    with open(SCRIPT, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1) ANTI-LOOK-AHEAD
# ---------------------------------------------------------------------------

def _foto(series, ts, sel_tf, i):
    """Reconstruye la foto del as_of tal como la arma `_pass`: plan + conteos."""
    sel = series[sel_tf]
    close_time = sel[i]["t"] + rsb.TF_MS[sel_tf]
    htf_map = {tf: rsb._htf_slice(series[tf], ts[tf], rsb.TF_MS[tf], close_time, rsb.WIN)
               for tf in rsb.POI_TFS}
    sel_win = sel[max(0, i - rsb.WIN + 1):i + 1]
    V._CAPTURA.clear()
    a = smc_live.analyze(sel_win, htf_map, sel[i]["c"], sel_tf)
    plan = a.get("tpsl")
    if not plan:
        return None
    entry = plan["entry"]
    long = plan["dir"] == "long"
    atr = smc.atr(sel[:i + 1], 14)[i]
    cands = V._cands(list(V._CAPTURA), a.get("levels") or [], entry, arriba=long)
    n, p1, k1, tf1 = V._contar(cands, entry, plan["tp"], long, atr)
    espejo = entry - (plan["tp"] - entry)
    cb = V._cands(list(V._CAPTURA), a.get("levels") or [], entry, arriba=not long)
    nb, _, _, _ = V._contar(cb, entry, espejo, not long, atr)
    return {"entry": entry, "tp": plan["tp"], "rr": plan["rr"], "dir": plan["dir"],
            "n": n, "primer": p1, "kind": k1, "tf": tf1, "behind": nb}


def test_no_hay_look_ahead_en_los_obstaculos():
    """La foto del as_of tiene que ser IDÉNTICA con la serie completa y con la serie
    truncada en la barra de decisión.

    Es el test que importa porque el colector recibe las series ENTERAS: si algo
    dentro de `analyze`, de `_htf_slice` o del ATR precalculado se asomara una vela
    más allá, acá cambiarían los conteos. Se prueban varias barras, no una, porque
    una sola puede no tener plan o no tener obstáculos y pasar por casualidad.
    """
    V._instrumentar()
    series = {tf: rsb._load("BTCUSDT", tf) for tf in set(rsb.POI_TFS) | set(rsb.SEL_TFS)}
    ts = {tf: [c["t"] for c in series[tf]] for tf in series}
    sel_tf = "1h"
    sel = series[sel_tf]
    import bisect
    comparadas = 0
    for i in range(len(sel) - 3000, len(sel) - 3000 + 200):
        completa = _foto(series, ts, sel_tf, i)
        if completa is None:
            continue
        close_time = sel[i]["t"] + rsb.TF_MS[sel_tf]
        # Serie truncada: literalmente no existe ninguna vela posterior al cierre
        # de la barra de decisión. Si el resultado cambia, hay fuga.
        trunc = {tf: series[tf][:bisect.bisect_right(ts[tf], close_time - rsb.TF_MS[tf])]
                 for tf in series}
        trunc[sel_tf] = sel[:i + 1]
        ts_t = {tf: [c["t"] for c in trunc[tf]] for tf in trunc}
        truncada = _foto(trunc, ts_t, sel_tf, len(trunc[sel_tf]) - 1)
        assert truncada == completa, f"fuga de futuro en la barra {i}: {completa} vs {truncada}"
        comparadas += 1
    assert comparadas >= 10, f"solo se compararon {comparadas} barras con plan"


def test_el_atr_precalculado_es_causal():
    """El colector precalcula el ATR sobre la serie ENTERA por velocidad. Eso sólo
    es legítimo si `smc.atr` es causal. Si alguien lo cambiara por un ATR centrado
    o normalizado por la muestra completa, este test lo caza."""
    sel = rsb._load("BTCUSDT", "1h")
    full = smc.atr(sel, 14)
    for i in (5000, 12000, 30000):
        parcial = smc.atr(sel[:i + 1], 14)
        assert abs(parcial[i] - full[i]) < 1e-9


def test_la_simulacion_forward_arranca_en_act_idx_mas_uno():
    """El bug real de 2026-07-25: contar la barra de activación regalaba TP1.

    Para un largo, activarse significa que el MÍNIMO de esa barra bajó a la zona —
    pero su MÁXIMO pudo ocurrir ANTES, mientras el precio venía cayendo. Con OHLC no
    se sabe el orden intrabarra. Test de comportamiento: una barra de activación con
    un máximo enorme NO debe marcar `reach_tp1`.
    """
    assert "for j in range(act_idx + 1, end)" in _fuente()
    setup = {"dir": "long", "entry": 100.0, "sl": 99.0, "tp": 130.0}
    velas = [{"t": 0, "o": 100, "h": 100, "l": 100, "c": 100},
             # barra de activación con un máximo que superaría TP1 (101) de sobra
             {"t": 1, "o": 100, "h": 120, "l": 99.5, "c": 100},
             {"t": 2, "o": 100, "h": 100.2, "l": 99.5, "c": 100}]
    ex = V._mfe_mae(setup, velas, act_idx=1, end=3)
    assert ex["reach_tp1"] is False, "contó la barra de activación (look-ahead intrabar)"
    ex2 = V._mfe_mae(setup, velas, act_idx=0, end=3)
    assert ex2["reach_tp1"] is True, "el test no discrimina: revisar el fixture"


def test_el_sl_pega_antes_que_el_objetivo_en_la_misma_barra():
    """Convención intrabar conservadora del proyecto: si una barra toca SL y TP, gana
    el SL. Sin esto, cualquier estudio se infla solo."""
    setup = {"dir": "long", "entry": 100.0, "sl": 99.0, "tp": 110.0}
    velas = [{"t": 0, "o": 100, "h": 100, "l": 100, "c": 100},
             {"t": 1, "o": 100, "h": 111, "l": 98.0, "c": 100}]
    ex = V._mfe_mae(setup, velas, act_idx=0, end=2)
    assert ex["reach_tp"] is False and ex["reach_tp1"] is False


# ---------------------------------------------------------------------------
# 2) CONTROL NEGATIVO (b) — el que puede invalidar el estudio entero
# ---------------------------------------------------------------------------

def test_control_b_esta_implementado_de_verdad():
    """El control (b) cuenta obstáculos DETRÁS de la entrada (banda espejo, misma
    distancia, dirección contraria). Si predijera algo, habría fuga.

    Se verifica por COMPORTAMIENTO, no por lectura del código: con una geometría
    fabricada, el conteo hacia adelante y el de la banda espejo tienen que recoger
    conjuntos DISJUNTOS de niveles, y cada uno el suyo.
    """
    entry, tp = 100.0, 110.0          # largo: banda adelante (100,110), espejo (90,100)
    atr = 1.0
    pois = [
        {"dir": "short", "tf": "4h", "lo": 105.0, "hi": 106.0, "valid": True},   # adelante
        {"dir": "long", "tf": "4h", "lo": 94.0, "hi": 95.0, "valid": True},      # detrás
        {"dir": "long", "tf": "1h", "lo": 99.5, "hi": 100.5, "valid": True},     # contiene la entrada
    ]
    levels = [{"price": 103.0, "kind": "strong", "type": "high"},
              {"price": 97.0, "kind": "weak", "type": "low"}]

    fwd = V._cands(pois, levels, entry, arriba=True)
    bwd = V._cands(pois, levels, entry, arriba=False)
    n_f, p_f, _, _ = V._contar(fwd, entry, tp, True, atr)
    n_b, p_b, _, _ = V._contar(bwd, entry, entry - (tp - entry), False, atr)

    assert n_f == 2 and p_f == 103.0, f"adelante: {n_f} obstáculos, primero {p_f}"
    assert n_b == 2 and p_b == 97.0, f"espejo: {n_b} obstáculos, primero {p_b}"
    # ningún precio de una banda aparece en la otra
    en_f = {c["price"] for c in fwd if V._en_banda(c["price"], entry, tp)}
    en_b = {c["price"] for c in bwd if V._en_banda(c["price"], entry, 2 * entry - tp)}
    assert en_f.isdisjoint(en_b)
    # la zona que CONTIENE la entrada no es pared en ninguna dirección: si contara,
    # el control quedaría con flag=1 en el 100% de los trades y sería inútil
    assert 99.5 not in {c["price"] for c in fwd}
    assert 100.5 not in {c["price"] for c in bwd}


def test_control_b_produce_variacion_real_en_los_datos():
    """Un control que sale constante no controla nada. En los datos reales el conteo
    detrás del entry tiene que tener celda 0 poblada y NO ser una copia del conteo
    hacia adelante."""
    filas = _cache()
    act = [r for r in filas if r["status"] in ("ganada", "perdida") and r["rr"] >= V.RR_MIN]
    assert act, "el caché no tiene trades activados"
    ceros = sum(1 for r in act if r["obst_behind"] == 0)
    assert ceros >= 50, f"el control (b) casi no tiene celda 0 ({ceros})"
    iguales = sum(1 for r in act if r["obst_behind"] == r["obst_all"])
    assert iguales < 0.5 * len(act), "obst_behind es prácticamente obst_all: no es un control"


def test_el_json_reporta_los_tres_controles_negativos():
    r = _res()
    c = r["controles_negativos"]
    for k in ("a_placebo", "b_detras_del_entry", "c_permutado_por_distancia"):
        assert k in c, f"falta el control {k}"
        for y in V.DESENLACES:
            assert c[k][y]["crudo"] is not None
    assert "INVALIDO" in c["b_detras_del_entry"]["que_es"]


def test_control_c_permuta_dentro_de_deciles_de_distancia():
    """El control (c) tiene que conservar la distribución de conteos DENTRO de cada
    decil de |tp-entry|/ATR: si permutara entre deciles, estaría destruyendo también
    la información de distancia y no probaría lo que dice probar."""
    rng = random.Random(1)
    filas = [{"band_atr": float(i), "obst_all": i % 7} for i in range(1000)]
    filas.sort(key=lambda r: r["band_atr"])
    for k in range(10):
        g = filas[int(len(filas) * k / 10):int(len(filas) * (k + 1) / 10)]
        antes = sorted(r["obst_all"] for r in g)
        vals = [r["obst_all"] for r in g]
        rng.shuffle(vals)
        for r, v in zip(g, vals):
            r["obst_perm"] = v
        assert sorted(r["obst_perm"] for r in g) == antes
    assert "for k in range(10)" in _fuente()


# ---------------------------------------------------------------------------
# 3) DEFINICIÓN DE OBSTÁCULO
# ---------------------------------------------------------------------------

def test_en_banda_es_estricto():
    """Estricto a propósito: el propio TP no es obstáculo de sí mismo, y el POI de
    entrada tampoco. Con `<=` el conteo se autoincrementaría en todos los trades."""
    assert V._en_banda(105, 100, 110)
    assert not V._en_banda(110, 100, 110)
    assert not V._en_banda(100, 100, 110)
    assert V._en_banda(105, 110, 100)      # el orden de los extremos no importa


def test_cands_usa_el_borde_cercano_de_la_zona():
    """La clase 7 lo dice explícito: la distancia al borde cercano es más honesta que
    al centro. Subiendo se choca con `lo`; bajando, con `hi`."""
    pois = [{"dir": "short", "tf": "4h", "lo": 105.0, "hi": 108.0, "valid": True}]
    arriba = V._cands(pois, [], 100.0, arriba=True)
    abajo = V._cands(pois, [], 100.0, arriba=False)
    assert [c["price"] for c in arriba] == [105.0]
    assert [c["price"] for c in abajo] == [108.0]


def test_contar_deduplica_paredes_vecinas_con_un_corte_en_ATR():
    """El corte de agrupación es 0,25 x ATR, RELATIVO a la volatilidad del propio
    instrumento. Un umbral fijo (0,1%, $50) es el defecto que ya apareció seis veces
    en este proyecto: con BTC a 100k y DOGE a 0,12 no significa lo mismo."""
    cands = [{"price": 101.0, "kind": "poi", "tf": "1h", "valid": True},
             {"price": 101.2, "kind": "poi", "tf": "1h", "valid": True},
             {"price": 105.0, "kind": "poi", "tf": "1h", "valid": True}]
    n, primero, _, _ = V._contar(cands, 100.0, 110.0, True, atr=1.0)
    assert n == 2 and primero == 101.0          # 101,0 y 101,2 son la misma pared
    n0, _, _, _ = V._contar(cands, 100.0, 110.0, True, atr=1.0, tol_atr=0.0)
    assert n0 == 3                               # sin agrupar, tres
    # con un ATR grande (activo volátil) las tres colapsan en una
    n1, _, _, _ = V._contar(cands, 100.0, 110.0, True, atr=40.0)
    assert n1 == 1


def test_contar_ordena_por_cercania_a_la_entrada_segun_la_direccion():
    cands = [{"price": 95.0, "kind": "poi", "tf": "1h", "valid": True},
             {"price": 98.0, "kind": "poi", "tf": "1h", "valid": True}]
    _, primero, _, _ = V._contar(cands, 100.0, 90.0, False, atr=1.0)
    assert primero == 98.0, "para un corto el primer obstáculo es el más ALTO de la banda"


def test_los_subconjuntos_de_obstaculos_estan_anidados():
    """obst_levels y obst_htf son subconjuntos de obst_all: si alguna definición
    contara de más, el anidamiento se rompe y la comparación entre definiciones
    dejaría de significar nada."""
    filas = _cache()
    malos = [r for r in filas
             if r["obst_levels"] > r["obst_all"] or r["obst_valid"] > r["obst_all"]
             or r["obst_htf"] > r["obst_all"]]
    assert not malos, f"{len(malos)} filas con subconjuntos mayores que el total"


# ---------------------------------------------------------------------------
# 4) ESTADÍSTICA
# ---------------------------------------------------------------------------

def test_el_bootstrap_remuestrea_dias_no_trades():
    """39 trades del Diario cayeron en 8 días, 31 en 3 días seguidos. Remuestrear
    trades sueltos finge independencia y estrecha el CI hasta mentir."""
    rows = [{"t": 1700000000000 + (i // 20) * 86400000, "x": 1.0} for i in range(200)]
    bl = V.bloques_diarios(rows)
    assert len(bl) == 10 and sum(len(b) for b in bl) == 200
    # el CI por bloques de una muestra con estructura diaria es MÁS ANCHO que el
    # ingenuo: si alguien cambiara el remuestreo, esta desigualdad se invierte
    rng = random.Random(7)
    dias = [rng.gauss(0, 1) for _ in range(30)]
    corr = [{"t": 1700000000000 + d * 86400000, "x": dias[d] + rng.gauss(0, 0.05)}
            for d in range(30) for _ in range(20)]
    est = V.boot_stat(corr, lambda rr: sum(r["x"] for r in rr) / len(rr), rng, B=400)
    ancho_bloques = est["ci95"][1] - est["ci95"][0]
    vals = sorted(sum(rng.choice(corr)["x"] for _ in range(len(corr))) / len(corr)
                  for _ in range(400))
    ancho_ingenuo = vals[389] - vals[10]
    assert ancho_bloques > 3 * ancho_ingenuo


def test_holm_corrige_y_es_monotono():
    """Ya nos pasó con fuerza relativa: 5 de 81 variantes se veían significativas sin
    corregir y ninguna sobrevivió."""
    out = V.holm({"a": 0.001, "b": 0.02, "c": 0.30, "d": 0.9})
    assert out["a"]["p_holm"] == 0.004 and out["a"]["sobrevive"]
    assert out["b"]["p_holm"] >= out["a"]["p_holm"]
    assert out["c"]["p_holm"] >= out["b"]["p_holm"]
    assert not out["d"]["sobrevive"]
    solo = V.holm({"a": 0.04})
    assert solo["a"]["p_holm"] == 0.04 and solo["a"]["sobrevive"]


def test_netR_descuenta_costos_y_pesa_mas_con_stop_ajustado():
    """El costo se paga sobre el NOCIONAL: en unidades de R pesa más cuando el stop
    es ajustado. Restar un fijo subestimaría el costo del decil más apretado."""
    ancho = V.netR(1.0, 0.02)
    apretado = V.netR(1.0, 0.004)
    assert ancho > apretado
    assert V.netR(1.0, 0.008) < 1.0
    assert V.netR(None, 0.01) is None and V.netR(1.0, 0) is None


def test_ols_recupera_un_coeficiente_conocido():
    """La OLS es artesanal (este venv no tiene numpy). Si la eliminación gaussiana o
    el ensamblado por bloques estuvieran mal, el coeficiente no sería el sembrado."""
    rng = random.Random(3)
    rows = []
    for d in range(60):
        for _ in range(10):
            x = rng.gauss(0, 1)
            rows.append({"t": 1700000000000 + d * 86400000, "x": x,
                         "y": 2.0 + 0.5 * x + rng.gauss(0, 0.1)})
    out = V.ols_bloques(rows, "y", [("x", lambda r: r["x"])], rng, B=60)
    assert abs(out["x"]["coef"] - 0.5) < 0.05
    assert out["x"]["ci95"][0] < 0.5 < out["x"]["ci95"][1]


# ---------------------------------------------------------------------------
# 5) HIGIENE DEL ENTREGABLE
# ---------------------------------------------------------------------------

def test_meta_declara_research_only():
    m = _res()["meta"]
    assert m["research_only"] is True
    assert m["execution_enabled"] is False
    assert m["validated"] is False


def test_el_diseno_preregistrado_viaja_en_el_json():
    """Sin el diseño escrito al lado de los números, nadie puede comprobar que los
    cortes no se movieron después de ver los resultados."""
    d = _res()["meta"]["diseno_preregistrado"]
    assert d["n_minimo_por_celda"] == 300
    assert d["is_oos_corte"] == "2025-03-19"
    assert "bootstrap de BLOQUES DIARIOS" in d["ci"]
    assert set(d["controles_negativos"]) == {
        "a_placebo_+-0.3ATR", "b_detras_del_entry", "c_permutado_por_distancia"}
    assert _res()["meta"]["desviaciones_del_diseno"], "toda desviación debe quedar escrita"


def test_las_celdas_bajo_el_minimo_quedan_marcadas():
    """El encargo: si una celda no llega a 300, se reporta y NO se interpreta."""
    r = _res()
    for d in V.DEFS:
        bajo = r["celdas_bajo_minimo"][d]
        for k in ("0", "1", "2", "3+"):
            n = r["distribucion_celdas"][d][k]
            assert (n < 300) == (k in bajo)


def test_el_universo_no_tiene_15m_ni_rr_bajo():
    """Medido: 1h gana a 15m en 45 de 49 variantes, y el 71% del universo de research
    antiguo era un timeframe que el bot no opera. El plan corre rr>=5."""
    u = _res()["meta"]["universo"]
    assert set(u["sel_tfs"]) <= {"1h", "4h"}
    filas = [r for r in _cache()
             if r["status"] in ("ganada", "perdida") and r["rr"] >= V.RR_MIN]
    assert all(r["sel_tf"] in ("1h", "4h") for r in filas)
    assert min(r["rr"] for r in filas) >= 5.0


def test_el_informe_trae_veredicto_y_los_tres_controles():
    """El criterio de decisión estaba pre-registrado: PROMOVER / SEGUIR / DESCARTAR.
    Un informe sin veredicto explícito deja la decisión al lector, que es justo lo
    que el pre-registro trata de evitar."""
    with open(INFORME, encoding="utf-8") as fh:
        txt = fh.read()
    assert "VEREDICTO" in txt
    assert any(v in txt for v in ("PROMOVER", "SEGUIR INVESTIGANDO", "DESCARTAR"))
    for c in ("placebo", "detrás del entry", "permutado"):
        assert c in txt, f"el informe no reporta el control {c}"
    assert "Limitaciones" in txt and "research_only" in txt
    # el alcance honesto: esto NO explica la brecha backtest vs Diario
    assert "33,3" in txt and "67,4" in txt


def test_el_estudio_no_toca_modules_ni_data():
    """Instrumentación en runtime, no edición de producción. Y `data/` es de lectura."""
    src = _fuente()
    assert "smc_live._pois_for_tf = wrapper" in src
    assert 'open(CACHE, "w"' in src and 'open(OUT_JSON, "w"' in src
    for salida in ("CACHE", "OUT_JSON"):
        ruta = getattr(V, salida)
        assert os.path.dirname(ruta).endswith("research")
        assert os.path.basename(ruta).startswith("vacio_disponible")
