import json
import time
from pathlib import Path

from core.module_base import ModuleContext
from modules.hypothesis_lab.module import HypothesisLabModule


ROOT = Path(__file__).resolve().parents[1]


def _module(tmp_path):
    context = ModuleContext(
        "hypothesis_lab",
        str(ROOT / "modules" / "hypothesis_lab"),
        {"runtime_data_root": str(tmp_path)},
        lambda _message: None,
    )
    return HypothesisLabModule(context)


def test_state_es_solo_lectura_y_separa_historico_de_forward(tmp_path):
    module = _module(tmp_path)
    status, content_type, body = module.api("state", {}, None)
    payload = json.loads(body)

    assert status == 200
    assert content_type.startswith("application/json")
    assert payload["research_only"] is True
    assert payload["execution_enabled"] is False
    assert {item["state"] for item in payload["studies"]} >= {"closed", "collecting"}
    assert all(item["promotion"] is False for item in payload["studies"])
    assert payload["observers"]["shadow_exit"]["status"] == "missing"
    assert payload["observers"]["candle_reversal"]["status"] == "missing"
    season = next(item for item in payload["studies"] if item["id"] == "HYP-SEASON-001")
    assert season["state"] == "exploratory"
    assert season["promotion"] is False
    trend = next(item for item in payload["studies"] if item["id"] == "HYP-TREND-001")
    assert trend["state"] == "exploratory"
    assert trend["promotion"] is False
    candle = next(item for item in payload["studies"] if item["id"] == "HYP-CANDLE-001")
    assert candle["state"] == "candidate"
    assert candle["promotion"] is False


def test_observador_con_error_no_puede_aparecer_sano(tmp_path):
    output = tmp_path / "hypothesis_lab" / "shadow" / "protect_3r_runner_original.json"
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps({
        "meta": {"generated_at_ms": 9_999_999_999_999, "errors": ["fallo"]},
        "decision": {"status": "collecting_insufficient_evidence"},
    }), encoding="utf-8")

    payload = json.loads(_module(tmp_path).api("state", {}, None)[2])
    assert payload["observers"]["shadow_exit"]["status"] == "degraded"


def _observador_sano(tmp_path, *, generado_ms, entrada_ms, registros=3):
    """Un observador que reescribe puntualmente su salida y tiene registros."""
    salida = tmp_path / "hypothesis_lab" / "shadow" / "protect_3r_runner_original.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps({
        "meta": {"generated_at_ms": generado_ms, "errors": [],
                 "n_records": registros, "cohort_start_ms": entrada_ms},
        "decision": {"status": "collecting_insufficient_evidence"},
        "records": [{"entry_at_ms": entrada_ms} for _ in range(registros)],
    }), encoding="utf-8")
    return salida


def _canonica(tmp_path, *, generado_ms, origenes_presentes=True):
    ruta = tmp_path / "hypothesis_lab" / "canonical" / "setups_canonical.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({
        "meta": {"generated_at_ms": generado_ms, "total": 171,
                 "sources": [{"path": "/origen/setups.json",
                              "present": origenes_presentes, "read": 171, "error": None}]},
    }), encoding="utf-8")
    return ruta


def test_archivo_fresco_con_cohorte_detenida_no_puede_reportarse_sano(tmp_path):
    """La regresión del 2026-08-06.

    Los observadores reescribían su JSON cada minuto sobre un `setups.json` muerto: el
    archivo se veía fresco, el módulo decía "ok" y dos cohortes llevaban días en cero.
    Un archivo recién escrito ya no alcanza para declararse sano."""
    ahora_ms = int(time.time() * 1000)
    hace_tres_dias = ahora_ms - 3 * 86_400_000
    _observador_sano(tmp_path, generado_ms=ahora_ms, entrada_ms=hace_tres_dias)
    _canonica(tmp_path, generado_ms=ahora_ms)

    modulo = _module(tmp_path)
    observador = json.loads(modulo.api("state", {}, None)[2])["observers"]["shadow_exit"]

    assert observador["status"] == "stalled"
    assert observador["stalled_reason"] == "no_new_records"
    assert observador["capturing"] is False
    assert modulo.health()["status"] == "degraded"
    assert "shadow_exit" in modulo.health()["stalled"]


def test_observador_con_registros_recientes_se_reporta_capturando(tmp_path):
    ahora_ms = int(time.time() * 1000)
    _observador_sano(tmp_path, generado_ms=ahora_ms, entrada_ms=ahora_ms - 3_600_000)
    _canonica(tmp_path, generado_ms=ahora_ms)

    observador = json.loads(_module(tmp_path).api("state", {}, None)[2])["observers"]["shadow_exit"]
    assert observador["status"] == "fresh"
    assert observador["capturing"] is True


def test_fuente_canonica_detenida_detiene_a_sus_observadores(tmp_path):
    """El detector rápido: aunque los registros sean recientes, si la fuente dejó de
    publicarse el observador no puede seguir avanzando y hay que decirlo."""
    ahora_ms = int(time.time() * 1000)
    _observador_sano(tmp_path, generado_ms=ahora_ms, entrada_ms=ahora_ms - 60_000)
    _canonica(tmp_path, generado_ms=ahora_ms - 2 * 3_600_000)

    observador = json.loads(_module(tmp_path).api("state", {}, None)[2])["observers"]["shadow_exit"]
    assert observador["status"] == "stalled"
    assert observador["stalled_reason"] == "source_stale"


def test_origen_ilegible_degrada_la_fuente_canonica(tmp_path):
    ahora_ms = int(time.time() * 1000)
    _observador_sano(tmp_path, generado_ms=ahora_ms, entrada_ms=ahora_ms - 60_000)
    _canonica(tmp_path, generado_ms=ahora_ms, origenes_presentes=False)

    estado = json.loads(_module(tmp_path).api("state", {}, None)[2])
    assert estado["sources"]["canonical_setups"]["status"] == "degraded"
    assert estado["observers"]["shadow_exit"]["stalled_reason"] == "source_degraded"


def test_el_ledger_de_progreso_no_inventa_movimiento_en_el_primer_arranque(tmp_path):
    """Sembrar el ledger con "ahora" habría escondido justo la falla que lo motivó."""
    ahora_ms = int(time.time() * 1000)
    _observador_sano(tmp_path, generado_ms=ahora_ms, entrada_ms=ahora_ms - 3 * 86_400_000)
    _canonica(tmp_path, generado_ms=ahora_ms)

    assert not (tmp_path / "hypothesis_lab" / "telemetry" / "observer_progress.json").exists()
    observador = json.loads(_module(tmp_path).api("state", {}, None)[2])["observers"]["shadow_exit"]
    assert observador["capturing"] is False


def test_modulo_no_importa_bot_ni_expone_post():
    source = (ROOT / "modules" / "hypothesis_lab" / "module.py").read_text(encoding="utf-8")
    assert "modules.bot" not in source
    assert "api_post" not in source
    assert "create_order" not in source


def test_vista_visible_y_con_candado_research():
    html = (ROOT / "modules" / "hypothesis_lab" / "public" / "index.html").read_text(encoding="utf-8")
    shell = (ROOT / "static" / "nexux-shell.js").read_text(encoding="utf-8")
    config = (ROOT / "config" / "nexus.json").read_text(encoding="utf-8")
    assert "Research only" in html
    assert "Sin promoción automática" in html
    assert "/m/hypothesis-lab/" in shell
    assert '"hypothesis_lab"' in config
