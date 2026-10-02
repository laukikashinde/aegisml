"""Monitoring API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from aegisml.api.schemas import DriftSummary, PerformanceSummary
from aegisml.database.base import get_db
from aegisml.database.models import MonitoringSnapshot

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/drift")
def get_drift(limit: int = 20, db: Session = Depends(get_db)):
    snapshots = (
        db.query(MonitoringSnapshot)
        .filter(MonitoringSnapshot.drift_detected.isnot(None))
        .order_by(desc(MonitoringSnapshot.created_at))
        .limit(limit)
        .all()
    )
    return [
        {
            "drift_detected": s.drift_detected,
            "drift_score": s.drift_score,
            "drifted_features": s.drifted_features,
            "drift_details": s.drift_details,
            "model_name": s.model_name,
            "timestamp": s.created_at.isoformat() if s.created_at else None,
        }
        for s in snapshots
    ]


@router.get("/performance")
def get_performance(limit: int = 50, db: Session = Depends(get_db)):
    snapshots = (
        db.query(MonitoringSnapshot)
        .filter(MonitoringSnapshot.f1_score.isnot(None))
        .order_by(desc(MonitoringSnapshot.created_at))
        .limit(limit)
        .all()
    )
    return [
        {
            "f1_score": s.f1_score,
            "accuracy": s.accuracy,
            "precision": s.precision,
            "recall": s.recall,
            "roc_auc": s.roc_auc,
            "avg_latency_ms": s.avg_latency_ms,
            "p95_latency_ms": s.p95_latency_ms,
            "error_rate": s.error_rate,
            "model_name": s.model_name,
            "model_version": s.model_version,
            "timestamp": s.created_at.isoformat() if s.created_at else None,
        }
        for s in snapshots
    ]


@router.get("/snapshots/latest")
def get_latest_snapshot(model_name: str | None = None, db: Session = Depends(get_db)):
    q = db.query(MonitoringSnapshot)
    if model_name:
        q = q.filter(MonitoringSnapshot.model_name == model_name)
    s = q.order_by(desc(MonitoringSnapshot.created_at)).first()
    if not s:
        return {}
    return {
        "f1_score": s.f1_score,
        "accuracy": s.accuracy,
        "drift_detected": s.drift_detected,
        "drift_score": s.drift_score,
        "drifted_features": s.drifted_features,
        "avg_latency_ms": s.avg_latency_ms,
        "error_rate": s.error_rate,
        "data_quality_status": s.data_quality_status,
        "timestamp": s.created_at.isoformat() if s.created_at else None,
    }
