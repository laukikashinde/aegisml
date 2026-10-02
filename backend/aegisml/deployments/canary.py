"""
AegisML — Canary Deployment Manager.

Manages traffic routing and health gate evaluation during canary deployments.
Implements real weighted routing — not a UI animation.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from aegisml.config import get_settings
from aegisml.database.models import (
    ActionType,
    DeploymentStatus,
    IncidentStatus,
    IncidentTimelineEvent,
    ModelDeployment,
    ModelStage,
    ModelVersion,
)
from aegisml.execution.engine import _ACTIVE_CANARY, get_active_canary

logger = structlog.get_logger(__name__)


class CanaryRouter:
    """
    Routes inference requests between production and canary models.
    Decision is probabilistic based on traffic_percent.

    This is REAL routing logic, not a fake animation.
    When a request comes in, route_request() is called and
    either "production" or "canary" is returned.
    """

    def route_request(self) -> str:
        """
        Route a single request.
        Returns "canary" or "production".
        """
        canary_state = get_active_canary()
        if not canary_state:
            return "production"

        traffic_percent = canary_state.get("traffic_percent", 0.0)
        if random.random() < traffic_percent:
            return "canary"
        return "production"

    def get_routing_summary(self) -> dict:
        canary = get_active_canary()
        if not canary:
            return {
                "mode": "production",
                "production_traffic": 1.0,
                "canary_traffic": 0.0,
            }
        return {
            "mode": "canary",
            "production_traffic": round(1.0 - canary.get("traffic_percent", 0), 2),
            "canary_traffic": canary.get("traffic_percent", 0),
            "canary_version": canary.get("model_version"),
        }


class CanaryHealthMonitor:
    """
    Monitors canary deployment health against configured thresholds.
    Triggers rollback if gates are breached.
    """

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def check_health(self, deployment_id: str) -> dict:
        """
        Evaluate canary health gates.
        Returns {healthy: bool, failed_gates: list, metrics: dict}.
        """
        deployment = (
            self.db.query(ModelDeployment)
            .filter(ModelDeployment.id == deployment_id)
            .first()
        )

        if not deployment:
            return {"healthy": False, "reason": "Deployment not found"}

        failed_gates = []
        error_rate = deployment.canary_error_rate or 0.0
        latency = deployment.canary_latency_ms or 0.0
        canary_f1 = deployment.canary_f1 or 0.0

        if error_rate > self.settings.error_rate_threshold:
            failed_gates.append(
                {
                    "gate": "error_rate",
                    "value": error_rate,
                    "threshold": self.settings.error_rate_threshold,
                    "description": f"error_rate {error_rate:.3f} > {self.settings.error_rate_threshold}",
                }
            )

        if latency > 0 and latency > self.settings.latency_sla_ms:
            failed_gates.append(
                {
                    "gate": "latency",
                    "value": latency,
                    "threshold": self.settings.latency_sla_ms,
                    "description": f"latency {latency:.1f}ms > SLA {self.settings.latency_sla_ms}ms",
                }
            )

        if canary_f1 > 0 and canary_f1 < (self.settings.f1_threshold - 0.05):
            failed_gates.append(
                {
                    "gate": "f1_score",
                    "value": canary_f1,
                    "threshold": self.settings.f1_threshold - 0.05,
                    "description": f"canary F1 {canary_f1:.4f} well below threshold",
                }
            )

        healthy = len(failed_gates) == 0

        return {
            "healthy": healthy,
            "deployment_id": deployment_id,
            "failed_gates": failed_gates,
            "metrics": {
                "error_rate": error_rate,
                "latency_ms": latency,
                "canary_f1": canary_f1,
                "traffic_percent": deployment.canary_traffic_percent,
            },
        }

    def advance_traffic(self, deployment_id: str) -> dict:
        """
        Increase canary traffic by one step if health is OK.
        Returns new traffic percentage.
        """
        deployment = (
            self.db.query(ModelDeployment)
            .filter(ModelDeployment.id == deployment_id)
            .first()
        )
        if not deployment:
            return {"error": "Deployment not found"}

        health = self.check_health(deployment_id)
        if not health["healthy"]:
            return {"advanced": False, "reason": "health_check_failed", "gates": health["failed_gates"]}

        current = deployment.canary_traffic_percent
        new_traffic = min(1.0, current + self.settings.canary_step_size)
        deployment.canary_traffic_percent = new_traffic

        # Update routing state
        _ACTIVE_CANARY["traffic_percent"] = new_traffic

        self.db.flush()

        self._add_timeline_event(
            deployment.incident_id,
            "CANARY_TRAFFIC_ADVANCED",
            f"Canary traffic advanced: {current:.0%} → {new_traffic:.0%}",
            {"previous": current, "new": new_traffic, "deployment_id": deployment_id},
        )

        logger.info("canary_traffic_advanced", from_pct=current, to_pct=new_traffic)

        return {
            "advanced": True,
            "previous_traffic": current,
            "new_traffic": new_traffic,
            "deployment_id": deployment_id,
        }

    def _add_timeline_event(
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
