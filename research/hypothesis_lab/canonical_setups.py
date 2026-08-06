"""Fuente canónica de setups para los observadores del laboratorio.

POR QUÉ EXISTE
--------------
El servidor de NexUX se mudó de repositorio (`crisol/nexux` → `crisol/nexux-command-center`)
y los observadores forward quedaron leyendo el `setups.json` del repo antiguo, que dejó de
recibir escrituras el 2026-08-03. Estuvieron 2,5 días releyendo un archivo muerto.

Repuntarlos sin más al store vivo NO era una opción: `shadow_exit` reconstruye sus registros
iterando los setups PRESENTES en el archivo fuente, y el store vivo empezó de cero el
2026-08-03. Apuntar ahí habría borrado los 15 registros de HYP-EXIT-003, o sea, reiniciado
la cohorte.

Este módulo resuelve las dos cosas a la vez: produce UN archivo canónico que es la unión
append-only de todos los stores de setups conocidos. Los observadores leen solo ese archivo.

QUÉ ES Y QUÉ NO ES
------------------
  • NO es un symlink: es un artefacto explícito, versionado en su propio directorio.
  • NO rellena huecos: solo une lo que cada store ya había registrado por su cuenta.
    Lo que ningún store capturó, no aparece acá y no se inventa.
  • NO muta ningún store de origen. Los abre en modo lectura y nunca escribe en ellos.
  • NO toca hipótesis, protocolos, umbrales ni resultados. Es plomería de entrada.
  • Es append-only: un setup que entró al canónico jamás se elimina, aunque desaparezca
    de todos los orígenes. Eso es lo que protege a las cohortes de otra mudanza de repo.

IDENTIDAD Y ACTUALIZACIONES
---------------------------
Cada setup se identifica por `(key, ts_created)`. Un mismo setup evoluciona en el tiempo
(pendiente → activo → ganada/perdida), así que cuando un origen trae una versión más nueva
de un setup ya conocido, se conserva la más reciente según `ts_updated` (con respaldo en
`ts_closed` / `ts_activated`). Nunca se pierde una fila; solo se actualiza.

    python3 -m research.hypothesis_lab.canonical_setups            # una pasada y sale
    python3 -m research.hypothesis_lab.canonical_setups --watch    # bucle
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

# Orígenes por defecto, en orden de autoridad creciente: el último que traiga una versión
# más nueva de un setup gana el desempate.
DEFAULT_SOURCES = (
    ROOT / "data" / "setups.json",
    Path("/Users/hugh/crisol/nexux-command-center/data/setups.json"),
)
DEFAULT_OUTPUT = ROOT / "data" / "hypothesis_lab" / "canonical" / "setups_canonical.json"


def _load_list(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Devuelve (setups, error). Un origen ausente o ilegible nunca detiene la unión.

    Acepta las dos formas: la lista plana que escribe el motor de setups, y el propio
    artefacto canónico `{meta, setups}` — que es como se relee lo ya canonizado para
    que la unión sea de verdad append-only."""
    for attempt in range(3):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return [], "source_missing"
        except (OSError, json.JSONDecodeError) as exc:
            if attempt == 2:
                return [], type(exc).__name__
            time.sleep(0.05)
        else:
            if isinstance(value, dict) and isinstance(value.get("setups"), list):
                value = value["setups"]
            if not isinstance(value, list):
                return [], "source_not_a_list"
            return [row for row in value if isinstance(row, dict)], None
    return [], "unreachable"


def identity(setup: dict[str, Any]) -> str:
    """Identidad estable de un setup, independiente de su estado actual."""
    return f"{setup.get('key')}|{setup.get('ts_created')}"


