"""Incident API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from aegisml.api.schemas import (
    ApproveRequest,
    IncidentDetail,
    IncidentSummary,
    InvestigateResponse,
    RemediateResponse,
    SimulateRequest,
    TimelineEvent,
)
from aegisml.database.base import get_db
from aegisml.database.models import (
    ApprovalStatus,
    Incident,
    IncidentStatus,
    SimulationType,
)
from aegisml.incidents.service import IncidentService
from aegisml.monitoring.simulation import SimulationEngine
from aegisml.orchestrator.self_healing import SelfHealingOrchestrator

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


def _incident_to_summary(i: Incident) -> IncidentSummary:
    return IncidentSummary(
        id=i.id,
        title=i.title,
        incident_type=i.incident_type.value,
        severity=i.severity.value,
        status=i.status.value,
        source=i.source,
        affected_model=i.affected_model,
        affected_feature=i.affected_feature,
        is_simulation=i.is_simulation,
        created_at=i.created_at,
        resolved_at=i.resolved_at,
    )


def _incident_to_detail(i: Incident) -> IncidentDetail:
    timeline = [
        TimelineEvent(
            id=e.id,
            event_type=e.event_type,
            description=e.description,
            details=e.details,
            occurred_at=e.occurred_at,
        )
        for e in (i.timeline_events or [])
    ]
    return IncidentDetail(
        id=i.id,
        title=i.title,
        incident_type=i.incident_type.value,
        severity=i.severity.value,
        status=i.status.value,
        source=i.source,
        affected_model=i.affected_model,
        affected_pipeline=i.affected_pipeline,
        affected_feature=i.affected_feature,
        observed_metrics=i.observed_metrics,
        diagnosis=i.diagnosis,
        suspected_root_cause=i.suspected_root_cause,
        confidence=i.confidence,
        recommended_action=i.recommended_action,
        risk_level=i.risk_level.value if i.risk_level else None,
        requires_human_approval=i.requires_human_approval or False,
        agent_evidence=i.agent_evidence,
        verification_plan=i.verification_plan,
        remediation_status=i.remediation_status,
        verification_status=i.verification_status,
        resolution_notes=i.resolution_notes,
        is_simulation=i.is_simulation,
        simulation_type=i.simulation_type,
        created_at=i.created_at,
        resolved_at=i.resolved_at,
        timeline=timeline,
    )


@router.get("", response_model=list[IncidentSummary])
def list_incidents(
    status: str | None = None,
    incident_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    svc = IncidentService(db)
    from aegisml.database.models import IncidentType
    i_type = IncidentType(incident_type) if incident_type else None
    i_status = IncidentStatus(status) if status else None
    incidents = svc.list_incidents(
        status=i_status, incident_type=i_type, limit=limit, offset=offset
    )
    return [_incident_to_summary(i) for i in incidents]


@router.get("/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: str, db: Session = Depends(get_db)):
    svc = IncidentService(db)
    incident = svc.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _incident_to_detail(incident)


@router.post("/simulate")
def simulate_incident(request: SimulateRequest, db: Session = Depends(get_db)):
    try:
        sim_type = SimulationType(request.simulation_type)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Unknown simulation type: {request.simulation_type}"
        )

    engine = SimulationEngine(db)
    try:
        result = engine.run_simulation(sim_type, request.parameters)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{incident_id}/investigate", response_model=InvestigateResponse)
def investigate_incident(incident_id: str, db: Session = Depends(get_db)):
    orchestrator = SelfHealingOrchestrator(db)
    try:
        diagnosis = orchestrator.investigate_incident(incident_id)
        db.commit()
        return InvestigateResponse(
            incident_id=diagnosis.incident_id,
            diagnosis=diagnosis.diagnosis,
            root_cause=diagnosis.root_cause,
            confidence=diagnosis.confidence,
            evidence=diagnosis.evidence,
            recommended_action=diagnosis.recommended_action,
            risk_level=diagnosis.risk_level,
            requires_human_approval=diagnosis.requires_human_approval,
            verification_plan=diagnosis.verification_plan,
            diagnosis_method=diagnosis.diagnosis_method,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{incident_id}/remediate")
def remediate_incident(incident_id: str, db: Session = Depends(get_db)):
    orchestrator = SelfHealingOrchestrator(db)
    try:
        result = orchestrator.remediate_incident(incident_id)
        db.commit()
        # Return as plain dict — result shape varies by action
        return result
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{incident_id}/approve")
def approve_incident(
    incident_id: str, request: ApproveRequest, db: Session = Depends(get_db)
):
    incident = IncidentService(db).get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Find pending approval for this incident
    from aegisml.database.models import Approval
    pending = (
        db.query(Approval)
        .filter(
            Approval.incident_id == incident_id,
            Approval.status == ApprovalStatus.PENDING,
        )
        .first()
    )
    if not pending:
        raise HTTPException(status_code=404, detail="No pending approval for this incident")

    orchestrator = SelfHealingOrchestrator(db)
    try:
        result = orchestrator.process_approval(
            approval_id=pending.id,
            approved=True,
            decided_by=request.decided_by,
            reason=request.reason,
        )
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{incident_id}/reject")
def reject_incident(
    incident_id: str, request: ApproveRequest, db: Session = Depends(get_db)
):
    from aegisml.database.models import Approval

    pending = (
        db.query(Approval)
        .filter(
            Approval.incident_id == incident_id,
            Approval.status == ApprovalStatus.PENDING,
        )
        .first()
    )
    if not pending:
        raise HTTPException(status_code=404, detail="No pending approval")

    orchestrator = SelfHealingOrchestrator(db)
    try:
        result = orchestrator.process_approval(
            approval_id=pending.id,
            approved=False,
            decided_by=request.decided_by,
            reason=request.reason,
        )
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
