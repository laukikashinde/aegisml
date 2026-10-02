"""
AegisML-Lite — Incident Simulation Engine.

All four failure types supported:
  F1 — Covariate drift (age/hours distribution shift)
  F2 — Concept drift (feature-target relationship weakens)
  F3 — Bad deployment (unhealthy canary)
  F4 — Data quality fault (missing values, invalid ranges, unknown categories)

All simulations trigger real AegisML workflows. Clearly labeled as SIMULATION.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.orm import Session

from aegisml.config import get_settings
from aegisml.database.models import (
    DeploymentStatus,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ModelDeployment,
    ModelStage,
    ModelVersion,
    MonitoringSnapshot,
    SimulationRun,
    SimulationType,
)
from aegisml.incidents.service import IncidentService

logger = structlog.get_logger(__name__)

# Global simulation state
_SIMULATION_STATE: dict = {
    "latency_spike": False,
    "latency_extra_ms": 0.0,
    "degraded_data": False,
    "pipeline_fail": False,
}


def get_simulation_state() -> dict:
    return _SIMULATION_STATE.copy()


def reset_simulation_state() -> None:
    _SIMULATION_STATE["latency_spike"] = False
    _SIMULATION_STATE["latency_extra_ms"] = 0.0
    _SIMULATION_STATE["degraded_data"] = False
    _SIMULATION_STATE["pipeline_fail"] = False


class SimulationEngine:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.incident_svc = IncidentService(db)

    def run_simulation(self, sim_type: SimulationType, parameters: dict | None = None) -> dict:
        sim_id = str(uuid.uuid4())
        params = parameters or {}

        sim_run = SimulationRun(
            id=sim_id,
            simulation_type=sim_type,
            parameters=params,
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(sim_run)
        self.db.flush()

        try:
            result = self._dispatch(sim_type, sim_id, params)
            sim_run.status = "COMPLETED"
            sim_run.incident_id = result.get("incident_id")
            sim_run.result = result
            sim_run.completed_at = datetime.now(timezone.utc)
        except Exception as exc:
            sim_run.status = "FAILED"
            sim_run.result = {"error": str(exc)}
            sim_run.completed_at = datetime.now(timezone.utc)
            self.db.flush()
            raise

        self.db.flush()
        return {"simulation_id": sim_id, "type": sim_type.value, **result}

    def _dispatch(self, sim_type: SimulationType, sim_id: str, params: dict) -> dict:
        if sim_type == SimulationType.DATA_DRIFT:
            return self._sim_f1_covariate_drift(sim_id, params)
        elif sim_type == SimulationType.MISSING_DATA:
            return self._sim_f4_data_quality(sim_id, params)
        elif sim_type == SimulationType.MODEL_DEGRADATION:
            return self._sim_f2_concept_drift(sim_id, params)
        elif sim_type == SimulationType.LATENCY_SPIKE:
            return self._sim_latency_spike(sim_id, params)
        elif sim_type == SimulationType.PIPELINE_FAILURE:
            return self._sim_pipeline_failure(sim_id, params)
        elif sim_type == SimulationType.DEPLOYMENT_FAILURE:
            return self._sim_f3_bad_deployment(sim_id, params)
        else:
            raise ValueError(f"Unknown simulation type: {sim_type.value}")

    # ── F1: Covariate Drift ───────────────────────────────────────────────────

    def _sim_f1_covariate_drift(self, sim_id: str, params: dict) -> dict:
        age_shift   = params.get("age_shift",    8)
        hours_scale = params.get("hours_scale",  1.3)
        drift_score = round(0.28 + age_shift * 0.004, 3)
        drifted = ["age", "hours_per_week", "education_num"]

        snapshot = MonitoringSnapshot(
            snapshot_type="drift",
            model_name=self.settings.mlflow_model_name,
            drift_detected=True,
            drift_score=drift_score,
            drifted_features=drifted,
            drift_details={
                "drift_type": "F1_COVARIATE",
                "method": "simulation",
                "features": {
                    "age": {
                        "baseline_mean": 38.6,
                        "current_mean": round(38.6 + age_shift, 1),
                        "drift_score": round(drift_score * 0.55, 3),
                        "severity": "HIGH",
                    },
                    "hours_per_week": {
                        "baseline_mean": 40.4,
                        "current_mean": round(40.4 * hours_scale, 1),
                        "drift_score": round(drift_score * 0.35, 3),
                        "severity": "MEDIUM",
                    },
                    "education_num": {
                        "baseline_mean": 10.1,
                        "current_mean": 12.1,
                        "drift_score": round(drift_score * 0.10, 3),
                        "severity": "LOW",
                    },
                },
            },
            data_quality_status="PASSED",
            f1_score=0.79,
            accuracy=0.81,
            avg_latency_ms=22.0,
            error_rate=0.01,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(snapshot)

        # Activate stream simulator covariate drift mode
        try:
            from aegisml.monitoring.stream_simulator import get_simulator
            get_simulator().set_mode("F1_COVARIATE", {
                "age_shift": age_shift, "hours_scale": hours_scale, "edu_shift": 2,
            })
        except Exception:
            pass

        incident = self.incident_svc.create_incident(
            title=f"[SIMULATION] F1 Covariate drift — age +{age_shift}y, hours ×{hours_scale}",
            incident_type=IncidentType.DATA_DRIFT,
            severity=IncidentSeverity.HIGH,
            source="simulation_engine",
            affected_model=self.settings.mlflow_model_name,
            affected_feature="age, hours_per_week, education_num",
            observed_metrics={
                "drift_score": drift_score,
                "threshold": self.settings.drift_threshold,
                "drifted_features": drifted,
                "age_shift": age_shift,
                "hours_scale": hours_scale,
                "f1_current": 0.79,
                "drift_type": "F1_COVARIATE",
            },
            is_simulation=True,
            simulation_type="DATA_DRIFT",
        )
        self.db.flush()
        return {
            "incident_id": incident.id,
            "description": (
                f"[F1] Covariate drift: age +{age_shift}y, hours ×{hours_scale}. "
                f"Drift score: {drift_score:.3f}. Features: {', '.join(drifted)}."
            ),
        }

    # ── F2: Concept Drift ─────────────────────────────────────────────────────

    def _sim_f2_concept_drift(self, sim_id: str, params: dict) -> dict:
        f1_drop    = params.get("f1_drop", 0.08)
        target_f1  = round(self.settings.f1_threshold - f1_drop, 4)
        drift_score = round(0.15 + f1_drop * 0.5, 3)  # lower drift score (no feature dist change)

        # Create 3 degradation windows (consecutive threshold breach)
        for i in range(3):
            snap = MonitoringSnapshot(
                snapshot_type="performance",
                model_name=self.settings.mlflow_model_name,
                f1_score=target_f1 - i * 0.01,
                accuracy=target_f1 + 0.02,
                precision=target_f1,
                recall=target_f1 - 0.01,
                roc_auc=0.78,
                avg_latency_ms=22.0,
                error_rate=0.015,
                prediction_count=300,
                drift_detected=True,
                drift_score=drift_score,   # low drift score despite degradation
                drifted_features=[],        # no feature drift — concept drift
                drift_details={"drift_type": "F2_CONCEPT", "note": "Performance degraded without feature distribution change"},
                data_quality_status="PASSED",
                created_at=datetime.now(timezone.utc),
            )
            self.db.add(snap)

        # Set stream simulator to concept drift mode
        try:
            from aegisml.monitoring.stream_simulator import get_simulator
            get_simulator().set_mode("F2_CONCEPT", {})
        except Exception:
            pass

        incident = self.incident_svc.create_incident(
            title=f"[SIMULATION] F2 Concept drift — model F1 degraded to {target_f1:.3f}",
            incident_type=IncidentType.MODEL_DEGRADATION,
            severity=IncidentSeverity.HIGH,
            source="simulation_engine",
            affected_model=self.settings.mlflow_model_name,
            observed_metrics={
                "f1_current": target_f1,
                "f1_threshold": self.settings.f1_threshold,
                "f1_drop": f1_drop,
                "drift_score": drift_score,
                "consecutive_windows": 3,
                "drift_type": "F2_CONCEPT",
                "note": "Performance degraded without feature distribution change — concept drift suspected",
            },
            is_simulation=True,
            simulation_type="MODEL_DEGRADATION",
        )
        self.db.flush()
        return {
            "incident_id": incident.id,
            "description": (
                f"[F2] Concept drift: F1 dropped to {target_f1:.3f} "
                f"(threshold: {self.settings.f1_threshold}) for 3 windows. "
                f"Low feature drift ({drift_score:.3f}) suggests feature-target relationship changed."
            ),
        }

    # ── F4: Data Quality Fault ────────────────────────────────────────────────

    def _sim_f4_data_quality(self, sim_id: str, params: dict) -> dict:
        missing_rate     = params.get("missing_rate",     0.40)
        invalid_rate     = params.get("invalid_rate",     0.10)
        unknown_cat_rate = params.get("unknown_cat_rate", 0.15)
        affected_features = params.get("features", ["age", "occupation", "workclass"])

        issues = [
            {"feature": "age",        "issue": "missing_rate",      "value": missing_rate,
             "threshold": 0.10, "severity": "ERROR"},
            {"feature": "occupation", "issue": "missing_rate",      "value": missing_rate * 0.8,
             "threshold": 0.10, "severity": "ERROR"},
            {"feature": "age",        "issue": "below_min",         "value": round(invalid_rate * 100, 1),
             "threshold": 0, "severity": "WARNING"},
            {"feature": "workclass",  "issue": "unknown_categories","value": "['UNKNOWN']",
             "threshold": None, "severity": "WARNING"},
        ]

        snapshot = MonitoringSnapshot(
            snapshot_type="data_quality",
            model_name=self.settings.mlflow_model_name,
            data_quality_status="FAILED",
            data_quality_issues=issues,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(snapshot)

        # Activate stream simulator F4 mode
        try:
            from aegisml.monitoring.stream_simulator import get_simulator
            get_simulator().set_mode("F4_QUALITY", {
                "missing_rate": missing_rate,
                "invalid_rate": invalid_rate,
                "unknown_cat_rate": unknown_cat_rate,
            })
        except Exception:
            pass

        _SIMULATION_STATE["degraded_data"] = True

        incident = self.incident_svc.create_incident(
            title=(f"[SIMULATION] F4 Data quality fault — "
                   f"{missing_rate:.0%} missing, {invalid_rate:.0%} invalid"),
            incident_type=IncidentType.DATA_QUALITY,
            severity=IncidentSeverity.HIGH,
            source="simulation_engine",
            affected_model=self.settings.mlflow_model_name,
            affected_feature=", ".join(affected_features),
            observed_metrics={
                "missing_rate": missing_rate,
                "invalid_rate": invalid_rate,
                "unknown_cat_rate": unknown_cat_rate,
                "affected_features": affected_features,
                "quality_issues_count": len(issues),
            },
            is_simulation=True,
            simulation_type="MISSING_DATA",
        )
        self.db.flush()
        return {
            "incident_id": incident.id,
            "description": (
                f"[F4] Data quality fault: {missing_rate:.0%} missing values in age/occupation, "
                f"{invalid_rate:.0%} invalid age ranges, "
                f"{unknown_cat_rate:.0%} unknown workclass categories."
            ),
        }

    # ── F3 / Latency spike / Pipeline failure (unchanged logic) ──────────────

    def _sim_latency_spike(self, sim_id: str, params: dict) -> dict:
        extra_ms    = params.get("extra_latency_ms", 350.0)
        spike_ms    = self.settings.latency_sla_ms + extra_ms

        _SIMULATION_STATE["latency_spike"]    = True
        _SIMULATION_STATE["latency_extra_ms"] = extra_ms

        snapshot = MonitoringSnapshot(
            snapshot_type="performance",
            model_name=self.settings.mlflow_model_name,
            avg_latency_ms=spike_ms,
            p95_latency_ms=spike_ms * 1.3,
            error_rate=0.01,
            f1_score=0.87,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(snapshot)

        incident = self.incident_svc.create_incident(
            title=f"[SIMULATION] Latency spike — {spike_ms:.0f}ms (SLA: {self.settings.latency_sla_ms}ms)",
            incident_type=IncidentType.LATENCY,
            severity=IncidentSeverity.MEDIUM,
            source="simulation_engine",
            affected_model=self.settings.mlflow_model_name,
            observed_metrics={
                "avg_latency_ms": spike_ms,
                "sla_ms": self.settings.latency_sla_ms,
                "p95_latency_ms": spike_ms * 1.3,
            },
            is_simulation=True,
            simulation_type="LATENCY_SPIKE",
        )
        self.db.flush()
        return {
            "incident_id": incident.id,
            "description": f"Latency spike: {spike_ms:.0f}ms (SLA: {self.settings.latency_sla_ms}ms).",
        }

    def _sim_pipeline_failure(self, sim_id: str, params: dict) -> dict:
        from aegisml.database.models import PipelineRun, PipelineRunStatus
        error_stage = params.get("error_stage", "preprocessing")
        error_msg   = params.get("error_message",
                                  "Simulated preprocessing failure: 40% missing values in 'age' column")

        pipeline_run = PipelineRun(
            id=str(uuid.uuid4()),
            pipeline_name="adult-income-training-pipeline",
            status=PipelineRunStatus.FAILED,
            trigger="simulation",
            error_stage=error_stage,
            error_message=error_msg,
            stages_completed=["validation"],
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        self.db.add(pipeline_run)
        _SIMULATION_STATE["pipeline_fail"] = True

        incident = self.incident_svc.create_incident(
            title=f"[SIMULATION] Pipeline failure at stage: {error_stage}",
            incident_type=IncidentType.PIPELINE_FAILURE,
            severity=IncidentSeverity.HIGH,
            source="simulation_engine",
            affected_pipeline="adult-income-training-pipeline",
            observed_metrics={
                "error_stage": error_stage,
                "pipeline_run_id": pipeline_run.id,
                "error_message": error_msg,
            },
            is_simulation=True,
            simulation_type="PIPELINE_FAILURE",
        )
        self.db.flush()
        return {
            "incident_id": incident.id,
            "description": f"Pipeline failed at '{error_stage}': {error_msg[:150]}",
        }

    def _sim_f3_bad_deployment(self, sim_id: str, params: dict) -> dict:
        error_rate  = params.get("error_rate",  0.18)
        latency_ms  = params.get("latency_ms",  450.0)

        latest_mv = (
            self.db.query(ModelVersion)
            .filter(ModelVersion.model_name == self.settings.mlflow_model_name)
            .order_by(ModelVersion.version.desc())
            .first()
        )
        next_version = (latest_mv.version + 1) if latest_mv else 2

        bad_mv = ModelVersion(
            model_name=self.settings.mlflow_model_name,
            version=next_version,
            stage=ModelStage.CANARY,
            f1_score=0.58,
            accuracy=0.65,
            precision=0.55,
            recall=0.62,
            roc_auc=0.63,
            avg_latency_ms=latency_ms,
            dataset_version="v_sim_bad",
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(bad_mv)
        self.db.flush()

        bad_dep = ModelDeployment(
            id=str(uuid.uuid4()),
            model_version_id=bad_mv.id,
            status=DeploymentStatus.CANARY,
            canary_traffic_percent=0.10,
            is_production=False,
            is_canary=True,
            canary_error_rate=error_rate,
            canary_latency_ms=latency_ms,
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(bad_dep)
        self.db.flush()

        from aegisml.execution.engine import _ACTIVE_CANARY
        _ACTIVE_CANARY["deployment_id"]    = bad_dep.id
        _ACTIVE_CANARY["model_version_id"] = bad_mv.id
        _ACTIVE_CANARY["model_version"]    = bad_mv.version
        _ACTIVE_CANARY["traffic_percent"]  = 0.10
        _ACTIVE_CANARY["is_unhealthy"]     = True

        incident = self.incident_svc.create_incident(
            title=f"[SIMULATION] F3 Bad deployment — canary v{next_version} health check failed",
            incident_type=IncidentType.DEPLOYMENT_FAILURE,
            severity=IncidentSeverity.HIGH,
            source="simulation_engine",
            affected_model=self.settings.mlflow_model_name,
            observed_metrics={
                "canary_error_rate": error_rate,
                "error_rate_threshold": self.settings.error_rate_threshold,
                "canary_latency_ms": latency_ms,
                "latency_sla_ms": self.settings.latency_sla_ms,
                "model_version": next_version,
                "deployment_id": bad_dep.id,
                "drift_type": "F3_BAD_DEPLOYMENT",
            },
            is_simulation=True,
            simulation_type="DEPLOYMENT_FAILURE",
        )
        self.db.flush()
        return {
            "incident_id": incident.id,
            "deployment_id": bad_dep.id,
            "model_version": next_version,
            "description": (
                f"[F3] Bad deployment: canary v{next_version} "
                f"error_rate={error_rate:.1%} (threshold: {self.settings.error_rate_threshold:.1%}), "
                f"latency={latency_ms:.0f}ms (SLA: {self.settings.latency_sla_ms:.0f}ms)."
            ),
        }
