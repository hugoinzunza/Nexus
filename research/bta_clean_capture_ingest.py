"""Prepare and summarize clean TradingView recapture evidence.

This script is intentionally conservative: it does not mutate the main visual
inventory. It only checks the clean screenshot folder against the checklist,
builds a contact sheet when images exist, and writes a coverage report.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
CHECKLIST = HERE / "bta_clean_capture_checklist_2026-07-01.json"
PRIORITY_CHECKLIST = HERE / "bta_recapture_priority_checklist_2026-07-01.json"
RECAPTURE_LOG = HERE / "bta_recapture_results_log_2026-07-01.json"
OUT_MD = HERE / "bta_clean_capture_coverage_2026-07-01.md"
OUT_JSON = HERE / "bta_clean_capture_coverage_2026-07-01.json"
OUT_SHEET = HERE / "tradingview_bta_clean_contact_sheet_2026-07-01.jpg"


def load_checklist():
    return json.loads(CHECKLIST.read_text(encoding="utf-8"))


def load_priority_checklist():
    if not PRIORITY_CHECKLIST.exists():
        return {"items": []}
    return json.loads(PRIORITY_CHECKLIST.read_text(encoding="utf-8"))


def load_recapture_log():
    if not RECAPTURE_LOG.exists():
        return {"items": []}
    return json.loads(RECAPTURE_LOG.read_text(encoding="utf-8"))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def image_info(path: Path) -> dict:
    with Image.open(path) as im:
        return {"width": im.width, "height": im.height, "bytes": path.stat().st_size}


def build_contact_sheet(files: list[Path]) -> bool:
    if not files:
        return False
    thumb_w, thumb_h = 520, 292
    pad = 24
    label_h = 54
    cols = 3
    rows = (len(files) + cols - 1) // cols
    width = cols * thumb_w + (cols + 1) * pad
    height = rows * (thumb_h + label_h) + (rows + 1) * pad
    sheet = Image.new("RGB", (width, height), (245, 245, 242))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 15)
    except Exception:
        font = ImageFont.load_default()

    for idx, path in enumerate(files):
        row, col = divmod(idx, cols)
        x = pad + col * (thumb_w + pad)
        y = pad + row * (thumb_h + label_h + pad)
        img = Image.open(path).convert("RGB")
        img.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (thumb_w, thumb_h), (30, 30, 30))
        frame.paste(img, ((thumb_w - img.width) // 2, (thumb_h - img.height) // 2))
        sheet.paste(frame, (x, y))
        label = path.name
        if len(label) > 48:
            label = label[:45] + "..."
        draw.text((x, y + thumb_h + 10), f"{idx + 1}. {label}", fill=(28, 28, 28), font=font)

    sheet.save(OUT_SHEET, quality=92)
    return True


def md_table(rows, headers):
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def main():
    checklist = load_checklist()
    priority_checklist = load_priority_checklist()
    recapture_log = load_recapture_log()
    target_dir = Path(checklist["target_dir"])
    ensure_dir(target_dir)

    expected = {item["target_file"]: item for item in checklist["items"]}
    priority_expected = {item["target_file"]: item for item in priority_checklist.get("items", [])}
    log_by_target = {item["target_file"]: item for item in recapture_log.get("items", [])}
    log_counts = Counter(item.get("status", "missing_status") for item in recapture_log.get("items", []))
    jpgs = sorted(p for p in target_dir.glob("*.jpg") if p.is_file())
    pngs = sorted(p for p in target_dir.glob("*.png") if p.is_file())
    found = {p.name: p for p in jpgs}

    rows = []
    covered = 0
    for name, item in expected.items():
        exists = name in found
        covered += 1 if exists else 0
        info = image_info(found[name]) if exists else {}
        rows.append({
            "priority": item["priority"],
            "date": item["date"],
            "target_file": name,
            "exists": "yes" if exists else "no",
            "size": info.get("bytes", ""),
            "dimensions": f"{info.get('width')}x{info.get('height')}" if info else "",
        })

    priority_rows = []
    priority_covered = 0
    for name, item in priority_expected.items():
        exists = name in found
        priority_covered += 1 if exists else 0
        info = image_info(found[name]) if exists else {}
        priority_rows.append({
            "priority": item["priority"],
            "time": item["date_time"],
            "dir": item["direction"],
            "tf": item["source_tf"],
            "target_file": name,
            "log_status": log_by_target.get(name, {}).get("status", "missing_log"),
            "exists": "yes" if exists else "no",
            "size": info.get("bytes", ""),
            "criteria": ", ".join(item.get("acceptance_criteria", [])[:3]),
        })

    log_rows = [
        {
            "status": status,
            "count": count,
        }
        for status, count in sorted(log_counts.items())
    ]

    all_expected_names = set(expected) | set(priority_expected)
    extras = [p for p in jpgs if p.name not in all_expected_names]
    sheet_created = build_contact_sheet(jpgs)
    report = {
        "target_dir": str(target_dir),
        "expected": len(expected),
        "found_expected": covered,
        "priority_expected": len(priority_expected),
        "priority_found_expected": priority_covered,
        "recapture_log_counts": dict(sorted(log_counts.items())),
        "extra_jpgs": [p.name for p in extras],
        "extra_pngs": [p.name for p in pngs],
        "contact_sheet": str(OUT_SHEET) if sheet_created else None,
        "rows": rows,
        "priority_rows": priority_rows,
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = f"""# Cobertura capturas limpias BTA

Carpeta: `{target_dir}`

Esperadas: `{len(expected)}`
Encontradas: `{covered}`
Prioridad esperadas: `{len(priority_expected)}`
Prioridad encontradas: `{priority_covered}`
Log pending: `{log_counts.get("pending", 0)}`
Log confirmed: `{log_counts.get("confirmed", 0)}`
Log no_annotation: `{log_counts.get("no_annotation", 0)}`
Log blank_projection: `{log_counts.get("blank_projection", 0)}`
Log not_matching: `{log_counts.get("not_matching", 0)}`
Log needs_review: `{log_counts.get("needs_review", 0)}`
Extras: `{len(extras)}`
PNGs vivos/no checklist: `{len(pngs)}`

Contact sheet: `{OUT_SHEET if sheet_created else "pendiente, sin imágenes"}`

## Checklist

{md_table(rows, ["priority", "date", "target_file", "exists", "size", "dimensions"])}

## Checklist priorizada

{md_table(priority_rows, ["priority", "time", "dir", "tf", "target_file", "log_status", "exists", "size", "criteria"])}

## Log de recaptura

{md_table(log_rows, ["status", "count"])}

## Extras

{os.linesep.join(f"- `{p.name}`" for p in extras) if extras else "Sin extras."}

## PNGs vivos/no checklist

{os.linesep.join(f"- `{p.name}`" for p in pngs[:60]) if pngs else "Sin PNGs."}
{f"{os.linesep}- ... {len(pngs) - 60} más" if len(pngs) > 60 else ""}

## Próximo paso

Cuando `Encontradas` o `Prioridad encontradas` sea mayor que cero, revisar la contact sheet limpia y actualizar el inventario estructurado sólo con capturas que cumplan los criterios del protocolo.
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"expected={len(expected)} found={covered} extras={len(extras)}")
    print(OUT_MD)
    if sheet_created:
        print(OUT_SHEET)


if __name__ == "__main__":
    main()
