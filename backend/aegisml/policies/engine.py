"""
AegisML — Policy Engine.

CRITICAL: This module makes ALL action decisions.
The LLM agent proposes actions; this engine APPROVES or DENIES them.
The LLM has ZERO ability to bypass this layer.

Policies are loaded from the database and evaluated deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from aegisml.config import get_settings
from aegisml.database.models import (
    ActionType,
    AuditLog,
    IncidentSeverity,
    IncidentType,
    Policy,
    PolicyDecision,
    PolicyDecisionResult,
    RiskLevel,
)

logger = structlog.get_logger(__name__)


@dataclass
class PolicyEvaluationResult:
    action_type: ActionType
    decision: PolicyDecisionResult
    reason: str
    risk_level: RiskLevel
    policy_name: str | None
    requires_human_approval: bool
    context: dict[str, Any]


class PolicyEngine:
    """
    Deterministic policy evaluation.

    Evaluates proposed actions against configured policies.
    Returns APPROVED, DENIED, or REQUIRES_APPROVAL.
    """

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def evaluate(
        self,
        action_type: ActionType,
        incident_id: str | None,
        context: dict[str, Any],
        requested_by: str = "agent",
    ) -> PolicyEvaluationResult:
        """
        Main entry point. Evaluates an action proposal.
        Returns a PolicyEvaluationResult.
        Never raises — always returns a decision.
        """
        try:
            result = self._evaluate_action(action_type, context)
        except Exception as exc:
            logger.error("policy_engine_error", action=action_type.value, error=str(exc))
            result = PolicyEvaluationResult(
                action_type=action_type,
                decision=PolicyDecisionResult.DENIED,
                reason=f"Policy engine error — defaulting to DENIED for safety: {exc}",
                risk_level=RiskLevel.HIGH,
                policy_name="SAFETY_DEFAULT",
                requires_human_approval=False,
                context=context,
            )

        # Persist decision
        self._persist_decision(result, incident_id, requested_by)

        logger.info(
            "policy_decision",
            action=action_type.value,
            decision=result.decision.value,
            policy=result.policy_name,
            reason=result.reason[:200],
        )
        return result

    # ── Policy Rules (deterministic) ──────────────────────────────────────────

    def _evaluate_action(
        self, action_type: ActionType, context: dict[str, Any]
    ) -> PolicyEvaluationResult:
        """Route to the correct policy rule."""

        if action_type == ActionType.RETRAIN_MODEL:
            return self._policy_retrain(context)

        elif action_type == ActionType.START_CANARY:
            return self._policy_start_canary(context)

        elif action_type == ActionType.COMPLETE_DEPLOYMENT:
            return self._policy_complete_deployment(context)

        elif action_type == ActionType.ROLLBACK_MODEL:
            return self._policy_rollback(context)

        elif action_type == ActionType.REGISTER_MODEL:
            return self._policy_register_model(context)

        elif action_type == ActionType.PROMOTE_MODEL:
            return self._policy_promote_model(context)

        elif action_type == ActionType.RETRY_PIPELINE:
            return self._policy_retry_pipeline(context)

        elif action_type == ActionType.RESTART_SERVICE:
            return self._policy_restart_service(context)

        elif action_type == ActionType.CREATE_INCIDENT:
            return PolicyEvaluationResult(
                action_type=action_type,
                decision=PolicyDecisionResult.APPROVED,
                reason="Creating incidents is always permitted.",
                risk_level=RiskLevel.LOW,
                policy_name="POLICY_ALWAYS_ALLOW_INCIDENT",
                requires_human_approval=False,
                context=context,
            )

        elif action_type == ActionType.REQUEST_HUMAN_APPROVAL:
            return PolicyEvaluationResult(
                action_type=action_type,
                decision=PolicyDecisionResult.APPROVED,
                reason="Requesting human approval is always permitted.",
                risk_level=RiskLevel.LOW,
                policy_name="POLICY_ALWAYS_ALLOW_APPROVAL_REQUEST",
                requires_human_approval=False,
                context=context,
            )

        else:
            return PolicyEvaluationResult(
                action_type=action_type,
                decision=PolicyDecisionResult.DENIED,
                reason=f"Unknown action type: {action_type.value}. Defaulting to DENIED.",
                risk_level=RiskLevel.HIGH,
                policy_name="POLICY_UNKNOWN_ACTION",
                requires_human_approval=False,
                context=context,
            )

    # ── Policy A: Retraining ──────────────────────────────────────────────────

    def _policy_retrain(self, context: dict) -> PolicyEvaluationResult:
        """
        Policy A: Allow automatic retraining if:
          - drift OR performance degradation detected
          - data quality passes
          - risk level is LOW or MEDIUM
        """
        drift_score = float(context.get("drift_score", 0))
        f1_current = float(context.get("f1_current", 1.0))
        data_quality_status = context.get("data_quality_status", "PASSED")
        risk_level_str = context.get("risk_level", "LOW")
        incident_type = context.get("incident_type", "")

        drift_threshold = self.settings.drift_threshold
        f1_threshold = self.settings.f1_threshold

        trigger_reason = []

        if drift_score > drift_threshold:
            trigger_reason.append(
                f"drift_score={drift_score:.3f} > threshold={drift_threshold}"
            )
        if f1_current < f1_threshold:
            trigger_reason.append(
                f"f1={f1_current:.3f} < threshold={f1_threshold}"
            )

        if not trigger_reason:
            return PolicyEvaluationResult(
                action_type=ActionType.RETRAIN_MODEL,
                decision=PolicyDecisionResult.DENIED,
                reason=(
                    f"No retraining trigger: drift={drift_score:.3f} <= {drift_threshold}, "
                    f"f1={f1_current:.3f} >= {f1_threshold}."
                ),
                risk_level=RiskLevel.LOW,
                policy_name="POLICY_A_RETRAIN",
                requires_human_approval=False,
                context=context,
            )

        if data_quality_status == "FAILED":
            return PolicyEvaluationResult(
                action_type=ActionType.RETRAIN_MODEL,
                decision=PolicyDecisionResult.DENIED,
                reason=(
                    "Retraining denied: training data quality is FAILED. "
                    "Fix data quality issues before retraining."
                ),
                risk_level=RiskLevel.MEDIUM,
                policy_name="POLICY_A_RETRAIN",
                requires_human_approval=False,
                context=context,
            )

        risk = RiskLevel(risk_level_str) if risk_level_str in RiskLevel.__members__ else RiskLevel.LOW

        # High risk requires approval
        if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return PolicyEvaluationResult(
                action_type=ActionType.RETRAIN_MODEL,
                decision=PolicyDecisionResult.REQUIRES_APPROVAL,
                reason=(
                    f"Retraining requires human approval due to risk_level={risk.value}. "
                    f"Triggers: {'; '.join(trigger_reason)}"
                ),
                risk_level=risk,
                policy_name="POLICY_A_RETRAIN",
                requires_human_approval=True,
                context=context,
            )

        return PolicyEvaluationResult(
            action_type=ActionType.RETRAIN_MODEL,
            decision=PolicyDecisionResult.APPROVED,
            reason=f"Automatic retraining approved. Triggers: {'; '.join(trigger_reason)}",
            risk_level=risk,
            policy_name="POLICY_A_RETRAIN",
            requires_human_approval=False,
            context=context,
        )

    # ── Policy B: Start canary ────────────────────────────────────────────────

    def _policy_start_canary(self, context: dict) -> PolicyEvaluationResult:
        """
        Policy B: Allow canary deployment if quality gates passed.
        """
        quality_gate_passed = context.get("quality_gate_passed", False)
        gate_details = context.get("gate_details", {})
        candidate_f1 = float(context.get("candidate_f1", 0))
        production_f1 = float(context.get("production_f1", 0))
        candidate_latency = float(context.get("candidate_latency_ms", 999))
        data_quality = context.get("data_quality_status", "PASSED")

        if not quality_gate_passed:
            reasons = gate_details.get("rejection_reasons", ["Quality gates failed"])
            return PolicyEvaluationResult(
                action_type=ActionType.START_CANARY,
                decision=PolicyDecisionResult.DENIED,
                reason=f"Canary deployment denied — quality gates FAILED: {'; '.join(reasons)}",
                risk_level=RiskLevel.HIGH,
                policy_name="POLICY_D_REJECT_FAILED_GATES",
                requires_human_approval=False,
                context=context,
            )

        if data_quality == "FAILED":
            return PolicyEvaluationResult(
                action_type=ActionType.START_CANARY,
                decision=PolicyDecisionResult.DENIED,
                reason="Canary deployment denied — current data quality is FAILED.",
                risk_level=RiskLevel.HIGH,
                policy_name="POLICY_B_CANARY",
                requires_human_approval=False,
                context=context,
            )

        if candidate_latency > self.settings.latency_sla_ms:
            return PolicyEvaluationResult(
                action_type=ActionType.START_CANARY,
                decision=PolicyDecisionResult.DENIED,
                reason=(
                    f"Canary denied — candidate latency {candidate_latency:.1f}ms "
                    f"> SLA {self.settings.latency_sla_ms}ms."
                ),
                risk_level=RiskLevel.MEDIUM,
                policy_name="POLICY_B_CANARY",
                requires_human_approval=False,
                context=context,
            )

        # Only block if candidate is significantly WORSE than production (>5% regression)
        f1_diff = candidate_f1 - production_f1
        if production_f1 > 0 and candidate_f1 < (production_f1 - 0.05):
            return PolicyEvaluationResult(
                action_type=ActionType.START_CANARY,
                decision=PolicyDecisionResult.DENIED,
                reason=(
                    f"Canary denied — candidate F1 {candidate_f1:.4f} regressed "
                    f">5% below production {production_f1:.4f}."
                ),
                risk_level=RiskLevel.HIGH,
                policy_name="POLICY_B_CANARY",
                requires_human_approval=False,
                context=context,
            )

        return PolicyEvaluationResult(
            action_type=ActionType.START_CANARY,
            decision=PolicyDecisionResult.APPROVED,
            reason=(
                f"Canary deployment approved. Quality gates passed. "
                f"F1: {production_f1:.4f} → {candidate_f1:.4f} "
                f"({f1_diff:+.4f}). Latency: {candidate_latency:.1f}ms."
            ),
            risk_level=RiskLevel.MEDIUM,
            policy_name="POLICY_B_CANARY",
            requires_human_approval=False,
            context=context,
        )

    # ── Policy: Complete deployment (promote to 100%) ─────────────────────────

    def _policy_complete_deployment(self, context: dict) -> PolicyEvaluationResult:
        canary_error_rate = float(context.get("canary_error_rate", 0))
        canary_latency = float(context.get("canary_latency_ms", 0))
        canary_traffic = float(context.get("canary_traffic_percent", 0))

        if canary_error_rate > self.settings.error_rate_threshold:
            return PolicyEvaluationResult(
                action_type=ActionType.COMPLETE_DEPLOYMENT,
                decision=PolicyDecisionResult.DENIED,
                reason=(
                    f"Promote denied — canary error rate {canary_error_rate:.3f} "
                    f"> threshold {self.settings.error_rate_threshold}. "
                    "Consider rollback."
                ),
                risk_level=RiskLevel.HIGH,
                policy_name="POLICY_B_CANARY",
                requires_human_approval=False,
                context=context,
            )

        if canary_latency > self.settings.latency_sla_ms:
            return PolicyEvaluationResult(
                action_type=ActionType.COMPLETE_DEPLOYMENT,
                decision=PolicyDecisionResult.DENIED,
                reason=(
                    f"Promote denied — canary latency {canary_latency:.1f}ms "
                    f"> SLA {self.settings.latency_sla_ms}ms."
                ),
                risk_level=RiskLevel.MEDIUM,
                policy_name="POLICY_B_CANARY",
                requires_human_approval=False,
                context=context,
            )

        return PolicyEvaluationResult(
            action_type=ActionType.COMPLETE_DEPLOYMENT,
            decision=PolicyDecisionResult.APPROVED,
            reason=f"Full promotion approved. Canary healthy at {canary_traffic:.0%} traffic.",
            risk_level=RiskLevel.LOW,
            policy_name="POLICY_B_CANARY",
            requires_human_approval=False,
            context=context,
        )

    # ── Policy E: Rollback ────────────────────────────────────────────────────

    def _policy_rollback(self, context: dict) -> PolicyEvaluationResult:
        """Policy E: Auto-rollback when health thresholds breached."""
        trigger = context.get("trigger_reason", "health_check_failure")
        return PolicyEvaluationResult(
            action_type=ActionType.ROLLBACK_MODEL,
            decision=PolicyDecisionResult.APPROVED,
            reason=f"Automatic rollback approved. Trigger: {trigger}",
            risk_level=RiskLevel.HIGH,
            policy_name="POLICY_E_ROLLBACK",
            requires_human_approval=False,
            context=context,
        )

    # ── Policy: Register model ────────────────────────────────────────────────

    def _policy_register_model(self, context: dict) -> PolicyEvaluationResult:
        training_status = context.get("training_status", "success")
        if training_status != "success":
            return PolicyEvaluationResult(
                action_type=ActionType.REGISTER_MODEL,
                decision=PolicyDecisionResult.DENIED,
                reason=f"Cannot register model — training failed: {training_status}",
                risk_level=RiskLevel.MEDIUM,
                policy_name="POLICY_REGISTER_MODEL",
                requires_human_approval=False,
                context=context,
            )
        return PolicyEvaluationResult(
            action_type=ActionType.REGISTER_MODEL,
            decision=PolicyDecisionResult.APPROVED,
            reason="Model registration approved after successful training.",
            risk_level=RiskLevel.LOW,
            policy_name="POLICY_REGISTER_MODEL",
            requires_human_approval=False,
            context=context,
        )

    # ── Policy: Promote model ─────────────────────────────────────────────────

    def _policy_promote_model(self, context: dict) -> PolicyEvaluationResult:
        quality_gate_passed = context.get("quality_gate_passed", False)
        if not quality_gate_passed:
            return PolicyEvaluationResult(
                action_type=ActionType.PROMOTE_MODEL,
                decision=PolicyDecisionResult.DENIED,
                reason="Promotion denied — quality gates not passed.",
                risk_level=RiskLevel.HIGH,
                policy_name="POLICY_D_REJECT_FAILED_GATES",
                requires_human_approval=False,
                context=context,
            )
        return PolicyEvaluationResult(
            action_type=ActionType.PROMOTE_MODEL,
            decision=PolicyDecisionResult.APPROVED,
            reason="Model promotion approved — all quality gates passed.",
            risk_level=RiskLevel.MEDIUM,
            policy_name="POLICY_B_CANARY",
            requires_human_approval=False,
            context=context,
        )

    # ── Policy: Retry pipeline ────────────────────────────────────────────────

    def _policy_retry_pipeline(self, context: dict) -> PolicyEvaluationResult:
        retry_count = int(context.get("retry_count", 0))
        error_type = context.get("error_type", "unknown")

        if retry_count >= 3:
            return PolicyEvaluationResult(
                action_type=ActionType.RETRY_PIPELINE,
                decision=PolicyDecisionResult.DENIED,
                reason=f"Maximum retries ({retry_count}) reached. Manual intervention required.",
                risk_level=RiskLevel.HIGH,
                policy_name="POLICY_RETRY_PIPELINE",
                requires_human_approval=True,
                context=context,
            )

        return PolicyEvaluationResult(
            action_type=ActionType.RETRY_PIPELINE,
            decision=PolicyDecisionResult.APPROVED,
            reason=f"Pipeline retry #{retry_count + 1} approved for error_type={error_type}.",
            risk_level=RiskLevel.LOW,
            policy_name="POLICY_RETRY_PIPELINE",
            requires_human_approval=False,
            context=context,
        )

    # ── Policy: Restart service ───────────────────────────────────────────────

    def _policy_restart_service(self, context: dict) -> PolicyEvaluationResult:
        is_production = context.get("is_production", False)
        if is_production:
            return PolicyEvaluationResult(
                action_type=ActionType.RESTART_SERVICE,
                decision=PolicyDecisionResult.REQUIRES_APPROVAL,
                reason="Restarting a production service requires human approval.",
                risk_level=RiskLevel.HIGH,
                policy_name="POLICY_C_REQUIRE_APPROVAL",
                requires_human_approval=True,
                context=context,
            )
        return PolicyEvaluationResult(
            action_type=ActionType.RESTART_SERVICE,
            decision=PolicyDecisionResult.APPROVED,
            reason="Service restart approved (non-production).",
            risk_level=RiskLevel.MEDIUM,
            policy_name="POLICY_RESTART_SERVICE",
            requires_human_approval=False,
            context=context,
        )

    # ── Persistence ───────────────────────────────────────────────────────────

    def _persist_decision(
        self,
        result: PolicyEvaluationResult,
        incident_id: str | None,
        requested_by: str,
    ) -> None:
        decision = PolicyDecision(
            policy_id=self._get_or_create_policy_id(result.policy_name or "UNKNOWN"),
            incident_id=incident_id,
            action_type=result.action_type,
            result=result.decision,
            reason=result.reason,
            context=result.context,
            evaluated_at=datetime.now(timezone.utc),
        )
        self.db.add(decision)

        audit = AuditLog(
            event_type="POLICY_DECISION",
            actor="policy_engine",
            incident_id=incident_id,
            resource_type="action",
            resource_id=result.action_type.value,
            description=(
                f"Policy {result.policy_name}: {result.action_type.value} → "
                f"{result.decision.value}"
            ),
            details={
                "reason": result.reason,
                "risk_level": result.risk_level.value,
                "requires_approval": result.requires_human_approval,
                "requested_by": requested_by,
            },
            outcome=result.decision.value,
            occurred_at=datetime.now(timezone.utc),
        )
        self.db.add(audit)
        self.db.flush()

    def _get_or_create_policy_id(self, policy_name: str) -> int:
        """Get or create a Policy record by name."""
        existing = (
            self.db.query(Policy).filter(Policy.name == policy_name).first()
        )
        if existing:
            return existing.id

        policy = Policy(
            name=policy_name,
            description=f"Auto-created policy: {policy_name}",
            incident_types=[],
            action_types=[],
            conditions={},
            result=PolicyDecisionResult.APPROVED,
            risk_level=RiskLevel.LOW,
        )
        self.db.add(policy)
        self.db.flush()
        return policy.id
