"""Gate 2 del renderer compartido: primitives SMC (FVG, OB y CDC).

NexUX Trading y Command Center dibujaban las mismas tres capas con dos
implementaciones distintas —hasta con paletas distintas para la misma zona—,
así que la misma lectura se veía de dos maneras según dónde se mirara.

Alcance acordado: SOLO FVG, OB y CDC. `curso`, `ribbon`, trades y TP/SL siguen
siendo exclusivos de NexUX y apagados por defecto.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CANONICO = ROOT / "static" / "nexux-smc-primitive.js"
PROVEEDOR = ROOT / "modules" / "command_center" / "public" / "nexux-chart-provider.js"
APP = ROOT / "modules" / "trading" / "public" / "app.js"

# Contexto 2D falso que REGISTRA cada operación de dibujo. Es la traza que
# permite comparar dos renders sin abrir un navegador.
GRABADOR = """
  const ops = [];
  const ctx = new Proxy({}, {
    get(_, k) {
      if (k === "measureText") return (t) => ({ width: t.length * 6 });
      if (k === "createLinearGradient") return (...a) => {
        ops.push(["createLinearGradient", ...a]);
        return { addColorStop: (...b) => ops.push(["addColorStop", ...b]) };
      };
      if (typeof k === "string" && /^(fill|stroke|begin|move|line|arc|rect|set|close|roundRect)/.test(k)) {
        return (...a) => ops.push([k, ...a]);
      }
      return undefined;
    },
    set(_, k, v) { ops.push(["set:" + k, v]); return true; },
  });
  const escena = {
    ancho: 400, alto: 200,
    xAt: (t) => (t == null ? null : t / 20),
    yAt: (p) => 200 - p,
  };
  const ANALISIS = {
    fvgs: [
      { t: 1000, hi: 110, lo: 105, bullish: true, filled: false },
      { t: 2000, hi: 90, lo: 88, bullish: false, filled: true },
    ],
    pois: [
      { t_conf: 1500, hi: 102, lo: 100, dir: "long", valid: true,
        reference: false, tf: "4h", dist_pct: 1.4 },
      { t_conf: 1600, hi: 99, lo: 97, dir: "short", valid: false, tf: "15m" },
    ],
    cdc_events: [
      { t_from: 1000, t_to: 2000, price: 101, pending: false },
      { t_from: 2000, t_to: null, price: 103, pending: true },
    ],
  };
