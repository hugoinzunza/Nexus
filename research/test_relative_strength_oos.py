#!/usr/bin/env python3
"""Tests del estudio de fuerza relativa.

El cómputo lo produjo un agente que fue detenido antes de entregar tests. Estos son
mi verificación de su trabajo: lo que se protege no es el número negativo —eso ya
está— sino que las propiedades que lo hacen creíble sigan ahí. Un resultado negativo
mal medido no sirve para descartar nada.
"""
from __future__ import annotations

import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

RESULTS = os.path.join(WT, "research", "relative_strength_oos_results.json")
SCRIPT = os.path.join(WT, "research", "relative_strength_oos.py")
INFORME = os.path.join(WT, "research", "relative_strength_oos_2026-07-25.md")


def _res():
    with open(RESULTS, encoding="utf-8") as fh:
        return json.load(fh)


def _fuente():
    with open(SCRIPT, encoding="utf-8") as fh:
        return fh.read()


def test_la_beta_no_usa_velas_futuras():
    """`idx_cerrada` devuelve la última vela cuyo CIERRE es anterior o igual al
    instante de decisión: `bisect_right(t, ms - 1h) - 1`. Si alguien le quitara el
    `- H_MS`, la beta leería la vela en curso.
    """
    fuente = _fuente()
    assert "bisect.bisect_right(self.t, ms - H_MS) - 1" in fuente
    bloque = fuente.split("def beta_sigma")[1].split("\n    def ")[0]
    # los prefijos se consultan con indices acotados por i, nunca mas alla
    assert "sa[i + 1]" in bloque and "i - n_beta + 1" in bloque
    assert "i + 2" not in bloque, "estaria leyendo una vela mas alla del indice"


def test_el_instante_de_decision_es_el_cierre_de_la_barra_de_senal():
    """`t` en el volcado es el OPEN de la barra de decisión (`sel[i]["t"]`, formato
    Binance), así que el cierre es `t + TF_MS`. Si se usara `t` pelado, la beta se
    calcularía con una vela menos; si se usara `t + 2*TF`, leería el futuro.
    """
    fuente = _fuente()
    assert 'dec = t["t"] + TF_MS[t["sel_tf"]]' in fuente
    meta = _res()["meta"]
    assert "cierre de la barra de senal" in meta["instante_de_evaluacion"]
    # y el volcado de origen guarda el open de la barra de decision
    origen = open(os.path.join(WT, "modules/trading/run_setup_backtest.py"),
                  encoding="utf-8").read()
    assert '"t": sel[i]["t"]' in origen


def test_btc_no_se_rankea_contra_si_mismo():
    """Un activo comparado consigo mismo tiene fuerza residual cero por
    construcción y ensuciaría el ranking transversal."""
    res = _res()
    assert res["meta"]["btc_en_el_ranking"].startswith("NO")
    for uni in ("plan_5_pares", "todos_7_pares"):
        alt = res[uni]["altcoins_en_el_ranking"]
        assert "BTCUSDT" not in alt
        assert len(alt) >= 4


def test_el_universo_es_el_del_bot_sin_15m():
    """El 71% del universo de research antiguo era 15m, un timeframe que el bot NO
    opera, y eso contaminó los titulares de varios estudios. Acá se usa el volcado
    del pipeline real."""
    meta = _res()["meta"]
    assert "setup_backtest_trades.json" in meta["universo"]
    assert "NO hay 15m" in meta["universo"]
    assert meta["min_rr"] == 5.0


def test_el_bootstrap_es_por_bloques_mensuales():
    """Remuestrear trades finge independencia: los setups se disparan agrupados en el
    tiempo y entre pares."""
    meta = _res()["meta"]
    assert "MENSUALES" in meta["bootstrap"]
    for uni in ("plan_5_pares", "todos_7_pares"):
        c = _res()[uni]["C_prioriza_coincidencias"]["bootstrap_dif_vs_azar"]
        assert c["meses"] >= 24, "muy pocos bloques para un CI creible"


