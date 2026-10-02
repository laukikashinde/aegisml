"""
AegisML — Model Evaluation and Quality Gate checks.

Used both during initial training and during candidate model evaluation
before promotion.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


@dataclass
class QualityGateResult:
    gate_name: str
    passed: bool
    candidate_value: float | str
    threshold: float | str
    production_value: float | str | None = None
    description: str = ""


@dataclass
class ModelEvaluationReport:
    model_name: str
    candidate_version: str
    run_id: str
    metrics: dict[str, float]
    quality_gates: list[QualityGateResult] = field(default_factory=list)
    overall_passed: bool = False
    rejection_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "candidate_version": self.candidate_version,
            "run_id": self.run_id,
            "metrics": self.metrics,
            "quality_gates": [
                {
                    "gate_name": g.gate_name,
                    "passed": g.passed,
                    "candidate_value": g.candidate_value,
                    "threshold": g.threshold,
                    "production_value": g.production_value,
                    "description": g.description,
                }
                for g in self.quality_gates
            ],
            "overall_passed": self.overall_passed,
            "rejection_reasons": self.rejection_reasons,
        }


class ModelEvaluator:
    """
    Evaluates candidate models against configurable quality gates.

    Quality gates (configurable, not hardcoded):
      - F1 >= production_F1 + min_improvement
      - Latency <= sla_ms
      - ROC-AUC >= minimum threshold
    """

    def __init__(
        self,
        min_f1_improvement: float = 0.02,
        latency_sla_ms: float = 200.0,
        min_roc_auc: float = 0.70,
        tracking_uri: str | None = None,
    ):
        self.min_f1_improvement = min_f1_improvement
        self.latency_sla_ms = latency_sla_ms
        self.min_roc_auc = min_roc_auc
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)

    def evaluate_from_mlflow(
        self,
        model_name: str,
        candidate_version: str,
        test_X: pd.DataFrame,
        test_y: pd.Series,
        production_metrics: dict[str, float] | None = None,
        preprocessor=None,
    ) -> ModelEvaluationReport:
        """
        Load a candidate model from MLflow, evaluate it, run quality gates.
        """
        from mlflow.tracking import MlflowClient
        client = MlflowClient()

        # Load model
        model_uri = f"models:/{model_name}/{candidate_version}"
        model = mlflow.sklearn.load_model(model_uri)

        # Get run metadata
        version_info = client.get_model_version(model_name, candidate_version)
        run_id = version_info.run_id

        # Preprocess if needed
        if preprocessor is not None:
            X_t = preprocessor.transform(test_X)
        else:
            X_t = test_X.values

        # Evaluate
        metrics = self._compute_metrics(model, X_t, test_y)

        # Quality gates
        gates, rejection_reasons = self._check_quality_gates(
            metrics=metrics,
            production_metrics=production_metrics,
        )

        overall_passed = len(rejection_reasons) == 0

        return ModelEvaluationReport(
            model_name=model_name,
            candidate_version=str(candidate_version),
            run_id=run_id,
            metrics=metrics,
            quality_gates=gates,
            overall_passed=overall_passed,
            rejection_reasons=rejection_reasons,
        )

    def _compute_metrics(
        self, model, X: np.ndarray, y: pd.Series
    ) -> dict[str, float]:
        y_pred = model.predict(X)
        y_prob = model.predict_proba(X)[:, 1]

        # Latency measurement
        n_samples = min(500, len(X))
        t0 = time.perf_counter()
        for _ in range(20):
            model.predict_proba(X[:n_samples])
        avg_latency_ms = ((time.perf_counter() - t0) / 20 / n_samples) * 1000

        return {
            "accuracy": float(accuracy_score(y, y_pred)),
            "precision": float(precision_score(y, y_pred, zero_division=0)),
            "recall": float(recall_score(y, y_pred, zero_division=0)),
            "f1_score": float(f1_score(y, y_pred, zero_division=0)),
            "roc_auc": float(roc_auc_score(y, y_prob)),
            "avg_latency_ms": avg_latency_ms,
        }

    def _check_quality_gates(
        self,
        metrics: dict[str, float],
        production_metrics: dict[str, float] | None,
    ) -> tuple[list[QualityGateResult], list[str]]:
        gates = []
        rejection_reasons = []

        candidate_f1 = metrics["f1_score"]
        candidate_latency = metrics["avg_latency_ms"]
        candidate_roc_auc = metrics["roc_auc"]

        # Gate 1: Minimum ROC-AUC
        gate1 = QualityGateResult(
            gate_name="minimum_roc_auc",
            passed=candidate_roc_auc >= self.min_roc_auc,
            candidate_value=round(candidate_roc_auc, 4),
            threshold=self.min_roc_auc,
            description=f"ROC-AUC >= {self.min_roc_auc}",
        )
        gates.append(gate1)
        if not gate1.passed:
            rejection_reasons.append(
                f"ROC-AUC {candidate_roc_auc:.4f} < minimum {self.min_roc_auc}"
            )

        # Gate 2: F1 improvement over production
        if production_metrics:
            prod_f1 = production_metrics.get("f1_score", 0.0)
            required_f1 = prod_f1 + self.min_f1_improvement
            gate2 = QualityGateResult(
                gate_name="f1_improvement",
                passed=candidate_f1 >= required_f1,
                candidate_value=round(candidate_f1, 4),
                threshold=round(required_f1, 4),
                production_value=round(prod_f1, 4),
                description=f"F1 >= production_F1({prod_f1:.4f}) + {self.min_f1_improvement}",
            )
            gates.append(gate2)
            if not gate2.passed:
                rejection_reasons.append(
                    f"F1 {candidate_f1:.4f} did not improve over "
                    f"production {prod_f1:.4f} by {self.min_f1_improvement}"
                )

        # Gate 3: Latency SLA
        gate3 = QualityGateResult(
            gate_name="latency_sla",
            passed=candidate_latency <= self.latency_sla_ms,
            candidate_value=round(candidate_latency, 3),
            threshold=self.latency_sla_ms,
            description=f"Avg latency <= {self.latency_sla_ms}ms",
        )
        gates.append(gate3)
        if not gate3.passed:
            rejection_reasons.append(
                f"Latency {candidate_latency:.2f}ms exceeds SLA {self.latency_sla_ms}ms"
            )

        return gates, rejection_reasons
