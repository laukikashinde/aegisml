"""
AegisML — Pydantic request/response schemas.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Incidents ─────────────────────────────────────────────────────────────────

class IncidentSummary(BaseModel):
    id: str
    title: str
    incident_type: str
    severity: str
    status: str
    source: str
    affected_model: str | None
    affected_feature: str | None
    is_simulation: bool
    created_at: datetime
    resolved_at: datetime | None

    class Config:
        from_attributes = True


class TimelineEvent(BaseModel):
    id: int
    event_type: str
    description: str
    details: dict | None
    occurred_at: datetime

    class Config:
        from_attributes = True


class EvidenceItem(BaseModel):
    id: int
    evidence_type: str
    title: str
    data: dict
    source_tool: str | None
    collected_at: datetime

    class Config:
        from_attributes = True


class IncidentDetail(BaseModel):
    id: str
    title: str
    incident_type: str
    severity: str
    status: str
    source: str
    affected_model: str | None
    affected_pipeline: str | None
    affected_feature: str | None
    observed_metrics: dict | None
    diagnosis: str | None
    root_cause: str | None = Field(None, alias="suspected_root_cause")
    confidence: float | None
    recommended_action: str | None
    risk_level: str | None
    requires_human_approval: bool
    agent_evidence: list | None
    verification_plan: list | None
    remediation_status: str | None
    verification_status: str | None
    resolution_notes: str | None
    is_simulation: bool
    simulation_type: str | None
    created_at: datetime
    resolved_at: datetime | None
    timeline: list[TimelineEvent] = []

    class Config:
        from_attributes = True
        populate_by_name = True


class SimulateRequest(BaseModel):
    simulation_type: str
    parameters: dict | None = None


class InvestigateResponse(BaseModel):
    incident_id: str
    diagnosis: str
    root_cause: str
    confidence: float
    evidence: list[dict]
    recommended_action: str
    risk_level: str
    requires_human_approval: bool
    verification_plan: list[str]
    diagnosis_method: str


class RemediateResponse(BaseModel):
    status: str
    action: str | None = None
    reason: str | None = None
    approval_id: str | None = None
    result: dict | None = None
    canary_result: dict | None = None
    retrain_result: dict | None = None


class ApproveRequest(BaseModel):
    decided_by: str = "operator"
    reason: str = ""


# ── Models ────────────────────────────────────────────────────────────────────

class ModelVersionSummary(BaseModel):
    id: int
    model_name: str
    version: int
    stage: str
    f1_score: float | None
    accuracy: float | None
    precision: float | None
    recall: float | None
    roc_auc: float | None
    avg_latency_ms: float | None
    dataset_version: str | None
    quality_gate_passed: bool | None
    created_at: datetime
    promoted_at: datetime | None

    class Config:
        from_attributes = True


# ── Deployments ───────────────────────────────────────────────────────────────

class DeploymentSummary(BaseModel):
    id: str
    model_version_id: int
    status: str
    canary_traffic_percent: float
    is_production: bool
    is_canary: bool
    canary_error_rate: float | None
    canary_latency_ms: float | None
    started_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True


# ── Pipelines ─────────────────────────────────────────────────────────────────

class PipelineRunSummary(BaseModel):
    id: str
    pipeline_name: str
    status: str
    trigger: str
    dataset_version: str | None
    duration_seconds: float | None
    error_stage: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True


class RetrainRequest(BaseModel):
    dataset_version: str = "v1"
    incident_id: str | None = None


# ── Approvals ─────────────────────────────────────────────────────────────────

class ApprovalDetail(BaseModel):
    id: str
    incident_id: str
    action_type: str
    risk_level: str
    status: str
    description: str
    context: dict | None
    requested_by: str
    decided_by: str | None
    created_at: datetime
    expires_at: datetime | None

    class Config:
        from_attributes = True


# ── Monitoring ────────────────────────────────────────────────────────────────

class DriftSummary(BaseModel):
    drift_detected: bool
    drift_score: float | None
    drifted_features: list[str] | None
    drift_details: dict | None
    timestamp: datetime | None

    class Config:
        from_attributes = True


class PerformanceSummary(BaseModel):
    f1_score: float | None
    accuracy: float | None
    precision: float | None
    recall: float | None
    roc_auc: float | None
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    error_rate: float | None
    timestamp: datetime

    class Config:
        from_attributes = True


# ── Audit ─────────────────────────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    id: int
    event_type: str
    actor: str
    incident_id: str | None
    resource_type: str | None
    description: str
    outcome: str | None
    occurred_at: datetime

    class Config:
        from_attributes = True


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardMetrics(BaseModel):
    active_incidents: int
    resolved_today: int
    total_incidents: int
    production_model_version: int | None
    production_f1: float | None
    latest_drift_score: float | None
    drift_detected: bool
    recent_pipeline_success_rate: float
    mttr_hours: float | None
    mttd_minutes: float | None
    auto_remediation_rate: float
    remediation_success_rate: float
    rollback_rate: float
    open_approvals: int
    recent_incidents: list[IncidentSummary]
    recent_actions: list[dict]


# ── Canary ────────────────────────────────────────────────────────────────────

class CanaryStatusResponse(BaseModel):
    has_active_canary: bool
    production_traffic: float
    canary_traffic: float
    canary_version: int | None = None
    deployment_id: str | None = None
