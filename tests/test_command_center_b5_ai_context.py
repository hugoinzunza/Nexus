import ast
import json
import subprocess
from pathlib import Path

import pytest

from modules.command_center.ai_context import (
    AiContextService,
    AiObservationInvalid,
)
from modules.command_center.contracts import CONTRACT_V1_FINGERPRINT
from modules.command_center.module import CommandCenterModule
from modules.command_center.module_registry import command_center_module_registry


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "modules" / "command_center" / "public"
NOW = 1_800_000_000_000


def test_sin_evidencia_no_inventa_observacion_ni_recomendacion() -> None:
    disabled = AiContextService(clock_ms=lambda: NOW).snapshot()
    enabled = AiContextService(
        enabled_loader=lambda: True,
        clock_ms=lambda: NOW,
    ).snapshot()

    assert disabled == {
        "generated_at_ms": NOW,
        "state": "disabled",
        "last_evaluation_ms": None,
        "severity": "normal",
        "summary": None,
        "freshness": "unknown",
        "source": None,
        "reason": "ai-disabled",
    }
    assert enabled["state"] == "unknown"
    assert enabled["summary"] is None
    assert enabled["reason"] == "ai-observation-unavailable"


def test_observacion_contractual_se_normaliza_sin_llamar_modelos() -> None:
    service = AiContextService(
        observation_loader=lambda: {
            "state": "ready",
            "last_evaluation_ms": NOW - 60_000,
            "severity": "warning",
            "summary": "Hay una observación verificable que requiere revisión.",
            "freshness": "current",
            "source": "fixture:test",
        },
        enabled_loader=lambda: True,
        clock_ms=lambda: NOW,
    )

    result = service.snapshot()

    assert result["summary"].startswith("Hay una observación")
    assert result["severity"] == "warning"
    assert result["reason"] is None


@pytest.mark.parametrize(
    "field,value",
    (
        ("state", "invented"),
        ("severity", "buy"),
        ("freshness", "future"),
        ("summary", ""),
        ("last_evaluation_ms", NOW + 60_001),
        ("source", ""),
    ),
)
def test_observacion_invalida_falla_cerrada(field, value) -> None:
    observation = {
        "state": "ready",
        "last_evaluation_ms": NOW,
        "severity": "info",
        "summary": "Contexto breve.",
        "freshness": "live",
        "source": "fixture:test",
    }
    observation[field] = value
    service = AiContextService(
        observation_loader=lambda: observation,
        clock_ms=lambda: NOW,
    )

    with pytest.raises(AiObservationInvalid):
        service.snapshot()


def test_b5_no_importa_anthropic_ni_brief_ni_grader() -> None:
    source = ROOT / "modules" / "command_center" / "ai_context.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")

    assert not any("anthropic" in name for name in imports)
    text = source.read_text(encoding="utf-8")
    assert "claude_brief" not in text
    assert "claude_grader" not in text


def test_endpoint_b5_es_autenticado_read_only_y_fuera_del_abi() -> None:
    class Context:
        @staticmethod
        def snapshot():
            return {"state": "unknown", "summary": None}

    module = object.__new__(CommandCenterModule)
    module.ai_context = Context()
    module.context = type("Context", (), {"log": lambda *_args: None})()

    assert module.api("ai-context", {}, user=None)[0] == 401
    response = module.api("ai-context", {}, user={"id": 1})

    assert response[0] == 200
    assert json.loads(response[2])["state"] == "unknown"
    assert command_center_module_registry().stats()["attached_factories"] == 0
    assert CONTRACT_V1_FINGERPRINT == (
        "b0a8a7efa623a1aae4b681c3cfc42790d36a6a14fbc689688026c523f2e49b46"
    )


def test_frontend_normaliza_unknown_sin_convertirlo_en_recomendacion() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        process.stdout.write(JSON.stringify({{
          empty: module.normalizeAiContext(null),
          invalid: module.normalizeAiContext({{
            state: "buy", severity: "strong_buy", summary: "  ",
            last_evaluation_ms: "x"
          }}),
          valid: module.normalizeAiContext({{
            state: "ready", severity: "warning",
            summary: "Revisar evidencia", last_evaluation_ms: {NOW},
            freshness: "current", source: "fixture"
          }})
        }}));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["empty"]["state"] == "unknown"
    assert payload["empty"]["summary"] is None
    assert payload["invalid"]["severity"] == "normal"
    assert payload["valid"]["summary"] == "Revisar evidencia"


def test_b5_historico_sale_del_viewport_y_lo_reemplaza_posiciones() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert 'class="ai-panel"' not in page
    assert 'id="ai-summary"' not in page
    assert page.count('class="positions-panel"') == 1
    assert 'id="positions-principal"' in page
    assert 'id="positions-bot"' in page
    assert "/m/command-center/api/positions-context" in script
    assert "new PositionsContextClient" in script
    positions_markup = page.split('class="positions-panel"', 1)[1].split(
        '<section class="attention-panel"', 1
    )[0]
    assert "<button" not in positions_markup
    assert "<a " not in positions_markup
    assert script.count('method: "POST"') == 1
    assert '"/m/command-center/api/media-command"' in script
    assert ".status-panel {\n  grid-column: 1 / -1;" in (
        PUBLIC / "command-center.css"
    ).read_text(encoding="utf-8")
