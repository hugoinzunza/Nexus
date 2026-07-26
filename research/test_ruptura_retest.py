"""Tests del estudio ruptura+retest.

No son tests de estilo: cada uno bloquea un defecto que YA se cometió en este
proyecto y que costó plata o credibilidad.

  1. Look-ahead por índice — hubo un bug real donde un bucle arrancaba en
     `act_idx` en vez de `act_idx + 1` y regalaba 1.5R por trade. Acá se verifica
     con velas sintéticas que ninguna resolución mira la vela del evento cuando
     no corresponde, y que el retest nunca se llena en la propia vela de ruptura.
  2. Pareo 1:1 — si el universo se mueve, la comparación contra los brazos ya
     publicados (base, cap03_8, mkt_4 sobre 8.440 trades) deja de valer.
  3. Umbral absoluto sobre cantidad de escala variable — el defecto que apareció
     seis veces: la tolerancia del nivel tiene que escalar con el activo.
  4. Conservadurismo intrabar — ante ambigüedad manda la pérdida.

Corre: .venv/bin/python3 -m pytest research/test_ruptura_retest.py -q
       (o .venv/bin/python3 research/test_ruptura_retest.py)
"""
from __future__ import annotations

import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import ruptura_retest as rr  # noqa: E402
from research import bta_visual_oos as oos  # noqa: E402

RES = os.path.join(WT, "research", "ruptura_retest_results.json")


def K(t, o, h, l, c):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": 1.0}


# ------------------------------ 1. anti look-ahead ------------------------------

def test_walk_resolve_no_mira_la_vela_del_fill_cuando_es_cierre():
    """Entrada al CIERRE de j0 => la vela j0 ya terminó y NO puede resolver.

    Si esto se rompe, un trade que entra al cierre de una vela cobraría el TP que
    esa misma vela ya hizo antes de la entrada: 1.5R regalados por trade.
    """
    velas = [K(0, 100, 200, 50, 100),      # j0: barre TP y SL "antes" de entrar
             K(1, 100, 101, 99, 100),
             K(2, 100, 100, 89, 90)]       # recién acá toca el SL real
    out = rr.walk_resolve(velas, 0, True, 100, 90, 150, include_j0=False)
    assert out is not None
    r, j_ex, _, _ = out
    assert j_ex == 2 and r == -1.0, out


def test_walk_resolve_fill_intrabar_si_revisa_su_vela_pero_solo_para_el_stop():
    """Fill intrabar (retest): la vela del fill puede matarte (SL) pero NO puede
    pagarte (TP). Ante ambigüedad intrabar, manda la pérdida."""
    velas = [K(0, 100, 160, 80, 100), K(1, 100, 100, 100, 100)]
    r, j_ex, _, _ = rr.walk_resolve(velas, 0, True, 100, 90, 150, include_j0=True)
    assert (r, j_ex) == (-1.0, 0)

    velas2 = [K(0, 100, 160, 95, 100), K(1, 100, 100, 100, 100)]
    out = rr.walk_resolve(velas2, 0, True, 100, 90, 150, include_j0=True)
    assert out is None or out[1] > 0      # el TP de la vela de fill no se cobra


def test_find_trigger_nunca_llena_en_la_vela_de_ruptura():
    """El retest se busca desde i_cdc+1. Llenar en la propia vela de ruptura sería
    exactamente el bug del `act_idx` sin +1."""
    velas = [K(0, 100, 100, 100, 100),
             K(1, 100, 120, 60, 118),      # vela de ruptura: su mínimo toca 60
             K(2, 118, 119, 117, 118),
             K(3, 118, 119, 99, 100)]      # acá sí vuelve al nivel
    j, mot = rr.find_trigger(velas, 1 + 1, 1 + 4, True, 100.0, 50.0, 500.0, True)
    assert (j, mot) == (3, "ok"), (j, mot)


def test_find_cdc_arranca_despues_del_toque():
    lh = [None, 100.0, 100.0, 100.0]
    ll = [None] * 4
    velas = [K(0, 99, 101, 98, 101),       # la vela del toque ya cierra sobre el nivel
             K(1, 99, 99.5, 98, 99),
             K(2, 99, 102, 98, 101.5),     # ruptura legítima
             K(3, 101, 102, 100, 101)]
    i, ref, mot = rr.find_cdc(velas, 0, True, 90.0, 500.0, lh, ll, 8)
    assert (i, ref, mot) == (2, 100.0, "ok")


def test_control_b_usa_el_nivel_confirmado_ANTES_de_la_vela():
    """El control (b) coloca la orden con lh2[j-1]. Si usara lh2[j] estaría
    usando un swing que se confirma en la misma vela en que opera."""
    src = open(os.path.join(WT, "research", "ruptura_retest.py")).read()
    blk = src.split("# --- control (b)")[1].split("rows.append")[0]
    code = "\n".join(l for l in blk.splitlines() if not l.strip().startswith("#"))
    assert "lh2[j - 1]" in code and "ll2[j - 1]" in code
    assert "lh2[j]" not in code and "ll2[j]" not in code


