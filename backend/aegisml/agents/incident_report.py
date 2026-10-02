"""
AegisML-Lite — Incident Report Generator.

After an incident has been diagnosed and remediated, generates a
human-readable engineering incident report.

The LLM receives ONLY structured data — it CANNOT decide actions.
If LLM is unavailable, the deterministic fallback produces a complete report.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from aegisml.config import get_settings


def generate_report(
    incident: dict,
    diagnosis: dict,
    remediation: dict,
    metrics_before: dict | None = None,
    metrics_after: dict | None = None,
) -> dict:
    """
    Generate a structured incident report.

    Parameters
    ----------
    incident:       incident summary dict
    diagnosis:      agent diagnosis dict
    remediation:    execution result dict
    metrics_before: model metrics before remediation
    metrics_after:  model metrics after remediation

    Returns
    -------
    dict with keys: summary, what_happened, detection_evidence,
    diagnosis, action_taken, validation_result, recovery_result,
    recommendations, generated_by, generated_at
    """
    settings = get_settings()

    if settings.llm_available:
        try:
            return _llm_report(incident, diagnosis, remediation, metrics_before, metrics_after)
        except Exception:
            pass  # fall through to deterministic

    return _deterministic_report(incident, diagnosis, remediation, metrics_before, metrics_after)


# ── LLM report ────────────────────────────────────────────────────────────────

def _llm_report(incident, diagnosis, remediation, metrics_before, metrics_after) -> dict:
    from langchain_openai import ChatOpenAI
    from langchain.schema import HumanMessage, SystemMessage

    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        temperature=0.2,
        timeout=30,
    )

    system_msg = """You are an engineering incident report writer for AegisML-Lite, 
an autonomous MLOps platform. Write concise, factual incident reports.
Respond ONLY with valid JSON. No markdown, no extra text."""

    user_msg = f"""Write a concise incident report for the following:

INCIDENT:
{json.dumps(incident, indent=2, default=str)}

DIAGNOSIS:
{json.dumps(diagnosis, indent=2, default=str)}

REMEDIATION:
{json.dumps(remediation, indent=2, default=str)}

METRICS BEFORE: {json.dumps(metrics_before, indent=2, default=str)}
METRICS AFTER:  {json.dumps(metrics_after, indent=2, default=str)}

