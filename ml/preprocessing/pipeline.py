"""
AegisML-Lite — Adult Income preprocessing pipeline.

Numeric:     impute median → StandardScaler
Categorical: impute 'Unknown' → OneHotEncoder(handle_unknown='ignore')
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# ── Feature schema ─────────────────────────────────────────────────────────────

NUMERIC_FEATURES = [
    "age", "fnlwgt", "education_num",
    "capital_gain", "capital_loss", "hours_per_week",
]
CATEGORICAL_FEATURES = [
    "workclass", "education", "marital_status",
    "occupation", "relationship", "race", "sex", "native_country",
]
TARGET = "income_above_50k"
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def build_preprocessor() -> ColumnTransformer:
    numeric_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler",  StandardScaler()),
    ])
    categorical_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value="Unknown")),
        ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, NUMERIC_FEATURES),
            ("cat", categorical_pipe, CATEGORICAL_FEATURES),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


def load_and_split(csv_path) -> tuple[pd.DataFrame, pd.Series]:
    df = pd.read_csv(csv_path)
    missing = [c for c in ALL_FEATURES + [TARGET] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    return df[ALL_FEATURES].copy(), df[TARGET].copy()


def fit_preprocessor(X_train: pd.DataFrame, save_path=None) -> ColumnTransformer:
    pre = build_preprocessor()
    pre.fit(X_train)
    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            pickle.dump(pre, f)
    return pre


def load_preprocessor(path) -> ColumnTransformer:
    with open(path, "rb") as f:
        return pickle.load(f)


def transform(X: pd.DataFrame, preprocessor: ColumnTransformer) -> np.ndarray:
    return preprocessor.transform(X)
