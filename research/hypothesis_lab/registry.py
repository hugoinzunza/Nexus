"""SQLite operational registry: immutable preregistration, runs, trials, candidates."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .contracts import ContractError, Spec, canonical_json


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS preregistrations (
  hypothesis_id TEXT PRIMARY KEY, spec_sha256 TEXT NOT NULL, spec_json BLOB NOT NULL,
  registered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, hypothesis_id TEXT NOT NULL, started_at TEXT NOT NULL,
  completed_at TEXT, status TEXT NOT NULL, manifest_json BLOB NOT NULL,
  total_trials INTEGER NOT NULL DEFAULT 0, FOREIGN KEY(hypothesis_id) REFERENCES preregistrations(hypothesis_id)
);
CREATE TABLE IF NOT EXISTS trials (
  run_id TEXT NOT NULL, trial_no INTEGER NOT NULL, pair TEXT NOT NULL, timeframe TEXT NOT NULL,
  target_id TEXT NOT NULL, cost_id TEXT NOT NULL, status TEXT NOT NULL, candidate_count INTEGER NOT NULL,
  PRIMARY KEY(run_id, trial_no), FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS candidates (
  run_id TEXT NOT NULL, trial_no INTEGER NOT NULL, setup_id TEXT NOT NULL, decision_ts INTEGER,
  activation_ts INTEGER, resolution_ts INTEGER, status TEXT NOT NULL, discarded_reason TEXT,
  gross_r REAL, cost_r REAL, net_r REAL, payload_json BLOB NOT NULL,
  PRIMARY KEY(run_id, trial_no, setup_id), FOREIGN KEY(run_id, trial_no) REFERENCES trials(run_id, trial_no)
);
"""


class Registry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def preregister(self, spec: Spec, registered_at: str) -> str:
        row = self.db.execute(
            "SELECT spec_sha256 FROM preregistrations WHERE hypothesis_id=?", (spec.hypothesis_id,)
        ).fetchone()
        if row and row[0] != spec.sha256:
            raise ContractError(f"immutable preregistration conflict for {spec.hypothesis_id}")
        if not row:
            self.db.execute(
                "INSERT INTO preregistrations VALUES(?,?,?,?)",
                (spec.hypothesis_id, spec.sha256, canonical_json(spec.raw), registered_at),
            )
            self.db.commit()
        return spec.sha256

    def start_run(self, run_id: str, spec: Spec, started_at: str, manifest: dict[str, Any]) -> None:
        self.db.execute("INSERT INTO runs(run_id,hypothesis_id,started_at,status,manifest_json) VALUES(?,?,?,?,?)",
                        (run_id, spec.hypothesis_id, started_at, "running", canonical_json(manifest)))
        self.db.commit()

    def add_trial(self, run_id: str, trial_no: int, pair: str, timeframe: str,
                  target_id: str, cost_id: str, candidates: Iterable[dict[str, Any]]) -> int:
        rows = list(candidates)
        status = "completed" if rows else "completed_empty_stratum"
        with self.db:
            self.db.execute("INSERT INTO trials VALUES(?,?,?,?,?,?,?,?)",
                            (run_id, trial_no, pair, timeframe, target_id, cost_id, status, len(rows)))
            self.db.executemany(
                "INSERT INTO candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                [(run_id, trial_no, r["setup_id"], r.get("decision_timestamp"),
                  r.get("activation_timestamp"), r.get("resolution_timestamp"), r["status"],
                  r.get("discarded_reason"), r.get("gross_r"), r.get("cost_r"), r.get("net_r"),
                  canonical_json(r)) for r in rows],
            )
        return len(rows)

    def finish_run(self, run_id: str, completed_at: str, total_trials: int,
                   manifest: dict[str, Any]) -> None:
        with self.db:
            actual = self.db.execute("SELECT COUNT(*) FROM trials WHERE run_id=?", (run_id,)).fetchone()[0]
            if actual != total_trials:
                raise ContractError(f"trial accounting mismatch: expected {total_trials}, stored {actual}")
            self.db.execute("UPDATE runs SET completed_at=?,status='completed',manifest_json=?,total_trials=? WHERE run_id=?",
                            (completed_at, canonical_json(manifest), actual, run_id))

    def fail_run(self, run_id: str, completed_at: str, error: str, manifest: dict[str, Any]) -> None:
        failed = {**manifest, "failed_at": completed_at, "error": error}
        with self.db:
            actual = self.db.execute("SELECT COUNT(*) FROM trials WHERE run_id=?", (run_id,)).fetchone()[0]
            self.db.execute("UPDATE runs SET completed_at=?,status='failed',manifest_json=?,total_trials=? WHERE run_id=?",
                            (completed_at, canonical_json(failed), actual, run_id))
