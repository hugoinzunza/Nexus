"""Versioned contracts and strict validation for Hypothesis Lab artifacts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import NOTICE


class ContractError(ValueError):
    """An artifact violates a scientific or serialization contract."""


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class Spec:
    path: Path
    raw: dict[str, Any]
    sha256: str

    @property
    def hypothesis_id(self) -> str:
        return str(self.raw["hypothesis_id"])

    @property
    def trial_budget(self) -> int:
        return int(self.raw["trial_budget"])

    @property
    def pairs(self) -> tuple[str, ...]:
        return tuple(self.raw["dataset"]["pairs"])

    @property
    def timeframes(self) -> tuple[str, ...]:
        return tuple(self.raw["dataset"]["timeframes"])

    @property
    def targets(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.raw["design"]["targets"])

    @property
    def costs(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.raw["design"]["cost_scenarios"])


def load_spec(path: str | Path) -> Spec:
    p = Path(path).resolve()
    raw_bytes = p.read_bytes()
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON spec: {exc}") from exc
    required = {"schema_version", "hypothesis_id", "frozen", "research_only", "notice",
                "trial_budget", "seed", "dataset", "design", "statistics", "sizing",
                "dependence", "governance"}
    missing = sorted(required - raw.keys())
    if missing:
        raise ContractError(f"spec missing keys: {missing}")
    if raw["schema_version"] != 1 or raw["frozen"] is not True:
        raise ContractError("only frozen schema_version=1 specs may run")
    if raw["research_only"] is not True or raw["notice"] != NOTICE:
        raise ContractError("research-only notice is mandatory")
    pairs, tfs = raw["dataset"].get("pairs", []), raw["dataset"].get("timeframes", [])
    targets = raw["design"].get("targets", [])
    costs = raw["design"].get("cost_scenarios", [])
    expected = len(pairs) * len(tfs) * len(targets) * len(costs)
    if raw["trial_budget"] != expected:
        raise ContractError(f"trial_budget={raw['trial_budget']} but factorial design requires {expected}")
    if len({x["id"] for x in targets}) != len(targets) or not any(x["id"] == "original" for x in targets):
        raise ContractError("target ids must be unique and include original")
    if len({x["id"] for x in costs}) != len(costs):
        raise ContractError("cost scenario ids must be unique")
    if any(float(x["total_rate"]) < 0 for x in costs):
        raise ContractError("cost rates cannot be negative")
    if raw["statistics"].get("bootstrap", {}).get("unit") != "calendar_month":
        raise ContractError("v1 requires calendar-month block bootstrap")
    if raw["statistics"].get("multiple_testing") != "holm":
        raise ContractError("Holm correction is mandatory")
    if raw["statistics"].get("multiple_testing_family") != "unique_target_vs_original_paired_differences_cost_invariant":
        raise ContractError("v1 requires one Holm family of unique target comparisons")
    if raw["governance"].get("automatic_winner_selection") is not False:
        raise ContractError("automatic winner selection must be disabled")
    return Spec(p, raw, sha256_bytes(raw_bytes))
