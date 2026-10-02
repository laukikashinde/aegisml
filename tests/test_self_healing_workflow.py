"""
End-to-end self-healing workflow test.

Tests the full lifecycle:
DATA DRIFT → INCIDENT → INVESTIGATION → DIAGNOSIS → POLICY → REMEDIATION

Also tests the rollback scenario:
BAD CANARY → HEALTH FAILURE → AUTOMATIC ROLLBACK
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from aegisml.database.models import (
    DeploymentStatus,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ModelDeployment,
    ModelStage,
    ModelVersion,
    MonitoringSnapshot,
    PolicyDecisionResult,
)
from aegisml.incidents.service import IncidentService


def _seed_production_model(db):
    """Create a production model version for testing."""
    from datetime import datetime, timezone
    mv = ModelVersion(
        model_name="churn-classifier",
        version=1,
        stage=ModelStage.PRODUCTION,
        f1_score=0.89,
        accuracy=0.87,
        roc_auc=0.93,
        avg_latency_ms=18.0,
        dataset_version="v1",
        quality_gate_passed=True,
    )
    db.add(mv)
    db.flush()
    dep = ModelDeployment(
        model_version_id=mv.id,
        status=DeploymentStatus.ACTIVE,
        canary_traffic_percent=1.0,
        is_production=True,
        is_canary=False,
    )
    db.add(dep)
    db.flush()
    return mv, dep


def _seed_drift_snapshot(db):
    s = MonitoringSnapshot(
        snapshot_type="drift",
        model_name="churn-classifier",
        drift_detected=True,
        drift_score=0.35,
        drifted_features=["income", "employment_years"],
        drift_details={"income": {"baseline_mean": 58240, "current_mean": 87360}},
        f1_score=0.79,
        data_quality_status="PASSED",
    )
    db.add(s)
    db.flush()
    return s


class TestSelfHealingInvestigation:
    def test_investigation_produces_diagnosis(self, db):
        """Agent investigation produces a complete, structured diagnosis."""
        from aegisml.orchestrator.self_healing import SelfHealingOrchestrator
        _seed_production_model(db)
        _seed_drift_snapshot(db)
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="[TEST] Data drift",
            incident_type=IncidentType.DATA_DRIFT,
            severity=IncidentSeverity.HIGH,
            source="test",
            affected_model="churn-classifier",
            observed_metrics={"drift_score": 0.35, "f1_current": 0.79},
        )
        db.flush()

        orchestrator = SelfHealingOrchestrator(db)
        diagnosis = orchestrator.investigate_incident(incident.id)
        db.flush()

        # Diagnosis is complete
        assert diagnosis.incident_id == incident.id
        assert diagnosis.diagnosis
        assert diagnosis.root_cause
        assert 0.0 <= diagnosis.confidence <= 1.0
        assert diagnosis.recommended_action in (
            "RETRAIN_MODEL", "MONITOR", "REQUEST_HUMAN_APPROVAL",
        )
        assert diagnosis.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert isinstance(diagnosis.verification_plan, list)
        assert len(diagnosis.verification_plan) > 0

        # Incident updated with diagnosis
        updated = svc.get_incident(incident.id)
        assert updated.status == IncidentStatus.DIAGNOSED
        assert updated.diagnosis is not None
        assert updated.suspected_root_cause is not None

    def test_investigation_transitions_status(self, db):
        """Status correctly transitions DETECTED → INVESTIGATING → DIAGNOSED."""
        from aegisml.orchestrator.self_healing import SelfHealingOrchestrator
        _seed_drift_snapshot(db)
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="Status transition test",
            incident_type=IncidentType.DATA_DRIFT,
            severity=IncidentSeverity.MEDIUM,
            source="test",
            affected_model="churn-classifier",
        )
        db.flush()
        assert incident.status == IncidentStatus.DETECTED

        orchestrator = SelfHealingOrchestrator(db)
        orchestrator.investigate_incident(incident.id)
        db.flush()
        assert incident.status == IncidentStatus.DIAGNOSED

    def test_timeline_events_recorded(self, db):
        """Timeline events are recorded during investigation."""
        from aegisml.database.models import IncidentTimelineEvent
        from aegisml.orchestrator.self_healing import SelfHealingOrchestrator
        _seed_drift_snapshot(db)
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="Timeline test",
            incident_type=IncidentType.DATA_DRIFT,
            severity=IncidentSeverity.HIGH,
            source="test",
            affected_model="churn-classifier",
        )
        db.flush()

        orchestrator = SelfHealingOrchestrator(db)
        orchestrator.investigate_incident(incident.id)
        db.flush()

        events = (
            db.query(IncidentTimelineEvent)
            .filter(IncidentTimelineEvent.incident_id == incident.id)
            .all()
        )
        event_types = {e.event_type for e in events}
        assert "INCIDENT_CREATED" in event_types
        assert "DIAGNOSIS_COMPLETE" in event_types


class TestPolicyRemediationWorkflow:
    def test_policy_approves_retrain_on_drift(self, db):
        """Policy engine approves retraining when drift is high."""
        from aegisml.policies.engine import PolicyEngine
        engine = PolicyEngine(db)
        result = engine.evaluate(
            action_type=__import__(
                "aegisml.database.models", fromlist=["ActionType"]
            ).ActionType.RETRAIN_MODEL,
            incident_id=None,
            context={
                "drift_score": 0.35,
                "f1_current": 0.79,
                "data_quality_status": "PASSED",
                "risk_level": "LOW",
            },
        )
        assert result.decision == PolicyDecisionResult.APPROVED

    def test_remediation_denied_for_unknown_action(self, db):
        """Incidents with unsupported recommended actions fail gracefully."""
        from aegisml.orchestrator.self_healing import SelfHealingOrchestrator
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="Bad action test",
            incident_type=IncidentType.UNKNOWN,
            severity=IncidentSeverity.LOW,
            source="test",
        )
        incident.status = IncidentStatus.DIAGNOSED
        incident.recommended_action = "INVALID_ACTION"
        db.flush()

        orchestrator = SelfHealingOrchestrator(db)
        with pytest.raises(ValueError, match="Unknown action type"):
            orchestrator.remediate_incident(incident.id)

    def test_remediation_blocked_when_not_diagnosed(self, db):
        """Remediation is blocked if incident is not yet diagnosed."""
        from aegisml.orchestrator.self_healing import SelfHealingOrchestrator
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="Not diagnosed",
            incident_type=IncidentType.DATA_DRIFT,
            severity=IncidentSeverity.HIGH,
            source="test",
        )
        db.flush()
        # Status is DETECTED — not DIAGNOSED
        orchestrator = SelfHealingOrchestrator(db)
        with pytest.raises(ValueError, match="Cannot remediate"):
            orchestrator.remediate_incident(incident.id)


class TestRollbackScenario:
    def test_canary_health_check_triggers_rollback(self, db):
        """Unhealthy canary automatically triggers rollback."""
        from datetime import datetime, timezone
        from aegisml.orchestrator.self_healing import SelfHealingOrchestrator

        # Set up production model
        prod_mv = ModelVersion(
            model_name="churn-classifier",
            version=10,
            stage=ModelStage.PRODUCTION,
            f1_score=0.89,
            avg_latency_ms=20.0,
        )
        db.add(prod_mv)
        db.flush()
        prod_dep = ModelDeployment(
            model_version_id=prod_mv.id,
            status=DeploymentStatus.ACTIVE,
            canary_traffic_percent=1.0,
            is_production=True,
            is_canary=False,
        )
        db.add(prod_dep)
        db.flush()

        # Set up bad canary
        bad_mv = ModelVersion(
            model_name="churn-classifier",
            version=11,
            stage=ModelStage.CANARY,
            f1_score=0.65,
            avg_latency_ms=450.0,
        )
        db.add(bad_mv)
        db.flush()
        bad_dep = ModelDeployment(
            model_version_id=bad_mv.id,
            status=DeploymentStatus.CANARY,
            canary_traffic_percent=0.10,
            is_production=False,
            is_canary=True,
            canary_error_rate=0.18,   # > 0.05 threshold
            canary_latency_ms=450.0,  # > 200ms SLA
        )
        db.add(bad_dep)
        db.flush()

        orchestrator = SelfHealingOrchestrator(db)
        result = orchestrator.verify_canary(bad_dep.id)
        db.flush()

        # Should have triggered rollback
        assert result["status"] == "rolled_back"
        assert len(result.get("failed_gates", [])) > 0

        # Bad deployment should be rolled back
        db.refresh(bad_dep)
        assert bad_dep.status == DeploymentStatus.ROLLED_BACK
        assert bad_dep.is_canary is False

        # Bad model version should be rolled back
        db.refresh(bad_mv)
        assert bad_mv.stage == ModelStage.ROLLED_BACK

    def test_healthy_canary_advances_traffic(self, db):
        """Healthy canary gets its traffic percentage increased."""
        from aegisml.orchestrator.self_healing import SelfHealingOrchestrator
        from aegisml.config import get_settings

        settings = get_settings()
        initial_traffic = 0.10

        good_mv = ModelVersion(
            model_name="churn-classifier",
            version=20,
            stage=ModelStage.CANARY,
            f1_score=0.92,
            avg_latency_ms=15.0,
        )
        db.add(good_mv)
        db.flush()
        good_dep = ModelDeployment(
            model_version_id=good_mv.id,
            status=DeploymentStatus.CANARY,
            canary_traffic_percent=initial_traffic,
            is_production=False,
            is_canary=True,
            canary_error_rate=0.005,  # healthy
            canary_latency_ms=15.0,   # healthy
        )
        db.add(good_dep)
        db.flush()

        orchestrator = SelfHealingOrchestrator(db)
        result = orchestrator.verify_canary(good_dep.id)
        db.flush()

        # Should be healthy and either advanced or promoted
        assert result["status"] in ("healthy", "promoted")
        db.refresh(good_dep)
        # Traffic should have increased
        assert good_dep.canary_traffic_percent >= initial_traffic


class TestQualityGates:
    def test_quality_gates_pass_when_improved(self, db):
        """Quality gates pass when candidate improves on production."""
        from aegisml.orchestrator.self_healing import SelfHealingOrchestrator
        orchestrator = SelfHealingOrchestrator(db)
        passed, details = orchestrator._check_quality_gates(
            candidate_metrics={"f1_score": 0.91, "avg_latency_ms": 20.0},
            production_metrics={"f1_score": 0.87, "avg_latency_ms": 18.0},
        )
        assert passed is True
        assert details["overall"] == "PASSED"
        assert len(details["rejection_reasons"]) == 0

    def test_quality_gates_fail_no_improvement(self, db):
        """Quality gates fail when candidate regresses >5% below production."""
        from aegisml.orchestrator.self_healing import SelfHealingOrchestrator
        orchestrator = SelfHealingOrchestrator(db)
        passed, details = orchestrator._check_quality_gates(
            candidate_metrics={"f1_score": 0.40, "avg_latency_ms": 20.0},
            production_metrics={"f1_score": 0.89, "avg_latency_ms": 18.0},  # candidate regresses >5%
        )
        assert passed is False
        assert details["overall"] == "FAILED"
        assert len(details["rejection_reasons"]) > 0

    def test_quality_gates_fail_on_latency(self, db):
        """Quality gates fail when candidate latency exceeds SLA."""
        from aegisml.orchestrator.self_healing import SelfHealingOrchestrator
        orchestrator = SelfHealingOrchestrator(db)
        passed, details = orchestrator._check_quality_gates(
            candidate_metrics={"f1_score": 0.92, "avg_latency_ms": 350.0},  # > 200ms
            production_metrics={"f1_score": 0.87, "avg_latency_ms": 18.0},
        )
        assert passed is False
        reasons = " ".join(details["rejection_reasons"]).lower()
        assert "latency" in reasons
