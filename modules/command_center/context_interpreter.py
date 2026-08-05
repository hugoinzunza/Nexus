"""Interpretacion determinista de historia causal registrada por NexUX."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path
from typing import Callable

from .context_recorder import (
    ContextRecorderIntegrityError,
    load_verified_events,
)


INTERPRETATION_SCHEMA = "nexux.context.interpretation.v1"
ONE_HOUR_MS = 60 * 60_000
SUPPORTED_HORIZONS_MS = frozenset({ONE_HOUR_MS})
_BASELINE_TOLERANCE_MS = 60_000
_MAX_SAMPLE_GAP_MS = 90_000
_MAX_LATEST_AGE_MS = 2 * 60_000
_CLOCK_TOLERANCE_MS = 30_000
_COMPARABLE_FRESHNESS = frozenset({"live", "current"})


class MarketContextInterpreter:
    """Describe cambios observados sin pronosticar ni reconstruir historia."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock_ms: Callable[[], int] | None = None,
        event_loader: Callable[[], list[dict]] | None = None,
    ):
        self.path = Path(path)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._event_loader = event_loader or (
            lambda: load_verified_events(self.path)
        )
        self._lock = threading.Lock()
        self._requests = 0
        self._claims = 0
        self._abstentions = 0
        self._integrity_failures = 0
        self._last_reason: str | None = None

    def compare(self, asset_id: str, *, horizon_ms: int = ONE_HOUR_MS) -> dict:
        """Compara dos observaciones verificadas o se abstiene con una razon."""
        normalized_id = str(asset_id or "").strip().lower()
        with self._lock:
            self._requests += 1
        if not normalized_id:
            return self._abstain("invalid_asset", normalized_id, horizon_ms)
        if horizon_ms not in SUPPORTED_HORIZONS_MS:
            return self._abstain("unsupported_horizon", normalized_id, horizon_ms)

        try:
            events = self._event_loader()
        except ContextRecorderIntegrityError:
            with self._lock:
                self._integrity_failures += 1
            return self._abstain("integrity_failure", normalized_id, horizon_ms)
        except (OSError, RuntimeError):
            return self._abstain("history_unavailable", normalized_id, horizon_ms)
        if not events:
            return self._abstain("no_history", normalized_id, horizon_ms)

        samples = self._samples(events, normalized_id)
        if not samples:
            return self._abstain("asset_unobserved", normalized_id, horizon_ms)
        if any(
            later["captured_at_ms"] < earlier["captured_at_ms"]
            for earlier, later in zip(samples, samples[1:])
        ):
            return self._abstain("capture_time_regressed", normalized_id, horizon_ms)
        if any(
            later["observed_at_ms"] < earlier["observed_at_ms"]
            for earlier, later in zip(samples, samples[1:])
        ):
            return self._abstain("observation_time_regressed", normalized_id, horizon_ms)
        current = samples[-1]
        now_ms = self._clock_ms()
        if current["captured_at_ms"] > now_ms + _CLOCK_TOLERANCE_MS:
            return self._abstain("future_capture", normalized_id, horizon_ms)
        current_age_ms = now_ms - current["observed_at_ms"]
        if current_age_ms < -_CLOCK_TOLERANCE_MS:
            return self._abstain("future_observation", normalized_id, horizon_ms)
        if current_age_ms > _MAX_LATEST_AGE_MS:
            return self._abstain("stale_history", normalized_id, horizon_ms)

        target_ms = current["captured_at_ms"] - horizon_ms
        candidates = [
            sample
            for sample in samples[:-1]
            if abs(sample["captured_at_ms"] - target_ms)
            <= _BASELINE_TOLERANCE_MS
        ]
        if not candidates:
            return self._abstain(
                "insufficient_history",
                normalized_id,
                horizon_ms,
            )
        baseline = min(
            candidates,
            key=lambda sample: (
                abs(sample["captured_at_ms"] - target_ms),
                -sample["captured_at_ms"],
            ),
        )
        window = [
            sample
            for sample in samples
            if baseline["captured_at_ms"]
            <= sample["captured_at_ms"]
            <= current["captured_at_ms"]
        ]
        sources = {sample["source"] for sample in window}
        if len(sources) != 1:
            return self._abstain("source_changed", normalized_id, horizon_ms)
        gaps = [
            later["captured_at_ms"] - earlier["captured_at_ms"]
            for earlier, later in zip(window, window[1:])
        ]
        max_gap_ms = max(gaps, default=0)
        if max_gap_ms > _MAX_SAMPLE_GAP_MS:
            return self._abstain("coverage_gap", normalized_id, horizon_ms)

        observed_window_ms = (
            current["captured_at_ms"] - baseline["captured_at_ms"]
        )
        baseline_price = baseline["price"]
        delta_price = current["price"] - baseline_price
        delta_pct = (delta_price / baseline_price) * 100
        direction = "up" if delta_price > 0 else "down" if delta_price < 0 else "flat"
        statement = self._statement(
            normalized_id,
            direction,
            delta_pct,
            observed_window_ms,
        )
        result = {
            "schema": INTERPRETATION_SCHEMA,
            "status": "observed_change",
            "reason": None,
            "asset_id": normalized_id,
            "horizon_ms": horizon_ms,
            "direction": direction,
            "delta_price": round(delta_price, 8),
            "delta_pct": round(delta_pct, 8),
            "statement": statement,
            "basis": "stored_snapshots_only",
            "evidence": {
                "baseline_sequence": baseline["sequence"],
                "baseline_event_hash": baseline["event_hash"],
                "baseline_captured_at_ms": baseline["captured_at_ms"],
                "baseline_observed_at_ms": baseline["observed_at_ms"],
                "baseline_price": baseline_price,
                "current_sequence": current["sequence"],
                "current_event_hash": current["event_hash"],
                "current_captured_at_ms": current["captured_at_ms"],
                "current_observed_at_ms": current["observed_at_ms"],
                "current_price": current["price"],
                "source": current["source"],
                "sample_count": len(window),
                "observed_window_ms": observed_window_ms,
                "max_gap_ms": max_gap_ms,
            },
        }
        with self._lock:
            self._claims += 1
            self._last_reason = None
        return result

    def stats(self) -> dict:
        with self._lock:
            return {
                "schema": INTERPRETATION_SCHEMA,
                "status": "ready",
                "supported_horizons_ms": sorted(SUPPORTED_HORIZONS_MS),
                "requests": self._requests,
                "claims": self._claims,
                "abstentions": self._abstentions,
                "integrity_failures": self._integrity_failures,
                "last_reason": self._last_reason,
            }

    @staticmethod
    def _samples(events: list[dict], asset_id: str) -> list[dict]:
        samples = []
        for event in events:
            snapshot = event.get("snapshot", {})
            for asset in snapshot.get("assets", []):
                if str(asset.get("id") or "").lower() != asset_id:
                    continue
                price = asset.get("price")
                observed_at_ms = asset.get("observed_at_ms")
                source = asset.get("source")
                if (
                    isinstance(price, bool)
                    or not isinstance(price, (int, float))
                    or not math.isfinite(price)
                    or price <= 0
                    or not isinstance(observed_at_ms, int)
                    or not source
                    or asset.get("freshness") not in _COMPARABLE_FRESHNESS
                ):
                    continue
                samples.append(
                    {
                        "sequence": event["sequence"],
                        "event_hash": event["event_hash"],
                        "captured_at_ms": event["captured_at_ms"],
                        "observed_at_ms": observed_at_ms,
                        "price": price,
                        "source": source,
                    }
                )
                break
        return samples

    def _abstain(self, reason: str, asset_id: str, horizon_ms: int) -> dict:
        with self._lock:
            self._abstentions += 1
            self._last_reason = reason
        return {
            "schema": INTERPRETATION_SCHEMA,
            "status": "insufficient_evidence",
            "reason": reason,
            "asset_id": asset_id,
            "horizon_ms": horizon_ms,
            "statement": None,
            "basis": "stored_snapshots_only",
            "evidence": None,
        }

    @staticmethod
    def _statement(
        asset_id: str,
        direction: str,
        delta_pct: float,
        observed_window_ms: int,
    ) -> str:
        minutes = round(observed_window_ms / 60_000)
        magnitude = f"{abs(delta_pct):.4f}".rstrip("0").rstrip(".")
        label = asset_id.upper()
        if direction == "flat":
            return (
                f"{label} no vario entre observaciones registradas "
                f"separadas por {minutes} min."
            )
        verb = "subio" if direction == "up" else "bajo"
        return (
            f"{label} {verb} {magnitude}% entre observaciones registradas "
            f"separadas por {minutes} min."
        )
