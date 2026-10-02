"""
AegisML-Lite — XGBoost Training Pipeline (Adult Income dataset).

Outputs: AEGISML_RESULT:{json} on final line for machine parsing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[3] / "backend"
_ML_PKG  = Path(__file__).resolve().parents[1]
for _p in [str(_BACKEND), str(_ML_PKG)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, f1_score, precision_score,
    recall_score, roc_auc_score,
)

try:
    import xgboost as xgb
    _XGB_AVAILABLE = True
except ImportError:
    _XGB_AVAILABLE = False

try:
    from preprocessing.pipeline import (
        ALL_FEATURES, TARGET, fit_preprocessor, load_and_split, transform,
    )
    from validation.data_validator import DataValidator
except ImportError:
    from aegisml.ml.preprocessing.pipeline import (
        ALL_FEATURES, TARGET, fit_preprocessor, load_and_split, transform,
    )
    from aegisml.ml.validation.data_validator import DataValidator

ML_DIR       = Path(__file__).resolve().parents[1]
DATA_DIR     = ML_DIR / "data" / "raw"
ARTIFACTS    = ML_DIR / "artifacts"
ARTIFACTS.mkdir(parents=True, exist_ok=True)

DEFAULT_PARAMS = {
    "n_estimators": 300,
    "max_depth": 6,
    "learning_rate": 0.08,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "random_state": 42,
    "eval_metric": "logloss",
    "use_label_encoder": False,
}


def train(
    train_path=None,
    val_path=None,
    test_path=None,
    dataset_version: str = "v1",
    model_params: dict | None = None,
    mlflow_tracking_uri: str | None = None,
    mlflow_experiment: str | None = None,
    mlflow_model_name: str | None = None,
    register_model: bool = True,
    git_commit: str | None = None,
    incident_id: str | None = None,
) -> dict:
    tracking_uri   = mlflow_tracking_uri  or os.getenv("MLFLOW_TRACKING_URI",   "http://localhost:5001")
    experiment_name = mlflow_experiment   or os.getenv("MLFLOW_EXPERIMENT_NAME", "aegisml-adult-income")
    model_name      = mlflow_model_name   or os.getenv("MLFLOW_MODEL_NAME",      "income-classifier")

    params = {**DEFAULT_PARAMS, **(model_params or {})}

    train_csv = train_path or DATA_DIR / f"train_{dataset_version}.csv"
    val_csv   = val_path   or DATA_DIR / f"val_{dataset_version}.csv"
    test_csv  = test_path  or DATA_DIR / f"test_{dataset_version}.csv"

    print(f"\n{'='*60}")
    print("AegisML-Lite Training — XGBoost / Adult Income")
    print(f"  Dataset  : {dataset_version}")
    print(f"  MLflow   : {tracking_uri}")
    print(f"{'='*60}")

    t0 = time.time()

    # ── Validate ──────────────────────────────────────────────────────────────
    print("[1/6] Validating data...")
    validator = DataValidator()
    train_report = validator.validate(pd.read_csv(train_csv), require_target=True)
    print(f"  Status: {train_report.status} ({len(train_report.issues)} issues)")
    if train_report.status == "FAILED":
        raise ValueError(f"Training data FAILED validation:\n{train_report}")

    # ── Load ──────────────────────────────────────────────────────────────────
    print("[2/6] Loading data...")
    X_train, y_train = load_and_split(train_csv)
    X_val,   y_val   = load_and_split(val_csv)
    X_test,  y_test  = load_and_split(test_csv)

    # ── Preprocess ────────────────────────────────────────────────────────────
    print("[3/6] Preprocessing...")
    prep_path = ARTIFACTS / f"preprocessor_{dataset_version}.pkl"
    preprocessor = fit_preprocessor(X_train, save_path=prep_path)
    X_train_t = transform(X_train, preprocessor)
    X_val_t   = transform(X_val,   preprocessor)
    X_test_t  = transform(X_test,  preprocessor)
    print(f"  Feature matrix: {X_train_t.shape}")

    # ── MLflow ────────────────────────────────────────────────────────────────
    print("[4/6] Configuring MLflow...")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)

    # ── Train ─────────────────────────────────────────────────────────────────
    print("[5/6] Training XGBoost...")
    if not _XGB_AVAILABLE:
        raise ImportError(
            "xgboost is not installed. Run: pip install xgboost"
        )

    # Remove keys not accepted by older XGBoost versions
    xgb_params = {k: v for k, v in params.items()
                  if k not in ("use_label_encoder",)}

    with mlflow.start_run() as run:
        run_id = run.info.run_id
        mlflow.log_params(xgb_params)
        mlflow.log_param("dataset_version", dataset_version)
        mlflow.log_param("model_type", "XGBoost")
        if git_commit:
            mlflow.log_param("git_commit", git_commit)
        if incident_id:
            mlflow.log_param("triggered_by_incident", incident_id)

        clf = xgb.XGBClassifier(**xgb_params)
        clf.fit(
            X_train_t, y_train,
            eval_set=[(X_val_t, y_val)],
            verbose=False,
        )

        # ── Evaluate ──────────────────────────────────────────────────────────
        print("[6/6] Evaluating...")

        def _eval(Xt, yt, prefix: str) -> dict[str, float]:
            yp = clf.predict(Xt)
            yprob = clf.predict_proba(Xt)[:, 1]
            return {
                f"{prefix}_accuracy":  float(accuracy_score(yt, yp)),
                f"{prefix}_precision": float(precision_score(yt, yp, zero_division=0)),
                f"{prefix}_recall":    float(recall_score(yt, yp, zero_division=0)),
                f"{prefix}_f1":        float(f1_score(yt, yp, zero_division=0)),
                f"{prefix}_roc_auc":   float(roc_auc_score(yt, yprob)),
            }

        val_m  = _eval(X_val_t,  y_val,  "val")
        test_m = _eval(X_test_t, y_test, "test")
        mlflow.log_metrics({**val_m, **test_m})

        # Latency
        ns = min(500, len(X_val_t))
        lt0 = time.perf_counter()
        for _ in range(20):
            clf.predict_proba(X_val_t[:ns])
        avg_latency_ms = ((time.perf_counter() - lt0) / 20 / ns) * 1000
        mlflow.log_metric("avg_latency_ms", avg_latency_ms)
        mlflow.log_artifact(str(prep_path))

        # ── Register ──────────────────────────────────────────────────────────
        registered_version = None
        model_uri = None
        if register_model:
            mlflow.sklearn.log_model(
                sk_model=clf,
                artifact_path="model",
                registered_model_name=model_name,
                # MLflow 2.x skops security: explicitly trust XGBoost types
                skops_trusted_types=[
                    "xgboost.core.Booster",
                    "xgboost.sklearn.XGBClassifier",
                    "sklearn.preprocessing._label.LabelEncoder",
                    "numpy.dtypes.Float64DType",
                    "numpy.dtypes.Int64DType",
                ],
            )
            model_uri = f"runs:/{run_id}/model"
            from mlflow.tracking import MlflowClient
            client = MlflowClient(tracking_uri=tracking_uri)
            versions = sorted(
                client.search_model_versions(f"name='{model_name}'"),
                key=lambda v: int(v.version), reverse=True,
            )
            if versions:
                registered_version = versions[0].version

    duration = time.time() - t0
    results = {
        "status": "success",
        "run_id": run_id,
        "registered_version": registered_version,
        "model_uri": model_uri,
        "dataset_version": dataset_version,
        "model_type": "XGBoost",
        "training_duration_seconds": round(duration, 2),
        "metrics": {
            "accuracy":       val_m["val_accuracy"],
            "precision":      val_m["val_precision"],
            "recall":         val_m["val_recall"],
            "f1_score":       val_m["val_f1"],
            "roc_auc":        val_m["val_roc_auc"],
            "avg_latency_ms": avg_latency_ms,
            "test_f1":        test_m["test_f1"],
            "test_accuracy":  test_m["test_accuracy"],
        },
        "validation_report": train_report.to_dict(),
        "params": xgb_params,
    }

    print(f"\n{'='*60}")
    print(f"  Duration   : {duration:.1f}s")
    print(f"  Val F1     : {val_m['val_f1']:.4f}")
    print(f"  Val ROC-AUC: {val_m['val_roc_auc']:.4f}")
    print(f"  Latency    : {avg_latency_ms:.3f}ms/sample")
    if registered_version:
        print(f"  MLflow ver : {registered_version}")
    print(f"{'='*60}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-version", default="v1")
    parser.add_argument("--no-register", action="store_true")
    args = parser.parse_args()

    r = train(dataset_version=args.dataset_version, register_model=not args.no_register)
    # Single-line JSON marker for execution engine to parse
    print("AEGISML_RESULT:" + json.dumps(r))
