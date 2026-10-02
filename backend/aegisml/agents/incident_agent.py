"""
AegisML — AI Incident Agent.

Architecture:
  1. Gather evidence using allowlisted tools
  2. If LLM available: use LangGraph tool-calling agent for rich diagnosis
  3. If LLM unavailable: fall back to deterministic rule-based diagnosis
  4. Produce structured AgentDiagnosis output
  5. The agent NEVER executes remediation — it only proposes

The agent has NO ability to modify data, deploy models, or run shell commands.
All tool calls are read-only.
"""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from aegisml.agents.tools import AgentToolbox
from aegisml.config import get_settings
from aegisml.database.models import Incident, IncidentType

logger = structlog.get_logger(__name__)


@dataclass
class AgentDiagnosis:
    incident_id: str
    diagnosis: str
    root_cause: str
    confidence: float
    evidence: list[dict]
    recommended_action: str
    risk_level: str
    requires_human_approval: bool
    verification_plan: list[str]
    diagnosis_method: str = "llm"  # llm | rule_based
    tool_calls_made: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "diagnosis": self.diagnosis,
            "root_cause": self.root_cause,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
            "recommended_action": self.recommended_action,
            "risk_level": self.risk_level,
            "requires_human_approval": self.requires_human_approval,
            "verification_plan": self.verification_plan,
            "diagnosis_method": self.diagnosis_method,
        }


