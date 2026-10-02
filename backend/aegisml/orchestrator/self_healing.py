"""
AegisML — Self-Healing Orchestrator.

Implements the full autonomous lifecycle:
DETECT → DIAGNOSE → PLAN → POLICY CHECK → REMEDIATE → VERIFY → LEARN

This orchestrates the other components in the correct order.
The LLM agent is advisory only — the policy engine makes all decisions.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from aegisml.agents.incident_agent import AgentDiagnosis, IncidentAgent
from aegisml.config import get_settings
from aegisml.database.models import (
    ActionType,
    Approval,
    ApprovalStatus,
    DeploymentStatus,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ModelDeployment,
    ModelVersion,
    MonitoringSnapshot,
    PolicyDecisionResult,
    RiskLevel,
)
from aegisml.deployments.canary import CanaryHealthMonitor
from aegisml.execution.engine import ExecutionEngine
from aegisml.incidents.service import IncidentService
from aegisml.policies.engine import PolicyEngine

logger = structlog.get_logger(__name__)


class SelfHealingOrchestrator:
    """
    Full autonomous incident lifecycle: Detect → Diagnose → Act → Verify → Learn.
    """

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.incident_svc = IncidentService(db)
        self.agent = IncidentAgent(db)
        self.policy_engine = PolicyEngine(db)
        self.execution = ExecutionEngine(db)
        self.canary_monitor = CanaryHealthMonitor(db)

    # ── Phase 3: Diagnose & Plan ──────────────────────────────────────────────

    def investigate_incident(self, incident_id: str) -> AgentDiagnosis:
        """
        Step 1 of remediation: Run agent investigation, update incident with diagnosis.
        """
        incident = self.incident_svc.get_incident(incident_id)
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")

        self.incident_svc.transition_status(
            incident,
            IncidentStatus.INVESTIGATING,
            "Agent investigation started",
        )

        diagnosis = self.agent.investigate(incident_id)

        self.incident_svc.add_diagnosis(
            incident,
            diagnosis=diagnosis.diagnosis,
            root_cause=diagnosis.root_cause,
            confidence=diagnosis.confidence,
            recommended_action=diagnosis.recommended_action,
            risk_level=diagnosis.risk_level,
            requires_human_approval=diagnosis.requires_human_approval,
            evidence=diagnosis.evidence,
            verification_plan=diagnosis.verification_plan,
        )

        self.incident_svc.transition_status(
            incident,
            IncidentStatus.DIAGNOSED,
            f"Diagnosis complete: {diagnosis.root_cause[:200]}",
            {"method": diagnosis.diagnosis_method, "confidence": diagnosis.confidence},
        )

        return diagnosis

    # ── Phase 4 & 5: Policy Check + Remediate ────────────────────────────────

    def remediate_incident(self, incident_id: str) -> dict:
        """
        Given a diagnosed incident, evaluate policy and execute if approved.
        Returns execution result.
        """
        incident = self.incident_svc.get_incident(incident_id)
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")

        if incident.status not in (IncidentStatus.DIAGNOSED, IncidentStatus.AWAITING_APPROVAL):
            raise ValueError(f"Cannot remediate incident in status {incident.status.value}")

        if not incident.recommended_action:
            raise ValueError("No recommended action on incident")

        # MONITOR means "watch, no action needed" — resolve as monitoring
        if incident.recommended_action == "MONITOR":
            self.incident_svc.transition_status(
                incident,
                IncidentStatus.VERIFYING,
                "Agent recommended MONITOR — no automated action required. Continuing to observe.",
            )
            self.db.flush()
            return {
                "status": "monitoring",
                "action": "MONITOR",
                "reason": (
                    "Agent assessed risk as LOW with no immediate action required. "
                    "The incident will remain open for monitoring."
                ),
            }

        try:
            action_type = ActionType(incident.recommended_action)
        except ValueError:
            raise ValueError(f"Unknown action type: {incident.recommended_action}")

        # Build policy context
        policy_context = self._build_policy_context(incident)

        # Evaluate
        policy_result = self.policy_engine.evaluate(
            action_type=action_type,
            incident_id=incident_id,
            context=policy_context,
            requested_by="self_healing_orchestrator",
        )

        self.incident_svc.add_timeline_event(
            incident,
            event_type=f"POLICY_EVALUATED",
            description=f"Policy decision: {policy_result.decision.value} — {policy_result.reason[:200]}",
            details={
                "decision": policy_result.decision.value,
                "policy": policy_result.policy_name,
                "risk_level": policy_result.risk_level.value,
                "action": action_type.value,
            },
        )

        # REQUIRES_APPROVAL → create approval record, block execution
        if policy_result.decision == PolicyDecisionResult.REQUIRES_APPROVAL:
            approval = self._create_approval_request(incident, action_type, policy_result)
            self.incident_svc.transition_status(
                incident,
                IncidentStatus.AWAITING_APPROVAL,
                f"Awaiting human approval for {action_type.value} (risk: {policy_result.risk_level.value})",
                {"approval_id": approval.id},
            )
            return {
                "status": "awaiting_approval",
                "approval_id": approval.id,
                "action": action_type.value,
                "reason": policy_result.reason,
            }

        # DENIED → update incident, do nothing
        if policy_result.decision == PolicyDecisionResult.DENIED:
            self.incident_svc.transition_status(
                incident,
                IncidentStatus.FAILED,
                f"Remediation denied by policy: {policy_result.reason[:300]}",
            )
            return {
                "status": "denied",
                "action": action_type.value,
                "reason": policy_result.reason,
            }

        # APPROVED → execute
        return self._execute_remediation(incident, action_type, policy_result, policy_context)

    def _execute_remediation(
        self,
        incident: Incident,
        action_type: ActionType,
        policy_result,
        policy_context: dict,
    ) -> dict:
        self.incident_svc.transition_status(
            incident,
            IncidentStatus.REMEDIATING,
            f"Executing remediation: {action_type.value}",
        )

        params = self._build_execution_params(incident, action_type, policy_context)

        try:
            result = self.execution.execute(
                action_type=action_type,
                policy_result=policy_result,
                incident_id=incident.id,
                parameters=params,
            )
        except Exception as exc:
            self.incident_svc.transition_status(
                incident,
                IncidentStatus.FAILED,
                f"Remediation execution failed: {exc}",
            )
            raise

        # Post-execution: handle specific action types
        if action_type == ActionType.RETRAIN_MODEL:
            return self._post_retrain(incident, result, policy_context)
        elif action_type == ActionType.ROLLBACK_MODEL:
            return self._post_rollback(incident, result)
        else:
            self.incident_svc.transition_status(
                incident,
                IncidentStatus.VERIFYING,
                f"Remediation complete. Beginning verification.",
            )
            return {"status": "success", "action": action_type.value, "result": result}

    def _post_retrain(self, incident: Incident, retrain_result: dict, context: dict) -> dict:
        """After successful retraining, run quality gates and decide on canary."""
        model_version_id = retrain_result.get("model_version_id")
        if not model_version_id:
            return {"status": "success", "action": "RETRAIN_MODEL", "result": retrain_result}

        mv = self.db.query(ModelVersion).filter(ModelVersion.id == model_version_id).first()

        # Run quality gates
        prod_mv = (
            self.db.query(ModelVersion)
            .filter(
                ModelVersion.model_name == self.settings.mlflow_model_name,
                ModelVersion.stage == "PRODUCTION",
            )
            .first()
        )

        production_metrics = {}
        if prod_mv:
            production_metrics = {
                "f1_score": prod_mv.f1_score or 0.0,
                "avg_latency_ms": prod_mv.avg_latency_ms or 100.0,
            }

        candidate_metrics = {
            "f1_score": mv.f1_score or 0.0,
            "avg_latency_ms": mv.avg_latency_ms or 50.0,
        }

        # Quality gate check
        gate_passed, gate_details = self._check_quality_gates(
            candidate_metrics, production_metrics
        )

        mv.quality_gate_passed = gate_passed
        mv.quality_gate_details = gate_details

        self.incident_svc.add_timeline_event(
            incident,
            "QUALITY_GATES_EVALUATED",
            f"Quality gates: {'PASSED' if gate_passed else 'FAILED'}",
            gate_details,
        )

        if not gate_passed:
            from aegisml.database.models import ModelStage
            mv.stage = ModelStage.REJECTED
            self.incident_svc.transition_status(
                incident,
                IncidentStatus.FAILED,
                f"Candidate model rejected: quality gates failed. {gate_details.get('rejection_reasons', [])}",
            )
            return {
                "status": "quality_gates_failed",
                "gate_details": gate_details,
                "model_version": mv.version,
            }

        # Try to start canary
        canary_context = {
            "quality_gate_passed": True,
            "gate_details": gate_details,
            "candidate_f1": candidate_metrics["f1_score"],
            "production_f1": production_metrics.get("f1_score", 0),
            "candidate_latency_ms": candidate_metrics["avg_latency_ms"],
            "data_quality_status": context.get("data_quality_status", "PASSED"),
        }

        canary_policy = self.policy_engine.evaluate(
            action_type=ActionType.START_CANARY,
            incident_id=incident.id,
            context=canary_context,
        )

        if canary_policy.decision == PolicyDecisionResult.REQUIRES_APPROVAL:
            approval = self._create_approval_request(incident, ActionType.START_CANARY, canary_policy)
            self.incident_svc.transition_status(
                incident,
                IncidentStatus.AWAITING_APPROVAL,
                f"Canary deployment requires human approval.",
                {"approval_id": approval.id},
            )
            return {
                "status": "awaiting_approval",
                "action": "START_CANARY",
                "approval_id": approval.id,
            }

        if canary_policy.decision == PolicyDecisionResult.APPROVED:
            canary_result = self.execution.execute(
                action_type=ActionType.START_CANARY,
                policy_result=canary_policy,
                incident_id=incident.id,
                parameters={"model_version_id": model_version_id},
            )
            self.incident_svc.transition_status(
                incident,
                IncidentStatus.VERIFYING,
                f"Canary deployment started. Monitoring health.",
            )
            return {
                "status": "canary_started",
                "canary_result": canary_result,
                "retrain_result": retrain_result,
            }

        return {"status": "success", "action": "RETRAIN_MODEL", "result": retrain_result}

    def _post_rollback(self, incident: Incident, rollback_result: dict) -> dict:
        self.incident_svc.transition_status(
            incident,
            IncidentStatus.ROLLED_BACK,
            f"Rollback complete. Previous model restored. Reason: {rollback_result.get('reason', 'health_check_failure')}",
            {"rollback_result": rollback_result},
        )
        return {"status": "rolled_back", "result": rollback_result}

    # ── Phase 6: Verify ───────────────────────────────────────────────────────

    def verify_canary(self, deployment_id: str, incident_id: str | None = None) -> dict:
        """
        Check canary health. If passing, advance traffic.
        If failing, trigger automatic rollback.
        """
        health = self.canary_monitor.check_health(deployment_id)

        if not health["healthy"]:
            # Automatic rollback — Policy E
            failed_gates = health.get("failed_gates", [])
            reason = "; ".join(g["description"] for g in failed_gates)

            rollback_policy = self.policy_engine.evaluate(
                action_type=ActionType.ROLLBACK_MODEL,
                incident_id=incident_id,
                context={"trigger_reason": f"canary_health_failure: {reason}"},
            )

            if rollback_policy.decision == PolicyDecisionResult.APPROVED:
                rollback_result = self.execution.execute(
                    action_type=ActionType.ROLLBACK_MODEL,
                    policy_result=rollback_policy,
                    incident_id=incident_id,
                    parameters={"reason": reason},
                )

                if incident_id:
                    incident = self.incident_svc.get_incident(incident_id)
                    if incident:
                        self.incident_svc.transition_status(
                            incident,
                            IncidentStatus.ROLLED_BACK,
                            f"Automatic rollback triggered: {reason}",
                            {"failed_gates": failed_gates},
                        )

            return {
                "status": "rolled_back",
                "reason": reason,
                "failed_gates": failed_gates,
            }

        # Healthy — advance traffic
        advance = self.canary_monitor.advance_traffic(deployment_id)

        dep = self.db.query(ModelDeployment).filter(ModelDeployment.id == deployment_id).first()
        new_traffic = dep.canary_traffic_percent if dep else 0

        if new_traffic >= 0.99:
            # Complete deployment
            complete_context = {
                "canary_error_rate": dep.canary_error_rate or 0,
                "canary_latency_ms": dep.canary_latency_ms or 0,
                "canary_traffic_percent": new_traffic,
            }
            complete_policy = self.policy_engine.evaluate(
                action_type=ActionType.COMPLETE_DEPLOYMENT,
                incident_id=incident_id,
                context=complete_context,
            )

            if complete_policy.decision == PolicyDecisionResult.APPROVED:
                complete_result = self.execution.execute(
                    action_type=ActionType.COMPLETE_DEPLOYMENT,
                    policy_result=complete_policy,
                    incident_id=incident_id,
                    parameters={"deployment_id": deployment_id},
                )

                if incident_id:
                    incident = self.incident_svc.get_incident(incident_id)
                    if incident:
                        incident.resolution_notes = "Canary deployment completed successfully. Model promoted to production."
                        incident.verification_status = "PASSED"
                        self.incident_svc.transition_status(
                            incident,
                            IncidentStatus.RESOLVED,
                            "Incident resolved. Candidate model promoted to production.",
                        )

                return {"status": "promoted", "result": complete_result}

        return {
            "status": "healthy",
            "traffic_advanced": advance,
            "current_traffic": new_traffic,
        }

    # ── Approval workflows ────────────────────────────────────────────────────

    def process_approval(
        self, approval_id: str, approved: bool, decided_by: str, reason: str = ""
    ) -> dict:
        approval = self.db.query(Approval).filter(Approval.id == approval_id).first()
        if not approval:
            raise ValueError(f"Approval {approval_id} not found")

        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(f"Approval already in state: {approval.status.value}")

        approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        approval.decided_by = decided_by
        approval.decision_reason = reason
        approval.decided_at = datetime.now(timezone.utc)

        incident = self.incident_svc.get_incident(approval.incident_id)

        if not approved:
            if incident:
                self.incident_svc.transition_status(
                    incident,
                    IncidentStatus.FAILED,
                    f"Human approval rejected by {decided_by}: {reason}",
                )
            self.db.flush()
            return {"status": "rejected", "approval_id": approval_id}

        # Approved — execute the action
        if incident:
            from aegisml.policies.engine import PolicyEvaluationResult

            fake_approval_result = PolicyEvaluationResult(
                action_type=approval.action_type,
                decision=PolicyDecisionResult.APPROVED,
                reason=f"Human approved by {decided_by}",
                risk_level=approval.risk_level,
                policy_name="HUMAN_APPROVAL",
                requires_human_approval=False,
                context=approval.context or {},
            )

            params = self._build_execution_params(incident, approval.action_type, approval.context or {})

            try:
                result = self.execution.execute(
                    action_type=approval.action_type,
                    policy_result=fake_approval_result,
                    incident_id=incident.id,
                    parameters=params,
                )
                self.incident_svc.transition_status(
                    incident,
                    IncidentStatus.VERIFYING,
                    f"Human-approved action {approval.action_type.value} executed.",
                )
                self.db.flush()
                return {"status": "approved_and_executed", "result": result}
            except Exception as exc:
                self.incident_svc.transition_status(
                    incident,
                    IncidentStatus.FAILED,
                    f"Execution failed after human approval: {exc}",
                )
                raise

        self.db.flush()
        return {"status": "approved", "approval_id": approval_id}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_policy_context(self, incident: Incident) -> dict:
        metrics = incident.observed_metrics or {}
        latest_snapshot = (
            self.db.query(MonitoringSnapshot)
            .filter(MonitoringSnapshot.model_name == incident.affected_model)
            .order_by(MonitoringSnapshot.created_at.desc())
            .first()
        )

        return {
            "incident_type": incident.incident_type.value,
            "severity": incident.severity.value,
            "drift_score": metrics.get("drift_score", 0),
            "f1_current": (
                latest_snapshot.f1_score if latest_snapshot and latest_snapshot.f1_score else 0.85
            ),
            "data_quality_status": (
                latest_snapshot.data_quality_status if latest_snapshot else "PASSED"
            ),
            "risk_level": incident.risk_level.value if incident.risk_level else "LOW",
            "recommended_action": incident.recommended_action,
        }

    def _build_execution_params(
        self, incident: Incident, action_type: ActionType, context: dict
    ) -> dict:
        metrics = incident.observed_metrics or {}

        if action_type == ActionType.RETRAIN_MODEL:
            # Use drifted dataset version if available from incident metrics
            obs = incident.observed_metrics or {}
            # F1 covariate drift → generate and use drift dataset
            drift_type = obs.get("drift_type", "")
            if "COVARIATE" in str(drift_type) or "CONCEPT" in str(drift_type):
                dataset_version = "v1"  # retrain on original — XGBoost will learn new pattern
            else:
                dataset_version = obs.get("dataset_version", "v1")
            return {
                "dataset_version": str(dataset_version),
                "incident_id": incident.id,
            }
        elif action_type == ActionType.START_CANARY:
            # Find the most recent VALIDATED candidate version
            mv = (
                self.db.query(ModelVersion)
                .filter(
                    ModelVersion.model_name == (
                        incident.affected_model or self.settings.mlflow_model_name
                    ),
                    ModelVersion.quality_gate_passed == True,
                )
                .order_by(ModelVersion.version.desc())
                .first()
            )
            return {"model_version_id": mv.id if mv else None}
        elif action_type == ActionType.ROLLBACK_MODEL:
            return {
                "reason": metrics.get("rollback_reason", "health_check_failure"),
                "deployment_id": metrics.get("deployment_id"),
            }
        elif action_type == ActionType.RETRY_PIPELINE:
            return {
                "dataset_version": metrics.get("dataset_version", "v1"),
                "retry_count": metrics.get("retry_count", 0),
            }
        else:
            return context

    def _check_quality_gates(
        self,
        candidate_metrics: dict,
        production_metrics: dict,
    ) -> tuple[bool, dict]:
        """
        Quality gate evaluation.
        Gates (in order):
          1. Candidate F1 >= absolute threshold
          2. Candidate F1 does NOT regress >5% below production
          3. Candidate latency <= SLA
        """
        settings = self.settings
        gates = []
        rejection_reasons = []

        candidate_f1      = float(candidate_metrics.get("f1_score", 0) or 0)
        candidate_latency = float(candidate_metrics.get("avg_latency_ms", 999) or 999)
        prod_f1           = float((production_metrics or {}).get("f1_score", 0) or 0)

        # Gate 1: Absolute F1 minimum
        g1_pass = candidate_f1 >= settings.f1_threshold
        gates.append({"gate": "minimum_f1", "passed": g1_pass,
                       "candidate": round(candidate_f1, 4), "threshold": settings.f1_threshold})
        if not g1_pass:
            rejection_reasons.append(
                f"F1 {candidate_f1:.4f} < minimum threshold {settings.f1_threshold}"
            )

        # Gate 2: No significant regression vs production (>5% F1 drop blocks)
        if prod_f1 > 0 and candidate_f1 < prod_f1 - 0.05:
            gates.append({"gate": "no_regression", "passed": False,
                           "candidate": round(candidate_f1, 4),
                           "production": round(prod_f1, 4), "threshold": round(prod_f1 - 0.05, 4)})
            rejection_reasons.append(
                f"Candidate F1 {candidate_f1:.4f} regressed >5% below production {prod_f1:.4f}"
            )
        else:
            gates.append({"gate": "no_regression", "passed": True,
                           "candidate": round(candidate_f1, 4), "production": round(prod_f1, 4)})

        # Gate 3: Latency SLA
        g3_pass = candidate_latency <= settings.latency_sla_ms
        gates.append({"gate": "latency_sla", "passed": g3_pass,
                       "candidate_ms": round(candidate_latency, 2), "sla_ms": settings.latency_sla_ms})
        if not g3_pass:
            rejection_reasons.append(
                f"Latency {candidate_latency:.1f}ms > SLA {settings.latency_sla_ms}ms"
            )

        passed = len(rejection_reasons) == 0
        return passed, {"gates": gates, "rejection_reasons": rejection_reasons,
                        "overall": "PASSED" if passed else "FAILED"}

        passed = len(rejection_reasons) == 0
        return passed, {
            "gates": gates,
            "rejection_reasons": rejection_reasons,
            "overall": "PASSED" if passed else "FAILED",
        }

    def _create_approval_request(
        self, incident: Incident, action_type: ActionType, policy_result
    ) -> Approval:
        from datetime import timedelta
        approval = Approval(
            incident_id=incident.id,
            action_type=action_type,
            risk_level=policy_result.risk_level,
            status=ApprovalStatus.PENDING,
            description=policy_result.reason,
            context=policy_result.context,
            requested_by="self_healing_orchestrator",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        self.db.add(approval)
        self.db.flush()
        return approval
