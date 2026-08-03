"""Small auditable JSON/Markdown research reports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import NOTICE
from .contracts import canonical_json


def write_reports(report_dir: Path, run_id: str, manifest: dict[str, Any], summary: dict[str, Any]) -> list[Path]:
    def fmt(value: Any, pattern: str) -> str:
        return "NA" if value is None else format(value, pattern)

    report_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = report_dir / f"{run_id}.manifest.json"
    summary_path = report_dir / f"{run_id}.summary.json"
    md_path = report_dir / f"{run_id}.md"
    manifest_path.write_bytes(canonical_json(manifest))
    summary_path.write_bytes(canonical_json(summary))
    lines = [f"# {summary['hypothesis_id']} — {run_id}", "", f"> {NOTICE}", "",
             "No se selecciona ganadora ni se promueve configuración alguna.", "",
             f"- Ensayos: {manifest['total_trials']} / budget {manifest['trial_budget']}",
             f"- Datos: `{manifest['dataset_classification']}`", f"- Spec SHA-256: `{manifest['spec_sha256']}`",
             f"- Commit: `{manifest['git_commit']}`", "", "## Métricas netas agregadas", "",
             "| Costos | Target | n | avg netR | PF neto | WR neto | WR break-even observado | DD R | Racha | Años + |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key, metric in summary["aggregate_metrics"].items():
        cost_id, target_id = key.split(":", 1)
        pf = metric["profit_factor_net"]
        wr = metric["win_rate_after_costs"]
        be = metric["break_even_win_rate_after_costs_observed_payoffs"]
        years = metric["temporal_stability"]["positive_year_fraction"]
        lines.append(f"| {cost_id} | {target_id} | {metric['n_used']} | {fmt(metric['avg_net_r'], '.4f')} | "
                     f"{fmt(pf, '.3f')} | {fmt(wr, '.1%')} | {fmt(be, '.1%')} | "
                     f"{metric['fixed_nominal_risk']['max_drawdown_r']:.1f} | "
                     f"{metric['fixed_nominal_risk']['max_losing_streak']} | {fmt(years, '.1%')} |")
    lines.extend(["", "`fixed_nominal_risk` (DD en R) y `fixed_fraction_of_equity` (contexto por setup al 1%, no cartera concurrente) permanecen separados en el JSON. El WR de break-even usa payoffs netos observados, no una fórmula RR simplificada.",
                  "", "## Comparaciones pareadas", ""])
    holm_lookup = {row["target_id"]: row["p_holm"]
                   for row in summary["holm_correction_global_family"]}
    for target, result in summary["paired_comparisons"].items():
        if result["status"] == "computed":
            lines.append(f"- {target}: n={result['n_paired']}, ΔavgR={result['mean_difference_net_r']:.4f}, "
                         f"CI95={result['ci95']}, p={result['p_two_sided']:.4f}, "
                         f"p_holm={holm_lookup[target]:.4f}")
        else:
            lines.append(f"- {target}: {result['status']} (n={result['n_paired']})")
    lines.extend(["", "Los costos se cancelan en cada diferencia pareada; sus tres escenarios se conservan como sensibilidad económica y no se cuentan como evidencia independiente.", ""])
    lines.extend(["## Limitaciones y bloqueos explícitos", "",
                  "Los datos son históricos ya consultados, no holdout virgen. Trades solapados, correlación entre pares y account heat no se suponen independientes.", "",
                  "La trayectoria fixed-fraction se calcula por setup y no representa una cartera con operaciones simultáneas.", "",
                  "DSR/PBO y Monte Carlo por bloques no se simulan en v1; el JSON registra estos bloqueos. No se permite permutar trades IID.", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return [manifest_path, summary_path, md_path]
