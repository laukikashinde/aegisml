"""
AegisML — AI Incident Agent Tools.

These are the ONLY tools the agent can use.
The agent cannot execute arbitrary code, shell commands, or SQL.
All tools return structured data from safe, controlled sources.

Tool allowlist:
  get_incident, get_recent_logs, get_model_metrics, get_drift_report,
  get_data_quality_report, get_recent_pipeline_runs, get_mlflow_runs,
  get_model_versions, get_deployment_status, get_previous_incidents,
  get_system_health, get_runbook
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import desc
from sqlalchemy.orm import Session

from aegisml.database.models import (
    AuditLog,
    Incident,
    IncidentStatus,
    IncidentType,
    ModelDeployment,
    ModelStage,
    ModelVersion,
    MonitoringSnapshot,
    PipelineRun,
    PipelineRunStatus,
)

logger = structlog.get_logger(__name__)
RUNBOOK_DIR = Path(__file__).resolve().parents[4] / "runbooks"


class AgentToolbox:
    """
    Controlled tool execution layer for the AI incident agent.
    All methods are safe — no shell execution, no arbitrary queries.
    """

    def __init__(self, db: Session):
        self.db = db
        self._call_log: list[dict] = []

    # ── Tool: get_incident ────────────────────────────────────────────────────

    def get_incident(self, incident_id: str) -> dict:
        """Retrieve incident details by ID."""
        self._log_call("get_incident", {"incident_id": incident_id})
        incident = self.db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            return {"error": f"Incident {incident_id} not found"}

        return {
            "id": incident.id,
            "title": incident.title,
            "type": incident.incident_type.value,
            "severity": incident.severity.value,
            "status": incident.status.value,
            "source": incident.source,
            "affected_model": incident.affected_model,
            "affected_feature": incident.affected_feature,
            "observed_metrics": incident.observed_metrics,
            "created_at": incident.created_at.isoformat() if incident.created_at else None,
            "is_simulation": incident.is_simulation,
            "simulation_type": incident.simulation_type,
        }

    # ── Tool: get_recent_logs ─────────────────────────────────────────────────

    def get_recent_logs(self, n: int = 50, level: str | None = None) -> dict:
        """Retrieve recent AuditLog entries (structured logs)."""
        self._log_call("get_recent_logs", {"n": n, "level": level})
        q = self.db.query(AuditLog).order_by(desc(AuditLog.occurred_at)).limit(n)
        logs = q.all()

        return {
            "count": len(logs),
            "logs": [
                {
                    "event_type": l.event_type,
                    "actor": l.actor,
                    "description": l.description,
                    "outcome": l.outcome,
                    "occurred_at": l.occurred_at.isoformat() if l.occurred_at else None,
                }
                for l in logs
            ],
        }

    # ── Tool: get_model_metrics ───────────────────────────────────────────────

    def get_model_metrics(self, model_name: str, n_windows: int = 10) -> dict:
        """Retrieve recent performance monitoring snapshots."""
        self._log_call("get_model_metrics", {"model_name": model_name, "n_windows": n_windows})
        snapshots = (
            self.db.query(MonitoringSnapshot)
            .filter(MonitoringSnapshot.model_name == model_name)
            .order_by(desc(MonitoringSnapshot.created_at))
            .limit(n_windows)
            .all()
        )

        if not snapshots:
            return {"model_name": model_name, "windows": [], "summary": "No data"}

        windows = [
            {
                "timestamp": s.created_at.isoformat(),
                "f1_score": s.f1_score,
                "accuracy": s.accuracy,
                "precision": s.precision,
                "recall": s.recall,
                "roc_auc": s.roc_auc,
                "avg_latency_ms": s.avg_latency_ms,
                "error_rate": s.error_rate,
                "drift_detected": s.drift_detected,
            }
            for s in reversed(snapshots)
        ]

        latest = snapshots[0]
        return {
            "model_name": model_name,
            "latest_f1": latest.f1_score,
            "latest_accuracy": latest.accuracy,
            "latest_latency_ms": latest.avg_latency_ms,
            "latest_error_rate": latest.error_rate,
            "windows": windows,
            "n_windows": len(windows),
        }

    # ── Tool: get_drift_report ────────────────────────────────────────────────

    def get_drift_report(self, model_name: str) -> dict:
        """Retrieve the most recent drift monitoring snapshot."""
        self._log_call("get_drift_report", {"model_name": model_name})
        snapshot = (
            self.db.query(MonitoringSnapshot)
            .filter(
                MonitoringSnapshot.model_name == model_name,
                MonitoringSnapshot.drift_detected.isnot(None),
            )
            .order_by(desc(MonitoringSnapshot.created_at))
            .first()
        )

        if not snapshot:
            return {"model_name": model_name, "drift_detected": False, "message": "No drift data"}

        return {
            "model_name": model_name,
            "drift_detected": snapshot.drift_detected,
            "drift_score": snapshot.drift_score,
            "drifted_features": snapshot.drifted_features,
            "drift_details": snapshot.drift_details,
            "timestamp": snapshot.created_at.isoformat(),
        }

    # ── Tool: get_data_quality_report ─────────────────────────────────────────

    def get_data_quality_report(self, model_name: str) -> dict:
        """Retrieve the most recent data quality snapshot."""
        self._log_call("get_data_quality_report", {"model_name": model_name})
        snapshot = (
            self.db.query(MonitoringSnapshot)
            .filter(
                MonitoringSnapshot.model_name == model_name,
                MonitoringSnapshot.data_quality_status.isnot(None),
            )
            .order_by(desc(MonitoringSnapshot.created_at))
            .first()
        )

        if not snapshot:
            return {
                "model_name": model_name,
                "status": "UNKNOWN",
                "message": "No data quality report available",
            }

        return {
            "model_name": model_name,
            "status": snapshot.data_quality_status,
            "issues": snapshot.data_quality_issues or [],
            "timestamp": snapshot.created_at.isoformat(),
        }

    # ── Tool: get_recent_pipeline_runs ────────────────────────────────────────

    def get_recent_pipeline_runs(self, n: int = 5) -> dict:
        """Get recent pipeline run summaries."""
        self._log_call("get_recent_pipeline_runs", {"n": n})
        runs = (
            self.db.query(PipelineRun)
            .order_by(desc(PipelineRun.started_at))
            .limit(n)
            .all()
        )

        return {
            "count": len(runs),
            "runs": [
                {
                    "id": r.id,
                    "pipeline_name": r.pipeline_name,
                    "status": r.status.value,
                    "trigger": r.trigger,
                    "dataset_version": r.dataset_version,
                    "duration_seconds": r.duration_seconds,
                    "error_stage": r.error_stage,
                    "error_message": r.error_message,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                }
                for r in runs
            ],
        }

    # ── Tool: get_mlflow_runs ─────────────────────────────────────────────────

    def get_mlflow_runs(self, experiment_name: str, n: int = 5) -> dict:
        """Retrieve recent MLflow experiment runs."""
        self._log_call("get_mlflow_runs", {"experiment_name": experiment_name, "n": n})
        try:
            import mlflow
            from aegisml.config import get_settings
            settings = get_settings()
            mlflow.set_tracking_uri(settings.mlflow_tracking_uri)

            experiment = mlflow.get_experiment_by_name(experiment_name)
            if not experiment:
                return {"experiment": experiment_name, "runs": [], "message": "Experiment not found"}

            runs = mlflow.search_runs(
                experiment_ids=[experiment.experiment_id],
                order_by=["start_time DESC"],
                max_results=n,
            )

            if runs.empty:
                return {"experiment": experiment_name, "runs": []}

            result = []
            for _, row in runs.iterrows():
                result.append(
                    {
                        "run_id": row.get("run_id"),
                        "status": row.get("status"),
                        "start_time": str(row.get("start_time", "")),
                        "metrics.val_f1": row.get("metrics.val_f1"),
                        "metrics.val_accuracy": row.get("metrics.val_accuracy"),
                        "params.dataset_version": row.get("params.dataset_version"),
                    }
                )
            return {"experiment": experiment_name, "runs": result}
        except Exception as exc:
            logger.warning("get_mlflow_runs_failed", error=str(exc))
            return {"experiment": experiment_name, "runs": [], "error": str(exc)}

    # ── Tool: get_model_versions ──────────────────────────────────────────────

    def get_model_versions(self, model_name: str) -> dict:
        """Get all model versions tracked in AegisML."""
        self._log_call("get_model_versions", {"model_name": model_name})
        versions = (
            self.db.query(ModelVersion)
            .filter(ModelVersion.model_name == model_name)
            .order_by(desc(ModelVersion.version))
            .all()
        )

        production = next((v for v in versions if v.stage == ModelStage.PRODUCTION), None)
        candidate = next((v for v in versions if v.stage == ModelStage.CANDIDATE), None)

        return {
            "model_name": model_name,
            "total_versions": len(versions),
            "production_version": production.version if production else None,
            "production_f1": production.f1_score if production else None,
            "candidate_version": candidate.version if candidate else None,
            "versions": [
                {
                    "version": v.version,
                    "stage": v.stage.value,
                    "f1_score": v.f1_score,
                    "roc_auc": v.roc_auc,
                    "avg_latency_ms": v.avg_latency_ms,
                    "dataset_version": v.dataset_version,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                }
                for v in versions
            ],
        }

    # ── Tool: get_deployment_status ───────────────────────────────────────────

    def get_deployment_status(self) -> dict:
        """Get current deployment status — production and canary models."""
        self._log_call("get_deployment_status", {})
        production = (
            self.db.query(ModelDeployment)
            .filter(ModelDeployment.is_production == True)
            .order_by(desc(ModelDeployment.started_at))
            .first()
        )
        canary = (
            self.db.query(ModelDeployment)
            .filter(ModelDeployment.is_canary == True)
            .order_by(desc(ModelDeployment.started_at))
            .first()
        )

        def _dep_dict(dep: ModelDeployment | None) -> dict | None:
            if not dep:
                return None
            return {
                "id": dep.id,
                "model_version_id": dep.model_version_id,
                "status": dep.status.value,
                "canary_traffic_percent": dep.canary_traffic_percent,
                "canary_error_rate": dep.canary_error_rate,
                "canary_latency_ms": dep.canary_latency_ms,
                "started_at": dep.started_at.isoformat() if dep.started_at else None,
            }

        return {
            "production": _dep_dict(production),
            "canary": _dep_dict(canary),
            "has_active_canary": canary is not None,
        }

    # ── Tool: get_previous_incidents ─────────────────────────────────────────

    def get_previous_incidents(
        self, incident_type: str, n: int = 5
    ) -> dict:
        """Retrieve recent resolved incidents of the same type (for historical context)."""
        self._log_call("get_previous_incidents", {"type": incident_type, "n": n})
        try:
            itype = IncidentType(incident_type)
        except ValueError:
            return {"error": f"Unknown incident type: {incident_type}"}

        incidents = (
            self.db.query(Incident)
            .filter(
                Incident.incident_type == itype,
                Incident.status.in_([IncidentStatus.RESOLVED, IncidentStatus.ROLLED_BACK]),
            )
            .order_by(desc(Incident.resolved_at))
            .limit(n)
            .all()
        )

        return {
            "count": len(incidents),
            "type": incident_type,
            "incidents": [
                {
                    "id": i.id,
                    "title": i.title,
                    "status": i.status.value,
                    "root_cause": i.suspected_root_cause,
                    "recommended_action": i.recommended_action,
                    "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
                    "resolution_notes": i.resolution_notes,
                }
                for i in incidents
            ],
        }

    # ── Tool: get_system_health ───────────────────────────────────────────────

    def get_system_health(self) -> dict:
        """Return high-level system health indicators."""
        self._log_call("get_system_health", {})
        active_incidents = (
            self.db.query(Incident)
            .filter(
                Incident.status.notin_(
                    [IncidentStatus.RESOLVED, IncidentStatus.ROLLED_BACK, IncidentStatus.FAILED]
                )
            )
            .count()
        )
        recent_failures = (
            self.db.query(PipelineRun)
            .filter(PipelineRun.status == PipelineRunStatus.FAILED)
            .order_by(desc(PipelineRun.started_at))
            .limit(10)
            .count()
        )
        return {
            "active_incidents": active_incidents,
            "recent_pipeline_failures": recent_failures,
            "status": "DEGRADED" if active_incidents > 0 else "HEALTHY",
        }

    # ── Tool: get_runbook ─────────────────────────────────────────────────────

    def get_runbook(self, incident_type: str) -> dict:
        """Load the runbook JSON for a given incident type."""
        self._log_call("get_runbook", {"incident_type": incident_type})
        runbook_file = RUNBOOK_DIR / f"{incident_type}_RUNBOOK.json"
        if not runbook_file.exists():
            # Try generic
            runbook_file = RUNBOOK_DIR / "DATA_DRIFT_RUNBOOK.json"

        try:
            return json.loads(runbook_file.read_text())
        except Exception:
            return {
                "runbook_id": f"{incident_type}_RUNBOOK",
                "steps": ["Investigate incident", "Identify root cause", "Propose remediation"],
            }

    # ── Tool: get_git_changes ─────────────────────────────────────────────────

    def get_git_changes(self, n_commits: int = 5) -> dict:
        """Get recent git commits in a safe, read-only way."""
        self._log_call("get_git_changes", {"n_commits": n_commits})
        try:
            result = subprocess.run(
                ["git", "log", f"--max-count={n_commits}", "--pretty=format:%H|%s|%an|%ar"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return {"commits": [], "message": "Git not available"}

            commits = []
            for line in result.stdout.strip().split("\n"):
                if "|" in line:
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        commits.append(
                            {
                                "hash": parts[0][:12],
                                "message": parts[1],
                                "author": parts[2],
                                "when": parts[3],
                            }
                        )
            return {"commits": commits, "count": len(commits)}
        except Exception as exc:
            return {"commits": [], "message": f"Git query failed: {exc}"}

    # ── Internal ──────────────────────────────────────────────────────────────

    def _log_call(self, tool_name: str, args: dict) -> None:
        self._call_log.append(
            {"tool": tool_name, "args": args, "timestamp": datetime.utcnow().isoformat()}
        )
        logger.debug("agent_tool_call", tool=tool_name)

    def get_call_log(self) -> list[dict]:
        return self._call_log.copy()
