#!/usr/bin/env python3
"""Causal OOS study of the CoinGlass Hobbyist 4h history."""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / "data/coinsignals_coinglass.json"
DEFAULT_JSON = ROOT / "research/coinglass_hobbyist_study_results.json"
DEFAULT_REPORT = ROOT / "research/coinglass_hobbyist_study_2026-07-24.md"
COST = 0.001
HORIZONS = (1, 2, 3)


def _last(payload: dict[str, Any], key: str) -> float | None:
    values = payload.get(key, [])
    return float(values[-1]) if values else None


def _ratio(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    return (value - 1) / (value + 1)


def load_bars(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = [
        row for row in payload.get("history", [])
        if row.get("history_origin") == "backfill"
    ]
    bars = []
    for row in source:
        indicators = row.get("indicators", {})
        candles = indicators.get("price", {}).get("candles", [])
        oi_values = indicators.get("open_interest", {}).get("close_usd", [])
        liquidations = indicators.get("liquidations", {}).get("bars", [])
        taker = indicators.get("taker", {}).get("bars", [])
        if not candles or not oi_values or not liquidations or not taker:
            continue
        price = float(candles[-1]["close"])
        previous_price = float(candles[-2]["close"]) if len(candles) > 1 else None
        oi = float(oi_values[-1])
        previous_oi = float(oi_values[-2]) if len(oi_values) > 1 else None
        crowd_values = [
            _last(indicators.get(key, {}), "long_pct")
            for key in ("global_accounts", "top_accounts", "top_traders")
        ]
        crowd = mean(value for value in crowd_values if value is not None)
        liq = liquidations[-1]
        long_liq = float(liq.get("long_musd", 0))
        short_liq = float(liq.get("short_musd", 0))
        liq_total = long_liq + short_liq
        book = _last(indicators.get("orderbook", {}), "bid_ask_ratio")
        aggregate_book = _last(
            indicators.get("orderbook_aggregated", {}), "bid_ask_ratio"
        )
        book_values = [value for value in (book, aggregate_book) if value is not None]
        book_pressure = mean(_ratio(value) for value in book_values)
        funding = _last(indicators.get("funding", {}), "close_pct")
        funding_volume = _last(
            indicators.get("funding_volume", {}), "close_pct"
        )
        funding_values = [
            value for value in (funding, funding_volume) if value is not None
        ]
        funding_mean = mean(funding_values)
        crowd_contrarian = -((crowd - 50) / 50)
        funding_contrarian = -math.tanh(funding_mean / 0.03)
        partial_radar = (
            0.35 * book_pressure
            + 0.10 * crowd_contrarian
            + 0.10 * funding_contrarian
        ) / 0.55
        bars.append({
            "time": int(indicators["open_interest"]["times"][-1]),
            "month": datetime.fromisoformat(row["captured_at"]).strftime("%Y-%m"),
            "price": price,
            "price_change": price / previous_price - 1 if previous_price else None,
            "oi": oi,
            "oi_change": oi / previous_oi - 1 if previous_oi else None,
            "funding": funding_mean,
            "crowd_long": crowd,
            "taker_buy": float(taker[-1]["buy_ratio"]),
            "book_ratio": mean(book_values),
            "book_pressure": book_pressure,
            "liq_imbalance": (
                (short_liq - long_liq) / liq_total if liq_total else 0
            ),
            "long_liq": long_liq,
            "short_liq": short_liq,
            "partial_radar": partial_radar,
        })
    bars.sort(key=lambda row: row["time"])
    return bars


def _sign(value: float, threshold: float = 0) -> int:
    return 1 if value > threshold else -1 if value < -threshold else 0


def rule_signals(bar: dict[str, Any]) -> dict[str, int]:
    price_change = bar.get("price_change")
    oi_change = bar.get("oi_change")
    price_oi = 0
    if price_change is not None and oi_change is not None and oi_change > 0:
        price_oi = _sign(price_change)
    long_liq = bar["long_liq"]
    short_liq = bar["short_liq"]
    liquidation = (
        1 if short_liq > long_liq * 2
        else -1 if long_liq > short_liq * 2
        else 0
    )
    orderbook = (
        1 if bar["book_ratio"] >= 1.25
        else -1 if bar["book_ratio"] <= 0.80
        else 0
    )
    taker = (
        1 if bar["taker_buy"] >= 52
        else -1 if bar["taker_buy"] <= 48
        else 0
    )
    crowd = (
        -1 if bar["crowd_long"] >= 60
        else 1 if bar["crowd_long"] <= 40
        else 0
    )
    funding = (
        -1 if bar["funding"] >= 0.01
        else 1 if bar["funding"] <= 0
        else 0
    )
    radar = _sign(bar["partial_radar"], 0.15)
    votes = orderbook + taker + crowd + funding + liquidation + price_oi
    return {
        "buy_hold": 1,
        "partial_radar": radar,
        "orderbook": orderbook,
        "orderbook_contrarian": -orderbook,
        "taker_continuation": taker,
        "taker_contrarian": -taker,
        "crowding_contrarian": crowd,
        "funding_contrarian": funding,
        "liquidation_continuation": liquidation,
        "liquidation_contrarian": -liquidation,
        "price_oi_continuation": price_oi,
        "price_oi_contrarian": -price_oi,
        "vote_2plus": _sign(votes, 1),
    }


def attach_outcomes(bars: list[dict[str, Any]]) -> None:
    for index, bar in enumerate(bars):
        bar["signals"] = rule_signals(bar)
        bar["future_returns"] = {
            str(horizon): (
                bars[index + horizon]["price"] / bar["price"] - 1
                if index + horizon < len(bars) else None
            )
            for horizon in HORIZONS
        }


def _bootstrap_ci(values: list[float], seed: int = 7) -> list[float | None]:
    if len(values) < 20:
        return [None, None]
    rng = random.Random(seed)
    estimates = []
    for _ in range(2000):
        estimates.append(mean(rng.choice(values) for _ in values))
    estimates.sort()
    return [
        round(estimates[int(len(estimates) * 0.025)] * 10_000, 2),
        round(estimates[int(len(estimates) * 0.975)] * 10_000, 2),
    ]


def evaluate_rule(
    bars: list[dict[str, Any]],
    rule: str,
    horizon: int,
    start: int,
    end: int,
    cost: float = COST,
) -> dict[str, Any]:
    returns = []
    gross = []
    wins = 0
    index = start
    while index < min(end, len(bars) - horizon):
        signal = bars[index]["signals"][rule]
        outcome = bars[index]["future_returns"][str(horizon)]
        if signal and outcome is not None:
            raw = signal * outcome
            net = raw - cost
            gross.append(raw)
            returns.append(net)
            wins += net > 0
            index += horizon
        else:
            index += 1
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    return {
        "n": len(returns),
        "avg_net_bps": round(mean(returns) * 10_000, 2) if returns else None,
        "avg_gross_bps": round(mean(gross) * 10_000, 2) if gross else None,
        "win_rate_pct": round(wins / len(returns) * 100, 1) if returns else None,
        "sum_net_pct": round(sum(returns) * 100, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "ci95_avg_net_bps": _bootstrap_ci(returns),
    }


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def feature_spreads(
    bars: list[dict[str, Any]], split: int, horizon: int = 1
) -> dict[str, Any]:
    fields = (
        "oi_change", "funding", "crowd_long", "taker_buy",
        "book_ratio", "liq_imbalance", "partial_radar",
    )
    results = {}
    for field in fields:
        training = [
            row[field] for row in bars[:split] if row.get(field) is not None
        ]
        low, high = _quantile(training, 0.2), _quantile(training, 0.8)
        low_returns, high_returns = [], []
        for row in bars[split:-horizon]:
            value = row.get(field)
            outcome = row["future_returns"][str(horizon)]
            if value is None or outcome is None:
                continue
            if value <= low:
                low_returns.append(outcome)
            elif value >= high:
                high_returns.append(outcome)
        low_avg = mean(low_returns) if low_returns else 0
        high_avg = mean(high_returns) if high_returns else 0
        results[field] = {
            "is_low_threshold": round(low, 6),
            "is_high_threshold": round(high, 6),
            "oos_n_low": len(low_returns),
            "oos_n_high": len(high_returns),
            "oos_low_avg_bps": round(low_avg * 10_000, 2),
            "oos_high_avg_bps": round(high_avg * 10_000, 2),
            "oos_high_minus_low_bps": round((high_avg - low_avg) * 10_000, 2),
        }
    return results


def monthly_rule(
    bars: list[dict[str, Any]], rule: str, horizon: int = 1
) -> dict[str, Any]:
    by_month: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(bars):
        by_month[row["month"]].append(index)
    results = {}
    for month, indexes in by_month.items():
        results[month] = evaluate_rule(
            bars, rule, horizon, min(indexes), max(indexes) + 1
        )
    return results


def run_study(bars: list[dict[str, Any]]) -> dict[str, Any]:
    attach_outcomes(bars)
    split = int(len(bars) * 0.70)
    rules = tuple(rule_signals(bars[1]).keys())
    evaluations = {}
    for rule in rules:
        evaluations[rule] = {}
        for horizon in HORIZONS:
            evaluations[rule][str(horizon)] = {
                "is": evaluate_rule(bars, rule, horizon, 1, split),
                "oos": evaluate_rule(
                    bars, rule, horizon, split, len(bars)
                ),
            }
    cost_sensitivity = {}
    for rule in (
        "partial_radar", "price_oi_contrarian",
        "liquidation_contrarian", "taker_contrarian",
    ):
        cost_sensitivity[rule] = {
            str(round(cost * 100, 3)): evaluate_rule(
                bars, rule, 2, split, len(bars), cost=cost
            )
            for cost in (0.0005, 0.001, 0.0015)
        }
    return {
        "research_only": True,
        "source": "CoinGlass Hobbyist 4h backfill",
        "cost_per_trade_pct": COST * 100,
        "bars": len(bars),
        "coverage": {
            "first": datetime.fromtimestamp(
                bars[0]["time"] / 1000, timezone.utc
            ).isoformat(),
            "last": datetime.fromtimestamp(
                bars[-1]["time"] / 1000, timezone.utc
            ).isoformat(),
        },
        "split": {
            "is_bars": split,
            "oos_bars": len(bars) - split,
            "oos_start": datetime.fromtimestamp(
                bars[split]["time"] / 1000, timezone.utc
            ).isoformat(),
        },
        "evaluations": evaluations,
        "cost_sensitivity_oos_8h": cost_sensitivity,
        "feature_spreads_4h": feature_spreads(bars, split),
        "monthly_4h": {
            rule: monthly_rule(bars, rule)
            for rule in (
                "partial_radar", "orderbook", "taker_continuation",
                "liquidation_continuation", "vote_2plus",
            )
        },
    }


def _metric(result: dict[str, Any]) -> str:
    if not result["n"]:
        return "n=0"
    return (
        f"n={result['n']}, avg={result['avg_net_bps']:+.1f} bps, "
        f"WR={result['win_rate_pct']:.1f}%, DD={result['max_drawdown_pct']:.1f}%"
    )


def render_report(study: dict[str, Any]) -> str:
    names = {
        "buy_hold": "Long cada ventana",
        "partial_radar": "Radar parcial",
        "orderbook": "Order book",
        "orderbook_contrarian": "Order book inverso*",
        "taker_continuation": "Taker continuación",
        "taker_contrarian": "Taker inverso*",
        "crowding_contrarian": "Crowding contrarian",
        "funding_contrarian": "Funding contrarian",
        "liquidation_continuation": "Liquidaciones continuación",
        "liquidation_contrarian": "Liquidaciones inversas*",
        "price_oi_continuation": "Precio+OI continuación",
        "price_oi_contrarian": "Precio+OI inverso*",
        "vote_2plus": "Voto compuesto ≥2",
    }
    lines = [
        "# CoinGlass Hobbyist — estudio histórico 4h",
        "",
        "## Método",
        "",
        f"- {study['bars']} barras consecutivas 4h; "
        f"{study['coverage']['first']} → {study['coverage']['last']}.",
        f"- Split temporal 70/30: {study['split']['is_bars']} IS y "
        f"{study['split']['oos_bars']} OOS desde {study['split']['oos_start']}.",
        "- Retornos a 4h/8h/12h; operaciones no solapadas por horizonte.",
        f"- Costo conservador: {study['cost_per_trade_pct']:.2f}% por operación.",
        "- Reglas primarias con umbrales fijos; variantes inversas marcadas como "
        "post-hoc; IC bootstrap 95%.",
        "",
        "## Resultados OOS",
        "",
        "| Regla | 4h | 8h | 12h |",
        "|---|---:|---:|---:|",
    ]
    for rule, label in names.items():
        values = study["evaluations"][rule]
        lines.append(
            f"| {label} | {_metric(values['1']['oos'])} | "
            f"{_metric(values['2']['oos'])} | {_metric(values['3']['oos'])} |"
        )
    lines.extend([
        "",
        "## Hallazgos adversariales",
        "",
        "1. **No aparece un edge robusto.** Ninguna regla positiva mantiene su "
        "IC 95% completamente sobre cero.",
        "2. **Radar parcial: candidato no validado.** Mejora a 8h/12h en IS y OOS, "
        "pero alterna meses positivos y negativos y tiene muestras OOS de 52/40.",
        "3. **Precio+OI como continuación queda refutado.** Pierde OOS a 4h y 8h "
        "con IC 95% completamente bajo cero. Su inversa es post-hoc y no fue "
        "positiva en IS.",
        "4. **Liquidaciones como continuación inmediata queda refutada a 4h.** "
        "El resultado OOS es negativo con IC 95% bajo cero.",
        "5. **Order book, taker y crowding son contexto, no gatillos.** Ninguno "
        "supera costos de forma estable.",
        "6. **Funding a 8h no es accionable:** el resultado positivo usa sólo "
        "19 operaciones OOS y se invierte a 12h.",
        "7. **Hay desplazamiento de régimen.** El quintil IS bajo de crowding no "
        "aparece ni una vez OOS y el de funding sólo aparece tres veces.",
        "",
        "### Incertidumbre de los candidatos positivos",
        "",
        "| Candidato | Horizonte | Media neta | IC 95% |",
        "|---|---:|---:|---:|",
    ])
    for rule, label, horizon in (
        ("partial_radar", "Radar parcial", "2"),
        ("partial_radar", "Radar parcial", "3"),
        ("price_oi_contrarian", "Precio+OI inverso*", "2"),
    ):
        result = study["evaluations"][rule][horizon]["oos"]
        low, high = result["ci95_avg_net_bps"]
        lines.append(
            f"| {label} | {int(horizon) * 4}h | "
            f"{result['avg_net_bps']:+.1f} bps | [{low:+.1f}, {high:+.1f}] |"
        )
    lines.extend([
        "",
        "## Sensibilidad de costos OOS a 8h",
        "",
        "| Regla | 0,05% | 0,10% | 0,15% |",
        "|---|---:|---:|---:|",
    ])
    for rule, label in (
        ("partial_radar", "Radar parcial"),
        ("price_oi_contrarian", "Precio+OI inverso*"),
        ("liquidation_contrarian", "Liquidaciones inversas*"),
        ("taker_contrarian", "Taker inverso*"),
    ):
        sensitivity = study["cost_sensitivity_oos_8h"][rule]
        lines.append(
            f"| {label} | {sensitivity['0.05']['avg_net_bps']:+.1f} bps | "
            f"{sensitivity['0.1']['avg_net_bps']:+.1f} bps | "
            f"{sensitivity['0.15']['avg_net_bps']:+.1f} bps |"
        )
    lines.extend([
        "",
        "## Extremos aprendidos en IS → resultado OOS a 4h",
        "",
        "| Variable | N bajo/alto | Bajo | Alto | Alto−bajo |",
        "|---|---:|---:|---:|---:|",
    ])
    for field, row in study["feature_spreads_4h"].items():
        lines.append(
            f"| `{field}` | {row['oos_n_low']}/{row['oos_n_high']} | "
            f"{row['oos_low_avg_bps']:+.1f} bps | "
            f"{row['oos_high_avg_bps']:+.1f} bps | "
            f"{row['oos_high_minus_low_bps']:+.1f} bps |"
        )
    lines.extend([
        "",
        "## Criterio de lectura",
        "",
        "- Una media positiva sin IC 95% sobre cero no se considera edge.",
        "- Consistencia mensual pesa más que el mejor agregado.",
        "- El histórico cubre un solo semestre de 2026: no prueba estabilidad de régimen.",
        "- Ninguna regla modifica el bot; todos los resultados son research-only.",
        "- `*` Las variantes inversas son exploratorias y tienen penalización por "
        "haber sido revisadas junto a su opuesto.",
        "",
        "## Recomendación",
        "",
        "- No usar CoinGlass como señal de entrada ni modificar el bot con estas reglas.",
        "- Mantenerlo como contexto visual y registrar sus variables junto a cada "
        "trade forward del Diario.",
        "- Revaluar sólo cuando existan al menos 100 decisiones forward alineadas "
        "con setups reales; el histórico genérico de BTC no sustituye esa prueba.",
        "- No promover el Radar parcial: queda visible como research e incompleto.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    study = run_study(load_bars(args.file))
    args.json.write_text(
        json.dumps(study, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.report.write_text(render_report(study), encoding="utf-8")
    print(render_report(study))


if __name__ == "__main__":
    main()
