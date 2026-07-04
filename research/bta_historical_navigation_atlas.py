"""Build a historical navigation atlas for TradingView recapture.

The atlas does not claim visual completion. It selects high-value M15 dates
from the research backtest so the next TradingView pass can jump directly to
likely POI/CDC/liquidity/structure areas.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import bta_visual_backtest as bt

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "bta_historical_navigation_atlas_2026-07-01.json"
OUT_MD = HERE / "bta_historical_navigation_atlas_2026-07-01.md"


def month_key(time_text: str) -> str:
    return time_text[:7]


def enrich_candidates(candles):
    records = bt.build_records(candles)
    candidates = []
    for r in records:
        score, ctx, reasons = bt.score_record(r, candles)
        rr_ok = r["rr_liq"] is not None and r["rr_liq"] >= bt.RR_MIN
        cdc_ok = r["cdc_within_window"] and (
            r["cdc_delay_bars"] is not None and r["cdc_delay_bars"] <= bt.CDC_MAX_DELAY
        )
        risk_ok = r["risk_pct"] is not None and r["risk_pct"] <= bt.RISK_MAX_PCT
        correct_side = (r["dir"] == "long" and r["entry_next_open"] <= ctx["eq"]) or (
            r["dir"] == "short" and r["entry_next_open"] >= ctx["eq"]
        )
        if not (rr_ok and cdc_ok and risk_ok):
            continue
        item = {
            "time": r["time"],
            "year": r["year"],
            "month": month_key(r["time"]),
            "dir": r["dir"],
            "source_tf": r["source_tf"],
            "session": r["session"],
            "score": score,
            "rr_liq": round(r["rr_liq"], 3) if r["rr_liq"] is not None else None,
            "risk_pct": round(r["risk_pct"], 3) if r["risk_pct"] is not None else None,
            "cdc_delay_bars": r["cdc_delay_bars"],
            "range_lo": round(ctx["lo"], 2),
            "range_eq": round(ctx["eq"], 2),
            "range_hi": round(ctx["hi"], 2),
            "range_pct": round(ctx["range_pct"], 2),
            "correct_premium_discount_side": correct_side,
            "reasons": reasons,
            "expected_visual_markers": expected_markers(r, score, correct_side),
        }
        candidates.append(item)
    candidates = dedupe_candidates(candidates)
    candidates.sort(key=lambda c: (
        c["year"],
        c["score"],
        c["correct_premium_discount_side"],
        c["rr_liq"],
    ), reverse=True)
    return candidates


def dedupe_candidates(candidates: list[dict]) -> list[dict]:
    """Keep one candidate per exact navigation target."""
    best_by_key = {}
    for c in candidates:
        key = (c["time"], c["dir"], c["source_tf"])
        prev = best_by_key.get(key)
        if prev is None or (c["score"], c["rr_liq"]) > (prev["score"], prev["rr_liq"]):
            best_by_key[key] = c
    return list(best_by_key.values())


def expected_markers(record: dict, score: int, correct_side: bool) -> list[str]:
    markers = ["CDC", "liquidez objetivo"]
    if correct_side:
        markers.append("premium/discount correcto")
    if record["dir"] == "long":
        markers.extend(["Discount POI", "weak high / high objetivo"])
    else:
        markers.extend(["Premium POI", "weak low / low objetivo"])
    if score >= 8:
        markers.append("posible check/reaccion")
    if record["source_tf"] in {"1h", "4h", "1d"}:
        markers.append(f"POI HTF {record['source_tf']}")
    return markers


def pick_monthly(candidates: list[dict], years: set[str], per_month: int = 3) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        if c["year"] in years:
            buckets[c["month"]].append(c)
    picked = []
    for month in sorted(buckets):
        rows = sorted(
            buckets[month],
            key=lambda c: (c["score"], c["correct_premium_discount_side"], c["rr_liq"]),
            reverse=True,
        )[:per_month]
        picked.extend(rows)
    return picked


def pick_top_by_year(candidates: list[dict], years: set[str], n: int = 12) -> dict[str, list[dict]]:
    out = {}
    for year in sorted(years):
        rows = [c for c in candidates if c["year"] == year]
        out[str(year)] = rows[:n]
    return out


def md_table(rows: list[dict], headers: list[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def main() -> None:
    candles = bt.base_study.load(bt.base_study.BASE_TF)
    candidates = enrich_candidates(candles)
    target_years = {"2024", "2025", "2026"}
    monthly = pick_monthly(candidates, target_years, per_month=3)
    top_by_year = pick_top_by_year(candidates, target_years, n=12)

    data = {
        "meta": {
            "created": "2026-07-01",
            "purpose": "Navigation targets for clean TradingView recapture.",
            "source": "bta_visual_backtest functions over local BTCUSDT M15/POI data",
            "status": "candidate_dates_not_visual_proof",
            "criteria": [
                "CDC within window",
                "liquidity target RR>=2",
                "risk <= 1.2%",
                "rank by visual score, premium/discount side, RR",
            ],
        },
        "counts": {
            "candidate_count": len(candidates),
            "monthly_targets": len(monthly),
        },
        "top_by_year": top_by_year,
        "monthly_targets": monthly,
    }
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    target_rows = [
        {
            "time": c["time"],
            "dir": c["dir"],
            "tf": c["source_tf"],
            "score": c["score"],
            "rr": c["rr_liq"],
            "risk%": c["risk_pct"],
            "range": f'{c["range_lo"]}/{c["range_eq"]}/{c["range_hi"]}',
            "markers": ", ".join(c["expected_visual_markers"][:4]),
        }
        for c in monthly
    ]
    top_rows = []
    for year, rows in top_by_year.items():
        for c in rows[:8]:
            top_rows.append({
            "year": year,
            "time": c["time"],
            "dir": c["dir"],
            "tf": c["source_tf"],
            "score": c["score"],
            "rr": c["rr_liq"],
            "markers": ", ".join(c["expected_visual_markers"][:4]),
            })

    md = f"""# Atlas histórico para re-navegar TradingView BTA

Estado: `candidate_dates_not_visual_proof`

Este atlas no reemplaza las capturas del chart del profe. Sirve para elegir fechas de alta prioridad al re-navegar TradingView limpio.

## Criterio

- CDC confirmado dentro de `{bt.CDC_MAX_DELAY}` velas.
- Liquidez objetivo con RR >= `{bt.RR_MIN}`.
- Riesgo <= `{bt.RISK_MAX_PCT}%`.
- Ranking por score visual, lado premium/discount y RR.

Total candidatos: `{len(candidates)}`

## Top por año

{md_table(top_rows, ["year", "time", "dir", "tf", "score", "rr", "markers"])}

## Objetivos mensuales 2024-2026

{md_table(target_rows, ["time", "dir", "tf", "score", "rr", "risk%", "range", "markers"])}

## Cómo usarlo en TradingView

1. Abrir el chart limpio `BTCUSDT.P M15`.
2. Ir a cada fecha de la tabla, priorizando 2024 y 2025.
3. Hacer zoom-out hasta ver rango operativo, POI, CDC y liquidez.
4. Guardar captura sólo si hay anotaciones visibles del profe.
5. Clasificar como `confirmado`, `sin anotacion`, `margen blanco`, o `no coincide`.

## Advertencia

Estas fechas vienen de Nexux/backtest, no del TradingView visual. Una fecha candidata sólo cuenta para cerrar la misión si luego se confirma con captura visual del layout del profe.
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"candidates={len(candidates)} monthly_targets={len(monthly)}")
    print(OUT_JSON)
    print(OUT_MD)


if __name__ == "__main__":
    main()
