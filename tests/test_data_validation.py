"""Tests for the data validation layer — Adult Income schema."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "ml"))

from validation.data_validator import DataValidator, DataQualityReport
from preprocessing.pipeline import ALL_FEATURES, TARGET


def _make_valid_df(n: int = 200) -> pd.DataFrame:
    """Generate a valid Adult Income DataFrame."""
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "age":            rng.integers(18, 80, n).astype(float),
        "fnlwgt":         rng.integers(20000, 500000, n).astype(float),
        "education_num":  rng.integers(1, 16, n).astype(float),
        "capital_gain":   np.where(rng.random(n) < 0.08, rng.integers(1000, 50000, n), 0).astype(float),
        "capital_loss":   np.where(rng.random(n) < 0.05, rng.integers(100, 2000, n), 0).astype(float),
        "hours_per_week": rng.integers(20, 60, n).astype(float),
        "workclass":      rng.choice(["Private","Self-emp-not-inc","Local-gov","State-gov"], n),
        "education":      rng.choice(["Bachelors","HS-grad","Some-college","Masters"], n),
        "marital_status": rng.choice(["Married-civ-spouse","Never-married","Divorced"], n),
        "occupation":     rng.choice(["Exec-managerial","Prof-specialty","Craft-repair","Sales"], n),
        "relationship":   rng.choice(["Husband","Not-in-family","Wife","Own-child"], n),
        "race":           rng.choice(["White","Black","Asian-Pac-Islander"], n),
        "sex":            rng.choice(["Male","Female"], n),
        "native_country": rng.choice(["United-States","Mexico","India"], n),
        TARGET:           rng.integers(0, 2, n),
    })


class TestDataValidator:

    def test_valid_df_passes(self):
        v = DataValidator()
        report = v.validate(_make_valid_df(200))
        assert report.status == "PASSED"
        assert not report.has_errors()
        assert report.n_rows == 200

    def test_missing_column_fails(self):
        df = _make_valid_df(100).drop(columns=["age"])
        report = DataValidator().validate(df)
        assert report.status == "FAILED"
        assert "age" in report.missing_features
        assert report.has_errors()

    def test_high_missing_rate_triggers_error(self):
        df = _make_valid_df(200)
        idx = df.sample(frac=0.50, random_state=42).index
        df.loc[idx, "age"] = np.nan
        report = DataValidator().validate(df)
        age_issues = [i for i in report.issues if i.feature == "age" and i.issue == "missing_rate"]
        assert len(age_issues) > 0
        assert age_issues[0].severity == "ERROR"

    def test_warning_for_moderate_missing(self):
        df = _make_valid_df(200)
        idx = df.sample(frac=0.15, random_state=42).index
        df.loc[idx, "age"] = np.nan
        report = DataValidator().validate(df)
        age_issues = [i for i in report.issues if i.feature == "age" and i.issue == "missing_rate"]
        # 15% > 10% threshold (age) → should warn
        assert len(age_issues) > 0

    def test_unknown_category_detected(self):
        df = _make_valid_df(100)
        df.loc[0, "workclass"] = "INVALID_WORKCLASS"
        report = DataValidator().validate(df)
        wc_issues = [i for i in report.issues if i.feature == "workclass"]
        assert len(wc_issues) > 0
        assert any(i.issue == "unknown_categories" for i in wc_issues)

    def test_below_range_warning(self):
        df = _make_valid_df(100)
        df.loc[0, "age"] = -5   # below min of 17
        report = DataValidator().validate(df)
        issues = [i for i in report.issues if i.feature == "age"]
        assert any(i.issue == "below_min" for i in issues)

    def test_stats_populated(self):
        df = _make_valid_df(200)
        report = DataValidator().validate(df)
        assert "age" in report.stats
        assert "mean" in report.stats["age"]

    def test_no_target_validation(self):
        df = _make_valid_df(100).drop(columns=[TARGET])
        report = DataValidator().validate(df, require_target=False)
        assert report.status in ("PASSED", "WARNING")

    def test_report_to_dict(self):
        report = DataValidator().validate(_make_valid_df(100))
        d = report.to_dict()
        assert "status" in d
        assert "issues" in d
        assert isinstance(d["issues"], list)


class TestDriftDetector:

    def _make_pair(self, n=300):
        base = _make_valid_df(n)
        curr = _make_valid_df(n)
        return base, curr

    def test_no_drift_on_same_data(self):
        from monitoring.drift_detector import DriftDetector
        base, curr = self._make_pair()
        detector = DriftDetector()
        report = detector.detect(base, curr)
        assert report.overall_drift_score < 0.50

    def test_drift_detected_on_shifted_data(self):
        from monitoring.drift_detector import DriftDetector
        base = _make_valid_df(400)
        drifted = _make_valid_df(400)
        drifted["age"] = drifted["age"] + 20   # extreme shift
        detector = DriftDetector(numeric_threshold=0.15)
        report = detector.detect(base, drifted, features=["age"])
        age_results = [r for r in report.feature_results if r.feature == "age"]
        assert len(age_results) > 0
        assert age_results[0].drifted == True  # noqa: E712

    def test_drift_report_to_dict(self):
        from monitoring.drift_detector import DriftDetector
        base, curr = self._make_pair(200)
        report = DriftDetector().detect(base, curr, features=["age", "education_num"])
        d = report.to_dict()
        assert "drift_detected" in d
        assert "feature_results" in d