Respond with exactly this JSON structure:
{{
  "summary": "one-sentence executive summary",
  "what_happened": "2-3 sentences describing what failed and when",
  "detection_evidence": "what monitoring signals triggered detection",
  "diagnosis": "root cause analysis in 2-3 sentences",
  "action_taken": "what remediation was executed and why it was safe",
  "validation_result": "how the candidate was validated before deployment",
  "recovery_result": "whether the system recovered and current state",
  "recommendations": ["follow-up action 1", "follow-up action 2"],
  "generated_by": "llm"
}}"""

    response = llm.invoke([
        SystemMessage(content=system_msg),
        HumanMessage(content=user_msg),
    ])

    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    parsed = json.loads(raw.strip())
    parsed["generated_at"] = datetime.now(timezone.utc).isoformat()
    return parsed


# ── Deterministic fallback ────────────────────────────────────────────────────

def _deterministic_report(
    incident, diagnosis, remediation, metrics_before, metrics_after
) -> dict:
    itype = incident.get("type", "UNKNOWN")
    severity = incident.get("severity", "UNKNOWN")
    model = incident.get("affected_model", "model")
    root_cause = diagnosis.get("root_cause", "See diagnosis details.")
    action = diagnosis.get("recommended_action", "N/A")
    confidence = diagnosis.get("confidence", 0)
    status = incident.get("status", "UNKNOWN")
    is_sim = incident.get("is_simulation", False)

    prefix = "[SIMULATION] " if is_sim else ""

    # Build evidence summary
    evidence_parts = []
    for e in (diagnosis.get("evidence") or []):
        if isinstance(e, dict) and e.get("title"):
            evidence_parts.append(e["title"])
    evidence_str = "; ".join(evidence_parts[:3]) if evidence_parts else "monitoring signals exceeded configured thresholds"

    # Metrics summary
    before_f1 = (metrics_before or {}).get("f1_score")
    after_f1  = (metrics_after  or {}).get("f1_score")
    metrics_change = ""
    if before_f1 and after_f1:
        direction = "improved" if after_f1 > before_f1 else "degraded"
        metrics_change = f" Model F1 {direction} from {before_f1:.4f} to {after_f1:.4f}."
    elif before_f1:
        metrics_change = f" Model F1 before remediation: {before_f1:.4f}."

    # Recovery
    recovered = status in ("RESOLVED", "ROLLED_BACK")
    recovery_str = (
        "System recovered successfully — model returned to healthy state."
        if recovered else
        "Remediation is in progress or requires manual intervention."
    )
    if status == "ROLLED_BACK":
        recovery_str = "Candidate model was rolled back. Previous production model restored."

    # Action explanation
    action_explanations = {
        "RETRAIN_MODEL": "Challenger model retrained on latest data and deployed via canary.",
        "ROLLBACK_MODEL": "Canary candidate rolled back to previous stable production model.",
        "MONITOR": "No automated action — system placed in enhanced monitoring mode.",
        "RESTART_SERVICE": "Inference service restarted to clear transient state.",
        "REQUEST_HUMAN_APPROVAL": "Action required human approval before execution.",
    }
    action_str = action_explanations.get(action, f"{action} executed.")

    failure_descriptions = {
        "DATA_DRIFT": "covariate drift in input feature distributions",
        "DATA_QUALITY": "data quality fault in incoming records",
        "MODEL_DEGRADATION": "model performance degradation detected via delayed labels",
        "DEPLOYMENT_FAILURE": "canary deployment health gate failure",
        "LATENCY": "inference latency SLA breach",
        "PIPELINE_FAILURE": "training pipeline failure",
    }
    failure_desc = failure_descriptions.get(itype, itype.lower().replace("_", " "))

    return {
        "summary": (
            f"{prefix}A {severity.lower()} {failure_desc} was detected on {model} "
            f"and {'automatically remediated' if recovered else 'is under investigation'}."
        ),
        "what_happened": (
            f"AegisML-Lite detected a {itype} incident on {model} with {severity} severity. "
            f"The monitoring system identified the problem through {evidence_str}. "
            f"{'This was a controlled simulation.' if is_sim else 'The incident affected production traffic.'}"
        ),
        "detection_evidence": evidence_str or "Monitoring thresholds exceeded.",
        "diagnosis": (
            f"Root cause identified with {int(confidence * 100)}% confidence: {root_cause}"
        ),
        "action_taken": action_str + metrics_change,
        "validation_result": (
            "Candidate model passed all quality gates (F1 improvement, latency SLA)."
            if action == "RETRAIN_MODEL" and recovered
            else "No retraining validation required for this incident type."
        ),
        "recovery_result": recovery_str,
        "recommendations": _get_recommendations(itype, status),
        "generated_by": "deterministic_fallback",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _get_recommendations(itype: str, status: str) -> list[str]:
    base = [
        "Monitor model performance for 3+ consecutive healthy windows.",
        "Review incident timeline for process improvement opportunities.",
    ]
    type_recs = {
        "DATA_DRIFT": [
            "Investigate upstream data pipeline for distribution changes.",
            "Consider updating the baseline dataset if drift is persistent.",
        ],
        "DATA_QUALITY": [
            "Audit data ingestion pipeline for source data quality issues.",
            "Add stricter validation at the data intake layer.",
        ],
        "MODEL_DEGRADATION": [
            "Review whether concept drift is driving the degradation.",
            "Consider more frequent monitoring windows during recovery.",
        ],
        "DEPLOYMENT_FAILURE": [
            "Review candidate model training data for quality issues.",
            "Lower canary initial traffic for future high-risk deployments.",
        ],
    }
    return type_recs.get(itype, []) + base
