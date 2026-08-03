"""Research-only operational viability audit for narrower stops.

The study reuses HYP-COST-001 simulations, but reports both fixed-risk R and
fixed-notional returns. It also applies deterministic account heat and notional
limits. It cannot select a production policy or call execution code.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.hypothesis_lab.cost_study import (
    ROOT,
    _sha256,
    friction_components,
    holm,
    load_inputs,
    load_frozen_spec as load_cost_spec,
    simulate_stop,
)


HERE = Path(__file__).resolve().parent
DEFAULT_SPEC = HERE / "specs" / "v1" / "HYP-COST-002.frozen.json"
COST_SPEC = HERE / "specs" / "v1" / "HYP-COST-001.frozen.json"
DEFAULT_REPORTS = HERE / "reports"


class ViabilityError(ValueError):
    pass


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_frozen_spec(path: Path = DEFAULT_SPEC) -> dict[str, Any]:
    spec = _read_json(path)
    if spec.get("hypothesis_id") != "HYP-COST-002":
        raise ViabilityError("unexpected hypothesis_id")
    if spec.get("frozen") is not True or spec.get("research_only") is not True:
        raise ViabilityError("the study requires a frozen research-only spec")
    if spec["design"].get("stop_multipliers") != [1.0, 0.75, 0.5, 0.35]:
        raise ViabilityError("frozen stop multipliers changed")
    if spec["design"].get("selection_rule") != "no_multiplier_selection":
        raise ViabilityError("multiplier selection must remain disabled")
    portfolio = spec["portfolio"]
    if portfolio.get("allocation_policy") != "all_or_nothing":
        raise ViabilityError("portfolio allocation policy changed")
    if portfolio.get("sizing_modes") != ["fixed_dollar", "fixed_fraction_current_equity"]:
        raise ViabilityError("portfolio sizing modes changed")
    if portfolio.get("primary_sizing_mode") != "fixed_dollar":
        raise ViabilityError("primary sizing mode changed")
    if portfolio.get("close_before_open_at_same_timestamp") is not True:
        raise ViabilityError("same-timestamp event precedence changed")
    if spec["statistics"].get("primary_estimand") != "paired_difference_in_net_return_per_entry_notional":
        raise ViabilityError("primary estimand changed")
    governance = spec["governance"]
    if any(governance.get(key) is not False for key in (
        "automatic_winner_selection", "automatic_promotion", "execution_enabled",
        "bot_changes_allowed", "testnet_changes_allowed", "live_changes_allowed",
    )):
        raise ViabilityError("research-only governance changed")
    return spec


def stop_loss_cost_r(setup: dict[str, Any], row: dict[str, Any], scenario: dict[str, Any]) -> float:
    """Worst-case friction in R if the tested stop executes as a taker."""
    entry = float(row["entry"])
    stop = float(row["tested_stop"])
    risk_fraction = float(row["risk_price"]) / entry
    costs = friction_components(setup, scenario, "taker")
    fee_rate = costs["entry_fee_rate"] + costs["exit_fee_rate"] * (stop / entry)
    friction_rate = costs["roundtrip_spread_rate"] + costs["entry_slippage_rate"] + costs["exit_slippage_rate"]
    return (fee_rate + friction_rate) / risk_fraction


def add_operational_fields(row: dict[str, Any], setup: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    if row.get("net_r") is None:
        return {**row, "net_return_per_entry_notional": None}
    risk_fraction = float(row["risk_price"]) / float(row["entry"])
    loss_cost_r = stop_loss_cost_r(setup, row, scenario)
    return {
        **row,
        "original_rr": float(setup.get("rr", 0.0)),
        "risk_fraction_of_entry_notional": risk_fraction,
        "net_return_per_entry_notional": float(row["net_r"]) * risk_fraction,
        "stop_loss_cost_r": loss_cost_r,
        "desired_notional_multiple_at_1pct_risk": 0.01 / (risk_fraction * (1.0 + loss_cost_r)),
    }


def fixed_notional_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    used = sorted(
        (row for row in rows if row.get("net_return_per_entry_notional") is not None),
        key=lambda row: (row["activation_timestamp"], row["setup_id"]),
    )
    values = [float(row["net_return_per_entry_notional"]) for row in used]
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    requested = sorted(float(row["desired_notional_multiple_at_1pct_risk"]) for row in used)
    costs = [float(row["total_cost_rate"]) for row in used]
    gross_abs = sum(abs(float(row["gross_r"]) * float(row["risk_fraction_of_entry_notional"])) for row in used)
    return {
        "n": len(used),
        "avg_net_return_pct_of_notional": statistics.fmean(values) * 100 if values else None,
        "profit_factor_fixed_notional": gains / losses if losses else None,
        "max_drawdown_pct_of_one_notional_unit": drawdown * 100,
        "mean_roundtrip_cost_pct_of_notional": statistics.fmean(costs) * 100 if costs else None,
        "aggregate_cost_to_absolute_gross_return": sum(costs) / gross_abs if gross_abs else None,
        "requested_notional_multiple_at_1pct_risk": _distribution(requested),
    }


def _distribution(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {
        "p50": statistics.median(ordered),
        "p95": ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))],
        "max": ordered[-1],
    }


def transition_decomposition(candidate: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> dict[str, Any]:
    base = {row["setup_id"]: row for row in baseline if row.get("net_r") is not None}
    groups: dict[str, list[dict[str, float]]] = defaultdict(list)
    for row in candidate:
        if row.get("net_r") is None or row["setup_id"] not in base:
            continue
        old = base[row["setup_id"]]
        key = f"{old['status']}->{row['status']}"
        groups[key].append({
            "delta_r": float(row["net_r"]) - float(old["net_r"]),
            "delta_notional": float(row["net_return_per_entry_notional"]) - float(old["net_return_per_entry_notional"]),
        })
    return {
        key: {
            "n": len(values),
            "mean_delta_r": statistics.fmean(item["delta_r"] for item in values),
            "mean_delta_notional_pct": statistics.fmean(item["delta_notional"] for item in values) * 100,
            "total_delta_notional_pct": sum(item["delta_notional"] for item in values) * 100,
        }
        for key, values in sorted(groups.items())
    }


def _month(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).strftime("%Y-%m")


def paired_month_bootstrap_notional(candidate: list[dict[str, Any]], baseline: list[dict[str, Any]], *,
                                    seed: int, iterations: int) -> dict[str, Any]:
    a = {row["setup_id"]: row for row in candidate if row.get("net_return_per_entry_notional") is not None}
    b = {row["setup_id"]: row for row in baseline if row.get("net_return_per_entry_notional") is not None}
    if a.keys() != b.keys():
        return {"status": "blocked_pairing_mismatch", "n_candidate": len(a), "n_baseline": len(b)}
    blocks: dict[str, list[float]] = defaultdict(list)
    for setup_id in sorted(a):
        delta = float(a[setup_id]["net_return_per_entry_notional"]) - float(b[setup_id]["net_return_per_entry_notional"])
        blocks[_month(int(a[setup_id]["activation_timestamp"]))].append(delta)
    months = sorted(blocks)
    if len(months) < 2:
        return {"status": "blocked_insufficient_months", "n_paired": len(a), "months": len(months)}
    observed = statistics.fmean(value for block in blocks.values() for value in block)
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
        "status": "computed",
        "n_paired": len(a),
        "months": len(months),
        "mean_difference_notional_pct": observed * 100,
        "ci95_notional_pct": [
            draws[int(0.025 * (iterations - 1))] * 100,
            draws[int(0.975 * (iterations - 1))] * 100,
        ],
        "p_two_sided_centered_block_bootstrap": p_value,
    }


def simulate_portfolio(rows: list[dict[str, Any]], portfolio: dict[str, Any], gross_cap: float,
                       sizing_mode: str) -> dict[str, Any]:
    """Close-based deterministic capacity audit; no intrabar mark-to-market."""
    used = [row for row in rows if row.get("net_r") is not None]
    openings: dict[int, list[dict[str, Any]]] = defaultdict(list)
    closings: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in used:
        openings[int(row["activation_timestamp"])].append(row)
        closings[int(row["resolution_timestamp"])].append(row)
    timestamps = sorted(set(openings) | set(closings))
    starting = float(portfolio["starting_equity_usd"])
    equity = peak = starting
    max_drawdown = 0.0
    max_drawdown_fraction = 0.0
    active: dict[str, dict[str, float]] = {}
    accepted: set[str] = set()
    skips = Counter()
    closed = 0
    max_active = 0
    max_heat_fraction = 0.0
    max_gross_multiple = 0.0

    def close_due(rows_due: list[dict[str, Any]]) -> None:
        nonlocal equity, peak, max_drawdown, max_drawdown_fraction, closed
        for row in sorted(rows_due, key=lambda item: item["setup_id"]):
            allocation = active.pop(row["setup_id"], None)
            if allocation is None:
                continue
            equity += allocation["risk_unit_usd"] * float(row["net_r"])
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
            max_drawdown_fraction = max(max_drawdown_fraction, (peak - equity) / peak if peak else 0.0)
            closed += 1

    for timestamp in timestamps:
        # Release positions opened before this timestamp first. A position that
        # opens and resolves now is closed only after the opening batch.
        close_due([row for row in closings[timestamp] if row["setup_id"] in active])
        opened_now = []
        for row in sorted(openings[timestamp], key=lambda item: item["setup_id"]):
            if sizing_mode == "fixed_dollar":
                desired_loss = float(portfolio["fixed_stop_loss_budget_usd"])
            elif sizing_mode == "fixed_fraction_current_equity":
                desired_loss = equity * float(portfolio["desired_stop_loss_fraction_of_equity"])
            else:
                raise ViabilityError(f"unknown sizing mode: {sizing_mode}")
            risk_unit = desired_loss / (1.0 + float(row["stop_loss_cost_r"]))
            requested_notional = risk_unit / float(row["risk_fraction_of_entry_notional"])
            active_heat = sum(item["stop_loss_budget_usd"] for item in active.values())
            active_notional = sum(item["notional_usd"] for item in active.values())
            if requested_notional > equity * float(portfolio["max_single_trade_notional_multiple"]):
                skips["single_trade_notional_cap"] += 1
                continue
            if active_notional + requested_notional > equity * gross_cap:
                skips["gross_notional_cap"] += 1
                continue
            if active_heat + desired_loss > equity * float(portfolio["max_account_heat_fraction"]):
                skips["account_heat_cap"] += 1
                continue
            active[row["setup_id"]] = {
                "risk_unit_usd": risk_unit,
                "stop_loss_budget_usd": desired_loss,
                "notional_usd": requested_notional,
            }
            accepted.add(row["setup_id"])
            opened_now.append(row)
            max_active = max(max_active, len(active))
            max_heat_fraction = max(max_heat_fraction, sum(item["stop_loss_budget_usd"] for item in active.values()) / equity)
            max_gross_multiple = max(max_gross_multiple, sum(item["notional_usd"] for item in active.values()) / equity)
        close_due([row for row in opened_now if int(row["resolution_timestamp"]) == timestamp])

    return {
        "sizing_mode": sizing_mode,
        "candidate_trades": len(used),
        "accepted": len(accepted),
        "closed": closed,
        "acceptance_rate": len(accepted) / len(used) if used else None,
        "skipped": dict(sorted(skips.items())),
        "ending_equity_usd": equity,
        "total_return_pct": (equity / starting - 1.0) * 100,
        "max_drawdown_usd_close_only": max_drawdown,
        "max_drawdown_pct_of_peak_close_only": max_drawdown_fraction * 100,
        "max_simultaneous_positions": max_active,
        "max_reserved_heat_fraction": max_heat_fraction,
        "max_gross_notional_multiple": max_gross_multiple,
        "unresolved_active": len(active),
    }


def _filter_universe(rows: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    if name == "all_activated":
        return rows
    if name == "original_rr_gte_5":
        return [row for row in rows if float(row.get("original_rr", 0.0)) >= 5.0]
    raise ViabilityError(f"unknown universe: {name}")


def run(spec_path: Path = DEFAULT_SPEC, report_dir: Path = DEFAULT_REPORTS) -> tuple[Path, Path]:
    spec = load_frozen_spec(spec_path)
    cost_spec = load_cost_spec(COST_SPEC)
    setups, candles, datasets = load_inputs(cost_spec)
    setup_by_id = {row["setup_id"]: row for row in setups}
    scenario_by_id = {row["id"]: row for row in cost_spec["costs"]["scenarios"]}
    variants: dict[tuple[str, float], list[dict[str, Any]]] = {}
    for scenario_id in [spec["design"]["primary_cost_scenario"], *spec["design"]["sensitivity_cost_scenarios"]]:
        scenario = scenario_by_id[scenario_id]
        for multiplier in spec["design"]["stop_multipliers"]:
            simulated = [
                simulate_stop(setup, candles[(setup["pair"], setup["sel_tf"])], float(multiplier), scenario)
                for setup in setups
            ]
            variants[(scenario_id, float(multiplier))] = [
                add_operational_fields(row, setup_by_id[row["setup_id"]], scenario) for row in simulated
            ]

    fixed_notional = {}
    comparisons = {}
    transitions = {}
    primary = spec["design"]["primary_cost_scenario"]
    family = []
    for scenario_id in scenario_by_id:
        if (scenario_id, 1.0) not in variants:
            continue
        baseline = variants[(scenario_id, 1.0)]
        for multiplier in spec["design"]["stop_multipliers"]:
            rows = variants[(scenario_id, float(multiplier))]
            fixed_notional[f"{scenario_id}:{multiplier:g}"] = fixed_notional_metrics(rows)
            if float(multiplier) == 1.0:
                continue
            key = f"{scenario_id}:{multiplier:g}_vs_1"
            comparisons[key] = paired_month_bootstrap_notional(
                rows, baseline,
                seed=int(spec["seed"]) + round(float(multiplier) * 1000),
                iterations=int(spec["statistics"]["bootstrap_iterations"]),
            )
            transitions[key] = transition_decomposition(rows, baseline)
            if scenario_id == primary and comparisons[key]["status"] == "computed":
                family.append({"id": key, "p": comparisons[key]["p_two_sided_centered_block_bootstrap"]})

    portfolios = {}
    for sizing_mode in spec["portfolio"]["sizing_modes"]:
        for universe in (spec["design"]["primary_universe"], spec["design"]["policy_aligned_diagnostic"]):
            for multiplier in spec["design"]["stop_multipliers"]:
                rows = _filter_universe(variants[(primary, float(multiplier))], universe)
                for cap in spec["portfolio"]["gross_notional_cap_multiples"]:
                    key = f"{sizing_mode}:{universe}:{multiplier:g}:cap{cap:g}"
                    portfolios[key] = simulate_portfolio(rows, spec["portfolio"], float(cap), sizing_mode)

    corrected = holm(family, float(spec["statistics"]["alpha"]))
    generated_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stem = f"HYP-COST-002-{generated_at}"
    summary = {
        "schema_version": 1,
        "research_only": True,
        "notice": "Research only - No signal - No bot",
        "hypothesis_id": "HYP-COST-002",
        "spec_sha256": _sha256(spec_path),
        "cost_spec_sha256": _sha256(COST_SPEC),
        "code_sha256": _sha256(Path(__file__)),
        "datasets": datasets,
        "selected_setups": len(setups),
        "fixed_notional_metrics": fixed_notional,
        "paired_month_bootstrap_fixed_notional": comparisons,
        "holm_primary_family": corrected,
        "exit_transition_decomposition": transitions,
        "capacity_constrained_portfolios": portfolios,
        "interpretation": {
            "fixed_notional_removes_pure_R_rescaling": True,
            "portfolio_paths_are_descriptive": True,
            "same_dataset_reused": True,
            "automatic_selection": False,
            "promotion": False,
        },
        "limitations": [
            "The same historical export used in HYP-COST-001 is reused, so every result is exploratory.",
            "Spread and slippage are declared scenarios because the export contains no observed fields.",
            "The portfolio uses close-only equity and does not model intrabar mark-to-market or liquidation.",
            "Compounded ending equity over thousands of recycled setups is numerically path-dependent and is retained only as a diagnostic, not a decision metric.",
            "Historical exchange filters, leverage brackets, margin mode and funding are not reconstructed.",
            "The all-setup portfolio is a capacity stress test, not the exact current bot selection policy.",
            "The rr>=5 universe is a pre-existing policy-aligned diagnostic, not an independent confirmation sample.",
        ],
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / f"{stem}.summary.json"
    markdown_path = report_dir / f"{stem}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# HYP-COST-002 - Viabilidad operacional de stops estrechos",
        "", "**Research only - No signal - No bot**", "",
        "Este estudio no busca una configuracion ganadora. Separa el cambio real por nocional de la amplificacion mecanica al medir en R y somete cada variante a limites de capacidad.",
        "", "## Retorno por nocional fijo", "",
        "| Escenario | Stop | n | retorno medio / nocional | PF | DD / nocional | costo | nocional p95 para riesgo 1% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario_id in [primary, *spec["design"]["sensitivity_cost_scenarios"]]:
        for multiplier in spec["design"]["stop_multipliers"]:
            value = fixed_notional[f"{scenario_id}:{multiplier:g}"]
            lines.append(
                f"| {scenario_id} | {multiplier:g} | {value['n']} | {value['avg_net_return_pct_of_notional']:+.4f}% | "
                f"{value['profit_factor_fixed_notional']:.3f} | {value['max_drawdown_pct_of_one_notional_unit']:.2f}% | "
                f"{value['mean_roundtrip_cost_pct_of_notional']:.4f}% | "
                f"{value['requested_notional_multiple_at_1pct_risk']['p95']:.2f}x |"
            )
    lines.extend(["", "## Comparacion primaria pareada", ""])
    corrected_by_id = {row["id"]: row for row in corrected}
    for multiplier in spec["design"]["stop_multipliers"][1:]:
        key = f"{primary}:{multiplier:g}_vs_1"
        value = comparisons[key]
        lines.append(
            f"- `{multiplier:g} vs 1.0`: delta {value['mean_difference_notional_pct']:+.4f}% del nocional por trade, "
            f"IC95 [{value['ci95_notional_pct'][0]:+.4f}%, {value['ci95_notional_pct'][1]:+.4f}%], "
            f"Holm reject={corrected_by_id[key]['reject_null']}."
        )
    lines.extend([
        "", "## Mecanismo de la diferencia - escenario base", "",
        "| Stop | Perdidas recortadas (SL->SL) | Winners destruidos (TP->SL) | Timeouts convertidos en SL | delta total / nocional |",
        "|---:|---:|---:|---:|---:|",
    ])
    for multiplier in spec["design"]["stop_multipliers"][1:]:
        key = f"{primary}:{multiplier:g}_vs_1"
        value = transitions[key]
        shortened = value.get("sl->sl", {"n": 0, "total_delta_notional_pct": 0.0})
        lost_winners = value.get("tp->sl", {"n": 0, "total_delta_notional_pct": 0.0})
        lost_timeouts = value.get("timeout->sl", {"n": 0, "total_delta_notional_pct": 0.0})
        total = sum(row["total_delta_notional_pct"] for row in value.values())
        lines.append(
            f"| {multiplier:g} | {shortened['n']} ({shortened['total_delta_notional_pct']:+.1f} pp) | "
            f"{lost_winners['n']} ({lost_winners['total_delta_notional_pct']:+.1f} pp) | "
            f"{lost_timeouts['n']} ({lost_timeouts['total_delta_notional_pct']:+.1f} pp) | {total:+.1f} pp |"
        )
    lines.extend(["", "## Capacidad operacional - escenario base, cap total 3x", "",
                  "| Universo | Stop | aceptadas | tasa | DD cierre | exposicion maxima | principal bloqueo |",
                  "|---|---:|---:|---:|---:|---:|---|" ])
    cap = float(spec["portfolio"]["primary_gross_notional_cap_multiple"])
    sizing_mode = spec["portfolio"]["primary_sizing_mode"]
    for universe in (spec["design"]["primary_universe"], spec["design"]["policy_aligned_diagnostic"]):
        for multiplier in spec["design"]["stop_multipliers"]:
            value = portfolios[f"{sizing_mode}:{universe}:{multiplier:g}:cap{cap:g}"]
            blocker = max(value["skipped"], key=value["skipped"].get) if value["skipped"] else "ninguno"
            lines.append(
                f"| {universe} | {multiplier:g} | {value['accepted']} | {value['acceptance_rate']:.1%} | "
                f"{value['max_drawdown_pct_of_peak_close_only']:.2f}% | {value['max_gross_notional_multiple']:.2f}x | {blocker} |"
            )
    lines.extend([
        "", "## Veredicto", "",
        "**Ninguna variante demuestra una mejora economica sobre el stop original.** Las tres comparaciones por nocional tienen intervalos al 95% que incluyen cero y ninguna supera Holm.",
        "El stop 0,50x conserva una senal mecanica interesante de reduccion de perdidas y drawdown, pero su efecto medio es pequeno, destruye winners y exige mas capacidad. Permanece como hipotesis exploratoria; no se promueve ni se optimiza otra vez sobre esta muestra.",
        "", "## Lectura permitida", "",
        "- El retorno por nocional muestra si queda beneficio despues de quitar la mera reexpresion en R.",
        "- La simulacion de capacidad muestra cuanto de ese beneficio podria asignarse bajo limites constantes.",
        "- El retorno compuesto de la cartera queda en el JSON solo como diagnostico; no es un estimador valido para promocion.",
        "- Las transiciones de salida identifican si la mejora viene de perdidas menores o de winners destruidos.",
        "- Ningun resultado selecciona una variante ni autoriza cambios en Bot, Testnet o Live.",
        "", "## Limitaciones", "",
    ])
    lines.extend(f"- {item}" for item in summary["limitations"])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return markdown_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="HYP-COST-002 research-only operational viability audit")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    args = parser.parse_args()
    try:
        paths = run(args.spec, args.reports)
    except (OSError, ValueError) as exc:
        print(json.dumps({"research_only": True, "error": str(exc)}))
        return 2
    print(json.dumps({"research_only": True, "reports": [str(path.relative_to(ROOT)) for path in paths]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
