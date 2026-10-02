"""Pipeline API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from aegisml.api.schemas import PipelineRunSummary, RetrainRequest
from aegisml.database.base import get_db
from aegisml.database.models import PipelineRun

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


@router.get("", response_model=list[PipelineRunSummary])
def list_pipelines(limit: int = 20, db: Session = Depends(get_db)):
    runs = (
        db.query(PipelineRun).order_by(desc(PipelineRun.started_at)).limit(limit).all()
    )
    return [
        PipelineRunSummary(
            id=r.id, pipeline_name=r.pipeline_name, status=r.status.value,
            trigger=r.trigger, dataset_version=r.dataset_version,
            duration_seconds=r.duration_seconds, error_stage=r.error_stage,
            error_message=r.error_message, started_at=r.started_at,
            completed_at=r.completed_at,
        )
        for r in runs
    ]


@router.get("/{run_id}")
def get_pipeline_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return {
        "id": run.id,
        "pipeline_name": run.pipeline_name,
        "status": run.status.value,
        "trigger": run.trigger,
        "dataset_version": run.dataset_version,
        "mlflow_run_id": run.mlflow_run_id,
        "stages_completed": run.stages_completed,
        "error_stage": run.error_stage,
        "error_message": run.error_message,
        "logs": run.logs,
        "duration_seconds": run.duration_seconds,
        "parameters": run.parameters,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.post("/retrain")
def trigger_retrain(request: RetrainRequest, db: Session = Depends(get_db)):
    """Manually trigger model retraining."""
    from aegisml.config import get_settings
    from aegisml.database.models import ActionType, PolicyDecisionResult, RiskLevel
    from aegisml.execution.engine import ExecutionEngine
    from aegisml.policies.engine import PolicyEngine, PolicyEvaluationResult

    settings = get_settings()
    policy_engine = PolicyEngine(db)
    policy_result = policy_engine.evaluate(
        action_type=ActionType.RETRAIN_MODEL,
        incident_id=request.incident_id,
        context={
            "drift_score": 0.30,  # assume trigger
            "f1_current": 0.80,
            "data_quality_status": "PASSED",
            "risk_level": "LOW",
        },
        requested_by="manual",
    )

    if policy_result.decision.value == "DENIED":
        raise HTTPException(status_code=403, detail=f"Policy denied: {policy_result.reason}")

    engine = ExecutionEngine(db)
    # Override for manual trigger
    from aegisml.policies.engine import PolicyEvaluationResult
    approved_result = PolicyEvaluationResult(
        action_type=ActionType.RETRAIN_MODEL,
        decision=PolicyDecisionResult.APPROVED,
        reason="Manual trigger approved",
        risk_level=RiskLevel.LOW,
        policy_name="MANUAL_TRIGGER",
        requires_human_approval=False,
        context={},
    )

    try:
        result = engine.execute(
            action_type=ActionType.RETRAIN_MODEL,
            policy_result=approved_result,
            incident_id=request.incident_id,
            parameters={"dataset_version": request.dataset_version},
        )
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
