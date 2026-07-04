"""Prototipo BTA visual sobre el universo POI existente.

No intenta copiar el indicador del profe. Traduce la lectura visual observada en
TradingView a filtros explícitos y comparables contra Nexux:

- rango operativo reciente y premium/discount global;
- CDC dentro de ventana;
- target hacia liquidez con R:R >= 2;
- riesgo acotado;
- score de contexto.

Salida:
  research/bta_visual_backtest_results.json
  research/bta_visual_backtest_2026-07-01.md
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from collections import defaultdict

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import engine  # noqa: E402
from modules.trading.backtest import metrics  # noqa: E402
from modules.trading.strategies import detect_pois  # noqa: E402

import bta_m15_structure_study as base_study  # noqa: E402

OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "bta_visual_backtest_results.json")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "bta_visual_backtest_2026-07-01.md")

RANGE_BARS = 7 * 24 * 4
RR_MIN = 2.0
RISK_MAX_PCT = 1.2
CDC_MAX_DELAY = 16
MAX_HOLD = 96


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def iso(ts_ms):
    return base_study.iso(ts_ms)


def year(ts_ms):
    return base_study.year(ts_ms)


def summarize(trades):
    m = metrics(trades)
    return {
        "trades": m["trades"],
        "win_rate": m["win_rate"],
        "expectancy_R": m["expectancy_R"],
        "profit_factor": m["profit_factor"],
        "total_R": m["total_R"],
        "max_drawdown_R": m["max_drawdown_R"],
        "timeouts": m["timeouts"],
    }


def range_context(candles, idx, bars=RANGE_BARS):
    start = max(0, idx - bars)
    window = candles[start: idx + 1]
    hi = max(c["h"] for c in window)
    lo = min(c["l"] for c in window)
    eq = (hi + lo) / 2.0
    return {
        "hi": hi,
        "lo": lo,
        "eq": eq,
        "range_pct": ((hi - lo) / lo * 100.0) if lo else 0.0,
        "bars": len(window),
    }


def score_record(record, candles):
    """Score 0-10 inspirado en la lectura visual documentada."""
    idx = record["idx"]
    entry = record["entry_next_open"]
    direction = record["dir"]
    ctx = range_context(candles, idx)

    correct_side = (direction == "long" and entry <= ctx["eq"]) or (
        direction == "short" and entry >= ctx["eq"])
    rr_ok = record["rr_liq"] is not None and record["rr_liq"] >= RR_MIN
    cdc_ok = record["cdc_within_window"] and (
        record["cdc_delay_bars"] is not None and record["cdc_delay_bars"] <= CDC_MAX_DELAY)
    risk_ok = record["risk_pct"] is not None and record["risk_pct"] <= RISK_MAX_PCT
    source_ok = record["source_tf"] in {"1h", "4h", "1d"}
    session_ok = record["session"] in {"Londres", "NY"}
    range_ok = ctx["range_pct"] >= 2.0

    score = 0
    score += 2 if correct_side else 0
    score += 2 if cdc_ok else 0
    score += 2 if rr_ok else 0
    score += 1 if risk_ok else 0
    score += 1 if source_ok else 0
    score += 1 if session_ok else 0
    score += 1 if range_ok else 0

    reasons = []
    if correct_side:
        reasons.append("premium/discount global correcto")
    if cdc_ok:
        reasons.append("CDC confirmado")
    if rr_ok:
        reasons.append("liquidez con RR>=2")
    if risk_ok:
        reasons.append("riesgo acotado")
    if source_ok:
        reasons.append("POI HTF")
    if session_ok:
        reasons.append("sesion liquida")
    if range_ok:
        reasons.append("rango reciente suficiente")

    return score, ctx, reasons


def build_records(candles):
    pois = []
    for tf in base_study.POI_SOURCES:
        for poi in detect_pois(base_study.load(tf), base_study.PIV_MICRO, base_study.DISP):
            pp = dict(poi)
            pp["source_tf"] = tf
            pois.append(pp)
    pois.sort(key=lambda p: p["t_conf"])
    records, _fixed, _liq = base_study.build_touch_records(candles, pois)
    return [r for r in records if r["event"] == "touch"]


def simulate_variant(candles, records, predicate, name):
    signals = []
    selected = []
    for r in records:
        score, ctx, reasons = score_record(r, candles)
        enriched = dict(r)
        enriched["visual_score"] = score
        enriched["range_eq"] = round(ctx["eq"], 2)
        enriched["range_hi"] = round(ctx["hi"], 2)
        enriched["range_lo"] = round(ctx["lo"], 2)
        enriched["range_pct"] = round(ctx["range_pct"], 2)
        enriched["reasons"] = reasons
        if not predicate(enriched):
            continue
        rr = enriched["rr_liq"] if enriched["rr_liq"] is not None else base_study.RR_FIXED
        signals.append((enriched["idx"], enriched["dir"], enriched["stop"], rr))
        selected.append(enriched)

    trades = engine.simulate(candles, signals, base_study.SYMBOL, base_study.BASE_TF,
                             f"bta_visual_{name}", max_hold=MAX_HOLD)
    return selected, trades


def aggregate_selected(selected, trades):
    by_year = defaultdict(int)
    by_source = defaultdict(int)
    by_score = defaultdict(int)
    risks = []
    rrs = []
    for r in selected:
        by_year[r["year"]] += 1
        by_source[r["source_tf"]] += 1
        by_score[str(r["visual_score"])] += 1
        if r["risk_pct"] is not None:
            risks.append(r["risk_pct"])
        if r["rr_liq"] is not None:
            rrs.append(r["rr_liq"])
    return {
        "selected": len(selected),
        "executed_trades": len(trades),
        "by_year": dict(sorted(by_year.items())),
        "by_source": dict(sorted(by_source.items())),
        "by_score": dict(sorted(by_score.items(), key=lambda kv: int(kv[0]))),
        "median_risk_pct": round(statistics.median(risks), 3) if risks else None,
        "median_rr_liq": round(statistics.median(rrs), 3) if rrs else None,
        "trade_metrics": summarize(trades),
    }


def md_table(rows, headers):
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def write_report(out):
    rows = []
    for name, data in out["variants"].items():
        m = data["summary"]["trade_metrics"]
        rows.append({
            "variante": name,
            "seleccionados": data["summary"]["selected"],
            "trades": m["trades"],
            "WR": f'{m["win_rate"]}%',
            "expR": m["expectancy_R"],
            "PF": m["profit_factor"],
            "totalR": m["total_R"],
            "DD": m["max_drawdown_R"],
            "med risk%": data["summary"]["median_risk_pct"],
            "med RRliq": data["summary"]["median_rr_liq"],
        })

    examples = out["examples"]
    text = f"""# Backtest prototipo BTA visual

