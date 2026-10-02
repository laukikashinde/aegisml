"""
AegisML — Incident Service.

Creates, updates, and retrieves incidents.
Persists timeline events alongside every state transition.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from aegisml.database.models import (
    AuditLog,
    Incident,
    IncidentAction,
    IncidentEvidence,
    IncidentSeverity,
    IncidentStatus,
    IncidentTimelineEvent,
    IncidentType,
)

logger = structlog.get_logger(__name__)


class IncidentService:
    """Create, read, and update incidents with full audit trail."""

    def __init__(self, db: Session):
        self.db = db

    # ── Creation ──────────────────────────────────────────────────────────────

    def create_incident(
        self,
        title: str,
        incident_type: IncidentType,
        severity: IncidentSeverity,
        source: str,
        affected_model: str | None = None,
        affected_pipeline: str | None = None,
        affected_feature: str | None = None,
        observed_metrics: dict | None = None,
        is_simulation: bool = False,
        simulation_type: str | None = None,
    ) -> Incident:
        """Create and persist a new incident. Adds initial timeline event."""
        incident_id = str(uuid.uuid4())

        incident = Incident(
            id=incident_id,
            title=title,
            incident_type=incident_type,
            severity=severity,
            status=IncidentStatus.DETECTED,
            source=source,
            affected_model=affected_model,
            affected_pipeline=affected_pipeline,
            affected_feature=affected_feature,
            observed_metrics=observed_metrics,
            is_simulation=is_simulation,
            simulation_type=simulation_type,
        )

        self.db.add(incident)
        self._add_timeline_event(
            incident,
            event_type="INCIDENT_CREATED",
            description=f"Incident created: {title}",
            details={
                "severity": severity.value,
                "type": incident_type.value,
                "source": source,
                "is_simulation": is_simulation,
            },
        )
        self._add_audit_log(
            event_type="INCIDENT_CREATED",
            actor="system",
            incident_id=incident_id,
            description=f"Incident {incident_id} created: {title}",
            details={"severity": severity.value, "type": incident_type.value},
            outcome="SUCCESS",
        )

        self.db.flush()
        logger.info("incident_created", incident_id=incident_id, type=incident_type.value,
                    severity=severity.value)
        return incident

    # ── State transitions ─────────────────────────────────────────────────────

    def transition_status(
        self,
        incident: Incident,
        new_status: IncidentStatus,
        description: str,
        details: dict | None = None,
        actor: str = "system",
    ) -> Incident:
        old_status = incident.status
        incident.status = new_status
        incident.updated_at = datetime.now(timezone.utc)

        if new_status == IncidentStatus.RESOLVED:
            incident.resolved_at = datetime.now(timezone.utc)

        self._add_timeline_event(
            incident,
            event_type=f"STATUS_CHANGED_{new_status.value}",
            description=description,
            details={**(details or {}), "from_status": old_status.value, "to_status": new_status.value},
        )
        self._add_audit_log(
            event_type=f"INCIDENT_STATUS_{new_status.value}",
            actor=actor,
            incident_id=incident.id,
            description=description,
            details=details,
            outcome="SUCCESS",
        )

        self.db.flush()
        logger.info("incident_status_changed", incident_id=incident.id,
                    from_status=old_status.value, to_status=new_status.value)
        return incident

    def add_diagnosis(
        self,
        incident: Incident,
        diagnosis: str,
        root_cause: str,
        confidence: float,
        recommended_action: str,
        risk_level: str,
        requires_human_approval: bool,
        evidence: list[dict],
        verification_plan: list[str],
    ) -> Incident:
        from aegisml.database.models import RiskLevel
        incident.diagnosis = diagnosis
        incident.suspected_root_cause = root_cause
        incident.confidence = confidence
        incident.recommended_action = recommended_action
        incident.risk_level = RiskLevel(risk_level)
        incident.requires_human_approval = requires_human_approval
        incident.agent_evidence = evidence
        incident.verification_plan = verification_plan

        self._add_timeline_event(
            incident,
            event_type="DIAGNOSIS_COMPLETE",
            description=f"Agent diagnosis complete. Root cause: {root_cause[:150]}",
            details={
                "confidence": confidence,
                "recommended_action": recommended_action,
                "risk_level": risk_level,
                "requires_approval": requires_human_approval,
            },
        )
        self.db.flush()
        return incident

    def add_evidence(
        self,
        incident: Incident,
        evidence_type: str,
        title: str,
        data: dict,
        source_tool: str | None = None,
    ) -> IncidentEvidence:
        ev = IncidentEvidence(
            incident_id=incident.id,
            evidence_type=evidence_type,
            title=title,
            data=data,
            source_tool=source_tool,
        )
        self.db.add(ev)
        self.db.flush()
        return ev

    def add_timeline_event(
        self,
        incident: Incident,
        event_type: str,
        description: str,
        details: dict | None = None,
    ) -> IncidentTimelineEvent:
        return self._add_timeline_event(incident, event_type, description, details)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_incident(self, incident_id: str) -> Incident | None:
        return self.db.query(Incident).filter(Incident.id == incident_id).first()

    def list_incidents(
        self,
        status: IncidentStatus | None = None,
        incident_type: IncidentType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Incident]:
        q = self.db.query(Incident)
        if status:
            q = q.filter(Incident.status == status)
        if incident_type:
            q = q.filter(Incident.incident_type == incident_type)
        return q.order_by(Incident.created_at.desc()).limit(limit).offset(offset).all()

    def get_similar_incidents(
        self, incident_type: IncidentType, limit: int = 5
    ) -> list[Incident]:
        """Retrieve recent resolved incidents of the same type for historical context."""
        return (
            self.db.query(Incident)
            .filter(
                Incident.incident_type == incident_type,
                Incident.status.in_([IncidentStatus.RESOLVED, IncidentStatus.ROLLED_BACK]),
                Incident.suspected_root_cause.isnot(None),
            )
            .order_by(Incident.resolved_at.desc())
            .limit(limit)
            .all()
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _add_timeline_event(
        self,
        incident: Incident,
        event_type: str,
        description: str,
        details: dict | None = None,
    ) -> IncidentTimelineEvent:
        event = IncidentTimelineEvent(
            incident_id=incident.id,
            event_type=event_type,
            description=description,
            details=details,
            occurred_at=datetime.now(timezone.utc),
        )
        self.db.add(event)
        return event

    def _add_audit_log(
        self,
        event_type: str,
        actor: str,
        incident_id: str | None = None,
        description: str = "",
        details: dict | None = None,
        outcome: str = "SUCCESS",
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> AuditLog:
        log = AuditLog(
            event_type=event_type,
            actor=actor,
            incident_id=incident_id,
            resource_type=resource_type,
            resource_id=resource_id,
            description=description,
            details=details,
            outcome=outcome,
            occurred_at=datetime.now(timezone.utc),
        )
        self.db.add(log)
        return log
