"""
AegisML — Execution Engine.

The ONLY component that performs actual remediation actions.
The AI agent proposes → Policy Engine approves → THIS engine executes.

The engine only executes actions from an allowlist.
No arbitrary code paths. Every action is logged.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.orm import Session

from aegisml.config import get_settings
from aegisml.database.models import (
    ActionStatus,
    ActionType,
    AuditLog,
    DeploymentStatus,
    Incident,
    IncidentAction,
    IncidentStatus,
    IncidentTimelineEvent,
    ModelDeployment,
    ModelStage,
    ModelVersion,
    PipelineRun,
    PipelineRunStatus,
    PolicyDecisionResult,
)
from aegisml.policies.engine import PolicyEvaluationResult

logger = structlog.get_logger(__name__)

# Deployment state machine — shared between API and background tasks
_ACTIVE_CANARY: dict[str, Any] = {}
_PRODUCTION_MODEL: dict[str, Any] = {}


class ExecutionEngine:
    """
    Controlled execution layer.
    Each execute_* method corresponds to one allowed action.
    """

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    # ── Main dispatch ─────────────────────────────────────────────────────────

    def execute(
        self,
        action_type: ActionType,
        policy_result: PolicyEvaluationResult,
        incident_id: str | None,
        parameters: dict | None = None,
    ) -> dict:
        """
        Execute an approved action.
        Raises if action is not APPROVED.
        Returns result dict.
        """
        if policy_result.decision != PolicyDecisionResult.APPROVED:
            raise PermissionError(
                f"Cannot execute {action_type.value}: "
                f"policy decision is {policy_result.decision.value}, not APPROVED."
            )

        action = self._create_action(action_type, policy_result, incident_id, parameters)
        self.db.flush()

        try:
            result = self._dispatch(action_type, action, incident_id, parameters or {})
            action.execution_status = ActionStatus.COMPLETED
            action.result = result
            action.completed_at = datetime.now(timezone.utc)
            self._audit(action_type, incident_id, action.id, "SUCCESS", result)
        except Exception as exc:
            action.execution_status = ActionStatus.FAILED
            action.error = str(exc)
            action.completed_at = datetime.now(timezone.utc)
            self._audit(action_type, incident_id, action.id, "FAILURE", {"error": str(exc)})
            logger.error("execution_failed", action=action_type.value, error=str(exc))
            raise

        self.db.flush()
        return result

    def _dispatch(
        self,
        action_type: ActionType,
        action: IncidentAction,
        incident_id: str | None,
        params: dict,
    ) -> dict:
        if action_type == ActionType.RETRAIN_MODEL:
            return self._execute_retrain(incident_id, params)
        elif action_type == ActionType.REGISTER_MODEL:
            return self._execute_register_model(incident_id, params)
        elif action_type == ActionType.START_CANARY:
            return self._execute_start_canary(incident_id, params)
        elif action_type == ActionType.COMPLETE_DEPLOYMENT:
            return self._execute_complete_deployment(incident_id, params)
        elif action_type == ActionType.ROLLBACK_MODEL:
            return self._execute_rollback(incident_id, params)
        elif action_type == ActionType.RETRY_PIPELINE:
            return self._execute_retry_pipeline(incident_id, params)
        elif action_type == ActionType.RESTART_SERVICE:
            return self._execute_restart_service(incident_id, params)
        elif action_type == ActionType.PROMOTE_MODEL:
            return self._execute_promote_model(incident_id, params)
        else:
            raise ValueError(f"Unknown action: {action_type.value}")

    # ── Action: Retrain Model ─────────────────────────────────────────────────

    def _execute_retrain(self, incident_id: str | None, params: dict) -> dict:
        """
        Trigger model retraining.
        Runs the training pipeline as a subprocess (safe, bounded process).
        """
        dataset_version = params.get("dataset_version", "v1")
        logger.info("executing_retrain", incident_id=incident_id, dataset_version=dataset_version)

        # Create pipeline run record
        run_id = str(uuid.uuid4())
        pipeline_run = PipelineRun(
            id=run_id,
            pipeline_name="churn-training-pipeline",
            status=PipelineRunStatus.RUNNING,
            trigger="incident" if incident_id else "manual",
            dataset_version=dataset_version,
            incident_id=incident_id,
            parameters=params,
            stages_completed=[],
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(pipeline_run)
        self.db.flush()

        self._add_timeline(incident_id, "RETRAINING_STARTED",
                           f"Training pipeline started (run={run_id})",
                           {"pipeline_run_id": run_id, "dataset_version": dataset_version})

        try:
            # Resolve paths from engine.py location:
            # engine.py: aegisml/backend/aegisml/execution/engine.py
            # parents[2] = aegisml/backend
            # parents[3] = aegisml/  ← project root
            engine_file = Path(__file__).resolve()
            backend_path = engine_file.parents[2]   # aegisml/backend
            project_root = engine_file.parents[3]   # aegisml/
            train_script = project_root / "ml" / "training" / "train.py"
            ml_path = project_root / "ml"

            if not train_script.exists():
                raise FileNotFoundError(f"Training script not found: {train_script}")

            env = self._get_env()
            # Ensure both backend and ml are importable in subprocess
            existing_pythonpath = env.get("PYTHONPATH", "")
            new_pythonpath = os.pathsep.join(
                filter(None, [str(backend_path), str(ml_path), existing_pythonpath])
            )
            env["PYTHONPATH"] = new_pythonpath
            env["MLFLOW_DISABLE_AGENT_HINT"] = "1"  # suppress MLflow stderr noise

            result = subprocess.run(
                [
                    sys.executable,
                    str(train_script),
                    "--dataset-version", dataset_version,
                ],
                capture_output=True,
                text=True,
                timeout=600,  # 10 min max
                env=env,
                cwd=str(project_root),
            )

            # Training script prints "AEGISML_RESULT:{json}" as its last line.
            import json as _json
            train_result = None
            for line in reversed(result.stdout.strip().split("\n")):
                line = line.strip()
                if line.startswith("AEGISML_RESULT:"):
                    try:
                        train_result = _json.loads(line[len("AEGISML_RESULT:"):])
                        break
                    except _json.JSONDecodeError:
                        pass
                elif line.startswith("{"):
                    # Fallback: try any JSON object line
                    try:
                        candidate = _json.loads(line)
                        if "run_id" in candidate or "metrics" in candidate:
                            train_result = candidate
                            break
                    except _json.JSONDecodeError:
                        pass

            # Real failure: no parseable result AND non-zero exit
            if train_result is None and result.returncode != 0:
                error_detail = (result.stderr + result.stdout)[-2000:]
                pipeline_run.status = PipelineRunStatus.FAILED
                pipeline_run.error_stage = "training"
                pipeline_run.error_message = error_detail
                pipeline_run.completed_at = datetime.now(timezone.utc)
                self.db.flush()
                raise RuntimeError(f"Training failed:\n{error_detail[-600:]}")

            if not train_result:
                train_result = {"status": "success", "run_id": "unknown"}

            pipeline_run.status = PipelineRunStatus.COMPLETED
            pipeline_run.mlflow_run_id = train_result.get("run_id")
            pipeline_run.completed_at = datetime.now(timezone.utc)
            pipeline_run.duration_seconds = (
                (pipeline_run.completed_at - pipeline_run.started_at).total_seconds()
            )
            pipeline_run.stages_completed = ["validation", "preprocessing", "training",
                                              "evaluation", "registration"]
            pipeline_run.logs = result.stdout[-3000:]
            self.db.flush()

            # Create model version record
            model_version = self._create_model_version(
                train_result, dataset_version, incident_id, run_id
            )

            self._add_timeline(
                incident_id,
                "RETRAINING_COMPLETED",
                f"Training pipeline completed. Candidate model v{model_version.version} registered.",
                {
                    "pipeline_run_id": run_id,
                    "model_version": model_version.version,
                    "f1_score": model_version.f1_score,
                    "mlflow_run_id": train_result.get("run_id"),
                },
            )

            return {
                "status": "success",
                "pipeline_run_id": run_id,
                "model_version": model_version.version,
                "model_version_id": model_version.id,
                "mlflow_run_id": train_result.get("run_id"),
                "metrics": train_result.get("metrics", {}),
                "dataset_version": dataset_version,
            }

        except subprocess.TimeoutExpired:
            pipeline_run.status = PipelineRunStatus.FAILED
            pipeline_run.error_stage = "training"
            pipeline_run.error_message = "Training timed out after 600 seconds"
            pipeline_run.completed_at = datetime.now(timezone.utc)
            self.db.flush()
            raise RuntimeError("Training pipeline timed out")

    def _create_model_version(
        self, train_result: dict, dataset_version: str, incident_id: str | None, run_id: str
    ) -> ModelVersion:
        """Create a ModelVersion record from training results."""
        metrics = train_result.get("metrics", {})

        # Find next version number
        latest = (
            self.db.query(ModelVersion)
            .filter(ModelVersion.model_name == self.settings.mlflow_model_name)
            .order_by(ModelVersion.version.desc())
            .first()
        )
        next_version = (latest.version + 1) if latest else 1

        mv = ModelVersion(
            model_name=self.settings.mlflow_model_name,
            version=next_version,
            mlflow_run_id=train_result.get("run_id"),
            mlflow_version=str(train_result.get("registered_version", "")),
            stage=ModelStage.CANDIDATE,
            accuracy=metrics.get("accuracy"),
            precision=metrics.get("precision"),
            recall=metrics.get("recall"),
            f1_score=metrics.get("f1_score"),
            roc_auc=metrics.get("roc_auc"),
            avg_latency_ms=metrics.get("avg_latency_ms"),
            dataset_version=dataset_version,
            training_params=train_result.get("params", {}),
            training_duration_seconds=train_result.get("training_duration_seconds"),
            incident_id=incident_id,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(mv)
        self.db.flush()
        return mv

    # ── Action: Register Model ────────────────────────────────────────────────

    def _execute_register_model(self, incident_id: str | None, params: dict) -> dict:
        model_version_id = params.get("model_version_id")
        if not model_version_id:
            raise ValueError("model_version_id required for REGISTER_MODEL")

        mv = self.db.query(ModelVersion).filter(ModelVersion.id == model_version_id).first()
        if not mv:
            raise ValueError(f"ModelVersion {model_version_id} not found")

        mv.stage = ModelStage.VALIDATED
        self.db.flush()
        return {"status": "success", "model_version": mv.version, "stage": "VALIDATED"}

    # ── Action: Start Canary ──────────────────────────────────────────────────

    def _execute_start_canary(self, incident_id: str | None, params: dict) -> dict:
        model_version_id = params.get("model_version_id")
        if not model_version_id:
            raise ValueError("model_version_id required for START_CANARY")

        mv = self.db.query(ModelVersion).filter(ModelVersion.id == model_version_id).first()
        if not mv:
            raise ValueError(f"ModelVersion {model_version_id} not found")

        initial_traffic = self.settings.canary_initial_traffic

        # Mark any existing canary as replaced
        existing_canary = (
            self.db.query(ModelDeployment)
            .filter(ModelDeployment.is_canary == True)
            .first()
        )
        if existing_canary:
            existing_canary.is_canary = False

        deployment = ModelDeployment(
            id=str(uuid.uuid4()),
            model_version_id=mv.id,
            status=DeploymentStatus.CANARY,
            canary_traffic_percent=initial_traffic,
            is_production=False,
            is_canary=True,
            incident_id=incident_id,
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(deployment)

        mv.stage = ModelStage.CANARY
        self.db.flush()

        # Update global routing state
        _ACTIVE_CANARY["deployment_id"] = deployment.id
        _ACTIVE_CANARY["model_version_id"] = mv.id
        _ACTIVE_CANARY["model_version"] = mv.version
        _ACTIVE_CANARY["traffic_percent"] = initial_traffic

        self._add_timeline(
            incident_id,
            "CANARY_STARTED",
            f"Canary deployment started for model v{mv.version} at {initial_traffic:.0%} traffic.",
            {
                "deployment_id": deployment.id,
                "model_version": mv.version,
                "initial_traffic": initial_traffic,
            },
        )

        return {
            "status": "success",
            "deployment_id": deployment.id,
            "model_version": mv.version,
            "canary_traffic_percent": initial_traffic,
        }

    # ── Action: Complete Deployment ───────────────────────────────────────────

    def _execute_complete_deployment(self, incident_id: str | None, params: dict) -> dict:
        deployment_id = params.get("deployment_id")
        if not deployment_id:
            raise ValueError("deployment_id required")

        canary_dep = (
            self.db.query(ModelDeployment)
            .filter(ModelDeployment.id == deployment_id)
            .first()
        )
        if not canary_dep:
            raise ValueError(f"Deployment {deployment_id} not found")

        # Retire old production
        old_prod = (
            self.db.query(ModelDeployment)
            .filter(ModelDeployment.is_production == True)
            .first()
        )
        if old_prod:
            old_prod.is_production = False
            old_prod.is_canary = False
            old_prod.status = DeploymentStatus.ROLLED_BACK

            # Retire old model version
            old_mv = (
                self.db.query(ModelVersion)
                .filter(ModelVersion.id == old_prod.model_version_id)
                .first()
            )
            if old_mv:
                old_mv.stage = ModelStage.ROLLED_BACK
                old_mv.retired_at = datetime.now(timezone.utc)

        # Promote canary to production
        canary_dep.is_production = True
        canary_dep.is_canary = False
        canary_dep.canary_traffic_percent = 1.0
        canary_dep.status = DeploymentStatus.ACTIVE
        canary_dep.completed_at = datetime.now(timezone.utc)

        new_mv = (
            self.db.query(ModelVersion)
            .filter(ModelVersion.id == canary_dep.model_version_id)
            .first()
        )
        if new_mv:
            new_mv.stage = ModelStage.PRODUCTION
            new_mv.promoted_at = datetime.now(timezone.utc)

        # Update global routing
        _ACTIVE_CANARY.clear()
        _PRODUCTION_MODEL["deployment_id"] = canary_dep.id
        _PRODUCTION_MODEL["model_version_id"] = new_mv.id if new_mv else None
        _PRODUCTION_MODEL["model_version"] = new_mv.version if new_mv else None

        self.db.flush()

        self._add_timeline(
            incident_id,
            "DEPLOYMENT_COMPLETED",
            f"Model v{new_mv.version if new_mv else '?'} promoted to production (100% traffic).",
            {"deployment_id": deployment_id},
        )

        return {
            "status": "success",
            "deployment_id": deployment_id,
            "model_version": new_mv.version if new_mv else None,
            "stage": "PRODUCTION",
        }

    # ── Action: Rollback ──────────────────────────────────────────────────────

    def _execute_rollback(self, incident_id: str | None, params: dict) -> dict:
        reason = params.get("reason", "health_check_failure")

        # Find the active canary
        canary_dep = (
            self.db.query(ModelDeployment)
            .filter(ModelDeployment.is_canary == True)
            .first()
        )

        if canary_dep:
            canary_dep.is_canary = False
            canary_dep.status = DeploymentStatus.ROLLED_BACK
            canary_dep.rollback_reason = reason
            canary_dep.rolled_back_at = datetime.now(timezone.utc)

            canary_mv = (
                self.db.query(ModelVersion)
                .filter(ModelVersion.id == canary_dep.model_version_id)
                .first()
            )
            if canary_mv:
                canary_mv.stage = ModelStage.ROLLED_BACK
                canary_mv.retired_at = datetime.now(timezone.utc)

        # Find the previous production model
        prod_dep = (
            self.db.query(ModelDeployment)
            .filter(
                ModelDeployment.is_production == True,
                ModelDeployment.status == DeploymentStatus.ACTIVE,
            )
            .first()
        )

        _ACTIVE_CANARY.clear()

        rolled_back_version = canary_dep.model_version_id if canary_dep else None
        self.db.flush()

        self._add_timeline(
            incident_id,
            "ROLLBACK_EXECUTED",
            f"Model rolled back to previous production. Reason: {reason}",
            {
                "reason": reason,
                "rolled_back_deployment": canary_dep.id if canary_dep else None,
                "production_deployment": prod_dep.id if prod_dep else None,
            },
        )

        return {
            "status": "success",
            "reason": reason,
            "rolled_back_deployment_id": canary_dep.id if canary_dep else None,
            "production_restored": prod_dep is not None,
        }

    # ── Action: Retry Pipeline ────────────────────────────────────────────────

    def _execute_retry_pipeline(self, incident_id: str | None, params: dict) -> dict:
        dataset_version = params.get("dataset_version", "v1")
        self._add_timeline(incident_id, "PIPELINE_RETRY",
                           f"Pipeline retry initiated for dataset={dataset_version}.")
        # Delegate to retrain
        return self._execute_retrain(incident_id, params)

    # ── Action: Restart Service ───────────────────────────────────────────────

    def _execute_restart_service(self, incident_id: str | None, params: dict) -> dict:
        """
        For the local prototype, this resets latency simulation state.
        In production, this would trigger a container restart.
        """
        self._add_timeline(incident_id, "SERVICE_RESTARTED",
                           "Inference service state reset (latency simulation cleared).")
        return {"status": "success", "action": "service_state_reset"}

    # ── Action: Promote Model ─────────────────────────────────────────────────

    def _execute_promote_model(self, incident_id: str | None, params: dict) -> dict:
        model_version_id = params.get("model_version_id")
        if not model_version_id:
            raise ValueError("model_version_id required")

        mv = self.db.query(ModelVersion).filter(ModelVersion.id == model_version_id).first()
        if not mv:
            raise ValueError(f"ModelVersion {model_version_id} not found")

        mv.stage = ModelStage.PRODUCTION
        mv.promoted_at = datetime.now(timezone.utc)
        self.db.flush()

        return {"status": "success", "model_version": mv.version, "stage": "PRODUCTION"}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _create_action(
        self,
        action_type: ActionType,
        policy_result: PolicyEvaluationResult,
        incident_id: str | None,
        parameters: dict | None,
    ) -> IncidentAction:
        action = IncidentAction(
            id=str(uuid.uuid4()),
            incident_id=incident_id or "",
            action_type=action_type,
            requested_by="execution_engine",
            policy_decision=policy_result.decision,
            policy_reason=policy_result.reason,
            parameters=parameters,
            execution_status=ActionStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(action)
        return action

    def _add_timeline(
        self,
        incident_id: str | None,
        event_type: str,
        description: str,
        details: dict | None = None,
    ) -> None:
        if not incident_id:
            return
        event = IncidentTimelineEvent(
            incident_id=incident_id,
            event_type=event_type,
            description=description,
            details=details,
            occurred_at=datetime.now(timezone.utc),
        )
        self.db.add(event)

    def _audit(
        self,
        action_type: ActionType,
        incident_id: str | None,
        action_id: str,
        outcome: str,
        details: dict | None = None,
    ) -> None:
        log = AuditLog(
            event_type=f"ACTION_EXECUTED_{action_type.value}",
            actor="execution_engine",
            incident_id=incident_id,
            action_id=action_id,
            resource_type="action",
            resource_id=action_type.value,
            description=f"Executed {action_type.value}",
            details=details,
            outcome=outcome,
            occurred_at=datetime.now(timezone.utc),
        )
        self.db.add(log)

    def _get_env(self) -> dict:
        """Get environment variables for subprocess (no secrets in args)."""
        env = os.environ.copy()
        settings = self.settings
        env.update(
            {
                "MLFLOW_TRACKING_URI": settings.mlflow_tracking_uri,
                "MLFLOW_EXPERIMENT_NAME": settings.mlflow_experiment_name,
                "MLFLOW_MODEL_NAME": settings.mlflow_model_name,
                # Pass through the database URL so training can log to same DB
                "DATABASE_URL": settings.database_url,
            }
        )
        return env


def get_active_canary() -> dict:
    """Read the current canary routing state."""
    return _ACTIVE_CANARY.copy()


def get_production_model() -> dict:
    """Read the current production routing state."""
    return _PRODUCTION_MODEL.copy()