"""

# Traza dorada: si el dibujo cambia, este hash cambia y hay que mirarlo.
TRAZA_DORADA = "d1f4943a61403c45938c198670e9f3bcb55c892b6c31f216603d702acca8c01b"


def _sin_comentarios(fuente: str) -> str:
    """Quita comentarios de bloque y de línea para poder afirmar sobre código."""
    fuera = re.sub(r"/\*.*?\*/", "", fuente, flags=re.S)
    return re.sub(r"^\s*//.*$", "", fuera, flags=re.M)


def _node(cuerpo: str) -> dict:
    try:
        salida = subprocess.run(["node", "--input-type=module", "-e", cuerpo],
                                check=True, capture_output=True, text=True,
                                cwd=ROOT)
    except FileNotFoundError:                      # pragma: no cover
        pytest.skip("node no está disponible")
    return json.loads(salida.stdout)


def test_una_sola_implementacion_del_dibujo():
    canonico = CANONICO.read_text(encoding="utf-8")
    proveedor = PROVEEDOR.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")

    for nombre in ("dibujarFvg", "dibujarOb", "dibujarCdc", "dibujarSmc",
                   "normalizarAnalisis"):
        assert f"export function {nombre}(" in canonico, nombre
        assert f"function {nombre}(" not in proveedor, nombre
        assert f"function {nombre}(" not in app, nombre

    assert 'from "../../../static/nexux-smc-primitive.js"' in proveedor
    assert 'import * as NexuxSmc from "../../../static/nexux-smc-primitive.js";' in app
    assert "NexuxSmc.dibujarSmc(" in app


def test_los_dos_consumidores_comparten_la_misma_funcion():
    """Identidad referencial: no basta con que dibujen parecido."""
    payload = _node("""
      import * as canon from "./static/nexux-smc-primitive.js";
      import * as prov from "./modules/command_center/public/nexux-chart-provider.js";
      console.log(JSON.stringify({
        smc: canon.dibujarSmc === prov.dibujarSmc,
        fvg: canon.dibujarFvg === prov.dibujarFvg,
        ob: canon.dibujarOb === prov.dibujarOb,
        cdc: canon.dibujarCdc === prov.dibujarCdc,
        norm: canon.normalizarAnalisis === prov.normalizarAnalisis,
      }));
    """)
    assert payload == {"smc": True, "fvg": True, "ob": True, "cdc": True,
                       "norm": True}, payload


def test_la_traza_de_canvas_es_estable():
    """Golden trace: mismas zonas → misma secuencia exacta de operaciones."""
    payload = _node("""
      import * as smc from "./static/nexux-smc-primitive.js";
      import { createHash } from "node:crypto";
    """ + GRABADOR + """
      const capas = smc.normalizarAnalisis(ANALISIS, {fvg:true, ob:true, cdc:true});
      smc.dibujarSmc(ctx, capas, escena);
      console.log(JSON.stringify({
        n: ops.length,
        sha: createHash("sha256").update(JSON.stringify(ops)).digest("hex"),
      }));
    """)
    assert payload["n"] == 102
    assert payload["sha"] == TRAZA_DORADA, payload["sha"]


def test_paridad_de_traza_entre_los_dos_consumidores():
    """La prueba del gate: el módulo canónico y lo que expone el proveedor
    producen la MISMA traza sobre las mismas zonas."""
    payload = _node("""
      import * as canon from "./static/nexux-smc-primitive.js";
      import * as prov from "./modules/command_center/public/nexux-chart-provider.js";
    """ + GRABADOR + """
      const trazar = (mod) => {
        ops.length = 0;
        mod.dibujarSmc(ctx, mod.normalizarAnalisis(ANALISIS,
          {fvg:true, ob:true, cdc:true}), escena);
        return JSON.stringify(ops);
      };
      const a = trazar(canon);
      const b = trazar(prov);
      console.log(JSON.stringify({ iguales: a === b, vacio: a.length < 100 }));
    """)
    assert payload == {"iguales": True, "vacio": False}


def test_el_adaptador_normaliza_y_filtra_sin_dibujar():
    """El primitive no interpreta mercado: filtrar es del adaptador."""
    payload = _node("""
      import * as smc from "./static/nexux-smc-primitive.js";
    """ + GRABADOR + """
      const todo = smc.normalizarAnalisis(ANALISIS, {fvg:true, ob:true, cdc:true});
      const soloHtf = smc.normalizarAnalisis(ANALISIS, {ob:true}, {soloHtf:true});
      const nada = smc.normalizarAnalisis(ANALISIS, {});
      console.log(JSON.stringify({
        fvg_sin_llenas: todo.fvg.length,          // la `filled` se descarta
        ob_todos: todo.ob.length,
        ob_solo_htf: soloHtf.ob.map((z) => z.tf),
        apagado: [nada.fvg.length, nada.ob.length, nada.cdc.length],
        sin_analisis: smc.normalizarAnalisis(null, {fvg:true}).fvg.length,
        ops_del_adaptador: ops.length,            // normalizar NO dibuja
      }));
    """)
    assert payload["fvg_sin_llenas"] == 1
    assert payload["ob_todos"] == 2
    assert payload["ob_solo_htf"] == ["4h"]
    assert payload["apagado"] == [0, 0, 0]
    assert payload["sin_analisis"] == 0
    assert payload["ops_del_adaptador"] == 0


def test_el_primitive_no_hace_fetch_ni_lee_el_chart():
    canonico = CANONICO.read_text(encoding="utf-8")
    for prohibido in ("fetch(", "WebSocket", "priceToCoordinate",
                      "timeToCoordinate", "timeScale", "localStorage",
                      "document.", "window."):
        assert prohibido not in canonico, prohibido


def test_cdc_se_rotula_como_evento_descriptivo():
    """Nunca «señal» ni «confirmación»: describe un tramo ya ocurrido."""
    canonico = CANONICO.read_text(encoding="utf-8")
    payload = _node("""
      import { CDC_ROTULO, CONTRATO_SMC } from "./static/nexux-smc-primitive.js";
      console.log(JSON.stringify({ rotulo: CDC_ROTULO, contrato: CONTRATO_SMC }));
    """)
    assert payload["rotulo"] == {"cerrado": "CDC", "pendiente": "CDC pendiente"}
    assert payload["contrato"]["cdc"] == "evento descriptivo legado"
    codigo = _sin_comentarios(canonico)
    bloque = codigo[codigo.index("export function dibujarCdc"):]
    bloque = bloque.split("export function dibujarSmc")[0].lower()
    for palabra in ("señal", "confirmación", "confirmado", "entrada"):
        assert palabra not in bloque, palabra


def test_el_contrato_declara_que_no_es_bot3():
    payload = _node("""
      import { CONTRATO_SMC } from "./static/nexux-smc-primitive.js";
      console.log(JSON.stringify(CONTRATO_SMC));
    """)
    assert payload["validated"] is False
    assert payload["bot3_compatible"] is False
    assert payload["source_kind"] == "visual_layer"
    assert payload["capas"] == ["fvg", "ob", "cdc"]


def test_curso_ribbon_trades_y_tpsl_siguen_siendo_exclusivos_de_nexux():
    """El alcance del gate 2 es geometría, no estrategia ni operaciones."""
    proveedor = PROVEEDOR.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")

    # Se mira el CÓDIGO, no los comentarios: el módulo documenta por qué esas
    # capas quedan fuera, así que sus nombres aparecen en la cabecera.
    codigo = _sin_comentarios(CANONICO.read_text(encoding="utf-8"))
    for exclusiva in ("ribbon", "tpsl", "curso", "trade"):
        assert exclusiva not in codigo.lower(), exclusiva
    # siguen existiendo, pero SOLO en NexUX
    assert "show.ribbon" in app and "show.tpsl" in app and "course" in app
    assert "show.ribbon" not in proveedor
    assert "drawTpsl" not in proveedor


def test_todas_las_capas_legadas_siguen_apagadas_por_defecto():
    app = APP.read_text(encoding="utf-8")
    proveedor = PROVEEDOR.read_text(encoding="utf-8")
    for capa in ("ribbon", "levels", "tpsl", "div", "htf", "curso"):
        assert f"{capa}: false" in app, capa
    for capa in ("structure", "fvg", "ob", "cdc", "ema", "rsi", "adx"):
        assert f"{capa}: false" in proveedor, capa
