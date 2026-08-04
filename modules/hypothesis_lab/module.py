"""Hypothesis Lab: evidencia historica y observadores forward, solo lectura."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from core.module_base import NexusModule


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "research" / "hypothesis_lab" / "reports"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _latest(pattern: str) -> dict[str, Any]:
    matches = sorted(REPORTS.glob(pattern))
    return _read_json(matches[-1]) if matches else {}


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


class HypothesisLabModule(NexusModule):
    slug = "hypothesis-lab"
    title = "Laboratorio de hipotesis"
    description = "Evidencia causal, cohortes forward y protocolos de decision."
    icon = "HL"

    def __init__(self, context):
        super().__init__(context)
        configured = str(self.config.get("runtime_data_root") or "").strip()
        env_root = os.environ.get("NEXUX_RESEARCH_RUNTIME_ROOT", "").strip()
        self.runtime_root = Path(configured or env_root or (ROOT / "data"))

    def public_dir(self):
        return str(Path(__file__).with_name("public"))

    @staticmethod
    def _freshness(path: Path, expected_seconds: int) -> dict[str, Any]:
        payload = _read_json(path)
        generated = payload.get("meta", {}).get("generated_at_ms")
        if not isinstance(generated, (int, float)):
            return {
                "status": "missing", "generated_at_ms": None,
                "age_seconds": None, "path_exists": path.exists(),
            }
        age = max(0.0, time.time() - generated / 1000)
        if payload.get("meta", {}).get("errors") or payload.get("meta", {}).get("load_errors"):
            status = "degraded"
        else:
            status = "fresh" if age <= expected_seconds else "stale"
        return {
            "status": status,
            "generated_at_ms": int(generated),
            "age_seconds": round(age, 1),
            "path_exists": True,
        }

    def _state(self) -> dict[str, Any]:
        exit_1 = _latest("HYP-EXIT-001-*.summary.json")
        exit_2 = _latest("HYP-EXIT-002-*.summary.json")
        cost_1 = _latest("HYP-COST-001-*.summary.json")
        cost_2 = _latest("HYP-COST-002-*.summary.json")
        season_1 = _latest("HYP-SEASON-001-*.summary.json")
        trend_1 = _latest("HYP-TREND-001-*.summary.json")
        candle_1 = _latest("HYP-CANDLE-001-*.summary.json")
        shadow_path = self.runtime_root / "hypothesis_lab" / "shadow" / "protect_3r_runner_original.json"
        telemetry_path = self.runtime_root / "hypothesis_lab" / "telemetry" / "execution_costs.json"
        candle_path = self.runtime_root / "hypothesis_lab" / "shadow" / "candle_reversal_forward.json"
        shadow = _read_json(shadow_path)
        telemetry = _read_json(telemetry_path)
        candle_shadow = _read_json(candle_path)

        base = exit_1.get("aggregate_metrics", {}).get("base:original", {})
        protected = exit_2.get("paired_comparisons", {}).get("protect_3r_runner_original", {})
        cost_base = cost_1.get("aggregate_metrics", {}).get("base:1", {})
        cost_holm = cost_2.get("holm_primary_family") or []
        shadow_meta = shadow.get("meta", {})
        shadow_decision = shadow.get("decision", {})
        telemetry_meta = telemetry.get("meta", {})
        telemetry_decision = telemetry.get("decision", {})
        candle_summary = candle_shadow.get("summary", {})

        return {
            "research_only": True,
            "execution_enabled": False,
            "notice": "Research only · No señal · No bot",
            "generated_at_ms": int(time.time() * 1000),
            "observers": {
                "shadow_exit": {
                    **self._freshness(shadow_path, 180),
                    "hypothesis_id": "HYP-EXIT-003-SHADOW",
                    "records": shadow_meta.get("n_records", 0),
                    "paired_closed": shadow_meta.get("n_paired_closed", 0),
                    "reached_3r": shadow_meta.get("n_reached_3r", 0),
                    "decision": shadow_decision.get("status", "not_available"),
                    "errors": shadow_meta.get("errors", []),
                },
                "cost_telemetry": {
                    **self._freshness(telemetry_path, 180),
                    "hypothesis_id": "HYP-COST-003-TELEMETRY",
                    "records": telemetry_meta.get("n_records", 0),
                    "decision": telemetry_decision.get("status", "not_available"),
                    "load_errors": telemetry_meta.get("load_errors", []),
                    "coverage": telemetry_decision.get("primary_live_counts", {}),
                },
                "candle_reversal": {
                    **self._freshness(candle_path, 420),
                    "hypothesis_id": "HYP-CANDLE-002-SHADOW",
                    "records": candle_summary.get("eligible_records", 0),
                    "patterns": candle_summary.get("patterns", 0),
                    "closed_patterns": candle_summary.get("closed_with_pattern", 0),
                    "decision": candle_summary.get("decision_status", "not_available"),
                    "errors": candle_shadow.get("meta", {}).get("errors", []),
                },
            },
            "studies": [
                {
                    "id": "HYP-EXIT-001", "family": "Salidas", "state": "closed",
                    "title": "Geometria pareada de TP/RR",
                    "verdict": "Los parciales 2R/3R reducen expectativa; 5R no supera al original.",
                    "n": base.get("n_used"), "avg_r": _number(base.get("avg_net_r")),
                    "profit_factor": _number(base.get("profit_factor_net")),
                    "promotion": False,
                },
                {
                    "id": "HYP-EXIT-002", "family": "Salidas", "state": "candidate",
                    "title": "Proteccion del runner al alcanzar 3R",
                    "verdict": "Unico candidato; el IC95 aun incluye cero.",
                    "n": protected.get("n_paired"),
                    "delta_avg_r": _number(protected.get("mean_difference_net_r")),
                    "ci95": protected.get("ci95"), "promotion": False,
                },
                {
                    "id": "HYP-EXIT-003-SHADOW", "family": "Salidas", "state": "collecting",
                    "title": "Cohorte forward protect_3r_runner_original",
                    "verdict": "Observacion paralela; no modifica operaciones.",
                    "n": shadow_meta.get("n_records", 0),
                    "paired_closed": shadow_meta.get("n_paired_closed", 0),
                    "reached_3r": shadow_meta.get("n_reached_3r", 0),
                    "promotion": False,
                },
                {
                    "id": "HYP-COST-001", "family": "Costos", "state": "closed",
                    "title": "Stops estrechos bajo friccion declarada",
                    "verdict": "Exploratorio; no autoriza recalibrar costos ni estrategia.",
                    "n": cost_base.get("n"), "avg_r": _number(cost_base.get("avg_net_r")),
                    "profit_factor": _number(cost_base.get("profit_factor_net")),
                    "promotion": False,
                },
                {
                    "id": "HYP-COST-002", "family": "Costos", "state": "closed",
                    "title": "Viabilidad operacional de stops estrechos",
                    "verdict": "Ninguna comparacion primaria sobrevive Holm.",
                    "n": cost_2.get("selected_setups"),
                    "holm_rejections": sum(1 for row in cost_holm if row.get("reject_null")),
                    "promotion": False,
                },
                {
                    "id": "HYP-COST-003-TELEMETRY", "family": "Costos", "state": "collecting",
                    "title": "Telemetria forward de ejecucion",
                    "verdict": "Espera operaciones live elegibles; Testnet es diagnostico y no satisface el minimo.",
                    "n": telemetry_meta.get("n_records", 0), "promotion": False,
                },
                {
                    "id": "HYP-SEASON-001", "family": "Estacionalidad", "state": "exploratory",
                    "title": "Julio después de mayo y junio negativos",
                    "verdict": season_1.get("verdict", {}).get("summary", "Estudio exploratorio pendiente."),
                    "n": season_1.get("may_june_negative_then_july", {}).get("n"),
                    "avg_pct": _number(season_1.get("may_june_negative_then_july", {}).get("avg_return_pct")),
                    "positive_rate": _number(season_1.get("may_june_negative_then_july", {}).get("positive_rate")),
                    "baseline_rate": _number(season_1.get("july_baseline", {}).get("positive_rate")),
                    "ci95": season_1.get("conditioned_vs_other_julys", {}).get("ci95"),
                    "p_value": _number(season_1.get("conditioned_vs_other_julys", {}).get("fisher_exact_two_sided_p")),
                    "promotion": False,
                },
                {
                    "id": "HYP-TREND-001", "family": "Estructura", "state": "exploratory",
                    "title": "Ruptura y retest causal de líneas por pivotes",
                    "verdict": trend_1.get("verdict", {}).get("summary", "Estudio exploratorio pendiente."),
                    "n": trend_1.get("event_count"),
                    "bullish_excess_10d": _number(
                        trend_1.get("groups", {}).get("bullish", {}).get("10", {})
                        .get("matched_same_year_month", {}).get("avg_excess_return_pct")
                    ),
                    "bearish_excess_10d": _number(
                        trend_1.get("groups", {}).get("bearish", {}).get("10", {})
                        .get("matched_same_year_month", {}).get("avg_excess_return_pct")
                    ),
                    "july_events": trend_1.get("july_events", {}).get("n"),
                    "promotion": False,
                },
                {
                    "id": "HYP-CANDLE-001", "family": "Velas", "state": "candidate",
                    "title": "Impulso, absorción y reclaim después del toque",
                    "verdict": candle_1.get("verdict", {}).get("summary", "Estudio exploratorio pendiente."),
                    "n": candle_1.get("coverage", {}).get("patterns"),
                    "information_delta_r": _number(candle_1.get("information_value", {}).get("mean_excess_net_r")),
                    "timing_delta_r": _number(
                        candle_1.get("timing_value", {}).get("paired_difference_confirmation_minus_original", {})
                        .get("mean_difference_net_r")
                    ),
                    "pattern_rate": _number(candle_1.get("coverage", {}).get("pattern_rate")),
                    "promotion": False,
                },
            ],
            "protocol": shadow.get("decision_protocol", {}),
            "sources": {
                "setups": self._file_meta(self.runtime_root / "setups.json"),
                "main_ledger": self._file_meta(self.runtime_root / "bot_trades.json"),
                "testnet_ledger": self._file_meta(self.runtime_root / "testnet" / "bot_trades.json"),
            },
        }

    @staticmethod
    def _file_meta(path: Path) -> dict[str, Any]:
        try:
            stat = path.stat()
        except OSError:
            return {"status": "missing", "updated_at_ms": None, "age_seconds": None}
        age = max(0.0, time.time() - stat.st_mtime)
        return {
            "status": "fresh" if age <= 86_400 else "stale",
            "updated_at_ms": int(stat.st_mtime * 1000),
            "age_seconds": round(age, 1), "bytes": stat.st_size,
        }

    def api(self, subpath, query, user=None):
        if subpath != "state":
            return None
        payload = json.dumps(self._state(), ensure_ascii=False).encode("utf-8")
        return 200, "application/json; charset=utf-8", payload

    def health(self):
        state = self._state()
        statuses = {item["status"] for item in state["observers"].values()}
        return {
            "slug": self.slug,
            "status": "ok" if statuses == {"fresh"} else "degraded",
            "mode": "research", "execution": False,
        }


def get_module(context):
    return HypothesisLabModule(context)
