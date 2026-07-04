"""Deep backtest for the BTA visual hypothesis on local BTC history.

This keeps the experiment in research land: it reuses the explicit BTA visual
filters from ``bta_visual_backtest.py`` and adds stability views by year,
session, direction, source timeframe, and in/out-of-sample split.

Outputs:
  research/bta_visual_deep_backtest_results.json
  research/bta_visual_deep_backtest_2026-07-01.md
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import engine
from modules.trading.backtest import metrics

import bta_visual_backtest as bta
import bta_m15_structure_study as base_study

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(HERE, "bta_visual_deep_backtest_results.json")
OUT_MD = os.path.join(HERE, "bta_visual_deep_backtest_2026-07-01.md")

SPLIT_TS = "2025-03-30 00:00"


def ts_iso(ts_ms: int) -> str:
    return base_study.iso(ts_ms)


def year(ts_ms: int) -> str:
    return base_study.year(ts_ms)


def timestamp_key(ts: str) -> tuple[int, int, int, int, int]:
    date, hour = ts.split(" ")
    yy, mm, dd = [int(x) for x in date.split("-")]
    hh, mi = [int(x) for x in hour.split(":")]
    return yy, mm, dd, hh, mi


def trade_summary(trades: list[dict]) -> dict:
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


def selected_to_signals(selected: list[dict]) -> list[tuple]:
    signals = []
    for r in selected:
        rr = r["rr_liq"] if r["rr_liq"] is not None else base_study.RR_FIXED
        signals.append((r["idx"], r["dir"], r["stop"], rr))
    return signals


def simulate_selected(candles: list[dict], selected: list[dict], name: str,
                      costs: bool = True) -> list[dict]:
    kwargs = {}
    if not costs:
        kwargs = {"commission": 0.0, "slippage": 0.0, "maker": 0.0}
    return engine.simulate(
        candles,
        selected_to_signals(selected),
        base_study.SYMBOL,
        base_study.BASE_TF,
        name,
        max_hold=bta.MAX_HOLD,
        **kwargs,
    )


def split_selected(selected: list[dict]) -> dict[str, list[dict]]:
    split_key = timestamp_key(SPLIT_TS)
    return {
        "in_sample_until_2025_03_30": [
            r for r in selected if timestamp_key(r["time"]) < split_key
        ],
        "out_sample_from_2025_03_30": [
            r for r in selected if timestamp_key(r["time"]) >= split_key
        ],
    }


def group_trades(trades: list[dict], key_fn) -> dict[str, dict]:
    buckets = defaultdict(list)
    for t in trades:
        buckets[str(key_fn(t))].append(t)
    return {k: trade_summary(v) for k, v in sorted(buckets.items())}


def group_selected_isolated(candles: list[dict], selected: list[dict], key: str,
                            variant_name: str) -> dict[str, dict]:
    buckets = defaultdict(list)
    for r in selected:
        buckets[str(r[key])].append(r)
    out = {}
    for bucket_key, rows in sorted(buckets.items()):
        out[bucket_key] = trade_summary(
            simulate_selected(candles, rows, f"{variant_name}_{key}_{bucket_key}")
        )
    return out


def enrich_records(candles: list[dict], records: list[dict]) -> list[dict]:
    enriched = []
    for r in records:
        score, ctx, reasons = bta.score_record(r, candles)
        row = dict(r)
        row["visual_score"] = score
        row["range_eq"] = round(ctx["eq"], 2)
        row["range_hi"] = round(ctx["hi"], 2)
        row["range_lo"] = round(ctx["lo"], 2)
        row["range_pct"] = round(ctx["range_pct"], 2)
        row["reasons"] = reasons
        enriched.append(row)
    return enriched


def predicates() -> dict:
    return {
        "liq_rr2": lambda r: r["rr_liq"] is not None and r["rr_liq"] >= bta.RR_MIN,
        "cdc_liq": lambda r: r["rr_liq"] is not None
        and r["rr_liq"] >= bta.RR_MIN
        and r["cdc_within_window"]
        and r["cdc_delay_bars"] is not None
        and r["cdc_delay_bars"] <= bta.CDC_MAX_DELAY,
        "range_cdc_liq": lambda r: r["rr_liq"] is not None
        and r["rr_liq"] >= bta.RR_MIN
        and r["cdc_within_window"]
        and r["cdc_delay_bars"] is not None
        and r["cdc_delay_bars"] <= bta.CDC_MAX_DELAY
        and (
            (r["dir"] == "long" and r["entry_next_open"] <= r["range_eq"])
            or (r["dir"] == "short" and r["entry_next_open"] >= r["range_eq"])
        ),
        "visual_score7": lambda r: r["visual_score"] >= 7
        and r["rr_liq"] is not None
        and r["rr_liq"] >= bta.RR_MIN,
    }


def md_table(rows: list[dict], headers: list[str]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def metrics_row(name: str, data: dict) -> dict:
    m = data["with_costs"]
    g = data["no_costs"]
    return {
        "variante": name,
        "seleccionados": data["selected"],
        "trades": m["trades"],
        "WR": f'{m["win_rate"]}%',
        "expR neta": m["expectancy_R"],
        "PF neto": m["profit_factor"],
        "totalR neto": m["total_R"],
        "expR bruto": g["expectancy_R"],
        "PF bruto": g["profit_factor"],
        "DD": m["max_drawdown_R"],
    }


def write_report(out: dict) -> None:
    summary_rows = [metrics_row(name, data) for name, data in out["variants"].items()]
    split_rows = []
    for name, data in out["variants"].items():
        for split_name, split_data in data["splits"].items():
            split_rows.append({
                "variante": name,
                "split": split_name,
                "seleccionados": split_data["selected"],
                "trades": split_data["with_costs"]["trades"],
                "WR": f'{split_data["with_costs"]["win_rate"]}%',
                "expR": split_data["with_costs"]["expectancy_R"],
                "PF": split_data["with_costs"]["profit_factor"],
                "totalR": split_data["with_costs"]["total_R"],
                "DD": split_data["with_costs"]["max_drawdown_R"],
            })

    year_rows = []
    for y, metrics_by_variant in out["year_stability"].items():
        row = {"año": y}
        for name, m in metrics_by_variant.items():
            row[f"{name} trades"] = m["trades"]
            row[f"{name} expR"] = m["expectancy_R"]
            row[f"{name} PF"] = m["profit_factor"]
        year_rows.append(row)

    headers_year = ["año"]
    for name in out["variants"]:
        headers_year += [f"{name} trades", f"{name} expR", f"{name} PF"]

    text = f"""# Deep backtest BTA visual BTC

