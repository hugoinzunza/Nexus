"""Build a conservative inventory for live TradingView recapture screenshots."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE_DIR = HERE / "tradingview_bta_screenshots_clean_2026-07-01"
AUDIT_JSON = LIVE_DIR / "live_capture_file_audit_2026-07-01.json"
OUT_JSON = HERE / "bta_live_capture_inventory_2026-07-01.json"
OUT_MD = HERE / "bta_live_capture_inventory_2026-07-01.md"

USEFUL = {
    "live_2026-07-01_current_jun_range.png": {
        "status": "useful",
        "period": "2026-06",
        "visual_role": "range_map_premium_discount",
        "visible_labels": [
            "Premium POI",
            "Discount POI x confirmación",
            "CDC",
            "Alto Referencial (Resistencia)",
            "Strong High (Nivel De Resistencia)",
            "Máximo",
            "Mínimo",
        ],
        "visible_objects": [
            "grey_decision_zones",
            "blue_reaction_band",
            "green_checks",
            "operational_high_low",
            "reference_levels",
        ],
        "bta_reading": "Mapa de rango de junio 2026. El profe organiza premium/discount, CDC, referencias de resistencia y mínimo objetivo dentro de una sola estructura.",
        "nexux_mapping": ["RangeMap", "Zone.state", "CharacterLevel", "ReferenceLevel"],
    },
    "live_pan_test_after_scrollX_negative.png": {
        "status": "useful",
        "period": "2026-06",
        "visual_role": "trade_box_with_cdc_and_liquidity",
        "visible_labels": [
            "Objetivo",
            "Stop",
            "Cerrado PyG",
            "ratio riesgo/beneficio",
            "CDC",
            "Premium POI",
            "Discount POI",
            "Mínimo",
        ],
        "visible_objects": [
            "trade_box",
            "green_checks",
            "cyan_pivots",
            "orange_leg",
            "red_diagonal_structure",
            "blue_reaction_bands",
        ],
        "bta_reading": "La anotación incluye operación completa: objetivo, stop, resultado, ratio, CDC y pivotes. Esto refuerza que la estrategia evalúa outcome y gestión, no sólo entrada en POI.",
        "nexux_mapping": ["TradePlan", "ZoneOutcome", "SwingLeg", "LiquidityTarget"],
    },
    "live_zoom_test_scrollY_positive.png": {
        "status": "duplicate_useful",
        "period": "2026-06",
        "visual_role": "trade_box_duplicate",
        "visible_labels": ["Objetivo", "Stop", "Cerrado PyG", "CDC"],
        "visible_objects": ["trade_box", "cyan_pivots", "green_checks"],
        "bta_reading": "Duplicado visual del trade box de junio. Se conserva como respaldo, no como caso independiente.",
        "nexux_mapping": ["TradePlan", "ZoneOutcome"],
    },
    "live_autoscale_after_blank_windows.png": {
        "status": "useful",
        "period": "2026-02",
        "visual_role": "bearish_swing_sequence",
        "visible_labels": ["Máximo", "Mínimo"],
        "visible_objects": ["cyan_pivots", "downtrend_leg", "horizontal_reference_zone"],
        "bta_reading": "Secuencia bajista de febrero 2026 con pivotes celestes y extremos operativos. Aporta evidencia de la capa swing/leg fuera del tramo de junio.",
        "nexux_mapping": ["SwingLeg", "ReferenceLevel"],
    },
    "live_reverse_from_blank_test.png": {
        "status": "partial",
        "period": "2026-01",
        "visual_role": "price_context_without_strong_annotations",
        "visible_labels": ["Mínimo"],
        "visible_objects": ["candles", "operational_low"],
        "bta_reading": "Contexto de precio de enero 2026. Útil para navegación, débil para inferir reglas del profe por falta de POI/CDC visibles.",
        "nexux_mapping": ["ContextWindow"],
    },
    "live_drag_right_test.png": {
        "status": "partial",
        "period": "2026-01",
        "visual_role": "intraday_range_context",
        "visible_labels": ["Máximo", "Mínimo"],
        "visible_objects": ["candles", "operational_high_low"],
        "bta_reading": "Rango intradía de enero 2026 con extremos operativos. No contiene POI/CDC fuertes visibles.",
        "nexux_mapping": ["RangeMap"],
    },
    "live_back_autoscale_2026_to_2025_01.png": {
        "status": "useful",
        "period": "2026-01",
        "visual_role": "january_reversal_context",
        "visible_labels": ["Mínimo"],
        "visible_objects": ["candles", "swing_reversal"],
        "bta_reading": "Ventana de enero 2026 que muestra reversión amplia y extremo mínimo. Complementa la navegación histórica, aunque sin POI/CDC claro.",
        "nexux_mapping": ["RangeMap", "SwingLeg"],
    },
    "live_back_autoscale_2026_to_2025_02.png": {
        "status": "useful",
        "period": "2025-12/2026-01",
        "visual_role": "late_december_impulse",
        "visible_labels": ["Mínimo"],
        "visible_objects": ["candles", "bullish_impulse"],
        "bta_reading": "Impulso alcista diciembre/enero. Evidencia de recorrido histórico, pero no de POI/CDC rotulado.",
        "nexux_mapping": ["SwingLeg"],
    },
    "live_back_autoscale_2026_to_2025_03.png": {
        "status": "useful",
        "period": "2025-12",
        "visual_role": "december_range_sweep_context",
        "visible_labels": ["Mínimo"],
        "visible_objects": ["candles", "large_wick", "range_context"],
        "bta_reading": "Rango de diciembre con barridos/mechas visibles. Sirve para comparar con lectura de liquidez, aunque no tiene etiquetas POI/CDC claras.",
        "nexux_mapping": ["LiquiditySweep", "RangeMap"],
    },
    "live_back_autoscale_2026_to_2025_04.png": {
        "status": "useful",
        "period": "2025-12",
        "visual_role": "zigzag_pivot_structure",
        "visible_labels": ["Mínimo"],
        "visible_objects": ["purple_zigzag", "cyan_pivots", "swing_arrows"],
        "bta_reading": "Caso más útil de diciembre 2025: zigzag morado y pivotes celestes conectan la estructura. Confirma la capa de legs que Nexux debe modelar.",
        "nexux_mapping": ["SwingLeg", "PivotGraph", "StructureState"],
    },
    "live_drag_history_2026_2025_01.png": {
        "status": "duplicate_useful",
        "period": "2025-12",
        "visual_role": "zigzag_pivot_structure_duplicate",
        "visible_labels": ["Mínimo"],
        "visible_objects": ["purple_zigzag", "cyan_pivots", "swing_arrows"],
        "bta_reading": "Duplicado/variación cercana del caso de zigzag de diciembre 2025. Se conserva como confirmación, no como muestra independiente.",
        "nexux_mapping": ["SwingLeg", "PivotGraph"],
    },
}


def load_audit() -> list[dict]:
    if not AUDIT_JSON.exists():
        return []
    return json.loads(AUDIT_JSON.read_text(encoding="utf-8"))


def classify_audit_row(row: dict) -> dict:
    name = row["file"]
    meta = USEFUL.get(name)
    if meta is None:
        density = row.get("density", 0)
        status = "discard_blank_or_projection" if density <= 0.26 else "weak_unclassified"
        meta = {
            "status": status,
            "period": "unknown",
            "visual_role": "not_inventoried",
            "visible_labels": [],
            "visible_objects": [],
            "bta_reading": "No se usa como evidencia independiente en esta pasada.",
            "nexux_mapping": [],
        }
    return {
        "file": name,
        "path": str(LIVE_DIR / name),
        "bytes": row.get("bytes"),
        "density": row.get("density"),
        "sha256": row.get("sha256"),
        **meta,
    }


def md_table(rows: list[dict], headers: list[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def main() -> None:
    audit_rows = load_audit()
    captures = [classify_audit_row(row) for row in audit_rows]
    counts = Counter(c["status"] for c in captures)
    useful = [c for c in captures if c["status"] in {"useful", "duplicate_useful", "partial"}]
    independent = [c for c in captures if c["status"] == "useful"]

    data = {
        "meta": {
            "created": "2026-07-01",
            "source": "Live Chrome recapture of TradingView chart c07zDMmj",
            "live_dir": str(LIVE_DIR),
            "status": "supplemental_not_full_multiyear_completion",
            "note": "Inventario complementario. No reemplaza la re-navegación limpia 2025/2024.",
        },
        "counts": dict(sorted(counts.items())),
        "independent_useful_count": len(independent),
        "captures": captures,
    }
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    useful_rows = [
        {
            "file": c["file"],
            "status": c["status"],
            "period": c["period"],
            "role": c["visual_role"],
            "objects": ", ".join(c["visible_objects"][:5]),
        }
        for c in useful
    ]
    status_rows = [{"status": k, "count": v} for k, v in sorted(counts.items())]
    md = f"""# Inventario capturas en vivo BTA

Fuente: `{LIVE_DIR}`

Estado: `supplemental_not_full_multiyear_completion`

## Conteo

{md_table(status_rows, ["status", "count"])}

Capturas útiles independientes: `{len(independent)}`

## Capturas inventariadas

{md_table(useful_rows, ["file", "status", "period", "role", "objects"])}

## Lectura agregada

- Junio 2026 confirma que el profe dibuja una operación completa: POI, CDC, pivotes, objetivo, stop, ratio y resultado.
- Febrero/enero 2026 aportan contexto de pivotes y extremos operativos, pero no todos tienen POI/CDC rotulado.
- Diciembre 2025 vuelve a confirmar la capa `zigzag + pivotes celestes`, que debe traducirse a `SwingLeg`/`PivotGraph` en Nexux.
- Muchas capturas del paneo largo quedaron en margen blanco/proyección y no se usan como evidencia independiente.

## Pendiente

Sigue faltando re-navegar 2025/2024 con una forma estable de ir a fecha o con el chart recargado/limpio. Este inventario mejora la evidencia, pero no cierra la misión multi-año.
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"captures={len(captures)} independent_useful={len(independent)}")
    print(OUT_JSON)
    print(OUT_MD)


if __name__ == "__main__":
    main()
