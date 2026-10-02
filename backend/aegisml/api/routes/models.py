"""Model registry API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from aegisml.api.schemas import DeploymentSummary, ModelVersionSummary
from aegisml.database.base import get_db
from aegisml.database.models import (
    ActionType,
    DeploymentStatus,
    ModelDeployment,
    ModelStage,
    ModelVersion,
)
from aegisml.deployments.canary import CanaryRouter

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=list[ModelVersionSummary])
def list_models(db: Session = Depends(get_db)):
    versions = (
        db.query(ModelVersion)
        .order_by(ModelVersion.version.desc())
        .all()
    )
    return [
        ModelVersionSummary(
            id=v.id,
            model_name=v.model_name,
            version=v.version,
            stage=v.stage.value,
            f1_score=v.f1_score,
            accuracy=v.accuracy,
            precision=v.precision,
            recall=v.recall,
            roc_auc=v.roc_auc,
            avg_latency_ms=v.avg_latency_ms,
            dataset_version=v.dataset_version,
            quality_gate_passed=v.quality_gate_passed,
            created_at=v.created_at,
            promoted_at=v.promoted_at,
        )
        for v in versions
    ]


@router.get("/{model_id}", response_model=ModelVersionSummary)
def get_model(model_id: int, db: Session = Depends(get_db)):
    mv = db.query(ModelVersion).filter(ModelVersion.id == model_id).first()
    if not mv:
        raise HTTPException(status_code=404, detail="Model version not found")
    return ModelVersionSummary(
        id=mv.id, model_name=mv.model_name, version=mv.version,
        stage=mv.stage.value, f1_score=mv.f1_score, accuracy=mv.accuracy,
        precision=mv.precision, recall=mv.recall, roc_auc=mv.roc_auc,
        avg_latency_ms=mv.avg_latency_ms, dataset_version=mv.dataset_version,
        quality_gate_passed=mv.quality_gate_passed, created_at=mv.created_at,
        promoted_at=mv.promoted_at,
    )


@router.get("/canary/status")
def canary_status(db: Session = Depends(get_db)):
    """Read canary status from DB (persistent) not in-memory state."""
    from aegisml.database.models import ModelDeployment, ModelVersion, DeploymentStatus
    from sqlalchemy import desc

    canary_dep = (
        db.query(ModelDeployment)
        .filter(ModelDeployment.is_canary == True)
        .order_by(desc(ModelDeployment.started_at))
        .first()
    )
    prod_dep = (
        db.query(ModelDeployment)
        .filter(ModelDeployment.is_production == True,
                ModelDeployment.status == DeploymentStatus.ACTIVE)
        .order_by(desc(ModelDeployment.started_at))
        .first()
    )

    prod_mv_version = None
    canary_mv_version = None
    prod_traffic = 1.0
    canary_traffic = 0.0

    if prod_dep:
        prod_mv = db.query(ModelVersion).filter(ModelVersion.id == prod_dep.model_version_id).first()
        prod_mv_version = prod_mv.version if prod_mv else None

    if canary_dep:
        canary_mv = db.query(ModelVersion).filter(ModelVersion.id == canary_dep.model_version_id).first()
        canary_mv_version = canary_mv.version if canary_mv else None
        canary_traffic = canary_dep.canary_traffic_percent
        prod_traffic = 1.0 - canary_traffic
        # Sync in-memory state
        from aegisml.execution.engine import _ACTIVE_CANARY
        if not _ACTIVE_CANARY:
            _ACTIVE_CANARY["deployment_id"]    = canary_dep.id
            _ACTIVE_CANARY["model_version_id"] = canary_dep.model_version_id
            _ACTIVE_CANARY["model_version"]    = canary_mv_version
            _ACTIVE_CANARY["traffic_percent"]  = canary_traffic

    return {
        "has_active_canary": canary_dep is not None,
        "mode": "canary" if canary_dep else "production",
        "production_traffic": round(prod_traffic, 2),
        "canary_traffic": round(canary_traffic, 2),
        "canary_version": canary_mv_version,
        "production_version": prod_mv_version,
        "deployment_id": canary_dep.id if canary_dep else None,
    }


@router.get("/deployments/list", response_model=list[DeploymentSummary])
def list_deployments(db: Session = Depends(get_db)):
    deployments = (
        db.query(ModelDeployment)
        .order_by(ModelDeployment.started_at.desc())
        .limit(20)
        .all()
    )
    return [
        DeploymentSummary(
            id=d.id, model_version_id=d.model_version_id,
            status=d.status.value, canary_traffic_percent=d.canary_traffic_percent,
            is_production=d.is_production, is_canary=d.is_canary,
            canary_error_rate=d.canary_error_rate, canary_latency_ms=d.canary_latency_ms,
            started_at=d.started_at, completed_at=d.completed_at,
        )
        for d in deployments
    ]


@router.post("/{model_id}/verify-canary")
def verify_canary(model_id: int, db: Session = Depends(get_db)):
    """Trigger a canary health check and potentially advance or rollback."""
    from aegisml.orchestrator.self_healing import SelfHealingOrchestrator
    from aegisml.execution.engine import _ACTIVE_CANARY

    canary_state = _ACTIVE_CANARY.copy()
    if not canary_state:
        raise HTTPException(status_code=404, detail="No active canary deployment")

    deployment_id = canary_state.get("deployment_id")
    orchestrator = SelfHealingOrchestrator(db)
    try:
        result = orchestrator.verify_canary(deployment_id)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
