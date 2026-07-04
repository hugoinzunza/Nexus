"""Validate and summarize the BTA visual inventory."""
from __future__ import annotations

import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
INVENTORY = os.path.join(HERE, "bta_visual_inventory_2026-07-01.json")
OUT_MD = os.path.join(HERE, "bta_visual_inventory_summary_2026-07-01.md")


def load_inventory():
    with open(INVENTORY, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate(inv):
    errors = []
    screenshots_dir = inv["meta"]["screenshots_dir"]
    required = [
        "id", "file", "confidence", "visual_role", "visible_labels",
        "visible_objects", "bta_reading", "measured_case", "nexux_mapping",
        "next_validation",
    ]
    ids = set()
    for idx, cap in enumerate(inv.get("captures", []), 1):
        for key in required:
            if key not in cap:
                errors.append(f"capture {idx} missing `{key}`")
        if cap.get("id") in ids:
            errors.append(f"duplicate id `{cap.get('id')}`")
        ids.add(cap.get("id"))
        path = os.path.join(screenshots_dir, cap.get("file", ""))
        if not os.path.isfile(path):
            errors.append(f"missing screenshot file `{path}`")
        mapping = cap.get("nexux_mapping", {})
        for key in ["required_objects", "zone_kinds", "required_states", "gap"]:
            if key not in mapping:
                errors.append(f"capture `{cap.get('id')}` mapping missing `{key}`")
    return errors


def md_table(rows, headers):
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def summarize(inv, errors):
    captures = inv["captures"]
    by_conf = Counter(c["confidence"] for c in captures)
    by_role = Counter(c["visual_role"] for c in captures)
    objects = Counter()
    states = Counter()
    zone_kinds = Counter()
    pending = []

    for c in captures:
        mapping = c["nexux_mapping"]
        objects.update(mapping.get("required_objects", []))
        states.update(mapping.get("required_states", []))
        zone_kinds.update(mapping.get("zone_kinds", []))
        if c["confidence"] in {"low", "low_medium", "medium"} or "Re-navigate" in c["next_validation"]:
            pending.append({
                "capture": c["id"],
                "confidence": c["confidence"],
                "next": c["next_validation"],
            })

    confidence_rows = [{"confianza": k, "capturas": v} for k, v in sorted(by_conf.items())]
    object_rows = [{"objeto": k, "apariciones": v} for k, v in sorted(objects.items())]
    state_rows = [{"estado": k, "apariciones": v} for k, v in sorted(states.items())]
    zone_rows = [{"tipo": k, "apariciones": v} for k, v in sorted(zone_kinds.items())]

    q = inv["core_quantitative_finding"]
    text = f"""# Resumen inventario visual BTA

Fuente: `/Users/hugh/crisol/nexux/research/bta_visual_inventory_2026-07-01.json`

## Validación

Errores: {len(errors)}

```text
{os.linesep.join(errors) if errors else "OK"}
```

## Cobertura

Capturas inventariadas: {len(captures)}

{md_table(confidence_rows, ["confianza", "capturas"])}

## Objetos Nexux requeridos

{md_table(object_rows, ["objeto", "apariciones"])}

## Tipos de zona

{md_table(zone_rows, ["tipo", "apariciones"])}

## Estados requeridos

{md_table(state_rows, ["estado", "apariciones"])}

## Hallazgo cuantitativo central

| filtro | trades | WR | expR | PF |
| --- | --- | --- | --- | --- |
| POI + liquidez RR>=2 | {q["poi_liquidity_rr2"]["trades"]} | {q["poi_liquidity_rr2"]["win_rate"]}% | {q["poi_liquidity_rr2"]["expectancy_R"]} | {q["poi_liquidity_rr2"]["profit_factor"]} |
| POI + CDC + liquidez | {q["poi_cdc_liquidity"]["trades"]} | {q["poi_cdc_liquidity"]["win_rate"]}% | {q["poi_cdc_liquidity"]["expectancy_R"]} | {q["poi_cdc_liquidity"]["profit_factor"]} |

## Capturas pendientes de re-navegación

{md_table(pending, ["capture", "confidence", "next"])}
"""
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    inv = load_inventory()
    errors = validate(inv)
    summarize(inv, errors)
    print(f"errors={len(errors)}")
    print(f"summary={OUT_MD}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
