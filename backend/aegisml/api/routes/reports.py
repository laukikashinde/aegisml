"""Incident report generation API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from aegisml.agents.incident_report import generate_report
from aegisml.database.base import get_db
from aegisml.incidents.service import IncidentService

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/incident/{incident_id}")
def get_incident_report(incident_id: str, db: Session = Depends(get_db)):
    svc = IncidentService(db)
    incident = svc.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident_dict = {
        "id": incident.id,
        "type": incident.incident_type.value,
        "severity": incident.severity.value,
        "status": incident.status.value,
        "affected_model": incident.affected_model,
        "is_simulation": incident.is_simulation,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
    }
    diagnosis_dict = {
        "root_cause": incident.suspected_root_cause,
        "diagnosis": incident.diagnosis,
        "confidence": incident.confidence,
        "recommended_action": incident.recommended_action,
        "evidence": incident.agent_evidence or [],
    }
    remediation_dict = {
        "status": incident.remediation_status,
        "action": incident.recommended_action,
    }

    report = generate_report(
        incident=incident_dict,
        diagnosis=diagnosis_dict,
        remediation=remediation_dict,
    )
    return report
