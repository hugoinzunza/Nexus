"""Dataset loading, hashing, provenance labels and export validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import ContractError, Spec, sha256_file


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def validate_setup_provenance(row: dict[str, Any], rows: list[dict[str, Any]], n: int) -> None:
    decision = row["decision_index"]
    activation = row["activation_index"]
    if not isinstance(decision, int) or not 0 <= decision < len(rows):
        raise ContractError(f"setup row {n} has invalid decision_index")
    if rows[decision]["t"] != row["decision_timestamp"]:
        raise ContractError(f"setup row {n} decision timestamp/index mismatch")
    source = row["original_tp_source"]
    if not isinstance(source, dict) or source.get("kind") not in {
        "confirmed_swing_level", "dealing_range"
    }:
        raise ContractError(f"setup row {n} has invalid original_tp_source")
    if source.get("confirm_t") is None or source["confirm_t"] > row["decision_timestamp"]:
        raise ContractError(f"setup row {n} original target was not confirmed at decision")
    if source.get("source_t") is None or source["source_t"] > row["decision_timestamp"]:
        raise ContractError(f"setup row {n} original target source is in the future")
    tolerance = max(1e-9, abs(float(row["original_tp"])) * 1e-9)
    if abs(float(source.get("price", 0.0)) - float(row["original_tp"])) > tolerance:
        raise ContractError(f"setup row {n} original target/source price mismatch")
    if activation is not None:
        if not isinstance(activation, int) or not decision <= activation < len(rows):
            raise ContractError(f"setup row {n} has invalid activation_index")
        if rows[activation]["t"] != row["activation_timestamp"]:
            raise ContractError(f"setup row {n} activation timestamp/index mismatch")


def load_inputs(root: Path, spec: Spec) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]], list[dict[str, Any]]]:
    export_path = root / spec.raw["dataset"]["setup_export"]
    if not export_path.is_file():
        raise ContractError(f"missing enriched setup export: {export_path}; run the research exporter first")
    setups = load_json(export_path)
    if not isinstance(setups, list):
        raise ContractError("setup export must remain a JSON list")
    required = {"research_export_version", "setup_id", "pair", "sel_tf", "dir", "entry", "sl",
                "original_tp", "original_tp_source", "decision_index", "decision_timestamp", "activation_index",
                "activation_timestamp", "max_forward_bars", "dataset_refs"}
    for n, row in enumerate(setups):
        missing = required - row.keys()
        if missing:
            raise ContractError(f"setup row {n} is legacy/incomplete; missing {sorted(missing)}")
        if row["research_export_version"] != "setup-backtest-research-v3":
            raise ContractError(f"setup row {n} requires setup-backtest-research-v3")
    setup_ids = [row["setup_id"] for row in setups]
    if len(setup_ids) != len(set(setup_ids)):
        raise ContractError("setup export contains duplicate setup_id values")
    candles: dict[tuple[str, str], list[dict[str, Any]]] = {}
    files = [export_path]
    for pair in spec.pairs:
        for tf in spec.timeframes:
            p = root / spec.raw["dataset"]["candle_pattern"].format(pair=pair, timeframe=tf)
            if not p.is_file():
                raise ContractError(f"missing candle dataset: {p}")
            rows = load_json(p)
            if any(rows[i]["t"] >= rows[i + 1]["t"] for i in range(len(rows) - 1)):
                raise ContractError(f"candles are not strictly ordered: {p}")
            candles[(pair, tf)] = rows
            files.append(p)
    for n, row in enumerate(setups):
        key = (row["pair"], row["sel_tf"])
        if key not in candles:
            continue
        rows = candles[key]
        validate_setup_provenance(row, rows, n)
    manifests = [{"path": str(p.relative_to(root)), "sha256": sha256_file(p), "bytes": p.stat().st_size}
                 for p in sorted(files)]
    return setups, candles, manifests
