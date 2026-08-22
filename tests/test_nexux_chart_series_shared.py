"""Gate 1 del renderer compartido: cálculos y series.

NexUX Trading y Command Center calculaban EMA, RSI y ADX con dos copias del
mismo algoritmo. Los datos ya venían de una sola fuente desde el gate anterior,
pero los NÚMEROS se derivaban dos veces, y dos implementaciones del mismo
cálculo pueden divergir sin que nadie lo note.

Estos gates exigen que exista UNA definición y que nadie conserve la suya.
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CANONICO = ROOT / "static" / "nexux-chart-series.js"
PROVEEDOR = ROOT / "modules" / "command_center" / "public" / "nexux-chart-provider.js"
APP = ROOT / "modules" / "trading" / "public" / "app.js"
INDEX_TRADING = ROOT / "modules" / "trading" / "public" / "index.html"


def _node(script: str) -> dict:
    try:
        salida = subprocess.run(["node", "--input-type=module", "-e", script],
                                check=True, capture_output=True, text=True,
                                cwd=ROOT)
    except FileNotFoundError:                      # pragma: no cover
        pytest.skip("node no está disponible")
    return json.loads(salida.stdout)


def test_existe_una_sola_definicion_de_los_calculos():
    """Nadie conserva una copia local: ni el proveedor ni la app."""
    canonico = CANONICO.read_text(encoding="utf-8")
    proveedor = PROVEEDOR.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")

    for nombre in ("emaValues", "rsiValues", "adxValues", "aggregateCandles"):
        assert f"export function {nombre}(" in canonico, nombre
        # el proveedor los re-exporta, pero NO los define
        assert f"export function {nombre}(" not in proveedor, nombre
    assert 'from "../../../static/nexux-chart-series.js"' in proveedor

    # la app tampoco: ni con los nombres viejos ni con los canónicos
    for viejo in ("function emaArr(", "function rsiCalc(", "function adxCalc("):
        assert viejo not in app, viejo
    for nombre in ("emaValues", "rsiValues", "adxValues"):
        assert f"function {nombre}(" not in app, nombre
        assert f"serie().{nombre}(" in app, nombre


def test_no_hay_respaldo_silencioso_si_falta_el_modulo():
    """Un fallback local recrearía justo la divergencia que esto elimina: si
    el módulo no está, la app tiene que fallar ruidosamente."""
    app = APP.read_text(encoding="utf-8")
    assert 'if (!s) throw new Error("nexux-chart-series no está cargado")' in app


def test_la_pagina_de_trading_carga_el_modulo_canonico():
    page = INDEX_TRADING.read_text(encoding="utf-8")
    assert '/static/nexux-chart-series.js' in page
    assert 'type="module"' in page


def test_los_dos_consumidores_producen_valores_identicos():
    """La propiedad que importa: mismos datos → mismos números, comparados
    byte a byte entre el módulo canónico y lo que expone el proveedor."""
    payload = _node("""
      import * as canon from "./static/nexux-chart-series.js";
      import * as prov from "./modules/command_center/public/nexux-chart-provider.js";
      const velas = Array.from({length: 240}, (_, i) => ({
        t: i * 900000, o: 100 + i, h: 101 + i + Math.cos(i),
        l: 99 + i - Math.sin(i), c: 100.5 + Math.sin(i) * 3, v: 10 + i,
      }));
      const closes = velas.map((v) => v.c);
      const par = (a, b) => JSON.stringify(a) === JSON.stringify(b);
      console.log(JSON.stringify({
        ema: par(canon.emaValues(closes, 21), prov.emaValues(closes, 21)),
        rsi: par(canon.rsiValues(closes, 14), prov.rsiValues(closes, 14)),
        adx: par(canon.adxValues(velas, 14), prov.adxValues(velas, 14)),
        agg30: par(canon.aggregateCandles(velas, "30m"),
                   prov.aggregateCandles(velas, "30m")),
        agg1W: par(canon.aggregateCandles(velas, "1W"),
                   prov.aggregateCandles(velas, "1W")),
        intervalos: par(canon.INTERVALS, prov.INTERVALS),
        misma_funcion: canon.emaValues === prov.emaValues,
      }));
    """)
    assert payload == {"ema": True, "rsi": True, "adx": True, "agg30": True,
                       "agg1W": True, "intervalos": True,
                       "misma_funcion": True}, payload


def test_el_modulo_canonico_declara_que_no_es_bot3():
    """La capa visual no puede presentarse como evidencia causal."""
    payload = _node("""
      import { CONTRATO_SERIES } from "./static/nexux-chart-series.js";
      console.log(JSON.stringify(CONTRATO_SERIES));
    """)
    assert payload["bot3_compatible"] is False
    assert payload["validated"] is False
    assert payload["source_kind"] == "visual_layer"


def test_los_calculos_siguen_dando_lo_mismo_que_antes():
    """Vectores fijos: mover la implementación NO puede mover los números."""
    payload = _node("""
      import * as s from "./static/nexux-chart-series.js";
      const velas = Array.from({length: 60}, (_, i) => ({
        t: i * 60000, o: 10, h: 12 + (i % 5), l: 8 - (i % 3),
        c: 10 + Math.sin(i), v: 1,
      }));
      const closes = velas.map((v) => v.c);
      console.log(JSON.stringify({
        ema0: s.emaValues(closes, 21)[0],
        ema59: s.emaValues(closes, 21)[59],
        rsi13: s.rsiValues(closes, 14)[13],
        rsi14: s.rsiValues(closes, 14)[14],
        adx28: s.adxValues(velas, 14)[28],
        adx59: s.adxValues(velas, 14)[59],
      }));
    """)
    # `null` hasta que hay período: RSI en 13, ADX antes de 2·período
    assert payload["rsi13"] is None
    assert payload["rsi14"] is not None
    assert payload["adx28"] is not None
    assert payload["ema0"] == pytest.approx(10.0)
    assert payload["ema59"] == pytest.approx(10.09872, abs=1e-5)
    assert payload["adx59"] == pytest.approx(33.03522, abs=1e-5)


def test_las_capas_smc_legadas_siguen_apagadas_por_defecto():
    """Requisito permanente: el gate del renderer no puede encender capas."""
    app = APP.read_text(encoding="utf-8")
    proveedor = PROVEEDOR.read_text(encoding="utf-8")
    assert ("ribbon: false" in app and "levels: false" in app
            and "tpsl: false" in app and "curso: false" in app)
    for capa in ("structure", "fvg", "ob", "cdc", "ema", "rsi", "adx"):
        assert f"{capa}: false" in proveedor, capa