def _version(setup: dict[str, Any]) -> float:
    """Qué tan nueva es esta versión del setup. Mayor gana."""
    for field in ("ts_updated", "ts_closed", "ts_activated", "ts_created"):
        value = setup.get(field)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def merge(sources: list[Path], output: Path) -> dict[str, Any]:
    """Une los orígenes sobre lo ya canonizado y escribe el resultado de forma atómica."""
    now_ms = int(time.time() * 1000)

    # El punto de partida es siempre lo que ya estaba: append-only de verdad.
    merged: dict[str, dict[str, Any]] = {}
    carried, _ = _load_list(output)
    for setup in carried:
        merged[identity(setup)] = setup
    carried_total = len(merged)

    per_source = []
    for path in sources:
        setups, error = _load_list(path)
        added = updated = 0
        for setup in setups:
            token = identity(setup)
            current = merged.get(token)
            if current is None:
                merged[token] = setup
                added += 1
            elif _version(setup) > _version(current):
                merged[token] = setup
                updated += 1
        newest = max((_version(row) for row in setups), default=None)
        per_source.append({
            "path": str(path),
            "present": error is None,
            "error": error,
            "read": len(setups),
            "added": added,
            "updated": updated,
            "newest_ts": newest,
        })

    rows = sorted(merged.values(), key=lambda row: (_version(row), identity(row)))
    activated = [row for row in rows if isinstance(row.get("ts_activated"), (int, float))]
    payload = {
        "research_only": True,
        "execution_enabled": False,
        "notice": "Fuente canónica de setups · solo lectura · no es señal ni bot",
        "meta": {
            "generated_at_ms": now_ms,
            "total": len(rows),
            "carried_from_previous": carried_total,
            "added_this_pass": sum(item["added"] for item in per_source),
            "updated_this_pass": sum(item["updated"] for item in per_source),
            "activated": len(activated),
            "newest_ts_created": max((row.get("ts_created") or 0 for row in rows), default=None),
            "newest_ts_activated": max((row.get("ts_activated") or 0 for row in activated), default=None),
            "sources": per_source,
        },
        "setups": rows,
    }
    _atomic_write(output, payload)
    return payload


def merge_to_flat(sources: list[Path], output: Path, flat_output: Path) -> dict[str, Any]:
    """Escribe además la lista plana que los observadores esperan (mismo formato que
    `setups.json`), para no tener que tocar el código congelado de cada observador.

    La lista plana solo se reescribe cuando su contenido cambió de verdad. Dos razones:
    `candle_reversal_shadow` aborta la pasada si el archivo se mueve mientras observa, y
    un archivo que se reescribe sin cambiar es justo el falso positivo de frescura que
    este sprint vino a eliminar."""
    payload = merge(sources, output)
    serialized = json.dumps(payload["setups"], ensure_ascii=False, sort_keys=True) + "\n"
    try:
        unchanged = flat_output.read_text(encoding="utf-8") == serialized
    except OSError:
        unchanged = False
    payload["meta"]["flat_rewritten"] = not unchanged
    if not unchanged:
        _atomic_write(flat_output, payload["setups"])
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", default=None,
                        help="Origen de setups. Repetible. Orden = autoridad creciente.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Artefacto canónico con metadatos.")
    parser.add_argument("--flat-output", type=Path, default=None,
                        help="Lista plana de setups para los observadores. "
                             "Por defecto, junto al canónico como setups.json.")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=60.0)
    args = parser.parse_args()

    sources = args.source or list(DEFAULT_SOURCES)
    flat = args.flat_output or args.output.with_name("setups.json")

    while True:
        payload = merge_to_flat(sources, args.output, flat)
        meta = payload["meta"]
        print(json.dumps({
            "generated_at_ms": meta["generated_at_ms"],
            "total": meta["total"],
            "added": meta["added_this_pass"],
            "updated": meta["updated_this_pass"],
            "activated": meta["activated"],
            "flat_rewritten": meta["flat_rewritten"],
            "sources": [
                {"path": item["path"], "present": item["present"],
                 "read": item["read"], "error": item["error"]}
                for item in meta["sources"]
            ],
        }, ensure_ascii=False), flush=True)
        if not args.watch:
            break
        time.sleep(max(15.0, args.interval))


if __name__ == "__main__":
    main()
