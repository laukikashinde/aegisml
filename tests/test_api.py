"""API integration tests using FastAPI TestClient."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


class TestHealthEndpoint:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestDashboardAPI:
    def test_dashboard_returns_200(self, client):
        r = client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "active_incidents" in data
        assert "total_incidents" in data
        assert "auto_remediation_rate" in data
        assert "recent_incidents" in data

    def test_dashboard_fields_present(self, client):
        r = client.get("/api/dashboard")
        data = r.json()
        required = [
            "active_incidents", "resolved_today", "total_incidents",
            "drift_detected", "recent_pipeline_success_rate",
            "auto_remediation_rate", "remediation_success_rate",
            "rollback_rate", "open_approvals", "recent_incidents", "recent_actions",
        ]
        for field in required:
            assert field in data, f"Missing field: {field}"


class TestIncidentsAPI:
    def test_list_incidents_empty(self, client):
        r = client.get("/api/incidents")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_simulate_data_drift(self, client):
        r = client.post("/api/incidents/simulate", json={
            "simulation_type": "DATA_DRIFT",
            "parameters": {"income_multiplier": 1.5},
        })
        assert r.status_code == 200
        data = r.json()
        assert "incident_id" in data
        assert "simulation_id" in data
        assert data["type"] == "DATA_DRIFT"

    def test_simulate_missing_data(self, client):
        r = client.post("/api/incidents/simulate", json={
            "simulation_type": "MISSING_DATA",
            "parameters": {"missing_rate": 0.45},
        })
        assert r.status_code == 200
        assert "incident_id" in r.json()

    def test_simulate_latency_spike(self, client):
        r = client.post("/api/incidents/simulate", json={
            "simulation_type": "LATENCY_SPIKE",
            "parameters": {"extra_latency_ms": 300},
        })
        assert r.status_code == 200
        assert "incident_id" in r.json()

    def test_simulate_model_degradation(self, client):
        r = client.post("/api/incidents/simulate", json={
            "simulation_type": "MODEL_DEGRADATION",
            "parameters": {"f1_drop": 0.10},
        })
        assert r.status_code == 200
        assert "incident_id" in r.json()

    def test_simulate_pipeline_failure(self, client):
        r = client.post("/api/incidents/simulate", json={
            "simulation_type": "PIPELINE_FAILURE",
            "parameters": {"error_stage": "preprocessing"},
        })
        assert r.status_code == 200

    def test_simulate_invalid_type(self, client):
        r = client.post("/api/incidents/simulate", json={
            "simulation_type": "INVALID_TYPE",
        })
        assert r.status_code == 400

    def test_get_incident(self, client):
        # Create one first
        r = client.post("/api/incidents/simulate", json={
            "simulation_type": "DATA_DRIFT",
            "parameters": {"income_multiplier": 1.6},
        })
        incident_id = r.json()["incident_id"]
        r2 = client.get(f"/api/incidents/{incident_id}")
        assert r2.status_code == 200
        data = r2.json()
        assert data["id"] == incident_id
        assert "timeline" in data
        assert isinstance(data["timeline"], list)

    def test_get_incident_not_found(self, client):
        r = client.get("/api/incidents/nonexistent-id-xyz")
        assert r.status_code == 404

    def test_investigate_incident(self, client):
        # Create and investigate
        r = client.post("/api/incidents/simulate", json={
            "simulation_type": "DATA_DRIFT",
        })
        incident_id = r.json()["incident_id"]
        r2 = client.post(f"/api/incidents/{incident_id}/investigate")
        assert r2.status_code == 200
        data = r2.json()
        assert "diagnosis" in data
        assert "root_cause" in data
        assert "recommended_action" in data
        assert "confidence" in data
        assert 0.0 <= data["confidence"] <= 1.0
        assert data["diagnosis_method"] in ("llm", "rule_based")

    def test_list_incidents_after_simulation(self, client):
        client.post("/api/incidents/simulate", json={"simulation_type": "LATENCY_SPIKE"})
        r = client.get("/api/incidents")
        assert r.status_code == 200
        incidents = r.json()
        assert len(incidents) > 0


class TestModelsAPI:
    def test_list_models(self, client):
        r = client.get("/api/models")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_canary_status(self, client):
        r = client.get("/api/models/canary/status")
        assert r.status_code == 200
        data = r.json()
        assert "production_traffic" in data or "mode" in data

    def test_list_deployments(self, client):
        r = client.get("/api/models/deployments/list")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestMonitoringAPI:
    def test_get_drift(self, client):
        r = client.get("/api/monitoring/drift")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_performance(self, client):
        r = client.get("/api/monitoring/performance")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_latest_snapshot(self, client):
        r = client.get("/api/monitoring/snapshots/latest")
        assert r.status_code == 200


class TestPipelinesAPI:
    def test_list_pipelines(self, client):
        r = client.get("/api/pipelines")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestApprovalsAPI:
    def test_list_approvals_empty(self, client):
        r = client.get("/api/approvals")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_pending_approvals(self, client):
        r = client.get("/api/approvals", params={"status": "PENDING"})
        assert r.status_code == 200

    def test_approve_nonexistent(self, client):
        r = client.post("/api/approvals/nonexistent-id/approve", json={
            "decided_by": "operator",
        })
        assert r.status_code in (404, 422)


class TestAuditAPI:
    def test_list_audit_logs(self, client):
        r = client.get("/api/audit")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_audit_log_entries_have_required_fields(self, client):
        # Trigger some audit entries
        client.post("/api/incidents/simulate", json={"simulation_type": "DATA_DRIFT"})
        r = client.get("/api/audit")
        logs = r.json()
        if logs:
            entry = logs[0]
            assert "event_type" in entry
            assert "actor" in entry
            assert "description" in entry
            assert "occurred_at" in entry
