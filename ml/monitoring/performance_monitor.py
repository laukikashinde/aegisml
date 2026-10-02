"""
AegisML — Model Performance Monitor.

Tracks model metrics over time and detects degradation.
Configurable thresholds — never hardcoded.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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
class PerformanceWindow:
    """Metrics snapshot for one monitoring window."""
    window_id: str
    model_name: str
    model_version: int
    timestamp: str
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    roc_auc: float
    avg_latency_ms: float
    p95_latency_ms: float
    error_rate: float
    prediction_count: int
    positive_rate: float  # fraction predicted as churn

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class DegradationAlert:
    metric_name: str
    current_value: float
    threshold: float
    consecutive_windows: int
    required_consecutive: int
    severity: str
    description: str


class PerformanceMonitor:
    """
    Tracks model performance windows and raises degradation alerts
    when thresholds are breached for N consecutive windows.
    """

    def __init__(
        self,
        f1_threshold: float = 0.82,
        accuracy_threshold: float = 0.75,
        latency_sla_ms: float = 200.0,
        error_rate_threshold: float = 0.05,
        consecutive_windows_for_alert: int = 3,
    ):
        self.f1_threshold = f1_threshold
        self.accuracy_threshold = accuracy_threshold
        self.latency_sla_ms = latency_sla_ms
        self.error_rate_threshold = error_rate_threshold
        self.consecutive_windows_for_alert = consecutive_windows_for_alert
        self._window_history: list[PerformanceWindow] = []

    def evaluate_window(
        self,
        y_true: pd.Series | np.ndarray,
        y_pred: np.ndarray,
        y_prob: np.ndarray,
        latencies_ms: list[float],
        error_count: int,
        request_count: int,
        model_name: str,
        model_version: int,
        window_id: str | None = None,
    ) -> tuple[PerformanceWindow, list[DegradationAlert]]:
        """Evaluate one window and return (window, alerts)."""
        ts = datetime.utcnow().isoformat()
        wid = window_id or ts

        metrics = self._compute_metrics(
            y_true, y_pred, y_prob, latencies_ms, error_count, request_count
        )

        window = PerformanceWindow(
            window_id=wid,
            model_name=model_name,
            model_version=model_version,
            timestamp=ts,
            **metrics,
        )
        self._window_history.append(window)

        alerts = self._check_thresholds(window)
        return window, alerts

    def _compute_metrics(
        self,
        y_true,
        y_pred,
        y_prob,
        latencies_ms: list[float],
        error_count: int,
        request_count: int,
    ) -> dict[str, float]:
        y_true = np.asarray(y_true)
        y_pred = np.asarray(y_pred)
        y_prob = np.asarray(y_prob)

        latencies = np.asarray(latencies_ms)
        avg_latency = float(np.mean(latencies)) if len(latencies) > 0 else 0.0
        p95_latency = float(np.percentile(latencies, 95)) if len(latencies) > 0 else 0.0
        error_rate = (error_count / request_count) if request_count > 0 else 0.0
        positive_rate = float(np.mean(y_pred)) if len(y_pred) > 0 else 0.0

        if len(y_true) == 0:
            return {
                "accuracy": 0.0, "precision": 0.0, "recall": 0.0,
                "f1_score": 0.0, "roc_auc": 0.0,
                "avg_latency_ms": avg_latency, "p95_latency_ms": p95_latency,
                "error_rate": error_rate, "prediction_count": request_count,
                "positive_rate": positive_rate,
            }

        return {
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "precision": float(precision_score(y_true, y_pred, zero_division=0)),
            "recall": float(recall_score(y_true, y_pred, zero_division=0)),
            "f1_score": float(f1_score(y_true, y_pred, zero_division=0)),
            "roc_auc": float(roc_auc_score(y_true, y_prob))
            if len(np.unique(y_true)) > 1 else 0.5,
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "error_rate": error_rate,
            "prediction_count": request_count,
            "positive_rate": positive_rate,
        }

    def _check_thresholds(
        self, window: PerformanceWindow
    ) -> list[DegradationAlert]:
        alerts = []

        checks = [
            ("f1_score", window.f1_score, self.f1_threshold, "below"),
            ("accuracy", window.accuracy, self.accuracy_threshold, "below"),
            ("avg_latency_ms", window.avg_latency_ms, self.latency_sla_ms, "above"),
            ("error_rate", window.error_rate, self.error_rate_threshold, "above"),
        ]

        for metric_name, value, threshold, direction in checks:
            breached = (
                (direction == "below" and value < threshold)
                or (direction == "above" and value > threshold)
            )

            if not breached:
                continue

            # Count consecutive breaches in recent history
            consecutive = self._count_consecutive_breaches(
                metric_name, threshold, direction
            )

            if consecutive >= self.consecutive_windows_for_alert:
                severity = self._determine_severity(metric_name, value, threshold)
                alerts.append(
                    DegradationAlert(
                        metric_name=metric_name,
                        current_value=round(value, 4),
                        threshold=threshold,
                        consecutive_windows=consecutive,
                        required_consecutive=self.consecutive_windows_for_alert,
                        severity=severity,
                        description=(
                            f"{metric_name} = {value:.4f} "
                            f"{'<' if direction == 'below' else '>'} "
                            f"threshold {threshold} "
                            f"for {consecutive} consecutive windows"
                        ),
                    )
                )

        return alerts

    def _count_consecutive_breaches(
        self, metric_name: str, threshold: float, direction: str
    ) -> int:
        count = 0
        for window in reversed(self._window_history):
            val = getattr(window, metric_name, None)
            if val is None:
                break
            breached = (
                (direction == "below" and val < threshold)
                or (direction == "above" and val > threshold)
            )
            if breached:
                count += 1
            else:
                break
        return count

    def _determine_severity(
        self, metric_name: str, value: float, threshold: float
    ) -> str:
        if metric_name in ("f1_score", "accuracy"):
            gap = threshold - value
            if gap >= 0.15:
                return "CRITICAL"
            elif gap >= 0.08:
                return "HIGH"
            elif gap >= 0.04:
                return "MEDIUM"
            return "LOW"
        elif metric_name == "avg_latency_ms":
            ratio = value / threshold
            if ratio >= 3:
                return "CRITICAL"
            elif ratio >= 2:
                return "HIGH"
            elif ratio >= 1.5:
                return "MEDIUM"
            return "LOW"
        else:
            ratio = value / threshold if threshold > 0 else 1
            if ratio >= 3:
                return "CRITICAL"
            elif ratio >= 2:
                return "HIGH"
            return "MEDIUM"

    def get_recent_windows(self, n: int = 10) -> list[PerformanceWindow]:
        return self._window_history[-n:]
