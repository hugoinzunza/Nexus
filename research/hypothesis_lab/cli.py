"""CLI for preregistration, validation and execution.

Run from repository root:
  python3 -m research.hypothesis_lab.cli validate
  python3 -m research.hypothesis_lab.cli preregister
  python3 -m research.hypothesis_lab.cli run
"""
from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import LAB_VERSION, NOTICE
from .contracts import ContractError, Spec, load_spec, sha256_bytes, sha256_file
from .datasets import load_inputs
from .metrics import EXPLICIT_BLOCKS, basic_metrics, block_bootstrap_mean, holm, paired_block_bootstrap
from .registry import Registry
from .report import write_reports
from .simulator import simulate_exit_variant

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_SPEC = HERE / "specs" / "v1" / "HYP-EXIT-001.frozen.json"
DEFAULT_DB = ROOT / "data" / "hypothesis_lab" / "lab.sqlite3"
DEFAULT_REPORTS = HERE / "reports"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def code_manifest() -> tuple[list[dict[str, str]], str]:
    # Include the upstream research exporter because its uncommitted version produced
    # the setup dataset. The output dataset is hashed separately as well.
    files = sorted(HERE.glob("*.py")) + [ROOT / "modules/trading/run_setup_backtest.py"]
    rows = [{"path": str(p.relative_to(ROOT)), "sha256": sha256_file(p)} for p in files]
    payload = "".join(f"{r['path']}:{r['sha256']}\n" for r in rows).encode()
    return rows, sha256_bytes(payload)


