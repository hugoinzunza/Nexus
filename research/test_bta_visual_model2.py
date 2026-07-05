"""Tests del modelo visual BTA v2 (research).

Correr con:  .venv/bin/python3 -m pytest research/test_bta_visual_model2.py -q
Cada test D1/D2/D3 demuestra la corrección de un defecto del v1 detectado en
la auditoría visual 2026-07-05.
"""
from __future__ import annotations

import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import bta_visual_model2 as v2  # noqa: E402
from research.bta_visual_model import SwingLeg  # noqa: E402

BAR = 900_000  # 15m en ms


def candle(i, o, h, l, c):
    return {"t": i * BAR, "o": o, "h": h, "l": l, "c": c, "v": 1.0}


def _leg(direction="up", lo=100.0, hi=110.0, enriquecida=True):
    """Pierna de prueba. `enriquecida=False` simula piernas del builder v1
    (sin t/confirm_t) para testear el contrato de active_leg."""
    a = {"side": "low" if direction == "up" else "high",
         "price": lo if direction == "up" else hi, "idx": 0, "confirm_idx": 1}
    b = {"side": "high" if direction == "up" else "low",
         "price": hi if direction == "up" else lo, "idx": 5, "confirm_idx": 6}
    if enriquecida:
        a["t"], a["confirm_t"] = 0, 1 * BAR
        b["t"], b["confirm_t"] = 5 * BAR, 6 * BAR
    return SwingLeg(id="leg_t", pivot_a=a, pivot_b=b, direction=direction,
                    leg_high=hi, leg_low=lo, fib0=a["price"], fib1=b["price"],
                    eq=(hi + lo) / 2.0)


# --------------------------- D1: lado LOCAL por pierna ---------------------------

def test_d1_leg_side_es_local_no_global():
    """Precio bajo el 0.5 de la pierna = discount LOCAL, aunque esté en premium
    del rango global (el caso que el veto disc_ok global botaba y era el bueno)."""
    leg = _leg("up", lo=100.0, hi=110.0)      # eq local = 105
    assert v2.leg_side(leg, 103.0) == "discount"
    assert v2.leg_side(leg, 107.0) == "premium"
    assert v2.leg_side(leg, 105.0) == "equilibrium"
    fibs = v2.leg_fibs(leg)
    assert fibs["fib0"] == 100.0 and fibs["fib05"] == 105.0 and fibs["fib1"] == 110.0


def test_d1_zone_from_poi_v2_clasifica_por_pierna():
    legs = [_leg("up", lo=100.0, hi=110.0)]
    poi = {"lo": 102.0, "hi": 103.0, "dir": "long", "t_conf": 7 * BAR, "tf": "15m"}
    z = v2.zone_from_poi_v2(poi, legs, "z0")
    assert z.kind == "discount_poi"           # mid=102.5 < eq local 105
    assert z.leg_side_at_birth == "discount"
    poi_hi = {"lo": 108.0, "hi": 109.0, "dir": "long", "t_conf": 7 * BAR}
    z2 = v2.zone_from_poi_v2(poi_hi, legs, "z1")
    assert z2.kind == "counter_poi"           # long en premium local = contra-pierna


# ---------------- D4: active_leg causal (fix look-ahead 2026-07-05) ----------------
# Estos tres tests FALLAN con la versión anterior de active_leg (filtraba por una
# clave "t" inexistente -> devolvía la pierna FINAL, con fallback a legs[:1]).

def _leg_conf(direction, lo, hi, confirm_t, lid="leg"):
    a = {"side": "low" if direction == "up" else "high",
         "price": lo if direction == "up" else hi, "idx": 0, "confirm_idx": 1,
         "t": 0, "confirm_t": 0}
    b = {"side": "high" if direction == "up" else "low",
         "price": hi if direction == "up" else lo, "idx": 5, "confirm_idx": 6,
         "t": confirm_t - BAR, "confirm_t": confirm_t}
    return SwingLeg(id=lid, pivot_a=a, pivot_b=b, direction=direction,
                    leg_high=hi, leg_low=lo, fib0=a["price"], fib1=b["price"],
                    eq=(hi + lo) / 2.0)


