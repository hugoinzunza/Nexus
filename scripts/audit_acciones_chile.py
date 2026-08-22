#!/usr/bin/env python3
"""Ejecuta explícitamente la auditoría Claude/Opus sobre un snapshot JSON.

Uso:
  ANTHROPIC_API_KEY=... .venv/bin/python scripts/audit_acciones_chile.py snapshot.json

El reporte se imprime a stdout para que el operador decida dónde conservarlo.
El script no lee la cartera ni otros archivos por su cuenta.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.acciones_chile.auditor import audit, availability  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoría manual Acciones Chile")
    parser.add_argument("snapshot", type=pathlib.Path, help="JSON acotado que se enviará a Claude")
    parser.add_argument("--model", default="claude-opus-4-8")
    args = parser.parse_args()
    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"snapshot inválido: {exc}", file=sys.stderr)
        return 2
    config = {"claude_auditor_enabled": True, "claude_auditor_model": args.model}
    status = availability(config)
    if not status["key_present"]:
        print("auditor pendiente: falta ANTHROPIC_API_KEY en el entorno", file=sys.stderr)
        return 3
    report = audit(snapshot, config)
    if report is None:
        print("auditoría falló cerrada: no se generó reporte", file=sys.stderr)
        return 4
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
