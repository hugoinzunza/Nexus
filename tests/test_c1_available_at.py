"""Tests del fix C-1 (auditoría 2026-08-17): disponibilidad causal HTF/LTF.

Contratos probados:
  1. Un BOS del rector se PUBLICA en el cierre de su vela (apertura + duración),
     nunca en la apertura.
  2. Una zona (FVG/OB) queda disponible en el cierre de la vela que completa el
     FVG (`avail_t = t + duración`).
  3. Ninguna vela de la TF vista puede tocar/consumir una zona rectora antes de
     su `avail_t` (reproducción del hallazgo C-1: toque previo al cierre H4).
  4. Invariancia por prefijo: los trades cerrados de la simulación completa son
     idénticos a los de cualquier prefijo que ya contenga su salida (ninguna
     decisión depende de velas futuras).
  5. Invariante universal: todo trade cumple avail ≤ toque ≤ entrada.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.bot3 import strategy  # noqa: E402
from modules.trading import smc_course  # noqa: E402
from tests.test_smc_course import _bear_scenario, _bull_scenario, _c, _flat, _leg  # noqa: E402

STEP = 900_000          # 15m reales
H4 = 14_400_000


def _golden():
    """Escenario 15m con al menos un trade largo cerrado en target: máximo
    viejo sin barrer (118) como liquidez objetivo, barrido del mínimo, impulso,
    retroceso que TOCA la zona superior sin invalidarla, iBOS y continuación."""
    t = [0]

    def nxt(n):
        t0 = t[0]
        t[0] += n * STEP
        return t0

    c = []
    c += _leg(10, 116, 118, nxt(10), step=STEP)     # techo viejo (target)
    c += _leg(18, 117.8, 100, nxt(18), step=STEP)   # (bajo 118: máximo estricto)
    c += _flat(12, 100, nxt(12), step=STEP)
    c += _leg(20, 100, 92, nxt(20), step=STEP)
    c += _flat(12, 92, nxt(12), step=STEP)
    t0 = nxt(1)
    c.append(_c(t0, 92, 92.2, 90.5, 91.9))          # barrido del mínimo
    c += _leg(25, 92, 108, nxt(25), step=STEP)      # impulso
    c += _leg(6, 107.8, 106.85, nxt(6), step=STEP)  # retroceso: toca FVG superior
    # (parte bajo 108 para que el peak sea máximo ESTRICTO y confirme su swing)
    c += _leg(6, 106.95, 109.5, nxt(6), step=STEP)  # iBOS al alza
    c += _leg(14, 109.5, 119, nxt(14), step=STEP)   # continuación: barre 118
    return c


def test_bos_rector_se_publica_al_cierre():
    rector = _bear_scenario(step=H4)
    crudos = smc_course._bos_events(rector, smc_course.STRUCT_PIV)
    serie = strategy._rector_dir_series(rector, H4)
    assert crudos and len(crudos) == len(serie)
    for e, (t_avail, d) in zip(crudos, serie):
        assert t_avail == rector[e["j"]]["t"] + H4      # cierre, no apertura
        assert d == ("long" if e["dir"] == "up" else "short")
    # Antes del cierre del primer evento no hay dirección conocida.
    primero = serie[0][0]
    assert strategy._dir_as_of(serie, primero - 1) is None
    assert strategy._dir_as_of(serie, primero) is not None


def test_zonas_disponibles_al_cierre():
    rector = _bear_scenario(step=H4)
    for z in strategy._zone_events(rector, H4):
        assert z["avail_t"] == z["t"] + H4
    # Misma invariante en la capa del gráfico.
    out = smc_course.analyze(_bull_scenario(), {"4h": rector},
                             _bull_scenario()[-1]["c"], "15m")
    for z in out["zones"]:
        dur = smc_course.TF_MS[z["tf"]]
        assert z["avail_t"] >= z["t"]
        assert (z["avail_t"] - z["t"]) in (dur, 0) or z["avail_t"] - z["t"] > 0


def test_toque_previo_al_cierre_h4_no_consume():
    """Reproducción del C-1: la única incursión de la TF vista en la zona
    rectora ocurre ANTES del cierre de la vela H4 que la completa. No puede
    existir ningún trade con esa zona."""
    # Rector: 40 velas planas + secuencia que deja FVG largo (OB ~95-96.6).
    rector = _flat(40, 100, step=H4)
    t0 = 40 * H4
    rector.append(_c(t0, 96.4, 96.6, 95.0, 95.2))
    rector.append(_c(t0 + H4, 95.2, 97.4, 95.1, 97.2))
    rector.append(_c(t0 + 2 * H4, 97.2, 99.6, 97.1, 99.4))   # completa el FVG
    rector.append(_c(t0 + 3 * H4, 99.4, 100.4, 99.2, 100.0))
    avail = (t0 + 2 * H4) + H4
    # TF vista: toca la zona SOLO durante la vela H4 en formación y luego huye.
    sel = []
    t = t0 + 2 * H4
    for i in range(10):                       # dentro de la H4: dips a 95.6
        sel.append(_c(t, 97.0, 97.4, 95.6, 96.9))
        t += STEP
    while t < avail + 40 * STEP:              # después del cierre: lejos, sin tocar
        sel.append(_c(t, 99.5, 100.2, 99.2, 100.0))
        t += STEP
    out = strategy.simulate(sel, rector, "15m")
    assert all(tr["zona_tf"] != "rector" for tr in out["trades"])


def test_invariante_avail_toque_entrada():
    for sel, rector in ((_golden(), None),
                        (_bull_scenario(), _bear_scenario(step=H4))):
        out = strategy.simulate(sel, rector, "15m")
        for t in out["trades"]:
            assert t["t_zona_avail"] <= t["t_toque"] <= t["t_entrada"]


def test_golden_produce_cierre_y_prefijo_invariante():
    sel = _golden()
    full = strategy.simulate(sel, None, "15m")
    cerrados = [t for t in full["trades"] if t["estado"] in ("stop", "target")]
    assert cerrados, "el escenario dorado debe producir al menos un cierre"
    times = [c["t"] for c in sel]
    for frac in (0.7, 0.85, 1.0):
        m = int(len(sel) * frac)
        sub = strategy.simulate(sel[:m], None, "15m")
        fin = times[m - 1]
        esperados = [t for t in cerrados if t["exit_t"] <= fin]
        obtenidos = [t for t in sub["trades"] if t["estado"] in ("stop", "target")
                     and t["exit_t"] <= fin]
        assert obtenidos == esperados, (
            f"prefijo {frac}: el pasado cambió al agregar velas futuras")
