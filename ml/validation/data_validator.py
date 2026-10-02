"""
AegisML-Lite — Data Validator (Adult Income schema).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

try:
    from preprocessing.pipeline import ALL_FEATURES, CATEGORICAL_FEATURES, NUMERIC_FEATURES, TARGET
except ImportError:
    from aegisml.ml.preprocessing.pipeline import ALL_FEATURES, CATEGORICAL_FEATURES, NUMERIC_FEATURES, TARGET

FEATURE_SCHEMA: dict[str, dict] = {
    "age":            {"dtype": "numeric", "min": 17,   "max": 90,        "missing_threshold": 0.10},
    "fnlwgt":         {"dtype": "numeric", "min": 10000,"max": 1_500_000, "missing_threshold": 0.05},
    "education_num":  {"dtype": "numeric", "min": 1,    "max": 16,        "missing_threshold": 0.05},
    "capital_gain":   {"dtype": "numeric", "min": 0,    "max": 100_000,   "missing_threshold": 0.05},
    "capital_loss":   {"dtype": "numeric", "min": 0,    "max": 5_000,     "missing_threshold": 0.05},
    "hours_per_week": {"dtype": "numeric", "min": 1,    "max": 99,        "missing_threshold": 0.05},
    "workclass": {
        "dtype": "categorical",
        "allowed_values": ["Private","Self-emp-not-inc","Self-emp-inc","Federal-gov",
                           "Local-gov","State-gov","Without-pay","Never-worked","Unknown"],
        "missing_threshold": 0.10,
    },
    "education": {
        "dtype": "categorical",
        "allowed_values": ["Bachelors","Some-college","11th","HS-grad","Prof-school",
                           "Assoc-acdm","Assoc-voc","9th","7th-8th","12th","Masters",
                           "1st-4th","10th","Doctorate","5th-6th","Preschool"],
        "missing_threshold": 0.05,
    },
    "marital_status": {
        "dtype": "categorical",
        "allowed_values": ["Married-civ-spouse","Divorced","Never-married","Separated",
                           "Widowed","Married-spouse-absent","Married-AF-spouse"],
        "missing_threshold": 0.05,
    },
    "occupation": {
        "dtype": "categorical",
        "allowed_values": ["Tech-support","Craft-repair","Other-service","Sales",
                           "Exec-managerial","Prof-specialty","Handlers-cleaners",
                           "Machine-op-inspct","Adm-clerical","Farming-fishing",
                           "Transport-moving","Priv-house-serv","Protective-serv",
                           "Armed-Forces","Unknown"],
        "missing_threshold": 0.10,
    },
    "relationship": {
        "dtype": "categorical",
        "allowed_values": ["Wife","Own-child","Husband","Not-in-family","Other-relative","Unmarried"],
        "missing_threshold": 0.05,
    },
    "race": {
        "dtype": "categorical",
        "allowed_values": ["White","Asian-Pac-Islander","Amer-Indian-Eskimo","Other","Black"],
        "missing_threshold": 0.05,
    },
    "sex": {
        "dtype": "categorical",
        "allowed_values": ["Male","Female"],
        "missing_threshold": 0.05,
    },
    "native_country": {
        "dtype": "categorical",
        "allowed_values": None,   # too many — skip allowlist check
        "missing_threshold": 0.10,
    },
}


@dataclass
class ValidationIssue:
    feature: str
    issue: str
    value: Any
    threshold: Any = None
    severity: str = "WARNING"


@dataclass
class DataQualityReport:
    status: str
    issues: list[ValidationIssue] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    n_rows: int = 0
    n_columns: int = 0
    missing_features: list[str] = field(default_factory=list)
    duplicate_rows: int = 0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "n_rows": self.n_rows,
            "n_columns": self.n_columns,
            "duplicate_rows": self.duplicate_rows,
            "missing_features": self.missing_features,
            "issues": [
                {"feature": i.feature, "issue": i.issue,
                 "value": i.value, "threshold": i.threshold, "severity": i.severity}
                for i in self.issues
            ],
            "stats": self.stats,
        }

    def has_errors(self) -> bool:
        return any(i.severity == "ERROR" for i in self.issues)

    def __str__(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


class DataValidator:
    def validate(self, df: pd.DataFrame, require_target: bool = True,
                 missing_threshold_override: float | None = None) -> DataQualityReport:
        issues: list[ValidationIssue] = []
        stats: dict = {}
        n_rows, n_cols = df.shape

        required = ALL_FEATURES.copy()
        if require_target:
            required.append(TARGET)

        missing_features = [c for c in required if c not in df.columns]
        if missing_features:
            for col in missing_features:
                issues.append(ValidationIssue(feature=col, issue="missing_column",
                                               value="absent", severity="ERROR"))
            return DataQualityReport(
                status="FAILED", issues=issues, n_rows=n_rows, n_columns=n_cols,
                missing_features=missing_features,
            )

        duplicate_rows = int(df.duplicated().sum())
        if duplicate_rows > 50:
            issues.append(ValidationIssue(feature="_dataset", issue="duplicate_rows",
                                           value=duplicate_rows, severity="WARNING"))

        for feature, schema in FEATURE_SCHEMA.items():
            if feature not in df.columns:
                continue
            col = df[feature]
            threshold = missing_threshold_override or schema["missing_threshold"]
            missing_rate = float(col.isna().mean())
            stats[feature] = {"missing_rate": round(missing_rate, 4)}

            if missing_rate > threshold:
                sev = "ERROR" if missing_rate > threshold * 2 else "WARNING"
                issues.append(ValidationIssue(feature=feature, issue="missing_rate",
                                               value=round(missing_rate, 4),
                                               threshold=threshold, severity=sev))

            if schema["dtype"] == "numeric":
                numeric_col = pd.to_numeric(col, errors="coerce").dropna()
                if len(numeric_col) == 0:
                    continue
                col_min = float(numeric_col.min())
                col_max = float(numeric_col.max())
                stats[feature].update({"min": round(col_min, 2), "max": round(col_max, 2),
                                        "mean": round(float(numeric_col.mean()), 2)})
                if col_min < schema["min"]:
                    issues.append(ValidationIssue(feature=feature, issue="below_min",
                                                   value=round(col_min, 2),
                                                   threshold=schema["min"], severity="WARNING"))
                if col_max > schema["max"]:
                    issues.append(ValidationIssue(feature=feature, issue="above_max",
                                                   value=round(col_max, 2),
                                                   threshold=schema["max"], severity="WARNING"))

            elif schema["dtype"] == "categorical" and schema.get("allowed_values"):
                non_null = col.dropna()
                allowed = set(schema["allowed_values"])
                unknown = set(str(v) for v in non_null.unique()) - allowed
                if unknown:
                    issues.append(ValidationIssue(feature=feature, issue="unknown_categories",
                                                   value=str(list(unknown)[:3]),
                                                   threshold=None, severity="WARNING"))
                stats[feature]["n_unique"] = int(col.nunique())

        if require_target and TARGET in df.columns:
            churn_col = df[TARGET].dropna()
            if not set(churn_col.unique()).issubset({0, 1}):
                issues.append(ValidationIssue(feature=TARGET, issue="invalid_target_values",
                                               value=str(set(churn_col.unique())), severity="ERROR"))
            stats[TARGET] = {"positive_rate": round(float(churn_col.mean()), 4)}

        errors = sum(1 for i in issues if i.severity == "ERROR")
        warns  = sum(1 for i in issues if i.severity == "WARNING")
        status = "FAILED" if errors > 0 else ("WARNING" if warns > 0 else "PASSED")

        return DataQualityReport(status=status, issues=issues, stats=stats,
                                 n_rows=n_rows, n_columns=n_cols,
                                 missing_features=[], duplicate_rows=duplicate_rows)


def validate_file(csv_path, require_target: bool = True) -> DataQualityReport:
    df = pd.read_csv(csv_path)
    return DataValidator().validate(df, require_target=require_target)
