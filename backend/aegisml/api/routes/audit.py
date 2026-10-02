"""Audit log API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from aegisml.api.schemas import AuditLogEntry
from aegisml.database.base import get_db
from aegisml.database.models import AuditLog

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditLogEntry])
def list_audit_logs(
    limit: int = 100,
    offset: int = 0,
    incident_id: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog)
    if incident_id:
        q = q.filter(AuditLog.incident_id == incident_id)
    logs = q.order_by(desc(AuditLog.occurred_at)).limit(limit).offset(offset).all()
    return [
        AuditLogEntry(
            id=l.id, event_type=l.event_type, actor=l.actor,
            incident_id=l.incident_id, resource_type=l.resource_type,
            description=l.description, outcome=l.outcome,
            occurred_at=l.occurred_at,
        )
        for l in logs
    ]
