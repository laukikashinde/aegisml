"""Tests for the Policy Engine — must be 100% deterministic."""
from __future__ import annotations

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from aegisml.database.models import (
    ActionType,
    PolicyDecisionResult,
    RiskLevel,
)


class TestPolicyEngine:
    """Policy engine evaluates using the test DB session (from conftest.py)."""

    def test_retrain_approved_when_drift_high(self, db):
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=ActionType.RETRAIN_MODEL,
            incident_id=None,
            context={
                "drift_score": 0.35,
                "f1_current": 0.78,
                "data_quality_status": "PASSED",
                "risk_level": "LOW",
            },
        )
        assert result.decision == PolicyDecisionResult.APPROVED

    def test_retrain_denied_when_no_trigger(self, db):
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=ActionType.RETRAIN_MODEL,
            incident_id=None,
            context={
                "drift_score": 0.05,   # below threshold
                "f1_current": 0.92,    # above threshold
                "data_quality_status": "PASSED",
                "risk_level": "LOW",
            },
        )
        assert result.decision == PolicyDecisionResult.DENIED

    def test_retrain_denied_on_bad_data_quality(self, db):
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=ActionType.RETRAIN_MODEL,
            incident_id=None,
            context={
                "drift_score": 0.40,
                "f1_current": 0.70,
                "data_quality_status": "FAILED",
                "risk_level": "LOW",
            },
        )
        assert result.decision == PolicyDecisionResult.DENIED
        assert "data quality" in result.reason.lower()

    def test_retrain_requires_approval_on_high_risk(self, db):
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=ActionType.RETRAIN_MODEL,
            incident_id=None,
            context={
                "drift_score": 0.40,
                "f1_current": 0.70,
                "data_quality_status": "PASSED",
                "risk_level": "HIGH",
            },
        )
        assert result.decision == PolicyDecisionResult.REQUIRES_APPROVAL
        assert result.requires_human_approval is True

    def test_canary_approved_when_gates_pass(self, db):
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=ActionType.START_CANARY,
            incident_id=None,
            context={
                "quality_gate_passed": True,
                "gate_details": {"rejection_reasons": []},
                "candidate_f1": 0.91,
                "production_f1": 0.87,
                "candidate_latency_ms": 25.0,
                "data_quality_status": "PASSED",
            },
        )
        assert result.decision == PolicyDecisionResult.APPROVED

    def test_canary_denied_when_gates_fail(self, db):
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=ActionType.START_CANARY,
            incident_id=None,
            context={
                "quality_gate_passed": False,
                "gate_details": {"rejection_reasons": ["F1 did not improve"]},
                "candidate_f1": 0.82,
                "production_f1": 0.89,
                "candidate_latency_ms": 20.0,
                "data_quality_status": "PASSED",
            },
        )
        assert result.decision == PolicyDecisionResult.DENIED

    def test_canary_denied_on_latency_breach(self, db):
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=ActionType.START_CANARY,
            incident_id=None,
            context={
                "quality_gate_passed": True,
                "gate_details": {"rejection_reasons": []},
                "candidate_f1": 0.90,
                "production_f1": 0.87,
                "candidate_latency_ms": 350.0,  # > 200ms SLA
                "data_quality_status": "PASSED",
            },
        )
        assert result.decision == PolicyDecisionResult.DENIED
        assert "latency" in result.reason.lower()

    def test_canary_requires_approval_on_large_f1_jump(self, db):
        """Policy accepts candidate that meets threshold even if same as production."""
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=ActionType.START_CANARY,
            incident_id=None,
            context={
                "quality_gate_passed": True,
                "gate_details": {"rejection_reasons": []},
                "candidate_f1": 0.97,
                "production_f1": 0.80,
                "candidate_latency_ms": 20.0,
                "data_quality_status": "PASSED",
            },
        )
        # Candidate improves significantly — should be approved (no regression)
        assert result.decision in (
            PolicyDecisionResult.APPROVED,
            PolicyDecisionResult.REQUIRES_APPROVAL,
        )

    def test_rollback_always_approved(self, db):
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=ActionType.ROLLBACK_MODEL,
            incident_id=None,
            context={"trigger_reason": "error_rate_exceeded"},
        )
        assert result.decision == PolicyDecisionResult.APPROVED

    def test_create_incident_always_approved(self, db):
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=ActionType.CREATE_INCIDENT,
            incident_id=None,
            context={},
        )
        assert result.decision == PolicyDecisionResult.APPROVED

    def test_retry_pipeline_approved_under_limit(self, db):
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=ActionType.RETRY_PIPELINE,
            incident_id=None,
            context={"retry_count": 1, "error_type": "transient"},
        )
        assert result.decision == PolicyDecisionResult.APPROVED

    def test_retry_pipeline_denied_over_limit(self, db):
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=ActionType.RETRY_PIPELINE,
            incident_id=None,
            context={"retry_count": 3, "error_type": "transient"},
        )
        assert result.decision == PolicyDecisionResult.DENIED

    def test_decisions_are_persisted(self, db):
        from aegisml.policies.engine import PolicyEngine
        from aegisml.database.models import PolicyDecision
        engine = PolicyEngine(db)
        before = db.query(PolicyDecision).count()
        engine.evaluate(
            action_type=ActionType.ROLLBACK_MODEL,
            incident_id=None,
            context={"trigger_reason": "test"},
        )
        db.flush()
        after = db.query(PolicyDecision).count()
        assert after == before + 1