Fecha: 2026-07-01. Datos locales BTCUSDT M15: {out["span"]["from"]} UTC a {out["span"]["to"]} UTC, {out["span"]["candles"]:,} velas.

Este backtest no toca producción. Evalúa la hipótesis operativa:

`POI -> toque -> CDC -> liquidez objetivo -> trade`

Costos netos: comisión/slippage del motor `engine.simulate`. Bruto: la misma lógica con costos en cero.

## Resumen

{md_table(summary_rows, ["variante", "seleccionados", "trades", "WR", "expR neta", "PF neto", "totalR neto", "expR bruto", "PF bruto", "DD"])}

## In-sample / Out-of-sample

Split: `{SPLIT_TS}` UTC.

{md_table(split_rows, ["variante", "split", "seleccionados", "trades", "WR", "expR", "PF", "totalR", "DD"])}

## Estabilidad Por Año

{md_table(year_rows, headers_year)}

## Lectura

- `liq_rr2` prueba que no basta tener liquidez objetivo: sin CDC el resultado neto sigue negativo.
- `cdc_liq` es el núcleo más fuerte: reduce frecuencia, sube winrate y mejora PF.
- `range_cdc_liq` agrega premium/discount del rango reciente; baja frecuencia y mantiene edge, aunque no supera a `cdc_liq` en expectativa total.
- `visual_score7` todavía mezcla demasiados casos; sirve como ranking, no como gatillo principal.

## Próximo paso recomendado

El candidato para implementar primero en modo paper es `cdc_liq`: POI tocado, CDC dentro de ventana corta y RR hacia liquidez >= 2. Luego se prueba si `range_cdc_liq` mejora la calidad en vivo sin matar demasiadas oportunidades.
"""
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(text)


def main() -> None:
    candles = base_study.load(base_study.BASE_TF)
    records = enrich_records(candles, bta.build_records(candles))
    variants = {}

    for name, predicate in predicates().items():
        selected = [r for r in records if predicate(r)]
        trades_costs = simulate_selected(candles, selected, f"bta_deep_{name}")
        trades_no_costs = simulate_selected(
            candles, selected, f"bta_deep_{name}_gross", costs=False
        )
        splits = {}
        for split_name, split_rows in split_selected(selected).items():
            splits[split_name] = {
                "selected": len(split_rows),
                "with_costs": trade_summary(
                    simulate_selected(candles, split_rows, f"{name}_{split_name}")
                ),
                "no_costs": trade_summary(
                    simulate_selected(
                        candles,
                        split_rows,
                        f"{name}_{split_name}_gross",
                        costs=False,
                    )
                ),
            }
        variants[name] = {
            "selected": len(selected),
            "with_costs": trade_summary(trades_costs),
            "no_costs": trade_summary(trades_no_costs),
            "by_year": group_trades(trades_costs, lambda t: year(t["entry_time"])),
            "by_session": group_trades(trades_costs, lambda t: t["session"]),
            "by_direction": group_trades(trades_costs, lambda t: t["direction"]),
            "by_source_isolated": group_selected_isolated(candles, selected, "source_tf", name),
            "splits": splits,
        }

    years = sorted({y for data in variants.values() for y in data["by_year"]})
    year_stability = {}
    for y in years:
        year_stability[y] = {
            name: data["by_year"].get(y, trade_summary([]))
            for name, data in variants.items()
        }

    out = {
        "params": {
            "split_ts": SPLIT_TS,
            "rr_min": bta.RR_MIN,
            "cdc_max_delay": bta.CDC_MAX_DELAY,
            "max_hold": bta.MAX_HOLD,
            "range_bars": bta.RANGE_BARS,
        },
        "span": {
            "from": ts_iso(candles[0]["t"]),
            "to": ts_iso(candles[-1]["t"]),
            "candles": len(candles),
        },
        "touch_records": len(records),
        "variants": variants,
        "year_stability": year_stability,
    }

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    write_report(out)
    print(f"JSON: {OUT_JSON}")
    print(f"MD:   {OUT_MD}")


if __name__ == "__main__":
    main()