class IncidentAgent:
    """
    MLOps Incident Investigation Agent.

    Evidence-first: always collects structured evidence before diagnosis.
    LLM provides richer reasoning when available.
    Rule-based fallback ensures the platform never fails silently.
    """

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.toolbox = AgentToolbox(db)

    def investigate(self, incident_id: str) -> AgentDiagnosis:
        """
        Main entry point. Investigate an incident end-to-end.
        Returns a structured diagnosis.
        """
        logger.info("agent_investigation_started", incident_id=incident_id)

        # Step 1: Gather evidence
        evidence_bundle = self._gather_evidence(incident_id)

        # Step 2: Diagnose
        if self.settings.llm_available:
            try:
                diagnosis = self._diagnose_with_llm(incident_id, evidence_bundle)
                logger.info("agent_llm_diagnosis_complete", incident_id=incident_id)
                return diagnosis
            except Exception as exc:
                logger.warning("agent_llm_failed", incident_id=incident_id, error=str(exc))
                # Fall through to rule-based

        # Fallback: deterministic
        diagnosis = self._diagnose_rule_based(incident_id, evidence_bundle)
        logger.info("agent_rule_based_diagnosis_complete", incident_id=incident_id)
        return diagnosis

    # ── Evidence gathering ────────────────────────────────────────────────────

    def _gather_evidence(self, incident_id: str) -> dict:
        """
        Collect all available evidence.
        Returns a structured bundle that both LLM and rule-based code can use.
        """
        tb = self.toolbox

        incident = tb.get_incident(incident_id)
        model_name = incident.get("affected_model", self.settings.mlflow_model_name)
        if not model_name:
            model_name = self.settings.mlflow_model_name

        evidence = {
            "incident": incident,
            "model_metrics": tb.get_model_metrics(model_name, n_windows=10),
            "drift_report": tb.get_drift_report(model_name),
            "data_quality": tb.get_data_quality_report(model_name),
            "recent_pipelines": tb.get_recent_pipeline_runs(n=5),
            "model_versions": tb.get_model_versions(model_name),
            "deployment_status": tb.get_deployment_status(),
            "recent_logs": tb.get_recent_logs(n=20),
            "previous_incidents": tb.get_previous_incidents(
                incident.get("type", "UNKNOWN"), n=5
            ),
            "system_health": tb.get_system_health(),
            "runbook": tb.get_runbook(incident.get("type", "UNKNOWN")),
            "git_changes": tb.get_git_changes(n_commits=5),
        }

        evidence["mlflow_runs"] = tb.get_mlflow_runs(
            self.settings.mlflow_experiment_name, n=5
        )

        # Enrich drift_report from incident's observed_metrics if snapshot has no data
        obs = incident.get("observed_metrics") or {}
        if not evidence["drift_report"].get("drift_detected") and obs.get("drift_score"):
            evidence["drift_report"] = {
                "drift_detected": True,
                "drift_score": obs.get("drift_score", 0),
                "overall_drift_score": obs.get("drift_score", 0),
                "drifted_features": obs.get("drifted_features", []),
                "severity": "HIGH" if obs.get("drift_score", 0) > 0.25 else "MEDIUM",
                "source": "observed_metrics",
            }

        # Enrich model_metrics from observed_metrics if snapshot has no data
        if evidence["model_metrics"].get("latest_f1") is None and obs.get("f1_current"):
            evidence["model_metrics"]["latest_f1"] = obs["f1_current"]
            evidence["model_metrics"]["latest_latency_ms"] = obs.get("latency_ms", 20)

        return evidence

    # ── LLM diagnosis ─────────────────────────────────────────────────────────

    def _diagnose_with_llm(
        self, incident_id: str, evidence: dict
    ) -> AgentDiagnosis:
        """Use the LLM to produce a rich, evidence-grounded diagnosis."""
        from langchain_openai import ChatOpenAI
        from langchain.schema import HumanMessage, SystemMessage

        settings = self.settings
        llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            temperature=0,
            timeout=settings.llm_timeout_seconds,
        )

        incident = evidence["incident"]
        model_metrics = evidence["model_metrics"]
        drift = evidence["drift_report"]
        dq = evidence["data_quality"]
        pipelines = evidence["recent_pipelines"]
        runbook = evidence["runbook"]
        prev = evidence["previous_incidents"]

        system_prompt = """You are an expert MLOps incident diagnosis agent for AegisML.
Your job is to investigate ML system incidents and provide grounded, evidence-based diagnoses.
You ONLY diagnose. You do NOT execute remediation.
You must cite specific evidence from the data provided.
Do NOT simply repeat the alert — provide an actual root cause analysis.
Return ONLY valid JSON matching the output schema. No markdown, no extra text."""

        user_prompt = f"""Incident to investigate:
{json.dumps(incident, indent=2, default=str)}

Model performance metrics (last 10 windows):
{json.dumps(model_metrics, indent=2, default=str)}

Drift report:
{json.dumps(drift, indent=2, default=str)}

Data quality report:
{json.dumps(dq, indent=2, default=str)}

Recent pipeline runs:
{json.dumps(pipelines, indent=2, default=str)}

Historical similar incidents:
{json.dumps(prev, indent=2, default=str)}

Runbook:
{json.dumps(runbook, indent=2, default=str)}

Based on all the evidence above, provide your diagnosis as STRICTLY valid JSON:
{{
  "diagnosis": "<concise 1-3 sentence diagnosis, citing specific features/metrics>",
  "root_cause": "<specific root cause — do not just say drift occurred, explain WHY and WHAT>",
  "confidence": <0.0-1.0>,
  "evidence": [
    {{"type": "drift_finding", "description": "...", "data": {{...}}}},
    ...
  ],
  "recommended_action": "<one of: RETRAIN_MODEL|START_CANARY|ROLLBACK_MODEL|RETRY_PIPELINE|REQUEST_HUMAN_APPROVAL|MONITOR>",
  "risk_level": "<LOW|MEDIUM|HIGH|CRITICAL>",
  "requires_human_approval": <true|false>,
  "verification_plan": ["...", "..."]
}}

IMPORTANT: recommended_action MUST be one of the allowed values exactly.
Do not expose internal chain of thought. Only include evidence you can cite."""

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

        response = llm.invoke(messages)
        raw = response.content.strip()

        # Parse JSON — strip any markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        parsed = json.loads(raw)

        # Build evidence list for DB
        evidence_items = []
        for e in parsed.get("evidence", []):
            evidence_items.append(
                {
                    "type": e.get("type", "llm_finding"),
                    "title": e.get("description", ""),
                    "data": e.get("data", {}),
                    "source_tool": "llm",
                }
            )

        # Add drift data as evidence if present
        if drift.get("drift_detected"):
            evidence_items.insert(
                0,
                {
                    "type": "drift_report",
                    "title": f"Drift detected in {len(drift.get('drifted_features', []))} features",
                    "data": drift,
                    "source_tool": "get_drift_report",
                },
            )

        return AgentDiagnosis(
            incident_id=incident_id,
            diagnosis=parsed.get("diagnosis", ""),
            root_cause=parsed.get("root_cause", ""),
            confidence=float(parsed.get("confidence", 0.75)),
            evidence=evidence_items,
            recommended_action=parsed.get("recommended_action", "REQUEST_HUMAN_APPROVAL"),
            risk_level=parsed.get("risk_level", "MEDIUM"),
            requires_human_approval=bool(parsed.get("requires_human_approval", False)),
            verification_plan=parsed.get("verification_plan", []),
            diagnosis_method="llm",
            tool_calls_made=self.toolbox.get_call_log(),
        )

    # ── Rule-based fallback ───────────────────────────────────────────────────

    def _diagnose_rule_based(
        self, incident_id: str, evidence: dict
    ) -> AgentDiagnosis:
        """
        Deterministic rule-based diagnosis.
        Used when LLM is unavailable or fails.
        Covers all major incident types.
        """
        incident = evidence["incident"]
        drift = evidence["drift_report"]
        model_metrics = evidence["model_metrics"]
        dq = evidence["data_quality"]
        pipelines = evidence["recent_pipelines"]
        deployment = evidence["deployment_status"]
        incident_type = incident.get("type", "UNKNOWN")
        settings = self.settings

        evidence_items = []

        # Collect drift evidence
        if drift.get("drift_detected"):
            drifted = drift.get("drifted_features", [])
            drift_score = drift.get("overall_drift_score", 0)
            evidence_items.append(
                {
                    "type": "drift_finding",
                    "title": f"Drift detected in {len(drifted)} features",
                    "data": {
                        "drifted_features": drifted,
                        "drift_score": drift_score,
                        "threshold": settings.drift_threshold,
                    },
                    "source_tool": "get_drift_report",
                }
            )

        # Performance evidence
        latest_f1 = model_metrics.get("latest_f1")
        latest_latency = model_metrics.get("latest_latency_ms", 0)
        if latest_f1 is not None:
            evidence_items.append(
                {
                    "type": "performance_metric",
                    "title": f"Current model F1: {latest_f1:.4f} (threshold: {settings.f1_threshold})",
                    "data": {
                        "f1_score": latest_f1,
                        "threshold": settings.f1_threshold,
                        "degraded": latest_f1 < settings.f1_threshold,
                    },
                    "source_tool": "get_model_metrics",
                }
            )

        # Data quality evidence
        dq_status = dq.get("status", "UNKNOWN")
        if dq_status in ("FAILED", "WARNING"):
            evidence_items.append(
                {
                    "type": "data_quality_report",
                    "title": f"Data quality: {dq_status}",
                    "data": dq,
                    "source_tool": "get_data_quality_report",
                }
            )

        # ── Rule logic ────────────────────────────────────────────────────────

        if incident_type == "DATA_DRIFT":
            return self._rule_data_drift(
                incident_id, incident, drift, model_metrics, dq, evidence_items
            )

        elif incident_type == "MODEL_DEGRADATION":
            return self._rule_model_degradation(
                incident_id, incident, drift, model_metrics, dq, evidence_items
            )

        elif incident_type == "DATA_QUALITY":
            return self._rule_data_quality(
                incident_id, incident, dq, evidence_items
            )

        elif incident_type == "LATENCY":
            return self._rule_latency(
                incident_id, incident, model_metrics, deployment, evidence_items
            )

        elif incident_type == "PIPELINE_FAILURE":
            return self._rule_pipeline_failure(
                incident_id, incident, pipelines, evidence_items
            )

        elif incident_type == "DEPLOYMENT_FAILURE":
            return self._rule_deployment_failure(
                incident_id, incident, deployment, evidence_items
            )

        else:
            return AgentDiagnosis(
                incident_id=incident_id,
                diagnosis=(
                    f"Incident type {incident_type} detected. "
                    "Unable to determine specific root cause with available evidence."
                ),
                root_cause="Unknown — insufficient evidence for automated diagnosis.",
                confidence=0.3,
                evidence=evidence_items,
                recommended_action="REQUEST_HUMAN_APPROVAL",
                risk_level="MEDIUM",
                requires_human_approval=True,
                verification_plan=["Monitor system metrics", "Review logs manually"],
                diagnosis_method="rule_based",
                tool_calls_made=self.toolbox.get_call_log(),
            )

    def _rule_data_drift(
        self, incident_id, incident, drift, model_metrics, dq, evidence_items
    ) -> AgentDiagnosis:
        drifted = drift.get("drifted_features") or []
        # Handle both key names: drift_score (from tool) and overall_drift_score (from DriftReport)
        drift_score = drift.get("drift_score") or drift.get("overall_drift_score") or 0.0
        # Fall back to observed_metrics if snapshot has no score
        if not drift_score:
            obs = incident.get("observed_metrics") or {}
            drift_score = obs.get("drift_score", 0.0)
            if not drifted:
                drifted = obs.get("drifted_features", [])

        severity = drift.get("severity", "MEDIUM")
        # Derive severity from score if not set
        if severity in ("NONE", None, ""):
            if drift_score >= 0.40:
                severity = "CRITICAL"
            elif drift_score >= 0.25:
                severity = "HIGH"
            elif drift_score >= 0.15:
                severity = "MEDIUM"
            else:
                severity = "LOW"

        latest_f1 = model_metrics.get("latest_f1")
        # Fall back to observed_metrics for f1
        if latest_f1 is None:
            obs = incident.get("observed_metrics") or {}
            latest_f1 = obs.get("f1_current")

        settings = self.settings

        performance_degraded = latest_f1 is not None and latest_f1 < settings.f1_threshold
        high_severity = severity in ("HIGH", "CRITICAL")

        if not drifted:
            feature_summary = "unknown features"
        else:
            feature_summary = ", ".join(drifted[:3])
            if len(drifted) > 3:
                feature_summary += f" and {len(drifted) - 3} others"

        diagnosis = (
            f"Data drift detected in {len(drifted)} feature(s): {feature_summary}. "
            f"Overall drift score: {drift_score:.3f} (threshold: {settings.drift_threshold}). "
        )
        if performance_degraded:
            diagnosis += (
                f"Model F1 has dropped to {latest_f1:.4f} (below threshold {settings.f1_threshold}), "
                f"indicating the drift is impacting predictions."
            )
        else:
            diagnosis += "Model performance has not yet degraded significantly."

        root_cause = (
            f"Distributional shift in features [{feature_summary}] "
            f"(drift_score={drift_score:.3f}, threshold={settings.drift_threshold}). "
        )
        if performance_degraded:
            root_cause += (
                f"The feature distribution shift is the primary contributor "
                f"to the observed F1 drop to {latest_f1:.4f}."
            )
        else:
            root_cause += (
                "The model has not yet degraded significantly but continued drift poses future risk."
            )

        # Decision: retrain if drift is above threshold (regardless of severity label)
        should_retrain = drift_score > settings.drift_threshold

        if should_retrain:
            action = "RETRAIN_MODEL"
            risk = "MEDIUM"
            confidence = 0.88 if performance_degraded else 0.78
            requires_approval = False
        else:
            action = "MONITOR"
            risk = "LOW"
            confidence = 0.70
            requires_approval = False

        verification_plan = [
            f"After retraining, verify F1 >= {settings.f1_threshold} on validation set.",
            "Run drift detection on new training data — confirm drift score < threshold.",
            "Monitor production for 3 consecutive windows without drift.",
            "Confirm incident status transitions to RESOLVED.",
        ]

        return AgentDiagnosis(
            incident_id=incident_id,
            diagnosis=diagnosis,
            root_cause=root_cause,
            confidence=confidence,
            evidence=evidence_items,
            recommended_action=action,
            risk_level=risk,
            requires_human_approval=requires_approval,
            verification_plan=verification_plan,
            diagnosis_method="rule_based",
            tool_calls_made=self.toolbox.get_call_log(),
        )

    def _rule_model_degradation(
        self, incident_id, incident, drift, model_metrics, dq, evidence_items
    ) -> AgentDiagnosis:
        latest_f1 = model_metrics.get("latest_f1", 0)
        drift_detected = drift.get("drift_detected", False)
        settings = self.settings

        if drift_detected:
            root_cause = (
                f"Model F1 degraded to {latest_f1:.4f} (threshold: {settings.f1_threshold}). "
                "Data drift is co-occurring, which is the likely contributing factor."
            )
            confidence = 0.85
        else:
            root_cause = (
                f"Model F1 degraded to {latest_f1:.4f} without obvious drift. "
                "Possible causes: data quality issues, pipeline anomaly, or concept drift."
            )
            confidence = 0.65

        return AgentDiagnosis(
            incident_id=incident_id,
            diagnosis=f"Model performance degradation: F1={latest_f1:.4f} < threshold={settings.f1_threshold}.",
            root_cause=root_cause,
            confidence=confidence,
            evidence=evidence_items,
            recommended_action="RETRAIN_MODEL",
            risk_level="HIGH",
            requires_human_approval=False,
            verification_plan=[
                f"Retrain model and verify F1 >= {settings.f1_threshold + 0.02:.2f}.",
                "Deploy via canary and monitor for 3 windows.",
            ],
            diagnosis_method="rule_based",
            tool_calls_made=self.toolbox.get_call_log(),
        )

    def _rule_data_quality(
        self, incident_id, incident, dq, evidence_items
    ) -> AgentDiagnosis:
        issues = dq.get("issues", [])
        issue_summary = "; ".join(
            f"{i.get('feature')}: {i.get('issue')}={i.get('value')}" for i in issues[:5]
        )

        return AgentDiagnosis(
            incident_id=incident_id,
            diagnosis=f"Data quality failure with {len(issues)} issue(s).",
            root_cause=f"Data validation failed: {issue_summary}",
            confidence=0.90,
            evidence=evidence_items,
            recommended_action="REQUEST_HUMAN_APPROVAL",
            risk_level="HIGH",
            requires_human_approval=True,
            verification_plan=[
                "Fix identified data quality issues.",
                "Re-run data validation pipeline.",
                "Confirm all checks PASS before proceeding.",
            ],
            diagnosis_method="rule_based",
            tool_calls_made=self.toolbox.get_call_log(),
        )

    def _rule_latency(
        self, incident_id, incident, model_metrics, deployment, evidence_items
    ) -> AgentDiagnosis:
        latency = model_metrics.get("latest_latency_ms", 0)
        settings = self.settings

        return AgentDiagnosis(
            incident_id=incident_id,
            diagnosis=f"Inference latency spike: {latency:.1f}ms exceeds SLA {settings.latency_sla_ms}ms.",
            root_cause=(
                f"Measured average inference latency of {latency:.1f}ms exceeds the "
                f"{settings.latency_sla_ms}ms SLA. This may indicate resource contention or model complexity increase."
            ),
            confidence=0.80,
            evidence=evidence_items,
            recommended_action="RESTART_SERVICE",
            risk_level="MEDIUM",
            requires_human_approval=False,
            verification_plan=[
                f"After restart, confirm avg_latency_ms <= {settings.latency_sla_ms}.",
                "Monitor for 3 consecutive windows.",
            ],
            diagnosis_method="rule_based",
            tool_calls_made=self.toolbox.get_call_log(),
        )

    def _rule_pipeline_failure(
        self, incident_id, incident, pipelines, evidence_items
    ) -> AgentDiagnosis:
        runs = pipelines.get("runs", [])
        failed_run = next((r for r in runs if r.get("status") == "FAILED"), None)
        error_stage = failed_run.get("error_stage", "unknown") if failed_run else "unknown"
        error_msg = failed_run.get("error_message", "") if failed_run else ""
        retry_count = sum(1 for r in runs if r.get("status") == "FAILED")

        return AgentDiagnosis(
            incident_id=incident_id,
            diagnosis=f"Training pipeline failed at stage: {error_stage}.",
            root_cause=f"Pipeline failure in stage '{error_stage}'. Error: {error_msg[:300]}",
            confidence=0.82,
            evidence=evidence_items,
            recommended_action="RETRY_PIPELINE" if retry_count < 3 else "REQUEST_HUMAN_APPROVAL",
            risk_level="MEDIUM",
            requires_human_approval=retry_count >= 3,
            verification_plan=[
                "Retry pipeline and confirm it completes all stages.",
                "Verify training metrics are within expected ranges.",
            ],
            diagnosis_method="rule_based",
            tool_calls_made=self.toolbox.get_call_log(),
        )

    def _rule_deployment_failure(
        self, incident_id, incident, deployment, evidence_items
    ) -> AgentDiagnosis:
        canary = deployment.get("canary")
        error_rate = canary.get("canary_error_rate", 0) if canary else 0
        latency = canary.get("canary_latency_ms", 0) if canary else 0

        reason = []
        if error_rate and error_rate > 0.05:
            reason.append(f"error_rate={error_rate:.3f} > 0.05")
        if latency and latency > 200:
            reason.append(f"latency={latency:.1f}ms > 200ms")

        return AgentDiagnosis(
            incident_id=incident_id,
            diagnosis=f"Canary deployment is unhealthy. {'; '.join(reason) or 'Health check failed.'}",
            root_cause=f"Deployment health gate(s) breached: {'; '.join(reason)}. Automatic rollback required.",
            confidence=0.92,
            evidence=evidence_items,
            recommended_action="ROLLBACK_MODEL",
            risk_level="HIGH",
            requires_human_approval=False,
            verification_plan=[
                "Confirm previous production model is restored and healthy.",
                "Verify error rate returns to baseline.",
                "Reject candidate model version in registry.",
            ],
            diagnosis_method="rule_based",
            tool_calls_made=self.toolbox.get_call_log(),
        )