def test_d4_active_leg_no_usa_pierna_futura():
    """Un observador en as_of=5*BAR NO puede ver la pierna que confirma en 100*BAR."""
    vieja = _leg_conf("up", 100.0, 110.0, confirm_t=3 * BAR, lid="vieja")
    futura = _leg_conf("up", 50.0, 200.0, confirm_t=100 * BAR, lid="futura")
    leg = v2.active_leg([vieja, futura], as_of=5 * BAR)
    assert leg is not None and leg.id == "vieja", \
        "active_leg devolvió una pierna confirmada DESPUÉS de as_of (look-ahead)"


def test_d4_active_leg_sin_pierna_confirmada_devuelve_none():
    """Antes de que confirme la primera pierna no hay contexto: None, no inventar."""
    futura = _leg_conf("up", 100.0, 110.0, confirm_t=50 * BAR)
    assert v2.active_leg([futura], as_of=10 * BAR) is None


def test_d4_active_leg_exige_confirm_t():
    """Piernas sin enriquecer (sin confirm_t) + as_of => error explícito, no
    degradación silenciosa a look-ahead."""
    cruda = _leg("up", 100.0, 110.0, enriquecida=False)   # pivotes sin confirm_t
    try:
        v2.active_leg([cruda], as_of=5 * BAR)
        raise AssertionError("debió levantar ValueError")
    except ValueError as exc:
        assert "confirm_t" in str(exc)


def test_d4_zone_from_poi_v2_ignora_pierna_futura():
    """La zona creada en t=500*BAR se clasifica con la pierna vigente (eq local 105
    -> mid 107 = premium local = counter_poi para un long), NO con la pierna futura
    (eq 125 -> daría discount_poi)."""
    vieja = _leg_conf("up", 100.0, 110.0, confirm_t=10 * BAR, lid="vieja")
    futura = _leg_conf("up", 50.0, 200.0, confirm_t=1000 * BAR, lid="futura")
    poi = {"lo": 106.5, "hi": 107.5, "dir": "long", "t_conf": 500 * BAR}
    z = v2.zone_from_poi_v2(poi, [vieja, futura], "z_causal")
    assert z.leg_side_at_birth == "premium"
    assert z.kind == "counter_poi", \
        f"clasificó {z.kind}: usó la pierna futura (look-ahead)"


def test_d4_zone_sin_pierna_confirmada_no_clasifica():
    """Zona creada ANTES de confirmar cualquier pivote/pierna: no puede usarlos."""
    futura = _leg_conf("up", 100.0, 110.0, confirm_t=1000 * BAR)
    poi = {"lo": 102.0, "hi": 103.0, "dir": "long", "t_conf": 5 * BAR}
    z = v2.zone_from_poi_v2(poi, [futura], "z_sin_ctx")
    assert z.leg_side_at_birth == "equilibrium"
    assert z.kind == "counter_poi"


def test_d4_build_swing_legs_v2_enriquece_timestamps():
    # zigzag real: 3 ondas de 15 velas (pivotes alternados que forman piernas)
    cs, i = [], 0
    for base, paso in ((100, +1), (115, -1), (100, +1), (115, -1)):
        for k in range(15):
            p = base + paso * k
            cs.append(candle(i, p, p + 1, p - 1, p + paso * 0.5))
            i += 1
    legs = v2.build_swing_legs_v2(cs, piv=5)
    assert legs, "debe encontrar al menos una pierna"
    for leg in legs:
        for p in (leg.pivot_a, leg.pivot_b):
            assert "confirm_t" in p and "t" in p
            assert p["confirm_t"] >= p["t"], "un pivote no confirma antes de existir"