def base_manifest(spec: Spec, started_at: str, datasets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    code_files, code_sha256 = code_manifest()
    return {
        "schema_version": 1, "research_only": True, "notice": NOTICE,
        "hypothesis_id": spec.hypothesis_id, "started_at": started_at,
        "git_commit": git_commit(ROOT), "spec_path": str(spec.path.relative_to(ROOT)),
        "spec_sha256": spec.sha256, "seed": spec.raw["seed"],
        "lab_version": LAB_VERSION, "code_sha256": code_sha256, "code_files": code_files,
        "dataset_classification": spec.raw["dataset"]["classification"],
        "datasets": datasets or [], "trial_budget": spec.trial_budget, "total_trials": 0,
    }


def preregister(spec: Spec, db_path: Path) -> None:
    registry = Registry(db_path)
    try:
        digest = registry.preregister(spec, utc_now())
    finally:
        registry.close()
    print(json.dumps({"hypothesis_id": spec.hypothesis_id, "spec_sha256": digest,
                      "research_only": True, "notice": NOTICE}, ensure_ascii=False))


def execute(spec: Spec, db_path: Path, report_dir: Path) -> str:
    started = utc_now()
    # Registration is committed before input loading or the first trial.
    registry = Registry(db_path)
    registry.preregister(spec, started)
    setups, candles, dataset_manifest = load_inputs(ROOT, spec)
    run_id = f"{spec.hypothesis_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    manifest = base_manifest(spec, started, dataset_manifest)
    registry.start_run(run_id, spec, started, manifest)
    trial_no = 0
    trials: dict[str, list[dict[str, Any]]] = {}
    pooled: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    setup_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in setups:
        if row["pair"] in spec.pairs and row["sel_tf"] in spec.timeframes:
            setup_groups[(row["pair"], row["sel_tf"])].append(row)
    try:
        for pair in spec.pairs:
            for timeframe in spec.timeframes:
                source = setup_groups[(pair, timeframe)]
                for cost in spec.costs:
                    for target in spec.targets:
                        trial_no += 1
                        rows = [simulate_exit_variant(s, candles[(pair, timeframe)], target, float(cost["total_rate"]))
                                for s in source]
                        for row in rows:
                            row.update({"pair": pair, "timeframe": timeframe,
                                        "target_id": target["id"], "cost_id": cost["id"]})
                        registry.add_trial(run_id, trial_no, pair, timeframe, target["id"], cost["id"], rows)
                        key = f"{trial_no:03d}:{pair}:{timeframe}:{cost['id']}:{target['id']}"
                        trial_metric = basic_metrics(rows, float(spec.raw["sizing"]["fixed_fraction_for_context"]))
                        trial_metric["bootstrap"] = block_bootstrap_mean(
                            rows, random.Random(int(spec.raw["seed"]) + trial_no),
                            int(spec.raw["statistics"]["bootstrap"]["iterations"]),
                        )
                        trials[key] = trial_metric
                        pooled[(cost["id"], target["id"])].extend(rows)
        if trial_no != spec.trial_budget:
            raise ContractError(f"executed {trial_no} trials but preregistered {spec.trial_budget}")

        comparisons: dict[str, dict[str, Any]] = {}
        correction_family: list[dict[str, Any]] = []
        iterations = int(spec.raw["statistics"]["bootstrap"]["iterations"])
        inferential_cost = spec.costs[0]["id"]
        baseline = pooled[(inferential_cost, "original")]
        for target in spec.targets:
            tid = target["id"]
            if tid == "original":
                continue
            result = paired_block_bootstrap(
                pooled[(inferential_cost, tid)], baseline,
                random.Random(int(spec.raw["seed"]) + sum(map(ord, tid))), iterations,
            )
            comparisons[tid] = result
            if result["status"] == "blocked_pairing_mismatch":
                raise ContractError(f"paired universe mismatch for {tid}: {result}")
            if result.get("p_two_sided") is not None:
                correction_family.append({"target_id": tid, "p": result["p_two_sided"]})

        # Equal per-setup costs cancel in candidate-minus-baseline comparisons.
        # Verify that property instead of counting each cost scenario as new evidence.
        for cost in spec.costs[1:]:
            cid = cost["id"]
            for target in spec.targets:
                tid = target["id"]
                if tid == "original":
                    continue
                check = paired_block_bootstrap(
                    pooled[(cid, tid)], pooled[(cid, "original")],
                    random.Random(int(spec.raw["seed"]) + sum(map(ord, tid))), iterations,
                )
                if not math.isclose(check.get("mean_difference_net_r", math.nan),
                                    comparisons[tid].get("mean_difference_net_r", math.nan),
                                    rel_tol=0.0, abs_tol=1e-12):
                    raise ContractError(f"cost-invariance check failed for {cid}:{tid}")

        aggregate = {f"{cost['id']}:{target['id']}": basic_metrics(
            pooled[(cost["id"], target["id"])], float(spec.raw["sizing"]["fixed_fraction_for_context"]))
            for cost in spec.costs for target in spec.targets}
        cost_sensitivity = {target["id"]: {cost["id"]: aggregate[f"{cost['id']}:{target['id']}"]["avg_net_r"]
                                           for cost in spec.costs} for target in spec.targets}
        summary = {
            "schema_version": 1, "research_only": True, "notice": NOTICE,
            "hypothesis_id": spec.hypothesis_id, "run_id": run_id,
            "winner_selected": False, "promotion_available": False,
            "trial_metrics": trials, "aggregate_metrics": aggregate,
            "paired_comparisons": comparisons,
            "holm_correction_global_family": holm(correction_family),
            "paired_inference_cost_handling": {
                "cost_id_used": inferential_cost,
                "cost_scenarios_are_sensitivity_not_independent_tests": True,
                "invariance_verified": True,
            },
            "cost_sensitivity_avg_net_r": cost_sensitivity,
            "explicit_blocks": EXPLICIT_BLOCKS,
            "interpretation_guardrails": [
                "recycled_research_data is not virgin holdout data",
                "fixed_nominal_risk and fixed_fraction_of_equity are reported separately",
                "fixed_fraction_of_equity is per-setup context, not a concurrent portfolio simulation",
                "trade independence is not assumed; overlap, cross-pair correlation and account heat remain limitations",
                "no automatic winner selection or live promotion",
            ],
        }
        completed = utc_now()
        manifest.update({"completed_at": completed, "total_trials": trial_no,
                         "candidate_rows_stored": sum(m["n_candidates"] for m in trials.values())})
        registry.finish_run(run_id, completed, spec.trial_budget, manifest)
        paths = write_reports(report_dir, run_id, manifest, summary)
        print(json.dumps({"run_id": run_id, "trials": trial_no,
                          "reports": [str(p.relative_to(ROOT)) for p in paths],
                          "research_only": True, "notice": NOTICE}, ensure_ascii=False))
        return run_id
    except Exception as exc:
        registry.fail_run(run_id, utc_now(), f"{type(exc).__name__}: {exc}", manifest)
        raise
    finally:
        registry.close()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=NOTICE)
    p.add_argument("command", choices=("validate", "preregister", "run"))
    p.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        spec = load_spec(args.spec)
        if args.command == "validate":
            print(json.dumps({"valid": True, "hypothesis_id": spec.hypothesis_id,
                              "trial_budget": spec.trial_budget, "spec_sha256": spec.sha256,
                              "research_only": True, "notice": NOTICE}, ensure_ascii=False))
        elif args.command == "preregister":
            preregister(spec, args.db)
        else:
            execute(spec, args.db, args.reports)
    except (ContractError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "research_only": True, "notice": NOTICE}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
