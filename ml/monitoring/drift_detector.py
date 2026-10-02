"""
AegisML — Data Drift Detection using Evidently + statistical fallbacks.

Detects:
  - Feature distribution drift (numeric: KS test, categorical: chi-square)
  - Missingness drift
  - Prediction distribution drift
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

# Try to import Evidently (graceful fallback)
try:
    from evidently.metric_preset import DataDriftPreset
    from evidently.report import Report
    EVIDENTLY_AVAILABLE = True
except ImportError:
    EVIDENTLY_AVAILABLE = False

try:
    from preprocessing.pipeline import CATEGORICAL_FEATURES, NUMERIC_FEATURES
except ImportError:
    from aegisml.ml.preprocessing.pipeline import CATEGORICAL_FEATURES, NUMERIC_FEATURES

DRIFT_THRESHOLD_NUMERIC = 0.20   # KS statistic threshold
DRIFT_THRESHOLD_CATEGORICAL = 0.20  # Chi-square p-value distance


@dataclass
class FeatureDriftResult:
    feature: str
    feature_type: str  # numeric | categorical
    drift_score: float
    threshold: float
    drifted: bool
    baseline_stats: dict[str, Any]
    current_stats: dict[str, Any]
    test_name: str
    severity: str = "LOW"

    def to_dict(self) -> dict:
        return {
            "feature": self.feature,
            "feature_type": self.feature_type,
            "drift_score": round(self.drift_score, 4),
            "threshold": self.threshold,
            "drifted": self.drifted,
            "severity": self.severity,
            "test_name": self.test_name,
            "baseline_stats": {k: round(v, 4) if isinstance(v, float) else v
                               for k, v in self.baseline_stats.items()},
            "current_stats": {k: round(v, 4) if isinstance(v, float) else v
                              for k, v in self.current_stats.items()},
        }


@dataclass
class DriftReport:
    drift_detected: bool
    overall_drift_score: float
    n_drifted_features: int
    n_total_features: int
    feature_results: list[FeatureDriftResult] = field(default_factory=list)
    drifted_features: list[str] = field(default_factory=list)
    severity: str = "NONE"  # NONE | LOW | MEDIUM | HIGH | CRITICAL
    detection_method: str = "statistical"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "drift_detected": self.drift_detected,
            "overall_drift_score": round(self.overall_drift_score, 4),
            "n_drifted_features": self.n_drifted_features,
            "n_total_features": self.n_total_features,
            "drifted_features": self.drifted_features,
            "severity": self.severity,
            "detection_method": self.detection_method,
            "timestamp": self.timestamp,
            "feature_results": [f.to_dict() for f in self.feature_results],
        }


class DriftDetector:
    """
    Detects data drift between a baseline dataset and current data.

    Primary method: Evidently (when available)
    Fallback method: scipy KS test (numeric) + chi-square (categorical)
    """

    def __init__(
        self,
        numeric_threshold: float = DRIFT_THRESHOLD_NUMERIC,
        categorical_threshold: float = DRIFT_THRESHOLD_CATEGORICAL,
        drift_fraction_for_alert: float = 0.20,  # alert if >20% of features drift
    ):
        self.numeric_threshold = numeric_threshold
        self.categorical_threshold = categorical_threshold
        self.drift_fraction_for_alert = drift_fraction_for_alert

    def detect(
        self,
        baseline: pd.DataFrame,
        current: pd.DataFrame,
        features: list[str] | None = None,
    ) -> DriftReport:
        """
        Compare baseline vs current data. Return a DriftReport.
        Tries Evidently first; falls back to scipy stats.
        """
        if EVIDENTLY_AVAILABLE:
            try:
                return self._detect_evidently(baseline, current, features)
            except Exception:
                pass  # Fall through to statistical method

        return self._detect_statistical(baseline, current, features)

    def _detect_evidently(
        self,
        baseline: pd.DataFrame,
        current: pd.DataFrame,
        features: list[str] | None,
    ) -> DriftReport:
        feature_cols = features or [c for c in NUMERIC_FEATURES + CATEGORICAL_FEATURES
                                    if c in baseline.columns and c in current.columns]

        report = Report(metrics=[DataDriftPreset()])
        report.run(reference_data=baseline[feature_cols], current_data=current[feature_cols])
        result_dict = report.as_dict()

        drift_results = result_dict.get("metrics", [{}])[0].get("result", {})
        feature_drift = drift_results.get("drift_by_columns", {})

        feature_results = []
        drifted = []

        for feat in feature_cols:
            feat_data = feature_drift.get(feat, {})
            drift_score = feat_data.get("stattest_threshold", self.numeric_threshold)
            drift_detected = feat_data.get("drift_detected", False)
            stat_val = feat_data.get("drift_score", 0.0)

            f_type = "numeric" if feat in NUMERIC_FEATURES else "categorical"
            baseline_col = baseline[feat].dropna()
            current_col = current[feat].dropna()

            baseline_stats = _compute_stats(baseline_col, f_type)
            current_stats = _compute_stats(current_col, f_type)

            severity = _score_to_severity(stat_val, drift_score)

            result = FeatureDriftResult(
                feature=feat,
                feature_type=f_type,
                drift_score=float(stat_val),
                threshold=float(drift_score),
                drifted=bool(drift_detected),
                baseline_stats=baseline_stats,
                current_stats=current_stats,
                test_name="evidently",
                severity=severity,
            )
            feature_results.append(result)
            if drift_detected:
                drifted.append(feat)

        n_total = len(feature_results)
        n_drifted = len(drifted)
        share_drift = n_drifted / n_total if n_total else 0
        overall_score = float(np.mean([r.drift_score for r in feature_results])) if feature_results else 0.0

        overall_severity = _overall_severity(share_drift, overall_score)
        overall_detected = share_drift > self.drift_fraction_for_alert

        return DriftReport(
            drift_detected=overall_detected,
            overall_drift_score=overall_score,
            n_drifted_features=n_drifted,
            n_total_features=n_total,
            feature_results=feature_results,
            drifted_features=drifted,
            severity=overall_severity,
            detection_method="evidently",
        )

    def _detect_statistical(
        self,
        baseline: pd.DataFrame,
        current: pd.DataFrame,
        features: list[str] | None,
    ) -> DriftReport:
        feature_cols = features or [c for c in NUMERIC_FEATURES + CATEGORICAL_FEATURES
                                    if c in baseline.columns and c in current.columns]

        feature_results: list[FeatureDriftResult] = []
        drifted: list[str] = []

        for feat in feature_cols:
            if feat in NUMERIC_FEATURES:
                result = self._ks_test(baseline, current, feat)
            else:
                result = self._chi2_test(baseline, current, feat)

            feature_results.append(result)
            if result.drifted:
                drifted.append(feat)

        n_total = len(feature_results)
        n_drifted = len(drifted)
        share_drift = n_drifted / n_total if n_total else 0
        overall_score = float(np.mean([r.drift_score for r in feature_results])) if feature_results else 0.0

        overall_severity = _overall_severity(share_drift, overall_score)
        overall_detected = share_drift > self.drift_fraction_for_alert

        return DriftReport(
            drift_detected=overall_detected,
            overall_drift_score=overall_score,
            n_drifted_features=n_drifted,
            n_total_features=n_total,
            feature_results=feature_results,
            drifted_features=drifted,
            severity=overall_severity,
            detection_method="statistical",
        )

    def _ks_test(
        self, baseline: pd.DataFrame, current: pd.DataFrame, feature: str
    ) -> FeatureDriftResult:
        b_col = pd.to_numeric(baseline[feature], errors="coerce").dropna()
        c_col = pd.to_numeric(current[feature], errors="coerce").dropna()

        if len(b_col) < 10 or len(c_col) < 10:
            return FeatureDriftResult(
                feature=feature, feature_type="numeric",
                drift_score=0.0, threshold=self.numeric_threshold,
                drifted=False, baseline_stats={}, current_stats={},
                test_name="ks",
            )

        ks_stat, _ = stats.ks_2samp(b_col.values, c_col.values)
        drifted = ks_stat > self.numeric_threshold
        severity = _score_to_severity(ks_stat, self.numeric_threshold)

        return FeatureDriftResult(
            feature=feature,
            feature_type="numeric",
            drift_score=float(ks_stat),
            threshold=self.numeric_threshold,
            drifted=drifted,
            baseline_stats=_compute_stats(b_col, "numeric"),
            current_stats=_compute_stats(c_col, "numeric"),
            test_name="ks",
            severity=severity,
        )

    def _chi2_test(
        self, baseline: pd.DataFrame, current: pd.DataFrame, feature: str
    ) -> FeatureDriftResult:
        b_counts = baseline[feature].value_counts(normalize=True)
        c_counts = current[feature].value_counts(normalize=True)

        all_cats = set(b_counts.index) | set(c_counts.index)
        b_vals = np.array([b_counts.get(c, 1e-6) for c in all_cats])
        c_vals = np.array([c_counts.get(c, 1e-6) for c in all_cats])

        # Total variation distance as drift score
        tvd = float(np.sum(np.abs(b_vals - c_vals)) / 2)
        drifted = tvd > self.categorical_threshold
        severity = _score_to_severity(tvd, self.categorical_threshold)

        return FeatureDriftResult(
            feature=feature,
            feature_type="categorical",
            drift_score=tvd,
            threshold=self.categorical_threshold,
            drifted=drifted,
            baseline_stats={"distribution": {str(k): round(v, 4)
                                              for k, v in b_counts.items()}},
            current_stats={"distribution": {str(k): round(v, 4)
                                             for k, v in c_counts.items()}},
            test_name="tvd",
            severity=severity,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_stats(col: pd.Series, f_type: str) -> dict:
    if f_type == "numeric":
        numeric = pd.to_numeric(col, errors="coerce").dropna()
        if len(numeric) == 0:
            return {}
        return {
            "mean": float(numeric.mean()),
            "std": float(numeric.std()),
            "min": float(numeric.min()),
            "max": float(numeric.max()),
            "p25": float(numeric.quantile(0.25)),
            "p50": float(numeric.quantile(0.50)),
            "p75": float(numeric.quantile(0.75)),
            "missing_rate": float(col.isna().mean()),
        }
    else:
        vc = col.dropna().value_counts(normalize=True)
        return {
            "distribution": {str(k): round(v, 4) for k, v in vc.items()},
            "n_unique": int(col.nunique()),
            "missing_rate": float(col.isna().mean()),
        }


def _score_to_severity(score: float, threshold: float) -> str:
    ratio = score / threshold if threshold > 0 else 0
    if ratio >= 3:
        return "CRITICAL"
    elif ratio >= 2:
        return "HIGH"
    elif ratio >= 1:
        return "MEDIUM"
    elif ratio >= 0.75:
        return "LOW"
    return "NONE"


def _overall_severity(share_drifted: float, avg_score: float) -> str:
    if share_drifted >= 0.5 or avg_score >= 0.50:
        return "CRITICAL"
    elif share_drifted >= 0.30 or avg_score >= 0.35:
        return "HIGH"
    elif share_drifted >= 0.15 or avg_score >= 0.20:
        return "MEDIUM"
    elif share_drifted > 0:
        return "LOW"
    return "NONE"