# --------------------------- D2: escalera CDC con vida ---------------------------

def test_d2_cdc_ladder_pending_broken_reclaimed():
    """Un swing high confirmado nace pending; cierre encima lo rompe (bullish);
    cierre de vuelta abajo lo reclama (quiebre fallido)."""
    cs = [candle(0, 100, 101, 99, 100),
          candle(1, 100, 102, 99.5, 101),
          candle(2, 101, 105, 100, 104),      # swing high 105 (piv=2: 2 velas por lado)
          candle(3, 104, 104.5, 102, 103),
          candle(4, 103, 103.5, 101, 102),    # confirma el high (confirm_idx=4)
          candle(5, 102, 106, 101.5, 105.5),  # cierre > 105 -> broken (bullish)
          candle(6, 105.5, 106, 103, 104),    # cierre < 105 -> reclaimed
          ]
    ladder = v2.cdc_ladder(cs, piv=2)
    bull = [l for l in ladder if l.side == "high" and l.price == 105]
    assert bull, "el peldaño del swing high 105 debe existir"
    lvl = bull[0]
    assert [s for s, _ in lvl.history] == ["pending", "broken", "reclaimed"]
    assert lvl.broken_dir == "bullish_break"
    assert lvl.broken_t == 5 * BAR and lvl.reclaimed_t == 6 * BAR


def test_d2_cdc_retest_cambia_de_rol():
    """Tras romper, si el precio VUELVE al nivel sin cerrarlo de vuelta -> retest
    (el nivel actúa de soporte: continuación, no reversa)."""
    cs = [candle(0, 100, 101, 99, 100),
          candle(1, 100, 102, 99.5, 101),
          candle(2, 101, 105, 100, 104),      # swing high 105
          candle(3, 104, 104.5, 102, 103),
          candle(4, 103, 103.5, 101, 102),    # confirma
          candle(5, 102, 107, 101.5, 106.5),  # broken bullish
          candle(6, 106.5, 107, 104.9, 105.8),  # toca 105 sin cerrar debajo -> retest
          ]
    ladder = v2.cdc_ladder(cs, piv=2)
    lvl = [l for l in ladder if l.price == 105][0]
    assert lvl.state == "retest"
    assert lvl.retest_t == 6 * BAR


# ------------------- D3: confirmación exige CDC DESPUÉS del toque -----------------

def _zone_long():
    z = v2.ZoneV2(id="z", kind="discount_poi", direction="long",
                  lo=100.0, hi=101.0, created_t=0)
    z.history.append(("pending", 0))
    return z


def _lvl(broken_t, direction="bullish_break"):
    l = v2.CDCLevel(id="cdc_x", price=102.0, side="high", created_t=0)
    l.state, l.broken_t, l.broken_dir = "broken", broken_t, direction
    return l


def test_d3_cdc_anterior_al_toque_no_confirma():
    """El error del v1 (y la 'entrada tardía' del Diario): un CDC roto ANTES del
    toque no puede confirmar la zona."""
    z = _zone_long()
    viejo = _lvl(broken_t=1 * BAR)
    z.step(candle(3, 102, 102.5, 100.5, 102), [viejo])   # toque en t=3
    assert z.state == "tapped"
    z.step(candle(4, 102, 103, 101.5, 102.5), [viejo])   # el CDC viejo sigue ahí
    assert z.state == "tapped", "CDC previo al toque NO confirma"


def test_d3_cdc_posterior_al_toque_confirma():
    z = _zone_long()
    z.step(candle(3, 102, 102.5, 100.5, 102), [])        # toque t=3
    nuevo = _lvl(broken_t=5 * BAR)
    z.step(candle(5, 102, 103.5, 102, 103.2), [nuevo])
    assert z.state == "confirmed"
    assert z.cdc_id == "cdc_x" and z.confirmed_t == 5 * BAR


