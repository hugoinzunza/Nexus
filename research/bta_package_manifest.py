"""Build and verify the BTA review package manifest."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(HERE, "bta_package_manifest_2026-07-01.json")
OUT_MD = os.path.join(HERE, "bta_package_manifest_2026-07-01.md")

ARTIFACTS = [
    ("entrypoint", "README_BTA_REVIEW_PACKAGE_2026-07-01.md"),
    ("entrypoint", "bta_review_index_2026-07-01.md"),
    ("entrypoint", "bta_morning_review_2026-07-01.html"),
    ("entrypoint", "bta_morning_review_agenda_2026-07-01.md"),
    ("summary", "bta_morning_status_2026-07-01.md"),
    ("summary", "bta_morning_brief_2026-07-01.md"),
    ("audit", "bta_goal_completion_audit_2026-07-01.md"),
    ("audit", "bta_goal_completion_checklist_2026-07-01.json"),
    ("audit", "bta_goal_completion_status.py"),
    ("audit", "bta_goal_completion_status_2026-07-01.md"),
    ("audit", "bta_final_completion_audit_2026-07-01.md"),
    ("notes", "bta_overnight_mission_notes_2026-07-01.md"),
    ("plan", "bta_tradingview_renavigation_protocol_2026-07-01.md"),
    ("plan", "bta_clean_capture_checklist_2026-07-01.md"),
    ("plan", "bta_clean_capture_checklist_2026-07-01.json"),
    ("plan", "bta_recapture_priority_checklist.py"),
    ("plan", "bta_recapture_priority_checklist_2026-07-01.json"),
    ("plan", "bta_recapture_priority_checklist_2026-07-01.md"),
    ("plan", "bta_recapture_log_template.py"),
    ("plan", "bta_recapture_results_log_2026-07-01.json"),
    ("plan", "bta_recapture_results_log_2026-07-01.md"),
    ("plan", "bta_recapture_session_2026-07-01.md"),
    ("plan", "bta_clean_capture_ingest.py"),
    ("plan", "bta_clean_capture_coverage_2026-07-01.md"),
    ("plan", "bta_clean_capture_coverage_2026-07-01.json"),
    ("plan", "tradingview_bta_clean_contact_sheet_2026-07-01.jpg"),
    ("plan", "bta_live_renavigation_notes_2026-07-01.md"),
    ("visual", "bta_live_capture_inventory.py"),
    ("visual", "bta_live_capture_inventory_2026-07-01.json"),
    ("visual", "bta_live_capture_inventory_2026-07-01.md"),
    ("package", "bta_package_zip.py"),
    ("visual", "tradingview_bta_contact_sheet_2026-07-01.jpg"),
    ("visual", "tradingview_bta_visual_audit_2026-06-30.md"),
    ("visual", "bta_visual_zone_catalog_2026-07-01.md"),
    ("visual", "bta_screenshot_similarity.py"),
    ("visual", "bta_screenshot_similarity_2026-07-01.json"),
    ("visual", "bta_screenshot_similarity_2026-07-01.md"),
    ("visual", "bta_visual_inventory_2026-07-01.json"),
    ("visual", "bta_visual_inventory_summary_2026-07-01.md"),
    ("visual", "bta_visual_inventory_summary.py"),
    ("comparison", "bta_nexux_alignment_matrix_2026-07-01.md"),
    ("comparison", "bta_nexux_implementation_backlog_2026-07-01.md"),
    ("comparison", "bta_operational_playbook_2026-07-01.md"),
    ("model", "bta_visual_model_spec_2026-07-01.md"),
    ("model", "bta_visual_model.py"),
    ("model", "test_bta_visual_model.py"),
    ("quant", "bta_visual_backtest.py"),
    ("quant", "bta_visual_backtest_2026-07-01.md"),
    ("quant", "bta_visual_backtest_results.json"),
    ("quant", "bta_historical_navigation_atlas.py"),
    ("quant", "bta_historical_navigation_atlas_2026-07-01.json"),
    ("quant", "bta_historical_navigation_atlas_2026-07-01.md"),
    ("quant", "bta_visual_cases_data.py"),
    ("quant", "bta_visual_cases_data.json"),
    ("quant", "bta_fetch_btcusdtp_recent.py"),
    ("quant", "bta_btcusdtp_15m_recent.json"),
    ("quant", "bta_m15_structure_study.py"),
    ("quant", "bta_m15_structure_2026-06-30.md"),
    ("quant", "bta_m15_structure_results.json"),
    ("html", "bta_morning_html.py"),
]

SCREENSHOT_DIR = os.path.join(HERE, "tradingview_bta_screenshots_2026-06-30")
CLEAN_SCREENSHOT_DIR = os.path.join(HERE, "tradingview_bta_screenshots_clean_2026-07-01")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_entry(role: str, rel_path: str) -> dict:
    path = os.path.join(HERE, rel_path)
    exists = os.path.isfile(path)
    return {
        "role": role,
        "path": path,
        "relative_path": rel_path,
        "exists": exists,
        "size_bytes": os.path.getsize(path) if exists else None,
        "sha256": sha256(path) if exists else None,
    }


def build_manifest() -> dict:
    entries = [artifact_entry(role, rel) for role, rel in ARTIFACTS]
    if os.path.isdir(SCREENSHOT_DIR):
        for name in sorted(os.listdir(SCREENSHOT_DIR)):
            if name.endswith(".jpg"):
                rel = os.path.join("tradingview_bta_screenshots_2026-06-30", name)
                entries.append(artifact_entry("screenshot", rel))
    if os.path.isdir(CLEAN_SCREENSHOT_DIR):
        for name in sorted(os.listdir(CLEAN_SCREENSHOT_DIR)):
            if name.endswith((".png", ".jpg", ".json")):
                rel = os.path.join("tradingview_bta_screenshots_clean_2026-07-01", name)
                entries.append(artifact_entry("live_screenshot", rel))

    missing = [e for e in entries if not e["exists"]]
    by_role = {}
    for e in entries:
        by_role[e["role"]] = by_role.get(e["role"], 0) + 1
    return {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "provisional_until_tradingview_clean_renavigation",
        "root": HERE,
        "artifact_count": len(entries),
        "missing_count": len(missing),
        "by_role": dict(sorted(by_role.items())),
        "artifacts": entries,
    }


def write_md(manifest: dict) -> None:
    lines = [
        "# Manifiesto paquete BTA",
        "",
        f"Estado: `{manifest['status']}`",
        f"Artefactos: `{manifest['artifact_count']}`",
        f"Faltantes: `{manifest['missing_count']}`",
        "",
        "## Conteo por rol",
        "",
        "| rol | archivos |",
        "| --- | --- |",
    ]
    for role, count in manifest["by_role"].items():
        lines.append(f"| `{role}` | {count} |")
    lines.extend([
        "",
        "## Archivos",
        "",
        "| rol | archivo | bytes | sha256 |",
        "| --- | --- | --- | --- |",
    ])
    for e in manifest["artifacts"]:
        digest = e["sha256"][:12] if e["sha256"] else "MISSING"
        size = e["size_bytes"] if e["size_bytes"] is not None else "MISSING"
        lines.append(f"| `{e['role']}` | `{e['relative_path']}` | {size} | `{digest}` |")
    lines.extend([
        "",
        "## Nota",
        "",
        "Este manifiesto confirma integridad de los artefactos locales, no completa la misión visual. Falta re-navegar TradingView limpio para 2025/2024.",
        "",
    ])
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main() -> None:
    manifest = build_manifest()
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    write_md(manifest)
    print(f"artifacts={manifest['artifact_count']} missing={manifest['missing_count']}")
    print(OUT_JSON)
    print(OUT_MD)
    if manifest["missing_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
