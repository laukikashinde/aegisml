"""
AegisML-Lite — Baseline Experiment Framework.

S0 — No Healing:        Detects failures but does NOT remediate.
S1 — Scheduled Retrain: Retrains on a fixed schedule regardless of failure state.
S2 — AegisML-Lite:      Full self-healing (detection → diagnosis → targeted remediation).

Each baseline run is persisted and compared via MTTD, MTTR,
false alarm rate, wasted retrains, and remediation correctness.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from aegisml.database.models import AuditLog


@dataclass
class ExperimentRun:
    """A single experiment run result."""
    run_id: str
    system: str              # S0 | S1 | S2
    failure_type: str        # F1 | F2 | F3 | F4
    started_at: str
    completed_at: str | None = None

    # Detection
    failure_injected_at: str | None = None
    failure_detected_at: str | None = None
    mttd_seconds: float | None = None        # Mean Time To Detect

    # Recovery
    recovery_started_at: str | None = None
    recovery_completed_at: str | None = None
    mttr_seconds: float | None = None        # Mean Time To Recover

    # Quality
    recovered: bool = False
    false_alarm: bool = False                # detected without real failure
    remediation_correct: bool | None = None  # matched expected action
    wasted_retrain: bool = False             # retrained when not needed (S1)

    # Details
    incident_id: str | None = None
    action_taken: str | None = None
    notes: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "system": self.system,
            "failure_type": self.failure_type,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "mttd_seconds": self.mttd_seconds,
            "mttr_seconds": self.mttr_seconds,
            "recovered": self.recovered,
            "false_alarm": self.false_alarm,
            "remediation_correct": self.remediation_correct,
            "wasted_retrain": self.wasted_retrain,
            "incident_id": self.incident_id,
            "action_taken": self.action_taken,
            "notes": self.notes,
        }


# In-memory store (persisted to AuditLog for durability)
_EXPERIMENT_RUNS: list[ExperimentRun] = []


def record_run(run: ExperimentRun, db: Session | None = None) -> None:
    _EXPERIMENT_RUNS.append(run)
    if db:
        log = AuditLog(
            event_type="EXPERIMENT_RUN_RECORDED",
            actor="experiment_framework",
            description=f"Experiment {run.system} / {run.failure_type}: "
                        f"MTTD={run.mttd_seconds}s MTTR={run.mttr_seconds}s "
                        f"recovered={run.recovered}",
            details=run.to_dict(),
            outcome="SUCCESS",
            occurred_at=datetime.now(timezone.utc),
        )
        db.add(log)
        db.flush()


def get_all_runs() -> list[dict]:
    return [r.to_dict() for r in _EXPERIMENT_RUNS]


def compute_summary() -> dict:
    """Compute aggregate metrics across all recorded experiment runs."""
    if not _EXPERIMENT_RUNS:
        return {"total_runs": 0, "systems": {}}

    systems: dict[str, list[ExperimentRun]] = {}
    for run in _EXPERIMENT_RUNS:
        systems.setdefault(run.system, []).append(run)

    summary: dict[str, Any] = {"total_runs": len(_EXPERIMENT_RUNS), "systems": {}}

    for sys_name, runs in systems.items():
        mttds = [r.mttd_seconds for r in runs if r.mttd_seconds is not None]
        mttrs = [r.mttr_seconds for r in runs if r.mttr_seconds is not None]
        n = len(runs)

        summary["systems"][sys_name] = {
            "total_runs": n,
            "avg_mttd_seconds":       round(sum(mttds) / len(mttds), 1) if mttds else None,
            "avg_mttr_seconds":       round(sum(mttrs) / len(mttrs), 1) if mttrs else None,
            "recovery_rate":          round(sum(1 for r in runs if r.recovered) / n, 3),
            "false_alarm_rate":       round(sum(1 for r in runs if r.false_alarm) / n, 3),
            "remediation_correct_rate": round(
                sum(1 for r in runs if r.remediation_correct is True) /
                max(1, sum(1 for r in runs if r.remediation_correct is not None)), 3
            ),
            "wasted_retrain_count":   sum(1 for r in runs if r.wasted_retrain),
            "runs": [r.to_dict() for r in runs],
        }

    return summary


def simulate_s0_run(
    failure_type: str,
    mttd_seconds: float,
    db: Session | None = None,
) -> ExperimentRun:
    """
    S0 — No Healing.
    Detects the failure but takes NO remediation action.
    MTTR = None (never recovers automatically).
    """
    run = ExperimentRun(
        run_id=str(uuid.uuid4()),
        system="S0",
        failure_type=failure_type,
        started_at=datetime.now(timezone.utc).isoformat(),
        mttd_seconds=mttd_seconds,
        mttr_seconds=None,
        recovered=False,
        remediation_correct=None,
        wasted_retrain=False,
        notes="S0: failure detected, no automatic remediation.",
    )
    run.completed_at = datetime.now(timezone.utc).isoformat()
    record_run(run, db)
    return run


def simulate_s1_run(
    failure_type: str,
    mttd_seconds: float,
    schedule_interval_seconds: float,
    failure_actually_occurred: bool,
    db: Session | None = None,
) -> ExperimentRun:
    """
    S1 — Scheduled Retraining.
    Retrains every N seconds regardless of failure state.
    If no failure occurred this cycle → wasted retrain.
    Recovery time = time until next scheduled retrain.
    """
    wasted = not failure_actually_occurred
    # Recovery time ≈ remaining time in schedule cycle
    import random
    mttr = random.uniform(0, schedule_interval_seconds) if failure_actually_occurred else None

    run = ExperimentRun(
        run_id=str(uuid.uuid4()),
        system="S1",
        failure_type=failure_type,
        started_at=datetime.now(timezone.utc).isoformat(),
        mttd_seconds=mttd_seconds,
        mttr_seconds=mttr,
        recovered=failure_actually_occurred,
        remediation_correct=failure_actually_occurred,  # retraining always correct for drift
        wasted_retrain=wasted,
        notes=f"S1: scheduled retrain (interval={schedule_interval_seconds}s). "
              f"{'Wasted — no real failure.' if wasted else 'Recovery via scheduled cycle.'}",
    )
    run.completed_at = datetime.now(timezone.utc).isoformat()
    record_run(run, db)
    return run
