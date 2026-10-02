"""Experiments (S0/S1/S2 baselines) API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from aegisml.database.base import get_db
from aegisml.experiments.baselines import (
    compute_summary, get_all_runs, simulate_s0_run, simulate_s1_run,
)

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


class S0RunRequest(BaseModel):
    failure_type: str = "F1"
    mttd_seconds: float = 45.0


class S1RunRequest(BaseModel):
    failure_type: str = "F1"
    mttd_seconds: float = 45.0
    schedule_interval_seconds: float = 300.0
    failure_actually_occurred: bool = True


@router.get("/summary")
def get_summary():
    return compute_summary()


@router.get("/runs")
def list_runs():
    return get_all_runs()


@router.post("/s0/simulate")
def run_s0(request: S0RunRequest, db: Session = Depends(get_db)):
    run = simulate_s0_run(
        failure_type=request.failure_type,
        mttd_seconds=request.mttd_seconds,
        db=db,
    )
    db.commit()
    return run.to_dict()


@router.post("/s1/simulate")
def run_s1(request: S1RunRequest, db: Session = Depends(get_db)):
    run = simulate_s1_run(
        failure_type=request.failure_type,
        mttd_seconds=request.mttd_seconds,
        schedule_interval_seconds=request.schedule_interval_seconds,
        failure_actually_occurred=request.failure_actually_occurred,
        db=db,
    )
    db.commit()
    return run.to_dict()


@router.get("/metrics")
def get_metrics():
    """Platform-level evaluation metrics across all systems."""
    summary = compute_summary()
    runs = get_all_runs()
    return {
        "summary": summary,
        "total_experiments": len(runs),
        "systems_tested": list(summary.get("systems", {}).keys()),
    }