# ------------------------------ 2. pareo 1:1 ------------------------------

def test_universo_identico_al_estudio_del_abort():
    """Mismo dataset, mismo n, mismos timestamps y MISMO netR del baseline.

    Es la condición sin la cual la comparación contra base/cap03_8/mkt_4 no vale.
    """
    from research import bta_visual_abort as ab
    a = ab.study_dataset("BTCUSDT", "1h")
    b = rr.study_dataset("BTCUSDT", "1h")
    assert len(a) == len(b) and len(a) > 100
    assert [x["t"] for x in a] == [x["t"] for x in b]
    assert [x["base"] for x in a] == [x["base"] for x in b]
    assert [x["cap03_8"] for x in a] == [x["cap03_8"] for x in b]
    assert [x["mkt_4"] for x in a] == [x["mkt_4"] for x in b]


def test_resultados_universo_8440_y_meta_research_only():
    if not os.path.isfile(RES):
        return
    d = json.load(open(RES))
    assert d["meta"]["research_only"] is True
    assert d["meta"]["execution_enabled"] is False
    assert d["meta"]["validated"] is False
    assert d["meta"]["n_universo"] == 8440       # mismo universo del abort
    assert d["cortes"]["ALL"]["base"]["n"] == 8440
    assert d["cortes"]["ALL"]["base"]["avg"] == -0.033
    assert d["meta"]["prereg"]["split_oos"].startswith("2025-06-01")


def test_pareados_solo_sobre_setups_donde_ambos_brazos_operan():
    rows = [{"pair": "X", "tf": "1h", "t": 0, "a": 1.0, "b": 0.5},
            {"pair": "X", "tf": "1h", "t": 0, "a": None, "b": 0.5},
            {"pair": "X", "tf": "1h", "t": 0, "a": 2.0, "b": None}]
    d, n = rr.paired(rows, "a", "b")
    assert n == 1 and sum(sum(v) for v in d.values()) == 0.5


# ------------------------------ 3. umbral relativo ------------------------------

def test_tolerancia_escala_con_el_activo():
    """La tolerancia es ATR, no %. Dos activos con el mismo % de rango pero
    precios distintos tienen que dar la MISMA tolerancia en R."""
    barato = [K(i, 0.1, 0.11, 0.09, 0.1) for i in range(40)]
    caro = [K(i, 100000, 110000, 90000, 100000) for i in range(40)]
    ab_, ac_ = rr.atr_array(barato), rr.atr_array(caro)
    assert abs((ab_[-1] / 0.1) - (ac_[-1] / 100000)) < 1e-9


def test_atr_es_causal():
    velas = [K(i, 100, 101, 99, 100) for i in range(20)]
    velas.append(K(20, 100, 500, 1, 100))          # vela monstruo al final
    a = rr.atr_array(velas)
    assert a[19] is not None and a[19] < 3         # no ve la vela 20
    assert a[20] > a[19]


# ------------------------------ 4. costos y coherencia ------------------------------

def test_netR_castiga_costos_en_ambos_sentidos():
    assert oos.netR(1.0, 100.0, 99.0) < 1.0
    assert oos.netR(-1.0, 100.0, 99.0) < -1.0


def test_controles_negativos_declarados_y_medidos():
    if not os.path.isfile(RES):
        return
    d = json.load(open(RES))
    for N in rr.RETEST_N:
        for tag in (f"up{N}", f"dn{N}", f"del{N}"):
            assert tag in d["cortes"]["ALL"], tag
    assert "lvl" in d["cortes"]["ALL"]
    # el desplazamiento del control (a) se corre a los DOS lados a propósito
    assert d["cortes"]["ALL"][f"up{rr.RETEST_N[0]}"]["n"] > 0
    assert d["cortes"]["ALL"][f"dn{rr.RETEST_N[0]}"]["n"] > 0


def test_cobertura_reportada_y_umbral_prerregistrado():
    if not os.path.isfile(RES):
        return
    d = json.load(open(RES))
    assert d["meta"]["prereg"]["n_min_retests"] == 500
    for N, cv in d["cobertura"]["por_N"].items():
        assert 0 <= cv["cobertura_universo_pct"] <= 100
        # los setups que rompen y nunca vuelven son un COSTO del brazo: se cuentan
        assert "rompen_y_no_vuelven_pct" in cv
        assert "mueren_esperando_pct" in cv


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as e:
            fails += 1
            print(f"  FALLA {name}: {e}")
    print(f"\n{'TODO OK' if not fails else str(fails) + ' FALLAS'}")
    sys.exit(1 if fails else 0)
