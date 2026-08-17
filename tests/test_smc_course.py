"""Tests de la capa 'curso' (smc_course): estrategia Bitcoin Traders playbook.v1.

Cubre las garantías críticas:
  1. AISLAMIENTO: el payload jamás incluye `tpsl` ni plan alguno (no puede
     alimentar el diario ni el bot — ECON-COHORT-001 congelada).
  2. Rango causal: dirección por ruptura con cuerpo, strong = origen de la
     pierna, weak = extremo posterior (target).
  3. Bloque trampa: liquidez sin barrer DETRÁS de la zona → z["trampa"].
  4. Fractal: retroceso ≥50% detectado (con mecha, regla verificada del curso).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.trading import smc_course  # noqa: E402


def _c(t, o, h, l, c):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": 1.0}


def _flat(n, px, t0=0, step=60_000, amp=0.15):
    """Tramo lateral con micro-deriva: los extremos son únicos (swing_points
    exige desigualdad ESTRICTA), así el último máximo del tramo puede confirmar
    como swing high real cuando después viene una bajada."""
    out = []
    for i in range(n):
        d = amp if i % 2 == 0 else -amp
        hi = px + abs(d) + i * 0.004     # máximos estrictamente crecientes
        lo = px - abs(d) + i * 0.002     # mínimos también únicos (y por sobre px-amp)
        out.append(_c(t0 + i * step, px, hi, lo, px + d * 0.5))
    return out


def _leg(n, p0, p1, t0, step=60_000):
    """Pierna direccional con velas de cuerpo dominante."""
    out = []
    for i in range(n):
        a = p0 + (p1 - p0) * i / max(1, n - 1)
        b = p0 + (p1 - p0) * (i + 0.9) / max(1, n)
        lo, hi = (a, b) if b >= a else (b, a)
        out.append(_c(t0 + i * step, a, hi + 0.05, lo - 0.05, b))
    return out


def _bull_scenario():
    """Bajada → mínimo con barrido (mecha) → impulso con cuerpo que rompe la
    estructura previa → retroceso >50% → continuación. Escala ~100."""
    t = [0]

    def nxt(n):
        t0 = t[0]
        t[0] += n * 60_000
        return t0

    c = []
    c += _flat(30, 100, nxt(30))                 # base
    c += _leg(20, 100, 92, nxt(20))              # bajada (deja swing lows)
    c += _flat(12, 92, nxt(12))
    # Barrido del mínimo: mecha bajo 91.85 y cierre de vuelta arriba.
    t0 = nxt(1)
    c.append(_c(t0, 92, 92.2, 90.5, 91.9))
    c += _leg(25, 92, 103, nxt(25))              # impulso: cierres rompen 100/101
    c += _leg(10, 103, 97.0, nxt(10))            # retroceso ~55% (103→97 de 90.5→103)
    c += _leg(6, 97.0, 99.5, nxt(6))             # reanuda
    return c


def test_payload_sin_tpsl_ni_plan():
    candles = _bull_scenario()
    out = smc_course.analyze(candles, candles[-1]["c"], "15m")
    assert "tpsl" not in out
    assert out["version"] == "curso.v1"
    for k in ("range", "fractal", "zones", "liquidity", "structure", "checklist", "note"):
        assert k in out
    # Ninguna zona trae entry/sl/tp: son contexto, no plan.
    for z in out["zones"]:
        for prohibido in ("entry", "sl", "tp", "rr"):
            assert prohibido not in z


def test_rango_alcista_strong_es_el_minimo_barrido():
    candles = _bull_scenario()
    out = smc_course.analyze(candles, candles[-1]["c"], "15m")
    rng = out["range"]
    assert rng is not None
    assert rng["dir"] == "alcista"
    # Strong low = el mínimo del barrido (90.45 con el margen de la mecha).
    assert abs(rng["strong"] - 90.45) < 0.2
    # Weak = el máximo posterior al BOS (target), por encima del strong.
    assert rng["weak"] > rng["strong"]
    assert rng["weak"] >= 102.0
    # EQ al 50% del rango.
    assert abs(rng["eq"] - (rng["strong"] + rng["weak"]) / 2) < 1e-6
    # El origen tomó liquidez (mecha bajo los swing lows de la bajada).
    assert rng["sweep"] is True


def test_fractal_retroceso_50_detectado():
    candles = _bull_scenario()
    out = smc_course.analyze(candles, candles[-1]["c"], "15m")
    fr = out["fractal"]
    assert fr is not None
    # El retroceso llegó a ~97 (>50% de la pierna) → regla cumplida.
    assert fr["retrace_ok"] is True


def test_structure_bos_ibos():
    """El impulso del escenario rompe estructura con cuerpo → debe existir al
    menos un BOS alcista dibujable, con segmento origen→quiebre."""
    candles = _bull_scenario()
    out = smc_course.analyze(candles, candles[-1]["c"], "15m")
    evs = out["structure"]
    assert evs, "el escenario debe producir marcas de estructura"
    assert any(e["label"] == "BOS" and e["dir"] == "up" for e in evs)
    for e in evs:
        assert e["label"] in ("BOS", "iBOS")
        assert e["t_from"] <= e["t_to"]


def test_checklist_es_descriptiva():
    candles = _bull_scenario()
    out = smc_course.analyze(candles, candles[-1]["c"], "15m")
    ck = out["checklist"]
    assert ck["direccion"] == "alcista"
    assert ck["precio_zona"] in ("premium", "descuento")
    assert ck["target"] == out["range"]["weak"]


def test_trampa_liquidez_detras_de_la_zona():
    """Zona larga con un pool de liquidez (swing low sin barrer) POR DEBAJO de
    su invalidación y cerca → bloque trampa (S05/S08 del curso)."""
    rng = {"dir": "alcista", "strong": 90.0, "weak": 110.0, "eq": 100.0,
           "lo": 90.0, "hi": 110.0, "state": "en_desarrollo", "sweep": True,
           "strong_t": 0, "weak_t": 0, "bos_t": 0, "bos_price": 100.0}
    pools = [{"type": "low", "kind": "EQL", "price": 94.0, "t": 0, "count": 2}]
    candles = _flat(40, 100)
    # Inyectamos un FVG alcista fresco con OB en ~95-96 (sobre el pool de 94).
    t0 = 40 * 60_000
    candles.append(_c(t0, 96.4, 96.6, 95.0, 95.2))          # vela OB (bajista)
    candles.append(_c(t0 + 60_000, 95.2, 97.4, 95.1, 97.2))
    candles.append(_c(t0 + 120_000, 97.2, 99.6, 97.1, 99.4))  # deja gap sobre 96.6
    candles.append(_c(t0 + 180_000, 99.4, 100.4, 99.2, 100.0))
    zones = smc_course._zones(candles, rng, pools, last_price=100.0)
    frescas_long = [z for z in zones if z["dir"] == "long" and z["fresh"]]
    assert frescas_long, "el escenario debe producir al menos una zona larga fresca"
    # El pool 94 queda detrás de la invalidación (bajo el lo de la zona) y a
    # menos de 35% del alto del rango (20 × 0.35 = 7) → trampa.
    assert any(z["trampa"] for z in frescas_long)


def test_pools_eqh_eql_cluster():
    """Dos swing lows sin barrer al mismo nivel → cluster EQL."""
    c = []
    t = [0]

    def nxt(n):
        t0 = t[0]
        t[0] += n * 60_000
        return t0

    c += _flat(20, 100, nxt(20))
    c += _leg(6, 100, 95, nxt(6))      # baja a 95 (swing low 1)
    c += _leg(6, 95.1, 99, nxt(6))     # rebote (arranca más arriba: pivote estricto)
    c += _leg(6, 99, 95.02, nxt(6))    # baja a ~95 otra vez (swing low 2, igual)
    c += _leg(6, 95.12, 100, nxt(6))
    c += _flat(10, 100, nxt(10))
    pools = smc_course._pools(c, last_price=100.0)
    eqls = [p for p in pools if p["kind"] == "EQL"]
    assert eqls and eqls[0]["count"] >= 2


def test_serie_corta_no_revienta():
    candles = _flat(5, 100)
    out = smc_course.analyze(candles, 100.0, "1h")
    assert out["range"] is None
    assert out["zones"] == []
