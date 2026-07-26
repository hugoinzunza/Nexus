"""Tests de los dos defectos que la auditoria de Codex reprodujo (2026-07-26).

Codex marco, con razon, que "varios tests actuales solo buscan texto en el codigo".
Un assert de tipo `"X" not in fuente` sirve de candado contra una regresion conocida,
pero NO habria encontrado ninguno de estos defectos. Estos tests EJECUTAN.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.coinglass import module as cgm          # noqa: E402
from modules.coinglass import visual as cgv          # noqa: E402
from tests.test_coinglass_visual import snapshot_patologico  # noqa: E402


def _con_desfase(minutos: int):
    """El mismo snapshot, con el reloj del heatmap corrido hacia atras.

    Devuelve tambien el `now` del observador: el fixture tiene un `captured_at` fijo
    y sin pasar `now` la validacion de ventana temporal lo rechaza por viejo. Eso no
    es lo que este test mide.
    """
    snap = json.loads(json.dumps(snapshot_patologico()))
    cap = datetime.fromisoformat(snap["captured_at"])
    viejo = (cap - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M")
    for lvl in snap["liquidation_heatmap"]["levels"]:
        lvl["timestamp"] = viejo
    return snap, cap + timedelta(seconds=30)


def _indicador(minutos: int):
    snap, ahora = _con_desfase(minutos)
    return cgv.build_visual_indicator(snap, now=ahora)


def test_el_heatmap_atrasado_deja_de_puntuar():
    """Reproduccion exacta del hallazgo: un heatmap atrasado 3h10 daba EXACTAMENTE
    el mismo score que uno fresco. Se medía, se avisaba, y no cambiaba nada."""
    fresco = _indicador(2)
    viejo = _indicador(190)

    assert fresco["stale_heatmap"] is False
    assert viejo["stale_heatmap"] is True
    assert viejo["score"] != fresco["score"], \
        "el heatmap atrasado sigue produciendo el mismo score"

    # y el payload dice POR QUE, para que un score degradado no se vea igual que uno
    # completo
    comp = viejo["score_components"]
    assert comp["heatmap"] is None
    assert comp["degradado"] is True
    assert "atrasado" in (comp["motivo"] or "")
    assert comp["peso_disponible"] == 0.5      # mapa 0,30 + profundidad 0,20
    assert fresco["score_components"]["degradado"] is False
    assert fresco["score_components"]["peso_disponible"] == 1.0


def test_el_umbral_del_aviso_y_el_del_score_son_el_mismo():
    """Dos criterios distintos para la misma pregunta obligan a explicar cual manda."""
    assert cgv.MAX_HEATMAP_LAG_S == 30 * 60
    justo_antes = _indicador(29)
    justo_despues = _indicador(31)
    assert justo_antes["stale_heatmap"] is False
    assert justo_antes["score_components"]["heatmap"] is not None
    assert justo_despues["stale_heatmap"] is True
    assert justo_despues["score_components"]["heatmap"] is None


class _Ctx:
    def __init__(self):
        self.mensajes = []
    def log(self, m):
        self.mensajes.append(m)


def _modulo():
    m = cgm.CoinGlassModule.__new__(cgm.CoinGlassModule)
    m._lock = threading.Lock()
    m._perdidas_por_archivo = 0
    m.context = _Ctx()
    return m


def test_si_el_archivo_no_acepta_la_ventana_caliente_NO_se_recorta(tmp_path, monkeypatch):
    """El defecto exacto: se archivaba, se botaba el resultado y se recortaba igual.
    Con el archivo lleno, la captura vieja no se guardaba Y desaparecia de la ventana.
    Perdida para siempre, en silencio."""
    lleno = tmp_path / "archivo.jsonl"
    lleno.write_bytes(b"x" * 10)
    monkeypatch.setattr(cgm, "MAX_ARCHIVE_BYTES", 1)     # ya esta "lleno"

    sobrantes = [{"captured_at": f"t{i}"} for i in range(3)]
    arch = cgm._archivar_descartadas(str(lleno), sobrantes)
    assert arch["lleno"] is True and arch["escritas"] == 0

    # la condicion que gobierna el recorte
    assert arch["escritas"] != len(sobrantes), \
        "con el archivo lleno NO se puede recortar la ventana caliente"


def test_cuando_el_archivo_si_acepta_se_recorta_normal(tmp_path):
    ok = tmp_path / "archivo.jsonl"
    filas = [{"captured_at": f"t{i}"} for i in range(5)]
    arch = cgm._archivar_descartadas(str(ok), filas)
    assert arch["escritas"] == 5 and arch["error"] is None and arch["lleno"] is False
    assert len(ok.read_text().strip().splitlines()) == 5


def test_un_error_de_disco_tampoco_autoriza_a_recortar(tmp_path, monkeypatch):
    """Segundo camino al mismo desastre: OSError se reportaba y se seguia igual."""
    def explota(*a, **k):
        raise OSError("disco lleno")
    monkeypatch.setattr("builtins.open", explota)
    arch = cgm._archivar_descartadas(str(tmp_path / "x.jsonl"), [{"captured_at": "t"}])
    assert arch["escritas"] == 0
    assert "disco" in (arch["error"] or "")


def test_las_perdidas_del_techo_duro_se_cuentan_y_se_publican():
    """Perder contando es malo; perder sin contar es indefendible. El contador tiene
    que llegar al estado, no quedarse en un log."""
    m = _modulo()
    m._perdidas_por_archivo = 7
    fuente = open(os.path.join(ROOT, "modules/coinglass/module.py"), encoding="utf-8").read()
    assert 'archivo["capturas_perdidas"] = self._perdidas_por_archivo' in fuente
    assert "2 * MAX_VISUAL_BOOK_HISTORY" in fuente, "falta el techo duro"


# --- #2: la exclusion de canceladas -----------------------------------

def test_la_traza_del_filtro_de_canceladas_sobrevive_a_la_normalizacion():
    """El colector marcaba cada fila con `cancel_filter` y la normalizacion la
    descartaba, mientras persistia `active_only: true`. O sea el panel afirmaba
    actividad verificada que nadie verifico, y muros cancelados podian contaminar el
    muro dominante y el flujo sin aviso."""
    snap = json.loads(json.dumps(snapshot_patologico()))
    cap = datetime.fromisoformat(snap["captured_at"])
    ahora = cap + timedelta(seconds=30)

    snap["whale_orders"]["cancel_filter"] = "first_checkbox_unverified"
    i = cgv.build_visual_indicator(snap, now=ahora)
    assert i["whale_cancel_filter"] == "first_checkbox_unverified"
    assert i["whale_cancel_verificado"] is False

    snap["whale_orders"]["cancel_filter"] = "by_label"
    ok = cgv.build_visual_indicator(snap, now=ahora)
    assert ok["whale_cancel_verificado"] is True

    # y sin el campo NO se asume verificado: la ausencia de prueba no es prueba
    del snap["whale_orders"]["cancel_filter"]
    mudo = cgv.build_visual_indicator(snap, now=ahora)
    assert mudo["whale_cancel_verificado"] is False


def test_el_aviso_de_canceladas_llega_a_la_pantalla():
    js = open(os.path.join(ROOT, "modules/coinglass/public/app.js"), encoding="utf-8").read()
    assert "whale_cancel_verificado === false" in js
    assert "SIN verificar exclusion de canceladas" in js


# --- #4: contabilidad de observaciones --------------------------------

def test_el_gate_no_puede_decir_listo_con_cero_observaciones_independientes():
    """Reproduccion: 100 capturas sin NINGUNA barra independiente daban
    `forward_observations: 0` y `status: ready_for_backtest` a la vez. Un gate que se
    contradice a si mismo es peor que no tenerlo."""
    from modules.coinglass import provider

    basic = {"price": 64_000.0, "open_interest_usd": 1e9, "funding_rate": 0.0001,
             "long_short_ratio": 1.0, "taker_buy_sell_ratio": 1.0}
    # 120 filas SIN bar_time: no son observaciones independientes
    historia = [{**basic, "captured_at": f"2026-07-26T{h:02d}:{m:02d}:00+00:00",
                 "time": f"t{h}{m}", "origin": "forward"}
                for h in range(12) for m in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45)]
    d = provider.build_dashboard(basic, historia, {})
    ep = d["experimental_pressure"]

    assert ep["forward_observations"] == 0
    assert ep["observations"] == 0, "observations debe contar independientes, no filas"
    assert ep["filas_sin_barra"] == len(historia)
    assert ep["status"] != "ready_for_backtest", \
        "el gate declaro listo un historial sin una sola observacion independiente"


# --- #5: fills del shadow ---------------------------------------------

def test_el_shadow_sale_al_nivel_y_no_al_precio_observado():
    """Las capturas van cada horas: un salto por encima del target regalaba beneficio
    que la orden nunca habria cobrado, y uno por debajo del stop exageraba la perdida.
    Inflaba las dos colas a la vez."""
    fuente = open(os.path.join(ROOT, "modules/coinglass/shadow.py"), encoding="utf-8").read()
    bloque = fuente.split("if reason:")[1].split("open_trade = None")[0]
    assert 'open_trade["target"] if reason == "target"' in bloque
    assert 'open_trade["stop"] if reason == "stop"' in bloque
    assert '_return_pct(direction, open_trade["entry"], salida)' in bloque, \
        "el neto se sigue calculando con el precio observado"
    # el precio observado NO se pierde: queda al lado para poder medir el gap
    assert '"exit_observado": price' in bloque
    assert '"exit_model"' in bloque, "hay que declarar con que modelo se salio"


# --- #6: el tope del cuerpo ------------------------------------------

def test_el_tope_del_cuerpo_se_aplica_antes_de_leerlo():
    """Los endpoints de ingesta se saltan la sesion, y FastAPI cargaba y parseaba el
    cuerpo entero antes de que nadie mirara el token ni el tamano. Verificado el
    2026-07-26: uvicorn 0.32 con h11 no trae limite por defecto y no hay ninguno
    configurado en el deploy, asi que este es el primero."""
    fuente = open(os.path.join(ROOT, "core/app.py"), encoding="utf-8").read()
    bloque = fuente.split("async def module_api_post")[1].split("\n@app.")[0]

    # el chequeo va ANTES de cualquier lectura del cuerpo
    assert bloque.index("content-length") < bloque.index("json"), \
        "el tope tiene que mirarse antes de parsear"
    assert "MAX_POST_BYTES" in bloque and "413" in bloque
    # y no se confia solo en el header declarado: chunked se lee por trozos con corte
    assert "request.stream()" in bloque
    assert "total > MAX_POST_BYTES" in bloque
    assert "await request.body()" not in bloque, \
        "volvio la lectura completa sin tope"
