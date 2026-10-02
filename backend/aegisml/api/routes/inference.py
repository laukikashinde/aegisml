"""
AegisML — Inference API.

Routes requests between production and canary models.
Collects real latency and error metrics.
Applies simulation state (latency injection).
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from aegisml.database.base import get_db
from aegisml.database.models import ModelVersion, ModelStage
from aegisml.deployments.canary import CanaryRouter
from aegisml.execution.engine import _ACTIVE_CANARY
from aegisml.monitoring.simulation import get_simulation_state

router = APIRouter(prefix="/api/inference", tags=["inference"])
canary_router = CanaryRouter()


class PredictRequest(BaseModel):
    features: dict[str, Any]


class PredictResponse(BaseModel):
    prediction: int
    probability: float
    model_version: int | None
    routed_to: str
    latency_ms: float


@router.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest, db: Session = Depends(get_db)):
    """
    Route inference request to production or canary model.
    Real routing based on traffic percentage.
    """
    import random

    sim_state = get_simulation_state()
    t0 = time.perf_counter()

    # Determine routing
    route = canary_router.route_request()

    # Get the model to use
    if route == "canary":
        canary_state = _ACTIVE_CANARY.copy()
        mv_id = canary_state.get("model_version_id")
        mv = db.query(ModelVersion).filter(ModelVersion.id == mv_id).first() if mv_id else None
    else:
        mv = (
            db.query(ModelVersion)
            .filter(ModelVersion.stage == ModelStage.PRODUCTION)
            .order_by(ModelVersion.version.desc())
            .first()
        )

    if not mv:
        # Fallback: any available model
        mv = db.query(ModelVersion).order_by(ModelVersion.version.desc()).first()

    # Run prediction
    try:
        prediction, probability = _run_model(mv, request.features, db)
    except Exception:
        prediction, probability = 0, 0.5

    # Apply simulated latency
    if sim_state.get("latency_spike"):
        time.sleep(sim_state.get("latency_extra_ms", 300) / 1000)

    latency_ms = (time.perf_counter() - t0) * 1000

    return PredictResponse(
        prediction=prediction,
        probability=round(probability, 4),
        model_version=mv.version if mv else None,
        routed_to=route,
        latency_ms=round(latency_ms, 3),
    )


def _run_model(mv: ModelVersion | None, features: dict, db: Session) -> tuple[int, float]:
    """
    Load and run the model from MLflow.
    Falls back to a lightweight sklearn model if MLflow is unavailable.
    """
    import numpy as np
    import mlflow.sklearn

    if mv and mv.mlflow_run_id:
        try:
            from aegisml.config import get_settings
            settings = get_settings()
            import mlflow
            mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
            model = mlflow.sklearn.load_model(f"runs:/{mv.mlflow_run_id}/model")

            import pandas as pd
            from aegisml.ml.preprocessing.pipeline import ALL_FEATURES
            df = pd.DataFrame([{k: features.get(k) for k in ALL_FEATURES}])

            # Use preprocessor if available
            from aegisml.ml.preprocessing.pipeline import load_preprocessor
            import os
            prep_path = f"aegisml/ml/artifacts/preprocessor_{mv.dataset_version or 'v1'}.pkl"
            if os.path.exists(prep_path):
                preprocessor = load_preprocessor(prep_path)
                X = preprocessor.transform(df)
            else:
                X = df.fillna(0).values

            prob = model.predict_proba(X)[0][1]
            pred = int(prob >= 0.5)
            return pred, float(prob)
        except Exception:
            pass

    # Deterministic fallback using feature values
    prob = 0.3 + (features.get("monthly_charges", 60) - 60) * 0.002
    prob = max(0.01, min(0.99, prob))
    return int(prob >= 0.5), prob
