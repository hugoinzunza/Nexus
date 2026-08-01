"""Research-only paired study of narrower stops under explicit trading costs.

This module intentionally does not import or call bot/trading execution code.
It consumes the already causal setup export and immutable OHLC datasets, keeps
the exported target fixed in price, and varies only the original stop distance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_SPEC = HERE / "specs" / "v1" / "HYP-COST-001.frozen.json"
DEFAULT_REPORTS = HERE / "reports"


class StudyError(ValueError):
    pass


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_frozen_spec(path: Path = DEFAULT_SPEC) -> dict[str, Any]:
    spec = _read_json(path)
    if spec.get("hypothesis_id") != "HYP-COST-001":
        raise StudyError("unexpected hypothesis_id")
    if spec.get("frozen") is not True or spec.get("research_only") is not True:
        raise StudyError("the study requires a frozen research-only spec")
    multipliers = [float(value) for value in spec["design"]["stop_multipliers"]]
    if multipliers != [1.0, 0.75, 0.5, 0.35]:
        raise StudyError("frozen stop multipliers changed")
    if spec["design"].get("target_policy") != "original_fixed_price":
        raise StudyError("target must remain fixed in price")
    if spec["statistics"].get("bootstrap_unit") != "calendar_month":
        raise StudyError("calendar-month block bootstrap is mandatory")
    if spec["statistics"].get("multiple_testing") != "holm":
        raise StudyError("Holm correction is mandatory")
    if spec["governance"].get("automatic_promotion") is not False:
        raise StudyError("automatic promotion must remain disabled")
    return spec


def _validate_setup(row: dict[str, Any], candles: list[dict[str, Any]]) -> None:
    required = {
        "setup_id", "research_export_version", "pair", "sel_tf", "dir", "entry", "sl",
        "original_tp", "original_tp_source", "decision_index", "decision_timestamp",
        "activation_index", "activation_timestamp", "max_forward_bars",
    }
    missing = required - row.keys()
    if missing:
        raise StudyError(f"setup {row.get('setup_id')} missing {sorted(missing)}")
    if row["research_export_version"] != "setup-backtest-research-v3":
        raise StudyError("only setup-backtest-research-v3 is accepted")
    decision = row["decision_index"]
    if not isinstance(decision, int) or not 0 <= decision < len(candles):
        raise StudyError(f"invalid decision index for {row['setup_id']}")
    if candles[decision]["t"] != row["decision_timestamp"]:
        raise StudyError(f"decision timestamp mismatch for {row['setup_id']}")
    source = row["original_tp_source"]
    if source.get("confirm_t") is None or source["confirm_t"] > row["decision_timestamp"]:
        raise StudyError(f"future target confirmation for {row['setup_id']}")
    if source.get("source_t") is None or source["source_t"] > row["decision_timestamp"]:
        raise StudyError(f"future target source for {row['setup_id']}")
    tolerance = max(1e-9, abs(float(row["original_tp"])) * 1e-9)
    if abs(float(source.get("price", 0.0)) - float(row["original_tp"])) > tolerance:
        raise StudyError(f"target/source price mismatch for {row['setup_id']}")
    activation = row["activation_index"]
    if activation is not None:
        if not isinstance(activation, int) or not decision <= activation < len(candles):
            raise StudyError(f"invalid activation index for {row['setup_id']}")
        if candles[activation]["t"] != row["activation_timestamp"]:
            raise StudyError(f"activation timestamp mismatch for {row['setup_id']}")


def load_inputs(spec: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]], list[dict[str, Any]]]:
    dataset = spec["dataset"]
    setup_path = ROOT / dataset["setup_export"]
    setups = _read_json(setup_path)
    pairs = set(dataset["pairs"])
    timeframes = set(dataset["timeframes"])
    candles: dict[tuple[str, str], list[dict[str, Any]]] = {}
    files = [setup_path]
    for pair in dataset["pairs"]:
        for timeframe in dataset["timeframes"]:
            path = ROOT / dataset["candle_pattern"].format(pair=pair, timeframe=timeframe)
            rows = _read_json(path)
            if any(rows[i]["t"] >= rows[i + 1]["t"] for i in range(len(rows) - 1)):
                raise StudyError(f"candles are not strictly ordered: {path}")
            candles[(pair, timeframe)] = rows
            files.append(path)
    selected = [row for row in setups if row["pair"] in pairs and row["sel_tf"] in timeframes]
    if len({row["setup_id"] for row in selected}) != len(selected):
        raise StudyError("duplicate setup_id in selected universe")
    for row in selected:
        _validate_setup(row, candles[(row["pair"], row["sel_tf"])])
    manifest = [
        {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path), "bytes": path.stat().st_size}
        for path in sorted(files)
    ]
    return selected, candles, manifest


def stop_price(setup: dict[str, Any], multiplier: float) -> float:
    entry = float(setup["entry"])
    original_distance = abs(entry - float(setup["sl"]))
    return entry - original_distance * multiplier if setup["dir"] == "long" else entry + original_distance * multiplier


def _observed_rate(setup: dict[str, Any], names: list[str]) -> tuple[float | None, str | None]:
    for name in names:
        value = setup.get(name)
        if value is not None:
            return float(value), name
    return None, None


def friction_components(setup: dict[str, Any], scenario: dict[str, Any], exit_liquidity: str) -> dict[str, Any]:
    """Resolve observed friction when present, otherwise the frozen scenario.

    Every supported export field is a decimal notional rate, never a percentage.
    The current v3 export has none of these fields, so runs are expected to state
    ``declared_scenario`` rather than imply that friction was observed.
    """
    spread, spread_field = _observed_rate(setup, ["observed_roundtrip_spread_rate"])
    entry_slippage, entry_field = _observed_rate(setup, ["observed_entry_slippage_rate"])
    exit_slippage, exit_field = _observed_rate(
        setup, [f"observed_{exit_liquidity}_exit_slippage_rate", "observed_exit_slippage_rate"]
    )
    observed_complete = all(x is not None for x in (spread, entry_slippage, exit_slippage))
    if not observed_complete:
        spread = float(scenario["roundtrip_spread_rate"])
        entry_slippage = float(scenario["entry_slippage_rate"])
        exit_slippage = float(scenario[f"exit_{exit_liquidity}_slippage_rate"])
    return {
        "entry_fee_rate": float(scenario["entry_maker_fee_rate"]),
        "exit_fee_rate": float(scenario[f"exit_{exit_liquidity}_fee_rate"]),
        "roundtrip_spread_rate": spread,
        "entry_slippage_rate": entry_slippage,
        "exit_slippage_rate": exit_slippage,
        "provenance": "observed" if observed_complete else "declared_scenario",
        "observed_fields": [x for x in (spread_field, entry_field, exit_field) if x],
    }


def _hit_stop(bar: dict[str, Any], stop: float, long: bool) -> bool:
    return float(bar["l"]) <= stop if long else float(bar["h"]) >= stop


def _hit_target(bar: dict[str, Any], target: float, long: bool) -> bool:
    return float(bar["h"]) >= target if long else float(bar["l"]) <= target


def simulate_stop(setup: dict[str, Any], candles: list[dict[str, Any]], multiplier: float,
                  scenario: dict[str, Any]) -> dict[str, Any]:
    base = {
        "setup_id": setup["setup_id"], "pair": setup["pair"], "timeframe": setup["sel_tf"],
        "activation_timestamp": setup.get("activation_timestamp"), "stop_multiplier": multiplier,
        "target_price": float(setup["original_tp"]),
    }
    activation = setup.get("activation_index")
    if activation is None:
        return {**base, "status": "discarded", "discarded_reason": "not_activated", "net_r": None}
    entry = float(setup["entry"])
    stop = stop_price(setup, multiplier)
    risk = abs(entry - stop)
    if risk <= 0 or activation < 0 or activation >= len(candles):
        return {**base, "status": "discarded", "discarded_reason": "invalid_risk_or_activation", "net_r": None}
    long = setup["dir"] == "long"
    target = float(setup["original_tp"])
    max_end = min(len(candles) - 1, int(setup["decision_index"]) + int(setup["max_forward_bars"]))
    status, end, exit_price = "timeout", max(activation, max_end), None

    # The activation bar may stop the setup but can never pay its target.
    if _hit_stop(candles[activation], stop, long):
        status, end, exit_price = "sl", activation, stop
    else:
        for index in range(activation + 1, max_end + 1):
            bar = candles[index]
            # Conservative OHLC ordering: adverse stop always wins ties.
            if _hit_stop(bar, stop, long):
                status, end, exit_price = "sl", index, stop
                break
            if _hit_target(bar, target, long):
                status, end, exit_price = "tp", index, target
                break
    if exit_price is None:
        exit_price = float(candles[end]["c"])
    gross_r = ((exit_price - entry) / risk) if long else ((entry - exit_price) / risk)
    exit_liquidity = "maker" if status == "tp" else "taker"
    costs = friction_components(setup, scenario, exit_liquidity)
    # Exit fee scales with exit notional; spread/slippage are frozen round-trip
    # rates relative to entry notional, matching the exported fixed-entry model.
    fee_rate = costs["entry_fee_rate"] + costs["exit_fee_rate"] * (exit_price / entry)
    friction_rate = costs["roundtrip_spread_rate"] + costs["entry_slippage_rate"] + costs["exit_slippage_rate"]
    total_cost_rate = fee_rate + friction_rate
    cost_r = total_cost_rate / (risk / entry)
    return {
        **base,
        "status": status,
        "discarded_reason": None,
        "resolution_timestamp": int(candles[end]["t"]),
        "entry": entry,
        "original_stop": float(setup["sl"]),
        "tested_stop": stop,
        "risk_price": risk,
        "gross_r": gross_r,
        "cost_r": cost_r,
        "net_r": gross_r - cost_r,
        "exit_price": exit_price,
        "exit_liquidity": exit_liquidity,
        "cost_components": costs,
        "total_cost_rate": total_cost_rate,
    }


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    used = sorted((row for row in rows if row.get("net_r") is not None), key=lambda row: (row["activation_timestamp"], row["setup_id"]))
    values = [float(row["net_r"]) for row in used]
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    provenance = defaultdict(int)
    statuses = defaultdict(int)
    for row in used:
        provenance[row["cost_components"]["provenance"]] += 1
        statuses[row["status"]] += 1
    return {
        "n": len(used),
        "discarded": len(rows) - len(used),
        "avg_net_r": statistics.fmean(values) if values else None,
        "profit_factor_net": gains / losses if losses else None,
        "win_rate_net": sum(value > 0 for value in values) / len(values) if values else None,
        "max_drawdown_r": drawdown,
        "mean_cost_r": statistics.fmean(float(row["cost_r"]) for row in used) if used else None,
        "cost_provenance": dict(sorted(provenance.items())),
        "exit_status_counts": dict(sorted(statuses.items())),
    }


def descriptive_strata(candidate: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> dict[str, Any]:
    """Diagnostics only; strata cannot select or promote a stop multiplier."""
    base_by_id = {row["setup_id"]: row for row in baseline if row.get("net_r") is not None}
    output: dict[str, Any] = {}
    for field in ("pair", "timeframe"):
        values = sorted({row[field] for row in candidate})
        output[f"by_{field}"] = {}
        for value in values:
            rows = [row for row in candidate if row[field] == value and row.get("net_r") is not None]
            deltas = [
                float(row["net_r"]) - float(base_by_id[row["setup_id"]]["net_r"])
                for row in rows if row["setup_id"] in base_by_id
            ]
            output[f"by_{field}"][value] = {
                "n": len(deltas),
                "paired_avg_net_r_delta": statistics.fmean(deltas) if deltas else None,
                "candidate_metrics": metrics(rows),
            }
    return output


def _month(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).strftime("%Y-%m")


def paired_month_bootstrap(candidate: list[dict[str, Any]], baseline: list[dict[str, Any]], *, seed: int,
                           iterations: int) -> dict[str, Any]:
    a = {row["setup_id"]: row for row in candidate if row.get("net_r") is not None}
    b = {row["setup_id"]: row for row in baseline if row.get("net_r") is not None}
    if a.keys() != b.keys():
        return {"status": "blocked_pairing_mismatch", "n_candidate": len(a), "n_baseline": len(b)}
    blocks: dict[str, list[float]] = defaultdict(list)
    for setup_id in sorted(a):
        blocks[_month(int(a[setup_id]["activation_timestamp"]))].append(float(a[setup_id]["net_r"]) - float(b[setup_id]["net_r"]))
    months = sorted(blocks)
    if len(months) < 2:
        return {"status": "blocked_insufficient_months", "n_paired": len(a), "months": len(months)}
    observed = statistics.fmean(value for values in blocks.values() for value in values)
    rng = random.Random(seed)
    draws = []
    for _ in range(iterations):
        sample = []
        for _ in months:
            sample.extend(blocks[months[rng.randrange(len(months))]])
        draws.append(statistics.fmean(sample))
    draws.sort()
    centered = [value - observed for value in draws]
    p_value = (sum(abs(value) >= abs(observed) for value in centered) + 1) / (iterations + 1)
    return {
        "status": "computed", "n_paired": len(a), "months": len(months),
        "mean_difference_net_r": observed,
        "ci95": [draws[int(0.025 * (iterations - 1))], draws[int(0.975 * (iterations - 1))]],
        "p_two_sided_centered_block_bootstrap": p_value,
    }


def holm(rows: list[dict[str, Any]], alpha: float) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (row["p"], row["id"]))
    keep_rejecting = True
    result = []
    count = len(ordered)
    for rank, row in enumerate(ordered, 1):
        threshold = alpha / (count - rank + 1)
        rejected = keep_rejecting and row["p"] <= threshold
        if not rejected:
            keep_rejecting = False
        result.append({**row, "rank": rank, "holm_threshold": threshold, "reject_null": rejected})
    return result


def run(spec_path: Path = DEFAULT_SPEC, report_dir: Path = DEFAULT_REPORTS) -> tuple[Path, Path]:
    spec = load_frozen_spec(spec_path)
    setups, candles, datasets = load_inputs(spec)
    variants: dict[tuple[str, float], list[dict[str, Any]]] = {}
    for scenario in spec["costs"]["scenarios"]:
        for multiplier in spec["design"]["stop_multipliers"]:
            variants[(scenario["id"], float(multiplier))] = [
                simulate_stop(setup, candles[(setup["pair"], setup["sel_tf"])], float(multiplier), scenario)
                for setup in setups
            ]
    aggregate = {
        f"{scenario['id']}:{multiplier:g}": metrics(variants[(scenario["id"], float(multiplier))])
        for scenario in spec["costs"]["scenarios"]
        for multiplier in spec["design"]["stop_multipliers"]
    }
    comparisons: dict[str, Any] = {}
    primary = spec["statistics"]["primary_cost_scenario"]
    iterations = int(spec["statistics"]["bootstrap_iterations"])
    family = []
    for scenario in spec["costs"]["scenarios"]:
        baseline = variants[(scenario["id"], 1.0)]
        for multiplier in spec["design"]["stop_multipliers"][1:]:
            key = f"{scenario['id']}:{multiplier:g}_vs_1"
            comparison = paired_month_bootstrap(
                variants[(scenario["id"], float(multiplier))], baseline,
                seed=int(spec["seed"]) + round(float(multiplier) * 1000), iterations=iterations,
            )
            comparisons[key] = comparison
            if scenario["id"] == primary and comparison["status"] == "computed":
                family.append({"id": key, "p": comparison["p_two_sided_centered_block_bootstrap"]})
    corrected = holm(family, float(spec["statistics"]["alpha"]))
    baseline_primary = variants[(primary, 1.0)]
    stratified = {
        f"{multiplier:g}_vs_1": descriptive_strata(
            variants[(primary, float(multiplier))], baseline_primary,
        )
        for multiplier in spec["design"]["stop_multipliers"][1:]
    }
    generated_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stem = f"HYP-COST-001-{generated_at}"
    summary = {
        "schema_version": 1,
        "research_only": True,
        "notice": "Research only - No signal - No bot",
        "hypothesis_id": "HYP-COST-001",
        "spec_sha256": _sha256(spec_path),
        "code_sha256": _sha256(Path(__file__)),
        "datasets": datasets,
        "selected_setups": len(setups),
        "target_policy": "original target fixed in price",
        "aggregate_metrics": aggregate,
        "paired_month_bootstrap": comparisons,
        "holm_primary_family": corrected,
        "descriptive_strata_primary_scenario": stratified,
        "inferential_scope": {
            "primary_cost_scenario": primary,
            "sensitivity_scenarios_are_not_independent_tests": True,
            "iid_assumption": False,
            "automatic_winner_selection": False,
            "promotion": False,
        },
        "limitations": [
            "The export contains no observed spread or slippage fields; declared scenarios are used and labeled.",
            "Calendar-month blocks preserve temporal clustering but do not model simultaneous account heat.",
            "Cross-pair dependence and overlapping trades remain present inside sampled months.",
            "A tighter stop changes activation-bar survival and target RR mechanically; this is a paired policy study, not a causal market experiment.",
            "Keeping the original target fixed means the study estimates the joint effect of a tighter stop and mechanically larger target R, not a pure transaction-cost effect.",
        ],
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / f"{stem}.summary.json"
    markdown_path = report_dir / f"{stem}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# HYP-COST-001 - Stops mas estrechos con costos explicitos",
        "", "**Research only - No signal - No bot**", "",
        f"Setups seleccionados: **{len(setups):,}**. Target original fijo en precio.",
        "El export no contiene spread/slippage observados; se usan escenarios declarados y etiquetados.",
        "", "## Resultados agregados", "",
        "| Escenario | Stop | n | avgR neto | PF neto | DD (R) | costo medio (R) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario in spec["costs"]["scenarios"]:
        for multiplier in spec["design"]["stop_multipliers"]:
            value = aggregate[f"{scenario['id']}:{multiplier:g}"]
            lines.append(
                f"| {scenario['id']} | {multiplier:g} | {value['n']} | {value['avg_net_r']:.4f} | "
                f"{value['profit_factor_net']:.3f} | {value['max_drawdown_r']:.2f} | {value['mean_cost_r']:.4f} |"
            )
    lines.extend(["", "## Comparaciones primarias pareadas", ""])
    by_id = {row["id"]: row for row in corrected}
    for multiplier in spec["design"]["stop_multipliers"][1:]:
        key = f"{primary}:{multiplier:g}_vs_1"
        value = comparisons[key]
        correction = by_id[key]
        lines.append(
            f"- `{multiplier:g} vs 1.0`: delta avgR {value['mean_difference_net_r']:+.4f}, "
            f"IC95 [{value['ci95'][0]:+.4f}, {value['ci95'][1]:+.4f}], "
            f"p={value['p_two_sided_centered_block_bootstrap']:.4f}, Holm reject={correction['reject_null']}."
        )
    lines.extend([
        "", "## Guardrails", "",
        "- Bootstrap por mes calendario; no se asume IID.",
        "- Holm se aplica una vez a las tres comparaciones del escenario primario.",
        "- Los escenarios adicionales son sensibilidad, no replicas independientes.",
        "- No existe seleccion automatica ni promocion a bot, Testnet o Live.",
        "- Los cortes por par y timeframe se guardan como diagnosticos descriptivos; no eligen una variante.",
        "", "## Limitaciones", "",
    ])
    lines.extend(f"- {item}" for item in summary["limitations"])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return markdown_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="HYP-COST-001 research-only runner")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    args = parser.parse_args()
    try:
        paths = run(args.spec, args.reports)
    except (OSError, StudyError, ValueError) as exc:
        print(json.dumps({"research_only": True, "error": str(exc)}))
        return 2
    display_paths = []
    for path in paths:
        try:
            display_paths.append(str(path.relative_to(ROOT)))
        except ValueError:
            display_paths.append(str(path))
    print(json.dumps({"research_only": True, "reports": display_paths}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
