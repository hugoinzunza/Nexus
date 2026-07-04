"""Generate a concrete recapture checklist from the historical atlas."""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATLAS = HERE / "bta_historical_navigation_atlas_2026-07-01.json"
OUT_JSON = HERE / "bta_recapture_priority_checklist_2026-07-01.json"
OUT_MD = HERE / "bta_recapture_priority_checklist_2026-07-01.md"


def slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()


def target_file(c: dict) -> str:
    stamp = c["time"].replace(" ", "_").replace(":", "")
    return f"{stamp}_{c['dir']}_{c['source_tf']}_bta_recapture.jpg"


def item_from_candidate(c: dict, priority: str, source: str) -> dict:
    poi = "Discount POI" if c["dir"] == "long" else "Premium POI"
    target = "weak high/high objetivo" if c["dir"] == "long" else "weak low/low objetivo"
    return {
        "priority": priority,
        "source": source,
        "date_time": c["time"],
        "year": c["year"],
        "month": c["month"],
        "direction": c["dir"],
        "source_tf": c["source_tf"],
        "score": c["score"],
        "rr_liq": c["rr_liq"],
        "risk_pct": c["risk_pct"],
        "range": {
            "low": c["range_lo"],
            "eq": c["range_eq"],
            "high": c["range_hi"],
            "pct": c["range_pct"],
        },
        "target_file": target_file(c),
        "expected_visual_markers": c["expected_visual_markers"],
        "must_capture": [
            "zoomed_range",
            "poi_zone",
            "cdc_or_confirmation",
            "liquidity_target",
            "swing_or_zigzag_context",
            "outcome_if_visible",
        ],
        "acceptance_criteria": [
            poi,
            "CDC or x confirmacion",
            target,
            "range/premium/discount context",
        ],
        "done": False,
    }


def dedupe(items: list[dict]) -> list[dict]:
    by_key = {}
    priority_rank = {"critical": 0, "high": 1, "medium": 2}
    for item in items:
        key = (item["date_time"], item["direction"], item["source_tf"])
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = item
            continue
        if priority_rank[item["priority"]] < priority_rank[prev["priority"]]:
            by_key[key] = item
    return sorted(
        by_key.values(),
        key=lambda i: (
            priority_rank[i["priority"]],
            i["year"],
            i["date_time"],
            -i["score"],
            -i["rr_liq"],
        ),
    )


def md_table(rows: list[dict], headers: list[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def main() -> None:
    atlas = json.loads(ATLAS.read_text(encoding="utf-8"))
    items = []
    for year in ["2024", "2025"]:
        for c in atlas["top_by_year"].get(year, [])[:8]:
            items.append(item_from_candidate(c, "critical", f"top_{year}"))
    for c in atlas["top_by_year"].get("2026", [])[:4]:
        items.append(item_from_candidate(c, "high", "top_2026_control"))

    seen_months = set()
    for c in atlas["monthly_targets"]:
        key = (c["year"], c["month"])
        if c["year"] not in {"2024", "2025"}:
            continue
        if key in seen_months:
            continue
        seen_months.add(key)
        items.append(item_from_candidate(c, "medium", "first_monthly_target"))

    items = dedupe(items)
    data = {
        "meta": {
            "created": "2026-07-01",
            "status": "pending_clean_tradingview_recapture",
            "target_dir": str(HERE / "tradingview_bta_screenshots_clean_2026-07-01"),
            "source_atlas": str(ATLAS),
            "purpose": "Concrete screenshot queue for completing 2024/2025 visual evidence.",
        },
        "counts": {
            "total": len(items),
            "critical": sum(1 for i in items if i["priority"] == "critical"),
            "high": sum(1 for i in items if i["priority"] == "high"),
            "medium": sum(1 for i in items if i["priority"] == "medium"),
        },
        "items": items,
    }
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = [
        {
            "priority": item["priority"],
            "time": item["date_time"],
            "dir": item["direction"],
            "tf": item["source_tf"],
            "score": item["score"],
            "rr": item["rr_liq"],
            "target_file": item["target_file"],
            "criteria": ", ".join(item["acceptance_criteria"]),
        }
        for item in items
    ]
    md = f"""# Checklist priorizada de recaptura BTA

Estado: `pending_clean_tradingview_recapture`

Fuente: `{ATLAS}`

Carpeta destino:

```text
{data["meta"]["target_dir"]}
```

## Conteo

- Total: `{data["counts"]["total"]}`
- Critical: `{data["counts"]["critical"]}`
- High: `{data["counts"]["high"]}`
- Medium: `{data["counts"]["medium"]}`

## Cola de capturas

{md_table(rows, ["priority", "time", "dir", "tf", "score", "rr", "target_file", "criteria"])}

## Método

1. Abrir TradingView limpio en `BTCUSDT.P M15`.
2. Ir a la fecha exacta.
3. Hacer zoom-out hasta que el rango operativo sea legible.
4. Capturar sólo si aparece evidencia visual del profe: POI/CDC/liquidez/estructura.
5. Si no hay anotación, registrar `sin_anotacion` en vez de forzar una captura.
6. Después correr `bta_clean_capture_ingest.py`, regenerar HTML y verificar paquete.

## Criterio de cierre

Para cerrar la misión, se necesitan capturas confirmadas de 2025 y 2024 o evidencia documentada de ausencia de anotaciones útiles en esas fechas prioritarias.
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"items={len(items)} critical={data['counts']['critical']} high={data['counts']['high']} medium={data['counts']['medium']}")
    print(OUT_JSON)
    print(OUT_MD)


if __name__ == "__main__":
    main()