Fecha: 2026-07-01. Datos: {out["span"]["from"]} UTC a {out["span"]["to"]} UTC, {out["span"]["candles"]:,} velas BTCUSDT M15.

Este prototipo no replica el indicador del profe. Traduce lo observado en TradingView a filtros auditables:

- premium/discount de un rango operativo reciente;
- CDC dentro de {CDC_MAX_DELAY} velas;
- liquidez objetivo con R:R >= {RR_MIN};
- riesgo máximo {RISK_MAX_PCT}%;
- preferencia por POI HTF y sesiones líquidas;
- score visual 0-10.

## Resultados

{md_table(rows, ["variante", "seleccionados", "trades", "WR", "expR", "PF", "totalR", "DD", "med risk%", "med RRliq"])}

## Lectura

- El filtro `liq_rr2` aísla la parte "target de liquidez" que Nexux ya tenía.
- `cdc_liq` exige que el toque tenga confirmación de carácter; baja frecuencia.
- `range_cdc_liq` agrega la idea visual del profe: long en discount o short en premium de un rango reciente.
- `visual_score6` suma contexto completo. Si mejora PF/expectativa, es la línea de trabajo para `bta_visual_model`; si no mejora, la interpretación visual todavía está incompleta.

## Ejemplos score alto

```json
{json.dumps(examples, ensure_ascii=False, indent=2)}
```

## Próximo paso

Validar estos candidatos contra capturas del chart del profe. El modelo sólo queda aceptado si reproduce los casos visuales de junio 2026, mayo 2026 y noviembre 2025 sin sobreajustar.
"""
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    candles = base_study.load(base_study.BASE_TF)
    records = build_records(candles)

    variants = {
        "liq_rr2": lambda r: r["rr_liq"] is not None and r["rr_liq"] >= RR_MIN,
        "cdc_liq": lambda r: r["rr_liq"] is not None and r["rr_liq"] >= RR_MIN and
        r["cdc_within_window"],
        "range_cdc_liq": lambda r: r["rr_liq"] is not None and r["rr_liq"] >= RR_MIN and
        r["cdc_within_window"] and (
            (r["dir"] == "long" and r["entry_next_open"] <= r["range_eq"]) or
            (r["dir"] == "short" and r["entry_next_open"] >= r["range_eq"])
        ),
        "visual_score6": lambda r: r["visual_score"] >= 6 and
        r["rr_liq"] is not None and r["rr_liq"] >= RR_MIN,
        "visual_score7": lambda r: r["visual_score"] >= 7 and
        r["rr_liq"] is not None and r["rr_liq"] >= RR_MIN,
    }

    out = {
        "params": {
            "range_bars": RANGE_BARS,
            "rr_min": RR_MIN,
            "risk_max_pct": RISK_MAX_PCT,
            "cdc_max_delay": CDC_MAX_DELAY,
            "max_hold": MAX_HOLD,
        },
        "span": {
            "from": iso(candles[0]["t"]),
            "to": iso(candles[-1]["t"]),
            "candles": len(candles),
        },
        "touch_records": len(records),
        "variants": {},
        "examples": [],
    }

    all_selected = []
    for name, pred in variants.items():
        selected, trades = simulate_variant(candles, records, pred, name)
        out["variants"][name] = {
            "summary": aggregate_selected(selected, trades),
        }
        all_selected.extend(selected)

    best = sorted(all_selected, key=lambda r: (r["visual_score"], r["rr_liq"] or 0),
                  reverse=True)
    seen = set()
    examples = []
    for r in best:
        key = (r["time"], r["dir"], r["source_tf"])
        if key in seen:
            continue
        seen.add(key)
        examples.append({
            "time": r["time"],
            "dir": r["dir"],
            "source_tf": r["source_tf"],
            "session": r["session"],
            "score": r["visual_score"],
            "rr_liq": r["rr_liq"],
            "risk_pct": r["risk_pct"],
            "range": [r["range_lo"], r["range_eq"], r["range_hi"]],
            "reasons": r["reasons"],
        })
        if len(examples) >= 12:
            break
    out["examples"] = examples

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    write_report(out)
    print(f"JSON: {OUT_JSON}")
    print(f"MD:   {OUT_MD}")


if __name__ == "__main__":
    main()
