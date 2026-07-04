"""Create a recapture result log template from the priority checklist.

The log is meant to be edited after a clean TradingView pass. Re-running this
script preserves existing statuses/notes while adding any new checklist items.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKLIST = HERE / "bta_recapture_priority_checklist_2026-07-01.json"
OUT_JSON = HERE / "bta_recapture_results_log_2026-07-01.json"
OUT_MD = HERE / "bta_recapture_results_log_2026-07-01.md"

DEFAULT_STATUS = "pending"
VALID_STATUSES = [
    "pending",
    "confirmed",
    "no_annotation",
    "blank_projection",
    "not_matching",
    "needs_review",
]


def load_existing() -> dict:
    if not OUT_JSON.exists():
        return {"items": []}
    return json.loads(OUT_JSON.read_text(encoding="utf-8"))


def md_table(rows: list[dict], headers: list[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def main() -> None:
    checklist = json.loads(CHECKLIST.read_text(encoding="utf-8"))
    existing = load_existing()
    old_by_file = {item["target_file"]: item for item in existing.get("items", [])}

    items = []
    for src in checklist["items"]:
        old = old_by_file.get(src["target_file"], {})
        item = {
            "target_file": src["target_file"],
            "status": old.get("status", DEFAULT_STATUS),
            "captured_file": old.get("captured_file", ""),
            "date_time": src["date_time"],
            "priority": src["priority"],
            "direction": src["direction"],
            "source_tf": src["source_tf"],
            "score": src["score"],
            "rr_liq": src["rr_liq"],
            "expected_visual_markers": src["expected_visual_markers"],
            "acceptance_criteria": src["acceptance_criteria"],
            "observed_markers": old.get("observed_markers", []),
            "notes": old.get("notes", ""),
            "reviewed_by": old.get("reviewed_by", ""),
            "reviewed_at": old.get("reviewed_at", ""),
        }
        items.append(item)

    counts = Counter(item["status"] for item in items)
    data = {
        "meta": {
            "created": "2026-07-01",
            "status": "template_pending_clean_recapture",
            "source_checklist": str(CHECKLIST),
            "valid_statuses": VALID_STATUSES,
            "status_meanings": {
                "pending": "not reviewed/captured yet",
                "confirmed": "visual TradingView evidence matches expected markers",
                "no_annotation": "date reached, chart had no useful professor annotation",
                "blank_projection": "navigation landed in blank/projection area",
                "not_matching": "visible chart did not match candidate expectation",
                "needs_review": "captured but requires manual decision",
            },
        },
        "counts": dict(sorted(counts.items())),
        "items": items,
    }
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = [
        {
            "status": item["status"],
            "priority": item["priority"],
            "time": item["date_time"],
            "dir": item["direction"],
            "tf": item["source_tf"],
            "target_file": item["target_file"],
            "captured_file": item["captured_file"] or "-",
        }
        for item in items
    ]
    count_rows = [{"status": k, "count": v} for k, v in sorted(counts.items())]
    md = f"""# Log de resultados de recaptura BTA

Estado: `template_pending_clean_recapture`

Este archivo se llena después de navegar TradingView limpio. No cuenta como evidencia visual hasta que cada item tenga `status=confirmed` y `captured_file`.

## Estados válidos

- `pending`: no revisado todavía.
- `confirmed`: captura visual coincide con los marcadores esperados.
- `no_annotation`: fecha alcanzada, sin anotación útil del profe.
- `blank_projection`: navegación cayó en margen blanco/proyección.
- `not_matching`: lo visible no coincide con la expectativa del candidato.
- `needs_review`: hay captura, pero requiere decisión manual.

## Conteo

{md_table(count_rows, ["status", "count"])}

## Items

{md_table(rows, ["status", "priority", "time", "dir", "tf", "target_file", "captured_file"])}

## Uso

1. Capturar el chart limpio con el nombre `target_file` cuando coincida.
2. Cambiar `status` en el JSON.
3. Rellenar `captured_file`, `observed_markers`, `notes`, `reviewed_by` y `reviewed_at`.
4. Regenerar cobertura y paquete.
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"items={len(items)} statuses={dict(sorted(counts.items()))}")
    print(OUT_JSON)
    print(OUT_MD)


if __name__ == "__main__":
    main()
