"""Tests for the incident service — state transitions and persistence."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from aegisml.database.models import (
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
)
from aegisml.incidents.service import IncidentService


class TestIncidentService:
    def test_create_incident(self, db):
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="Test drift incident",
            incident_type=IncidentType.DATA_DRIFT,
            severity=IncidentSeverity.HIGH,
            source="test",
        )
        db.flush()
        assert incident.id is not None
        assert incident.status == IncidentStatus.DETECTED
        assert incident.incident_type == IncidentType.DATA_DRIFT
        assert incident.severity == IncidentSeverity.HIGH

    def test_create_simulation_incident(self, db):
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="[SIMULATION] Test",
            incident_type=IncidentType.DATA_DRIFT,
            severity=IncidentSeverity.MEDIUM,
            source="test",
            is_simulation=True,
            simulation_type="DATA_DRIFT",
        )
        db.flush()
        assert incident.is_simulation is True
        assert incident.simulation_type == "DATA_DRIFT"

    def test_transition_status(self, db):
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="Test", incident_type=IncidentType.LATENCY,
            severity=IncidentSeverity.MEDIUM, source="test",
        )
        db.flush()
        svc.transition_status(incident, IncidentStatus.INVESTIGATING, "Starting investigation")
        assert incident.status == IncidentStatus.INVESTIGATING

    def test_full_lifecycle_transitions(self, db):
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="Lifecycle test",
            incident_type=IncidentType.MODEL_DEGRADATION,
            severity=IncidentSeverity.HIGH,
            source="test",
        )
        db.flush()

        transitions = [
            (IncidentStatus.INVESTIGATING, "Investigating"),
            (IncidentStatus.DIAGNOSED, "Diagnosed"),
            (IncidentStatus.REMEDIATING, "Remediating"),
            (IncidentStatus.VERIFYING, "Verifying"),
            (IncidentStatus.RESOLVED, "Resolved"),
        ]
        for status, desc in transitions:
            svc.transition_status(incident, status, desc)
            assert incident.status == status

        assert incident.resolved_at is not None

    def test_add_diagnosis(self, db):
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="Diag test", incident_type=IncidentType.DATA_DRIFT,
            severity=IncidentSeverity.HIGH, source="test",
        )
        db.flush()
        svc.add_diagnosis(
            incident,
            diagnosis="Feature drift in income",
            root_cause="Income distribution shifted by 1.5x",
            confidence=0.88,
            recommended_action="RETRAIN_MODEL",
            risk_level="MEDIUM",
            requires_human_approval=False,
            evidence=[{"type": "drift", "title": "Income drift", "data": {"score": 0.34}}],
            verification_plan=["Check F1 after retrain"],
        )
        db.flush()
        assert incident.diagnosis == "Feature drift in income"
        assert incident.confidence == 0.88
        assert incident.recommended_action == "RETRAIN_MODEL"
        assert incident.requires_human_approval is False

    def test_add_evidence(self, db):
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="Ev test", incident_type=IncidentType.DATA_DRIFT,
            severity=IncidentSeverity.LOW, source="test",
        )
        db.flush()
        ev = svc.add_evidence(
            incident,
            evidence_type="drift_report",
            title="Drift score",
            data={"drift_score": 0.35, "features": ["income"]},
            source_tool="get_drift_report",
        )
        db.flush()
        assert ev.id is not None
        assert ev.incident_id == incident.id

    def test_timeline_events_created_on_transition(self, db):
        from aegisml.database.models import IncidentTimelineEvent
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="Timeline test", incident_type=IncidentType.LATENCY,
            severity=IncidentSeverity.LOW, source="test",
        )
        db.flush()
        svc.transition_status(incident, IncidentStatus.INVESTIGATING, "Test transition")
        db.flush()
        events = db.query(IncidentTimelineEvent).filter(
            IncidentTimelineEvent.incident_id == incident.id
        ).all()
        # Should have at least INCIDENT_CREATED + STATUS_CHANGED_INVESTIGATING
        assert len(events) >= 2

    def test_list_incidents(self, db):
        svc = IncidentService(db)
        for i in range(3):
            svc.create_incident(
                title=f"Test {i}", incident_type=IncidentType.DATA_DRIFT,
                severity=IncidentSeverity.LOW, source="test",
            )
        db.flush()
        results = svc.list_incidents(limit=10)
        assert len(results) >= 3

    def test_get_similar_incidents(self, db):
        from datetime import datetime, timezone
        svc = IncidentService(db)
        # Create a resolved incident
        resolved = svc.create_incident(
            title="Historical drift", incident_type=IncidentType.DATA_DRIFT,
            severity=IncidentSeverity.HIGH, source="test",
        )
        db.flush()
        resolved.suspected_root_cause = "Income drift"
        svc.transition_status(resolved, IncidentStatus.INVESTIGATING, "x")
        svc.transition_status(resolved, IncidentStatus.DIAGNOSED, "x")
        svc.transition_status(resolved, IncidentStatus.RESOLVED, "x")
        db.flush()

        similar = svc.get_similar_incidents(IncidentType.DATA_DRIFT, limit=5)
        assert len(similar) >= 1
        assert similar[0].incident_type == IncidentType.DATA_DRIFT
