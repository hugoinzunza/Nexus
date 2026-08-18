"""Gates pesados de Bot3.v9 sobre datos REALES (marcados `lento`).

Son los gates que rechazaron a v1 y a la primera corrección de C-1:

  1. **Invariancia por prefijo** en ventana real (≥2000 velas M15 de BTC,
     >300 zonas H4 vigentes): los eventos ya emitidos NO cambian al alargar
     la serie. Si un cierre del pasado cambia, la implementación se rechaza.
  2. **Determinismo de ingestión**: las mismas fuentes entregadas en un solo
     bloque o troceadas en varios ciclos producen el MISMO almacén y el
     MISMO libro (la profundidad/orden de carga es irrelevante).
  3. **Continuidad H4 fail-closed**: sin época única desde génesis, el
     mercado abstiene (`historia_insuficiente`) en vez de inventar rango.

Se ejecutan con `-m lento` o completos en CI; el resto de la suite no los
necesita para pasar.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.bot3.v9 import primitives as P  # noqa: E402
from modules.bot3.v9 import runner as R  # noqa: E402
from modules.bot3.v9.engine import DUR_H4, DUR_M15, Motor  # noqa: E402
from modules.bot3.v9.ledger import Ledger  # noqa: E402

pytestmark = pytest.mark.lento

MERCADO = ("BTCUSDT",)
VENTANA = 2200          # ≥2000 velas M15 exigidas por el gate


def _tiene_datos():
    return bool(R.leer_versionado(R.ROOT, "BTCUSDT", "15m"))


requiere_datos = pytest.mark.skipif(not _tiene_datos(),
                                    reason="sin klines versionadas de BTC")


def _firma_dominio(led: Ledger) -> list[tuple]:
    """Eventos de dominio (sin barreras de lote) como tuplas comparables."""
    return [(e["tipo"], e.get("mercado"), e["effective_at"], e.get("id"),
             e.get("r"), e.get("precio"), e.get("motivo"))
            for e in led.eventos if e["tipo"] != "lote_finalizado"]


@requiere_datos
def test_ventana_real_tiene_mas_de_300_zonas():
    """El gate exige una ventana con >300 zonas H4 vigentes."""
    h4 = R.construir_almacenes(R.ROOT, MERCADO, "4h")["BTCUSDT"]
    zonas = P.zonas_de_epoca(h4.velas, DUR_H4)
    assert len(zonas) > 300, f"solo {len(zonas)} zonas"


@requiere_datos
def test_invariancia_por_prefijo_en_ventana_real():
    """Correr hasta T_final vs hasta T_medio: todo evento con
    `effective_at ≤ T_medio` debe ser IDÉNTICO en ambas corridas."""
    m15 = R.construir_almacenes(R.ROOT, MERCADO, "15m")["BTCUSDT"]
    ts = [int(v["t"]) for v in m15.velas]
    desde = ts[-VENTANA] + DUR_M15
    t_medio = ts[-(VENTANA // 2)] + DUR_M15
    t_final = ts[-1] + DUR_M15

    _, led_largo = R.correr(mercados=MERCADO, desde=desde, hasta=t_final)
    _, led_corto = R.correr(mercados=MERCADO, desde=desde, hasta=t_medio)

    largo = [e for e in _firma_dominio(led_largo) if e[2] <= t_medio]
    corto = [e for e in _firma_dominio(led_corto) if e[2] <= t_medio]
    assert corto == largo, "el pasado cambió al agregar velas futuras"


@requiere_datos
def test_determinismo_de_ingestion_por_troceo():
    """Mismas fuentes, distinto troceo de ciclos → mismo almacén (cadena de
    hashes idéntica) y mismo libro."""
    filas = sorted(R.leer_versionado(R.ROOT, "BTCUSDT", "15m"),
                   key=lambda r: int(r["t"]))[-VENTANA:]
    from modules.bot3.v9 import store as S
    ancla = int(filas[0]["t"])

    entero = S.Almacen("BTCUSDT", "15m"); entero.nacer_en(ancla)
    entero.ofrecer(filas, "versionado"); entero.drenar()

    troceado = S.Almacen("BTCUSDT", "15m"); troceado.nacer_en(ancla)
    paso = max(1, len(filas) // 7)
    for i in range(0, len(filas), paso):          # 7 ciclos de ingestión
        troceado.ofrecer(filas[i:i + paso], "versionado")
        troceado.drenar()
        troceado.declarar_hueco_local()

    assert entero.head == troceado.head
    assert [r["hash_acum"] for r in entero.registros] == \
           [r["hash_acum"] for r in troceado.registros]


@requiere_datos
def test_ingestion_desordenada_converge():
    """Las mismas velas ofrecidas en orden INVERSO producen el mismo almacén:
    el buffer y el prefijo continuo eliminan la dependencia del arribo."""
    from modules.bot3.v9 import store as S
    filas = sorted(R.leer_versionado(R.ROOT, "BTCUSDT", "15m"),
                   key=lambda r: int(r["t"]))[-400:]
    ancla = int(filas[0]["t"])
    a = S.Almacen("BTCUSDT", "15m"); a.nacer_en(ancla)
    a.ofrecer(filas, "versionado"); a.drenar()
    b = S.Almacen("BTCUSDT", "15m"); b.nacer_en(ancla)
    for fila in reversed(filas):                  # llegada invertida
        b.ofrecer([fila], "versionado")
        b.drenar()
    assert a.head == b.head
    assert len(a.velas) == len(b.velas) == len(filas)


@requiere_datos
def test_h4_sin_continuidad_desde_genesis_abstiene():
    """CF-13 fail-closed: si el almacén H4 no es una época única desde
    GENESIS, el motor abstiene con `historia_insuficiente` (no inventa
    rango). Esto es lo que vuelve irrelevante la profundidad de carga."""
    m15 = R.construir_almacenes(R.ROOT, MERCADO, "15m")
    h4_parcial = R.construir_almacenes(R.ROOT, MERCADO, "4h", limite=800)
    ts = [int(v["t"]) for v in m15["BTCUSDT"].velas]
    desde = ts[-200] + DUR_M15
    led = Ledger()
    motor = Motor(m15, h4_parcial, ("BTCUSDT",), led)
    for T in [t + DUR_M15 for t in ts[-200:]]:
        if T >= desde and motor.lote_finalizable(T):
            motor.procesar_lote(T)
    motivos = {e.get("motivo") for e in led.eventos if e["tipo"] == "abstencion"}
    assert motivos == {"historia_insuficiente"}
    assert not any(e["tipo"] in ("candidato", "orden_creada", "fill")
                   for e in led.eventos)
