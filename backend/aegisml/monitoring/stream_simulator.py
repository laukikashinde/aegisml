"""
AegisML-Lite — Production Stream Simulator.

Continuously generates Adult Income records at a configurable rate.
Supports:
  - Normal production mode
  - Delayed ground-truth label arrival
  - F1 covariate drift injection
  - F2 concept drift injection
  - F4 data quality fault injection
  - Configurable stream speed
  - State transitions between modes

The stream feeds directly into the monitoring engine.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

# ── State ─────────────────────────────────────────────────────────────────────

@dataclass
class StreamState:
    running: bool = False
    mode: str = "NORMAL"           # NORMAL | F1_COVARIATE | F2_CONCEPT | F4_QUALITY
    records_processed: int = 0
    records_per_second: float = 2.0
    started_at: Optional[str] = None
    last_record_at: Optional[str] = None
    drift_config: dict = field(default_factory=dict)
    pending_labels: list = field(default_factory=list)  # delayed ground truth
    recent_predictions: list = field(default_factory=list)
    recent_actuals: list = field(default_factory=list)
    error_count: int = 0

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "mode": self.mode,
            "records_processed": self.records_processed,
            "records_per_second": self.records_per_second,
            "started_at": self.started_at,
            "last_record_at": self.last_record_at,
            "drift_config": self.drift_config,
            "pending_labels_count": len(self.pending_labels),
            "error_count": self.error_count,
        }


class StreamSimulator:
    """
    Background thread that emits synthetic Adult Income records continuously.
    Observers can register callbacks to receive each batch of records.
    """

    def __init__(self, records_per_second: float = 2.0):
        self.state = StreamState(records_per_second=records_per_second)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._observers: list[Callable] = []
        self._rng = np.random.default_rng(42)
        self._lock = threading.Lock()
        self._batch_size = 5  # records per emission cycle

    # ── Control ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self.state.running:
            return
        self._stop_event.clear()
        self.state.running = True
        self.state.started_at = datetime.now(timezone.utc).isoformat()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="stream-simulator"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.state.running = False
        if self._thread:
            self._thread.join(timeout=3)

    def set_mode(self, mode: str, drift_config: dict | None = None) -> None:
        """
        Change the stream mode. Valid modes:
          NORMAL, F1_COVARIATE, F2_CONCEPT, F4_QUALITY
        """
        valid = {"NORMAL", "F1_COVARIATE", "F2_CONCEPT", "F4_QUALITY"}
        if mode not in valid:
            raise ValueError(f"Unknown mode: {mode}. Valid: {valid}")
        with self._lock:
            self.state.mode = mode
            self.state.drift_config = drift_config or _DRIFT_PRESETS.get(mode, {})

    def reset_to_normal(self) -> None:
        with self._lock:
            self.state.mode = "NORMAL"
            self.state.drift_config = {}

    def add_observer(self, callback: Callable[[list[dict]], None]) -> None:
        """Register a callback that receives a list of record dicts per batch."""
        self._observers.append(callback)

    def get_state(self) -> dict:
        return self.state.to_dict()

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        interval = self._batch_size / max(self.state.records_per_second, 0.1)
        while not self._stop_event.is_set():
            t0 = time.perf_counter()
            try:
                with self._lock:
                    mode = self.state.mode
                    drift_config = dict(self.state.drift_config)

                batch = self._generate_batch(self._batch_size, mode, drift_config)
                self.state.records_processed += len(batch)
                self.state.last_record_at = datetime.now(timezone.utc).isoformat()

                for obs in self._observers:
                    try:
                        obs(batch)
                    except Exception:
                        self.state.error_count += 1

                # Simulate delayed ground truth (arrive ~30s later)
                self._schedule_labels(batch)

            except Exception:
                self.state.error_count += 1

            elapsed = time.perf_counter() - t0
            sleep_time = max(0, interval - elapsed)
            self._stop_event.wait(timeout=sleep_time)

    # ── Record generation ─────────────────────────────────────────────────────

    def _generate_batch(
        self, n: int, mode: str, drift_config: dict
    ) -> list[dict]:
        rng = self._rng
        records = []

        # Base feature distributions (Adult Income)
        ages = rng.normal(38.6, 13.6, n).clip(17, 90).round()
        education_nums = rng.normal(10.1, 2.6, n).clip(1, 16).round()
        hours = rng.normal(40.4, 12.3, n).clip(1, 99).round()
        capital_gains = np.where(rng.random(n) < 0.08,
                                 rng.lognormal(8.5, 1.5, n).clip(1, 99999), 0.0)
        capital_losses = np.where(rng.random(n) < 0.05,
                                  rng.lognormal(7.0, 1.0, n).clip(1, 4999), 0.0)
        fnlwgts = rng.lognormal(11.2, 0.6, n).clip(10000, 1500000).round()

        workclasses = rng.choice(
            ["Private", "Self-emp-not-inc", "Self-emp-inc",
             "Federal-gov", "Local-gov", "State-gov", "Without-pay"],
            p=[0.69, 0.08, 0.035, 0.03, 0.065, 0.04, 0.06],
            size=n,
        )
        marital_statuses = rng.choice(
            ["Married-civ-spouse", "Divorced", "Never-married",
             "Separated", "Widowed", "Married-spouse-absent"],
            p=[0.459, 0.135, 0.328, 0.034, 0.026, 0.018],
            size=n,
        )
        occupations = rng.choice(
            ["Tech-support", "Craft-repair", "Other-service", "Sales",
             "Exec-managerial", "Prof-specialty", "Handlers-cleaners",
             "Machine-op-inspct", "Adm-clerical", "Farming-fishing",
             "Transport-moving", "Priv-house-serv", "Protective-serv"],
            size=n,
        )
        sexes = rng.choice(["Male", "Female"], p=[0.669, 0.331], size=n)
        races = rng.choice(
            ["White", "Asian-Pac-Islander", "Amer-Indian-Eskimo", "Other", "Black"],
            p=[0.855, 0.031, 0.009, 0.008, 0.097], size=n,
        )
        relationships = rng.choice(
            ["Wife", "Own-child", "Husband", "Not-in-family", "Other-relative", "Unmarried"],
            p=[0.103, 0.157, 0.404, 0.192, 0.032, 0.112], size=n,
        )
        educations = rng.choice(
            ["Bachelors", "Some-college", "HS-grad", "Masters", "Assoc-voc",
             "11th", "Assoc-acdm", "10th", "Doctorate", "Prof-school", "9th"],
            size=n,
        )

        # ── Apply drift ───────────────────────────────────────────────────────
        if mode == "F1_COVARIATE":
            ages = (ages + drift_config.get("age_shift", 8)).clip(17, 90)
            hours = (hours * drift_config.get("hours_scale", 1.3)).clip(1, 99)
            education_nums = (education_nums + drift_config.get("edu_shift", 2)).clip(1, 16)

        elif mode == "F4_QUALITY":
            miss_rate = drift_config.get("missing_rate", 0.35)
            invalid_rate = drift_config.get("invalid_rate", 0.10)
            # Inject missingness
            missing_mask = rng.random(n) < miss_rate
            ages = ages.astype(object)
            ages[missing_mask] = None
            # Inject range violations
            invalid_mask = rng.random(n) < invalid_rate
            valid_age_arr = np.array(ages, dtype=object)
            valid_age_arr[invalid_mask] = rng.choice([-5, 999, -1], size=invalid_mask.sum())
            ages = valid_age_arr
            # Unknown categories
            unk_mask = rng.random(n) < drift_config.get("unknown_cat_rate", 0.15)
            wc_arr = list(workclasses)
            for i in np.where(unk_mask)[0]:
                wc_arr[i] = "UNKNOWN"
            workclasses = np.array(wc_arr)

        # Build records
        for i in range(n):
            record = {
                "record_id": str(uuid.uuid4()),
                "stream_timestamp": datetime.now(timezone.utc).isoformat(),
                "stream_mode": mode,
                # Features
                "age":            _safe_float(ages[i]),
                "fnlwgt":         float(fnlwgts[i]),
                "education":      str(educations[i]),
                "education_num":  _safe_float(education_nums[i]),
                "marital_status": str(marital_statuses[i]),
                "occupation":     str(occupations[i]),
                "relationship":   str(relationships[i]),
                "race":           str(races[i]),
                "sex":            str(sexes[i]),
                "capital_gain":   float(capital_gains[i]),
                "capital_loss":   float(capital_losses[i]),
                "hours_per_week": _safe_float(hours[i]),
                "workclass":      str(workclasses[i]),
                "native_country": "United-States",
                # Ground truth arrives later (concept drift check uses this)
                "true_label": None,
                "mode": mode,
            }
            records.append(record)

        # For concept drift mode: deliberately corrupt labels later
        if mode == "F2_CONCEPT":
            # Mark records — actual labels will flip when delivered
            for r in records:
                r["concept_drift_active"] = True

        return records

    def _schedule_labels(self, batch: list[dict]) -> None:
        """Schedule ground-truth labels to arrive ~30 seconds later."""
        arrival_time = time.time() + 30.0
        self.state.pending_labels.append({
            "records": batch,
            "arrive_at": arrival_time,
        })
        # Keep only last 1000 pending label batches
        if len(self.state.pending_labels) > 1000:
            self.state.pending_labels = self.state.pending_labels[-1000:]

    def collect_arrived_labels(self) -> list[dict]:
        """Return all label batches whose arrival time has passed."""
        now = time.time()
        arrived = []
        remaining = []
        for entry in self.state.pending_labels:
            if entry["arrive_at"] <= now:
                arrived.extend(entry["records"])
            else:
                remaining.append(entry)
        self.state.pending_labels = remaining
        return arrived


# ── Drift presets ─────────────────────────────────────────────────────────────

_DRIFT_PRESETS: dict[str, dict] = {
    "F1_COVARIATE": {
        "age_shift": 8,
        "hours_scale": 1.3,
        "edu_shift": 2,
    },
    "F2_CONCEPT": {},   # handled in generation logic
    "F4_QUALITY": {
        "missing_rate": 0.35,
        "invalid_rate": 0.10,
        "unknown_cat_rate": 0.15,
    },
}


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v  # keep invalid values for F4 detection


# ── Module-level singleton ────────────────────────────────────────────────────

_SIMULATOR: Optional[StreamSimulator] = None


def get_simulator() -> StreamSimulator:
    global _SIMULATOR
    if _SIMULATOR is None:
        _SIMULATOR = StreamSimulator(records_per_second=2.0)
    return _SIMULATOR
