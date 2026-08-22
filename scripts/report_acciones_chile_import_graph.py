#!/usr/bin/env python3
"""Emite evidencia reproducible del grafo first-party de Acciones Chile."""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone


ROOT = pathlib.Path(__file__).resolve().parents[1]
FORBIDDEN = ("modules.trading", "modules.bot", "modules.coinsignals")


def module_path(name: str) -> pathlib.Path | None:
    direct = ROOT.joinpath(*name.split(".")).with_suffix(".py")
    package = ROOT.joinpath(*name.split("."), "__init__.py")
    return direct if direct.is_file() else package if package.is_file() else None


def dependencies(name: str, path: pathlib.Path) -> list[str]:
    package = name.rsplit(".", 1)[0]
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[:len(parts) - node.level + 1])
                if node.module:
                    found.append(f"{base}.{node.module}")
                else:
                    found.extend(f"{base}.{alias.name}" for alias in node.names)
            elif node.module:
                found.append(node.module)
    return sorted(set(found))


def main() -> int:
    pending = [f"modules.acciones_chile.{path.stem}" for path in
               (ROOT / "modules/acciones_chile").glob("*.py") if path.stem != "__init__"]
    graph, forbidden_hits = {}, []
    while pending:
        name = pending.pop()
        if name in graph:
            continue
        path = module_path(name)
        if not path:
            continue
        imports = dependencies(name, path)
        hits = [item for item in imports if item.startswith(FORBIDDEN)]
        forbidden_hits.extend({"source": name, "target": item} for item in hits)
        first_party = [item for item in imports if module_path(item)]
        pending.extend(first_party)
        graph[name] = {
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "first_party_imports": first_party,
        }
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    report = {
        "schema_version": "acciones-chile-import-graph-0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit, "module_count": len(graph),
        "forbidden_prefixes": list(FORBIDDEN), "forbidden_hits": forbidden_hits,
        "modules": {name: graph[name] for name in sorted(graph)},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if forbidden_hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
