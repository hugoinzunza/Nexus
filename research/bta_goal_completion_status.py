"""Summarize mission completion status from the BTA checklist."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKLIST = HERE / "bta_goal_completion_checklist_2026-07-01.json"
OUT_MD = HERE / "bta_goal_completion_status_2026-07-01.md"


def md_table(rows, headers):
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def main():
    data = json.loads(CHECKLIST.read_text(encoding="utf-8"))
    counts = Counter(req["status"] for req in data["requirements"])
    rows = []
    for req in data["requirements"]:
        rows.append({
            "id": req["id"],
            "status": req["status"],
            "requirement": req["requirement"],
            "missing": req["missing"] or "-",
        })

    gate = "\n".join(f"- {item}" for item in data["completion_gate"]["required_for_complete"])
    md = f"""# Estado completitud misión BTA

Estado general: `{data["overall_status"]}`

Razón: {data["reason"]}

## Conteo

| estado | cantidad |
| --- | --- |
| complete | {counts.get("complete", 0)} |
| partial | {counts.get("partial", 0)} |
| missing | {counts.get("missing", 0)} |

## Requisitos

{md_table(rows, ["id", "status", "requirement", "missing"])}

## Gate para completar

{gate}
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"overall_status={data['overall_status']}")
    print(f"complete={counts.get('complete', 0)} partial={counts.get('partial', 0)} missing={counts.get('missing', 0)}")
    print(OUT_MD)


if __name__ == "__main__":
    main()
