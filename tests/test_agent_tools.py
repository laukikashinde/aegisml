"""Tests for the AI agent toolbox — all tools are read-only and safe."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from aegisml.database.models import (
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    MonitoringSnapshot,
)
from aegisml.incidents.service import IncidentService


def _seed_snapshot(db, drift_detected=False, drift_score=0.1, f1=0.88):
    s = MonitoringSnapshot(
        snapshot_type="performance",
        model_name="churn-classifier",
        f1_score=f1,
        accuracy=0.85,
        avg_latency_ms=20.0,
        error_rate=0.01,
        drift_detected=drift_detected,
        drift_score=drift_score,
        drifted_features=["income"] if drift_detected else [],
        data_quality_status="PASSED",
        data_quality_issues=[],
    )
    db.add(s)
    db.flush()
    return s


class TestAgentToolbox:
    def test_get_incident(self, db):
        from aegisml.agents.tools import AgentToolbox
        svc = IncidentService(db)
        incident = svc.create_incident(
            title="Tool test", incident_type=IncidentType.DATA_DRIFT,
            severity=IncidentSeverity.HIGH, source="test",
        )
        db.flush()
        toolbox = AgentToolbox(db)
        result = toolbox.get_incident(incident.id)
        assert result["id"] == incident.id
        assert result["type"] == "DATA_DRIFT"

    def test_get_incident_not_found(self, db):
        from aegisml.agents.tools import AgentToolbox
        toolbox = AgentToolbox(db)
        result = toolbox.get_incident("nonexistent-id")
        assert "error" in result

    def test_get_model_metrics(self, db):
        from aegisml.agents.tools import AgentToolbox
        _seed_snapshot(db, f1=0.89)
        _seed_snapshot(db, f1=0.87)
        toolbox = AgentToolbox(db)
        result = toolbox.get_model_metrics("churn-classifier", n_windows=5)
        assert "latest_f1" in result
        assert len(result["windows"]) >= 1

    def test_get_drift_report(self, db):
        from aegisml.agents.tools import AgentToolbox
        _seed_snapshot(db, drift_detected=True, drift_score=0.35)
        toolbox = AgentToolbox(db)
        result = toolbox.get_drift_report("churn-classifier")
        assert result["drift_detected"] is True
        assert result["drift_score"] > 0

    def test_get_drift_report_no_data(self, db):
        from aegisml.agents.tools import AgentToolbox
        toolbox = AgentToolbox(db)
        result = toolbox.get_drift_report("nonexistent-model")
        assert result["drift_detected"] is False

    def test_get_data_quality_report(self, db):
        from aegisml.agents.tools import AgentToolbox
        _seed_snapshot(db)
        toolbox = AgentToolbox(db)
        result = toolbox.get_data_quality_report("churn-classifier")
        assert result["status"] in ("PASSED", "WARNING", "FAILED", "UNKNOWN")

    def test_get_system_health(self, db):
        from aegisml.agents.tools import AgentToolbox
        toolbox = AgentToolbox(db)
        result = toolbox.get_system_health()
        assert "status" in result
        assert "active_incidents" in result

    def test_get_runbook_data_drift(self, db):
        from aegisml.agents.tools import AgentToolbox
        toolbox = AgentToolbox(db)
        result = toolbox.get_runbook("DATA_DRIFT")
        assert "steps" in result
        assert len(result["steps"]) > 0

    def test_get_previous_incidents(self, db):
        from aegisml.agents.tools import AgentToolbox
        svc = IncidentService(db)
        i = svc.create_incident(
            title="Old incident", incident_type=IncidentType.DATA_DRIFT,
            severity=IncidentSeverity.HIGH, source="test",
        )
        db.flush()
        i.suspected_root_cause = "Income drift"
        svc.transition_status(i, IncidentStatus.INVESTIGATING, "x")
        svc.transition_status(i, IncidentStatus.DIAGNOSED, "x")
        svc.transition_status(i, IncidentStatus.RESOLVED, "x")
        db.flush()
        toolbox = AgentToolbox(db)
        result = toolbox.get_previous_incidents("DATA_DRIFT", n=5)
        assert result["count"] >= 1

    def test_get_previous_incidents_invalid_type(self, db):
        from aegisml.agents.tools import AgentToolbox
        toolbox = AgentToolbox(db)
        result = toolbox.get_previous_incidents("INVALID_TYPE")
        assert "error" in result

    def test_tool_call_log(self, db):
        from aegisml.agents.tools import AgentToolbox
        toolbox = AgentToolbox(db)
        toolbox.get_system_health()
        toolbox.get_drift_report("churn-classifier")
        log = toolbox.get_call_log()
        assert len(log) == 2
        assert log[0]["tool"] == "get_system_health"
        assert log[1]["tool"] == "get_drift_report"

    def test_get_deployment_status(self, db):
        from aegisml.agents.tools import AgentToolbox
        toolbox = AgentToolbox(db)
        result = toolbox.get_deployment_status()
        assert "has_active_canary" in result
