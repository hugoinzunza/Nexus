"""Auditoría manual e independiente con Claude Opus.

El auditor revisa evidencia y arquitectura. Nunca produce señales, cambia datos,
aprueba releases ni llama al broker. La llamada requiere acción explícita.
"""
from __future__ import annotations

import json
import os


SYSTEM = """Eres auditor independiente y adversarial del módulo Acciones Chile de NexUX.
Revisa: separación respecto de cripto y ejecución, procedencia CMF, privacidad de cartera,
look-ahead, afirmaciones predictivas sin evidencia, reproducibilidad y fail-closed.
No recomiendes comprar o vender. No apruebas releases: entregas hallazgos verificables."""


def availability(config: dict) -> dict:
    enabled = bool(config.get("claude_auditor_enabled", False))
    return {
        "enabled": enabled,
        "model": config.get("claude_auditor_model", "claude-opus-4-8"),
        "run_mode": "manual",
        "key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "authority": "advisory_only",
    }


def audit(snapshot: dict, config: dict) -> dict | None:
    """Ejecuta una revisión solo cuando un script/handler la invoca explícitamente."""
    status = availability(config)
    if not status["enabled"] or not status["key_present"]:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model=status["model"], max_tokens=3000, system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)}],
        )
        text = "\n".join(block.text for block in response.content if block.type == "text")
        return {"auditor": "Claude/Opus", "model": status["model"], "report": text,
                "authority": "advisory_only"}
    except Exception:
        return None
