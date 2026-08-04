import json
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
    season = next(item for item in payload["studies"] if item["id"] == "HYP-SEASON-001")
    assert season["state"] == "exploratory"
    assert season["promotion"] is False
    trend = next(item for item in payload["studies"] if item["id"] == "HYP-TREND-001")
    assert trend["state"] == "exploratory"
    assert trend["promotion"] is False


def test_observador_con_error_no_puede_aparecer_sano(tmp_path):
    output = tmp_path / "hypothesis_lab" / "shadow" / "protect_3r_runner_original.json"
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps({
        "meta": {"generated_at_ms": 9_999_999_999_999, "errors": ["fallo"]},
        "decision": {"status": "collecting_insufficient_evidence"},
    }), encoding="utf-8")

    payload = json.loads(_module(tmp_path).api("state", {}, None)[2])
    assert payload["observers"]["shadow_exit"]["status"] == "degraded"


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