def test_d3_cdc_fuera_de_ventana_no_confirma():
    z = _zone_long()
    z.step(candle(3, 102, 102.5, 100.5, 102), [])        # toque t=3
    tarde = _lvl(broken_t=(3 + v2.CONFIRM_WINDOW + 2) * BAR)
    z.step(candle(3 + v2.CONFIRM_WINDOW + 2, 102, 103.5, 102, 103.2), [tarde])
    assert z.state == "tapped", "CDC fuera de la ventana no confirma"


# ------------------------ estados restantes de la zona ---------------------------

def test_zone_failed_y_retest_continuation_invierte_direccion():
    z = _zone_long()
    z.step(candle(3, 102, 102.5, 100.5, 102), [])        # tapped
    z.step(candle(4, 101, 101.5, 98, 98.5), [])          # cierre < lo -> failed
    assert z.state == "failed" and z.failed_t == 4 * BAR
    # misma vela del fallo NO puede retestear (transición inválida corregida en v1)
    z.step(candle(5, 98.5, 100.6, 98, 99.5), [])         # vuelve a tocar la zona
    assert z.state == "retest_continuation"
    assert z.direction == "short", "la zona perdida cambia de rol"


def test_zone_target_hit_tras_confirmar():
    z = _zone_long()
    z.step(candle(3, 102, 102.5, 100.5, 102), [])
    z.step(candle(5, 102, 103.5, 102, 103.2), [_lvl(broken_t=5 * BAR)])
    assert z.state == "confirmed"
    tgt = v2.TargetLiquidity(id="t0", price=106.0, kind="weak_high", created_t=0)
    v2.update_targets([tgt], candle(7, 104, 106.5, 104, 106.2))
    assert tgt.state == "hit"
    z.step(candle(7, 104, 106.5, 104, 106.2), [], target=tgt)
    assert z.state == "target_hit" and z.target_id == "t0"


# ------------------------------ targets y repisas --------------------------------

def test_find_targets_weak_high_alto_referencial_y_repisa():
    cs = []
    i = 0
    # dos picos casi iguales (repisa, en idx 2 y 5) + un techo mayor sin barrer (idx 8)
    for o, h, l, c in [(100, 101, 99, 100), (100, 102, 99.5, 101),
                       (101, 105, 100, 104),        # pico 105
                       (104, 104.5, 102, 103), (103, 103.5, 101, 102),
                       (102, 105.05, 101, 104),     # pico ~105 de nuevo
                       (104, 104.5, 102, 103), (103, 103.5, 101, 102),
                       (102, 108, 102, 107),        # techo 108 (queda sin barrer)
                       (107, 107.5, 104, 105),
                       (105, 105.5, 103, 104), (104, 104.5, 102, 103),
                       (103, 103.5, 101, 102), (102, 102.5, 100, 101)]:
        cs.append(candle(i, o, h, l, c))
        i += 1
    tg = v2.find_targets(cs, piv=2)
    kinds = {t.kind for t in tg}
    assert "alto_referencial" in kinds
    assert "weak_high" in kinds
    repisas = [t for t in tg if t.kind == "repisa"]
    assert any(abs(t.price - 105.02) < 0.5 for t in repisas), \
        "los dos picos ~105 deben agruparse como repisa"


# ------------------------------ snapshot integrado -------------------------------

def test_visual_snapshot_smoke_con_datos_reales():
    import json
    path = os.path.join(WT, "research", "bta_btcusdtp_15m_recent.json")
    if not os.path.exists(path):
        return  # sin datos locales, el smoke no aplica
    candles = json.load(open(path))[-1200:]
    snap = v2.visual_snapshot(candles)
    assert snap["research_only"] is True
    assert snap["active_leg"] is not None
    assert snap["range"]["eq"] > 0
    assert len(snap["cdc_ladder"]) <= v2.CDC_KEEP
    assert snap["targets"], "debe encontrar liquidez visible en 1200 velas reales"
    assert "LOCAL por pierna" in snap["nota"]
