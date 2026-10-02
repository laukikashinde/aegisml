"""
AegisML — SQLAlchemy ORM models.
Proper relational design; JSON used only for flexible evidence/config blobs.
native_enum=False on all Enum columns so SQLite works for tests.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aegisml.database.base import Base


def _E(enum_cls):
    """SQLAlchemy Enum that works on both PostgreSQL and SQLite (native_enum=False)."""
    return Enum(enum_cls, native_enum=False)


# ── Enumerations ──────────────────────────────────────────────────────────────

class IncidentSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentType(str, enum.Enum):
    DATA_QUALITY = "DATA_QUALITY"
    DATA_DRIFT = "DATA_DRIFT"
    MODEL_DEGRADATION = "MODEL_DEGRADATION"
    LATENCY = "LATENCY"
    PIPELINE_FAILURE = "PIPELINE_FAILURE"
    DEPLOYMENT_FAILURE = "DEPLOYMENT_FAILURE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    UNKNOWN = "UNKNOWN"


class IncidentStatus(str, enum.Enum):
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    DIAGNOSED = "DIAGNOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REMEDIATING = "REMEDIATING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


class ModelStage(str, enum.Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    CANARY = "CANARY"
    PRODUCTION = "PRODUCTION"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class ActionType(str, enum.Enum):
    RETRAIN_MODEL = "RETRAIN_MODEL"
    REGISTER_MODEL = "REGISTER_MODEL"
    PROMOTE_MODEL = "PROMOTE_MODEL"
    START_CANARY = "START_CANARY"
    COMPLETE_DEPLOYMENT = "COMPLETE_DEPLOYMENT"
    ROLLBACK_MODEL = "ROLLBACK_MODEL"
    RETRY_PIPELINE = "RETRY_PIPELINE"
    RESTART_SERVICE = "RESTART_SERVICE"
    CREATE_INCIDENT = "CREATE_INCIDENT"
    REQUEST_HUMAN_APPROVAL = "REQUEST_HUMAN_APPROVAL"


class ActionStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PolicyDecisionResult(str, enum.Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PipelineRunStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DeploymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    CANARY = "CANARY"
    PROMOTING = "PROMOTING"
    ACTIVE = "ACTIVE"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


class SimulationType(str, enum.Enum):
    DATA_DRIFT = "DATA_DRIFT"
    MISSING_DATA = "MISSING_DATA"
    MODEL_DEGRADATION = "MODEL_DEGRADATION"
    LATENCY_SPIKE = "LATENCY_SPIKE"
    PIPELINE_FAILURE = "PIPELINE_FAILURE"
    DEPLOYMENT_FAILURE = "DEPLOYMENT_FAILURE"


# ── ORM Models ────────────────────────────────────────────────────────────────

class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    incident_type: Mapped[IncidentType] = mapped_column(_E(IncidentType), nullable=False)
    severity: Mapped[IncidentSeverity] = mapped_column(_E(IncidentSeverity), nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(
        _E(IncidentStatus), default=IncidentStatus.DETECTED, nullable=False
    )
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    affected_model: Mapped[str | None] = mapped_column(String(200))
    affected_pipeline: Mapped[str | None] = mapped_column(String(200))
    affected_feature: Mapped[str | None] = mapped_column(String(500))
    observed_metrics: Mapped[dict | None] = mapped_column(JSON)

    suspected_root_cause: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    diagnosis: Mapped[str | None] = mapped_column(Text)
    recommended_action: Mapped[str | None] = mapped_column(String(100))
    risk_level: Mapped[RiskLevel | None] = mapped_column(_E(RiskLevel))
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_evidence: Mapped[list | None] = mapped_column(JSON)
    verification_plan: Mapped[list | None] = mapped_column(JSON)

    remediation_status: Mapped[str | None] = mapped_column(String(50))
    verification_status: Mapped[str | None] = mapped_column(String(50))
    resolution_notes: Mapped[str | None] = mapped_column(Text)

    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False)
    simulation_type: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    evidence: Mapped[list["IncidentEvidence"]] = relationship(
        "IncidentEvidence", back_populates="incident", cascade="all, delete-orphan"
    )
    actions: Mapped[list["IncidentAction"]] = relationship(
        "IncidentAction", back_populates="incident", cascade="all, delete-orphan"
    )
    timeline_events: Mapped[list["IncidentTimelineEvent"]] = relationship(
        "IncidentTimelineEvent", back_populates="incident", cascade="all, delete-orphan",
        order_by="IncidentTimelineEvent.occurred_at",
    )
    approvals: Mapped[list["Approval"]] = relationship(
        "Approval", back_populates="incident"
    )


class IncidentEvidence(Base):
    __tablename__ = "incident_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id"), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_tool: Mapped[str | None] = mapped_column(String(100))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    incident: Mapped["Incident"] = relationship("Incident", back_populates="evidence")


class IncidentTimelineEvent(Base):
    __tablename__ = "incident_timeline_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    incident: Mapped["Incident"] = relationship(
        "Incident", back_populates="timeline_events"
    )


class IncidentAction(Base):
    __tablename__ = "incident_actions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id"), nullable=False
    )
    action_type: Mapped[ActionType] = mapped_column(_E(ActionType), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    policy_decision: Mapped[PolicyDecisionResult | None] = mapped_column(
        _E(PolicyDecisionResult)
    )
    policy_reason: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict | None] = mapped_column(JSON)
    execution_status: Mapped[ActionStatus] = mapped_column(
        _E(ActionStatus), default=ActionStatus.PENDING
    )
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incident: Mapped["Incident"] = relationship("Incident", back_populates="actions")


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    incident_types: Mapped[list] = mapped_column(JSON, nullable=False)
    action_types: Mapped[list] = mapped_column(JSON, nullable=False)
    conditions: Mapped[dict] = mapped_column(JSON, nullable=False)
    result: Mapped[PolicyDecisionResult] = mapped_column(
        _E(PolicyDecisionResult), nullable=False
    )
    risk_level: Mapped[RiskLevel] = mapped_column(_E(RiskLevel), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    decisions: Mapped[list["PolicyDecision"]] = relationship(
        "PolicyDecision", back_populates="policy"
    )


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[int] = mapped_column(Integer, ForeignKey("policies.id"), nullable=False)
    incident_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("incidents.id"))
    action_type: Mapped[ActionType] = mapped_column(_E(ActionType), nullable=False)
    result: Mapped[PolicyDecisionResult] = mapped_column(
        _E(PolicyDecisionResult), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSON)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    policy: Mapped["Policy"] = relationship("Policy", back_populates="decisions")


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    mlflow_run_id: Mapped[str | None] = mapped_column(String(200))
    mlflow_version: Mapped[str | None] = mapped_column(String(50))
    stage: Mapped[ModelStage] = mapped_column(
        _E(ModelStage), default=ModelStage.CANDIDATE, nullable=False
    )
    accuracy: Mapped[float | None] = mapped_column(Float)
    precision: Mapped[float | None] = mapped_column(Float)
    recall: Mapped[float | None] = mapped_column(Float)
    f1_score: Mapped[float | None] = mapped_column(Float)
    roc_auc: Mapped[float | None] = mapped_column(Float)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float)
    dataset_version: Mapped[str | None] = mapped_column(String(200))
    git_commit: Mapped[str | None] = mapped_column(String(100))
    training_params: Mapped[dict | None] = mapped_column(JSON)
    artifact_uri: Mapped[str | None] = mapped_column(String(500))
    training_duration_seconds: Mapped[float | None] = mapped_column(Float)
    quality_gate_passed: Mapped[bool | None] = mapped_column(Boolean)
    quality_gate_details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incident_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("incidents.id"))

    __table_args__ = (UniqueConstraint("model_name", "version"),)

    deployments: Mapped[list["ModelDeployment"]] = relationship(
        "ModelDeployment", back_populates="model_version"
    )


class ModelDeployment(Base):
    __tablename__ = "model_deployments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("model_versions.id"), nullable=False
    )
    status: Mapped[DeploymentStatus] = mapped_column(
        _E(DeploymentStatus), default=DeploymentStatus.PENDING, nullable=False
    )
    canary_traffic_percent: Mapped[float] = mapped_column(Float, default=0.0)
    is_production: Mapped[bool] = mapped_column(Boolean, default=False)
    is_canary: Mapped[bool] = mapped_column(Boolean, default=False)
    canary_error_rate: Mapped[float | None] = mapped_column(Float)
    canary_latency_ms: Mapped[float | None] = mapped_column(Float)
    canary_f1: Mapped[float | None] = mapped_column(Float)
    rollback_reason: Mapped[str | None] = mapped_column(Text)
    previous_deployment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("model_deployments.id")
    )
    incident_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("incidents.id"))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    model_version: Mapped["ModelVersion"] = relationship(
        "ModelVersion", back_populates="deployments"
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    pipeline_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[PipelineRunStatus] = mapped_column(
        _E(PipelineRunStatus), default=PipelineRunStatus.RUNNING, nullable=False
    )
    trigger: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_version: Mapped[str | None] = mapped_column(String(200))
    git_commit: Mapped[str | None] = mapped_column(String(100))
    mlflow_run_id: Mapped[str | None] = mapped_column(String(200))
    model_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("model_versions.id")
    )
    incident_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("incidents.id"))
    parameters: Mapped[dict | None] = mapped_column(JSON)
    stages_completed: Mapped[list | None] = mapped_column(JSON)
    error_stage: Mapped[str | None] = mapped_column(String(200))
    error_message: Mapped[str | None] = mapped_column(Text)
    logs: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id"), nullable=False
    )
    action_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("incident_actions.id")
    )
    action_type: Mapped[ActionType] = mapped_column(_E(ActionType), nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(_E(RiskLevel), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        _E(ApprovalStatus), default=ApprovalStatus.PENDING, nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSON)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    incident: Mapped["Incident"] = relationship("Incident", back_populates="approvals")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    incident_id: Mapped[str | None] = mapped_column(String(36))
    action_id: Mapped[str | None] = mapped_column(String(36))
    resource_type: Mapped[str | None] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON)
    outcome: Mapped[str | None] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MonitoringSnapshot(Base):
    __tablename__ = "monitoring_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_type: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(200))
    model_version: Mapped[int | None] = mapped_column(Integer)
    accuracy: Mapped[float | None] = mapped_column(Float)
    precision: Mapped[float | None] = mapped_column(Float)
    recall: Mapped[float | None] = mapped_column(Float)
    f1_score: Mapped[float | None] = mapped_column(Float)
    roc_auc: Mapped[float | None] = mapped_column(Float)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float)
    p95_latency_ms: Mapped[float | None] = mapped_column(Float)
    error_rate: Mapped[float | None] = mapped_column(Float)
    request_count: Mapped[int | None] = mapped_column(Integer)
    drift_detected: Mapped[bool | None] = mapped_column(Boolean)
    drift_score: Mapped[float | None] = mapped_column(Float)
    drifted_features: Mapped[list | None] = mapped_column(JSON)
    drift_details: Mapped[dict | None] = mapped_column(JSON)
    data_quality_status: Mapped[str | None] = mapped_column(String(50))
    data_quality_issues: Mapped[list | None] = mapped_column(JSON)
    raw_metrics: Mapped[dict | None] = mapped_column(JSON)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    simulation_type: Mapped[SimulationType] = mapped_column(
        _E(SimulationType), nullable=False
    )
    parameters: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(50), default="RUNNING")
    incident_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("incidents.id")
    )
    description: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