def test_ninguna_variante_sobrevive_la_correccion_multiple():
    """El hallazgo central. Se probaron 81 y 135 variantes; en la tabla SIN corregir
    hay ~5 con CI que no cruza cero, que es justo lo que produce el azar al 5%.
    Holm las elimina todas.
    """
    res = _res()
    for uni, minimo in (("plan_5_pares", 81), ("todos_7_pares", 135)):
        total = significativas = 0
        mejor = 1.0
        for familia in res[uni]["D_correccion_multiple_holm"].values():
            for r in familia["resultados"]:
                total += 1
                significativas += bool(r["significativo_005"])
                mejor = min(mejor, r["p"])
                # con esta cantidad de pruebas, Holm tiene que castigar fuerte
                assert r["p_holm"] >= r["p"]
        assert total >= minimo, f"{uni}: se perdieron pruebas de la familia"
        assert significativas == 0, \
            f"{uni}: {significativas} variantes sobrevivieron a Holm; hay que rehacer el veredicto"
        assert mejor < 0.10, "ni el mejor p crudo se acerca: revisar que el test corra"


def test_no_hay_monotonia_entre_ranking_y_resultado():
    """Sin monotonía, cualquier umbral que funcione es un umbral elegido."""
    res = _res()
    for uni in ("plan_5_pares", "todos_7_pares"):
        mono = res[uni]["B_monotonia_pendiente_vs_posicion"]
        pendientes = [v for f in mono.values() for v in f.values()
                      if isinstance(v, dict) and "cruza_cero" in v]
        cruzan = sum(1 for v in pendientes if v["cruza_cero"])
        assert len(pendientes) >= 12
        assert cruzan >= len(pendientes) - 1, \
            f"{uni}: aparecio monotonia donde no habia; revisar"


def test_el_placebo_cubre_las_mismas_variantes_y_sale_plano():
    """El placebo cubre los mismos lados y las mismas 81 variantes, y ninguna se
    separa de cero en el bootstrap del período completo.

    ASIMETRÍA DECLARADA: al placebo le falta el bootstrap específico de OOS
    (`OOS_dif_vs_baseline`) que sí tiene el filtro direccional. Lo encontré al
    escribir este test. No invalida la conclusión negativa —el filtro ya muere en
    Holm, y el placebo sale plano en el período completo— pero significa que el
    placebo NO es un control perfectamente pareado, y eso queda escrito en el
    informe en vez de taparse.
    """
    res = _res()["plan_5_pares"]
    d, e = res["D_filtro_direccional"], res["E_placebo_contrario"]
    assert set(d) == set(e), "el placebo no cubre los mismos lados"
    for lado in d:
        assert set(d[lado]) == set(e[lado]), "el placebo no cubre las mismas variantes"

    planos = [o for variantes in e.values() for o in variantes.values()
              if isinstance(o, dict) and o.get("bootstrap_dif_vs_baseline")]
    assert len(planos) >= 81
    assert all(o["bootstrap_dif_vs_baseline"]["cruza_cero"] for o in planos), \
        "el placebo mostro senal: habria que rehacer el veredicto"

    # Se normalizan los espacios: el markdown envuelve las frases y ya me hizo fallar
    # tres tests hoy buscando texto que estaba partido por un salto de linea.
    txt = " ".join(open(INFORME, encoding="utf-8").read().split())
    assert "no es un control perfectamente pareado" in txt, \
        "la asimetria del placebo debe quedar declarada en el informe"


def test_no_se_forzo_el_cruce_con_coinglass():
    """El store es sólo BTC y arranca en 2026-01: una fuerza relativa transversal
    necesita OI/funding/taker POR PAR, que no existen. Forzarlo habría producido un
    número sin sentido con apariencia de resultado."""
    cg = _res()["coinglass"]
    assert cg["solo_btc"] is True
    assert cg["trades_del_backtest_dentro_de_la_ventana"] < cg["trades_totales"] * 0.2
    assert "NO ALCANZA" in cg["veredicto"]
    assert "POR PAR" in cg["veredicto"]


def test_el_informe_dice_NO_USAR_y_declara_la_procedencia():
    """Un resultado negativo sirve para descartar sólo si queda escrito como tal. Y
    el informe debe declarar que el cómputo lo hizo un agente detenido y que la
    causalidad se verificó a mano."""
    txt = " ".join(open(INFORME, encoding="utf-8").read().split())
    assert "NO USAR" in txt
    assert "DESCARTAD" in txt
    assert "fue detenido" in txt, "la procedencia del computo debe quedar declarada"
    assert "verifiqué" in txt or "verifique" in txt
    # y las limitaciones que reducen el poder del test
    assert "1% de trades = 30%" in txt or "aporta el 30%" in txt
    assert "no se vería" in txt or "no verse" in txt


def test_marcado_como_research():
    meta = _res()["meta"]
    assert meta["research_only"] is True
    assert meta["execution_enabled"] is False
    assert meta["validated"] is False
