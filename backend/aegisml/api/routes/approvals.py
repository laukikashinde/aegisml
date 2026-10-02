"""Approvals API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from aegisml.api.schemas import ApprovalDetail, ApproveRequest
from aegisml.database.base import get_db
from aegisml.database.models import Approval, ApprovalStatus
from aegisml.orchestrator.self_healing import SelfHealingOrchestrator

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalDetail])
def list_approvals(
    status: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(Approval)
    if status:
        try:
            q = q.filter(Approval.status == ApprovalStatus(status))
        except ValueError:
            pass
    approvals = q.order_by(desc(Approval.created_at)).limit(limit).all()
    return [
        ApprovalDetail(
            id=a.id, incident_id=a.incident_id,
            action_type=a.action_type.value, risk_level=a.risk_level.value,
            status=a.status.value, description=a.description,
            context=a.context, requested_by=a.requested_by,
            decided_by=a.decided_by, created_at=a.created_at,
            expires_at=a.expires_at,
        )
        for a in approvals
    ]


@router.post("/{approval_id}/approve")
def approve(
    approval_id: str, request: ApproveRequest, db: Session = Depends(get_db)
):
    orchestrator = SelfHealingOrchestrator(db)
    try:
        result = orchestrator.process_approval(
            approval_id=approval_id, approved=True,
            decided_by=request.decided_by, reason=request.reason,
        )
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{approval_id}/reject")
def reject(
    approval_id: str, request: ApproveRequest, db: Session = Depends(get_db)
):
    orchestrator = SelfHealingOrchestrator(db)
    try:
        result = orchestrator.process_approval(
            approval_id=approval_id, approved=False,
            decided_by=request.decided_by, reason=request.reason,
        )
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
