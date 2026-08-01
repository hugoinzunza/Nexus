from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.hypothesis_lab import NOTICE
from research.hypothesis_lab.contracts import ContractError, Spec, load_spec
from research.hypothesis_lab.registry import Registry

ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "research/hypothesis_lab/specs/v1/HYP-EXIT-001.frozen.json"


def test_frozen_spec_has_exact_authorized_factorial():
    spec = load_spec(SPEC_PATH)
    assert spec.trial_budget == 210
    assert spec.pairs == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT")
    assert spec.timeframes == ("1h", "4h")
    assert [x["rr"] for x in spec.targets] == [.5, .75, 1.0, 2.0, 3.0, 5.0, None]
    assert [x["id"] for x in spec.costs] == ["base", "hard", "extreme"]
    assert spec.raw["dataset"]["classification"] == "recycled_research_data"
    assert spec.raw["statistics"]["multiple_testing_family"].startswith("unique_target")
    assert spec.raw["notice"] == NOTICE


def test_preregistration_is_immutable_and_precedes_runs(tmp_path):
    spec = load_spec(SPEC_PATH)
    registry = Registry(tmp_path / "lab.sqlite3")
    registry.preregister(spec, "before")
    registry.preregister(spec, "same-is-idempotent")
    mutated = Spec(spec.path, {**spec.raw, "seed": 99}, "different-sha")
    with pytest.raises(ContractError, match="immutable"):
        registry.preregister(mutated, "after")
    registry.close()


def test_trial_budget_accounting_and_discarded_candidate_persistence(tmp_path):
    spec = load_spec(SPEC_PATH)
    registry = Registry(tmp_path / "lab.sqlite3")
    registry.preregister(spec, "t0")
    registry.start_run("r1", spec, "t1", {})
    discarded = {"setup_id": "s", "status": "discarded", "discarded_reason": "not_activated",
                 "gross_r": None, "cost_r": None, "net_r": None}
    registry.add_trial("r1", 1, "BTCUSDT", "1h", "rr_1", "base", [discarded])
    with pytest.raises(ContractError, match="accounting mismatch"):
        registry.finish_run("r1", "t2", 2, {})
    saved = registry.db.execute("SELECT status,discarded_reason FROM candidates").fetchone()
    assert saved == ("discarded", "not_activated")
    registry.close()


def test_lab_has_no_execution_module_imports_or_promotion_surface():
    lab = ROOT / "research/hypothesis_lab"
    sources = "\n".join(p.read_text(encoding="utf-8") for p in lab.glob("*.py"))
    assert "from modules." not in sources and "import modules." not in sources
    assert "promotion_available\": False" in sources
    assert NOTICE in sources


def test_contract_requires_one_global_holm_family(tmp_path):
    spec = load_spec(SPEC_PATH)
    raw = json.loads(json.dumps(spec.raw))
    raw["statistics"]["multiple_testing_family"] = "by_cost"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError, match="unique target"):
        load_spec(path)
