"""
Admin/utility endpoints — reset demo data, clear test state.
Only for development use.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from aegisml.database.base import get_db
from aegisml.database.models import (
    AuditLog, Incident, IncidentEvidence, IncidentTimelineEvent,
    IncidentAction, Approval, ModelDeployment, ModelVersion,
    MonitoringSnapshot, PipelineRun, PolicyDecision, SimulationRun,
    ModelStage, DeploymentStatus,
)
from aegisml.monitoring.simulation import reset_simulation_state
from aegisml.execution.engine import _ACTIVE_CANARY, _PRODUCTION_MODEL

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/reset")
def reset_demo_data(db: Session = Depends(get_db)):
    """
    Delete all demo/test data and re-seed fresh baseline.
    Use this to start a clean demo without restarting the backend.
    """
    from aegisml.config import get_settings
    from datetime import datetime, timezone

    settings = get_settings()

    # Clear all operational data
    db.query(SimulationRun).delete()
    db.query(Approval).delete()
    db.query(PolicyDecision).delete()
    db.query(AuditLog).delete()
    db.query(IncidentAction).delete()
    db.query(IncidentEvidence).delete()
    db.query(IncidentTimelineEvent).delete()
    db.query(Incident).delete()
    db.query(MonitoringSnapshot).delete()
    db.query(PipelineRun).delete()
    db.query(ModelDeployment).delete()
    db.query(ModelVersion).delete()

    # Re-seed production model
    mv = ModelVersion(
        model_name=settings.mlflow_model_name,
        version=1,
        stage=ModelStage.PRODUCTION,
        f1_score=0.50,
        accuracy=0.70,
        precision=0.57,
        recall=0.44,
        roc_auc=0.72,
        avg_latency_ms=8.0,
        dataset_version="v1",
        quality_gate_passed=True,
        quality_gate_details={"overall": "PASSED", "gates": []},
        created_at=datetime.now(timezone.utc),
        promoted_at=datetime.now(timezone.utc),
    )
    db.add(mv)
    db.flush()

    dep = ModelDeployment(
        model_version_id=mv.id,
        status=DeploymentStatus.ACTIVE,
        canary_traffic_percent=1.0,
        is_production=True,
        is_canary=False,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(dep)

    snap = MonitoringSnapshot(
        snapshot_type="performance",
        model_name=settings.mlflow_model_name,
        model_version=1,
        f1_score=0.50,
        accuracy=0.70,
        precision=0.57,
        recall=0.44,
        roc_auc=0.72,
        avg_latency_ms=8.0,
        p95_latency_ms=15.0,
        error_rate=0.008,
        request_count=1000,
        drift_detected=False,
        drift_score=0.04,
        drifted_features=[],
        data_quality_status="PASSED",
        created_at=datetime.now(timezone.utc),
    )
    db.add(snap)
    db.commit()

    # Reset in-memory state
    reset_simulation_state()
    _ACTIVE_CANARY.clear()
    _PRODUCTION_MODEL.clear()
    _PRODUCTION_MODEL["model_version"] = 1
    _PRODUCTION_MODEL["model_version_id"] = mv.id

    return {
        "status": "reset",
        "message": "All demo data cleared. Fresh baseline seeded.",
        "production_model": f"v{mv.version}",
    }
