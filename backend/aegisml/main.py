"""
AegisML — FastAPI Application Entry Point.
"""
from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import (
    Counter,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from starlette.responses import Response

from aegisml.config import get_settings
from aegisml.database.base import init_db

# ── Logging ───────────────────────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

# ── Prometheus metrics ────────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "aegisml_requests_total", "Total API requests", ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "aegisml_request_latency_seconds", "API request latency", ["endpoint"]
)
INCIDENT_COUNT = Counter(
    "aegisml_incidents_total", "Total incidents created", ["type", "severity"]
)
AGENT_INVOCATIONS = Counter(
    "aegisml_agent_invocations_total", "AI agent invocations", ["outcome"]
)
REMEDIATION_COUNT = Counter(
    "aegisml_remediations_total", "Remediation actions executed", ["action", "outcome"]
)

# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="AegisML",
        description="Autonomous Self-Healing MLOps Platform",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── API key middleware ────────────────────────────────────────────────────
    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next):
        # Skip docs, health, metrics
        skip_paths = {"/api/docs", "/api/redoc", "/api/openapi.json",
                      "/health", "/metrics"}
        if request.url.path in skip_paths:
            return await call_next(request)

        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if not settings.is_production:
            # Dev mode: log warning but don't block
            pass
        elif api_key != settings.aegisml_api_key:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or missing API key"},
            )
        return await call_next(request)

    # ── Prometheus middleware ─────────────────────────────────────────────────
    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next):
        import time
        t0 = time.perf_counter()
        response = await call_next(request)
        latency = time.perf_counter() - t0
        path = request.url.path
        REQUEST_COUNT.labels(
            method=request.method, endpoint=path, status=response.status_code
        ).inc()
        REQUEST_LATENCY.labels(endpoint=path).observe(latency)
        return response

    # ── Routes ────────────────────────────────────────────────────────────────
    from aegisml.api.routes.incidents import router as incidents_router
    from aegisml.api.routes.models import router as models_router
    from aegisml.api.routes.monitoring import router as monitoring_router
    from aegisml.api.routes.pipelines import router as pipelines_router
    from aegisml.api.routes.audit import router as audit_router
    from aegisml.api.routes.approvals import router as approvals_router
    from aegisml.api.routes.dashboard import router as dashboard_router
    from aegisml.api.routes.inference import router as inference_router
    from aegisml.api.routes.stream import router as stream_router
    from aegisml.api.routes.experiments import router as experiments_router
    from aegisml.api.routes.reports import router as reports_router
    from aegisml.api.routes.admin import router as admin_router

    app.include_router(incidents_router)
    app.include_router(models_router)
    app.include_router(monitoring_router)
    app.include_router(pipelines_router)
    app.include_router(audit_router)
    app.include_router(approvals_router)
    app.include_router(dashboard_router)
    app.include_router(inference_router)
    app.include_router(stream_router)
    app.include_router(experiments_router)
    app.include_router(reports_router)
    app.include_router(admin_router)

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health")
    def health():
        return {"status": "ok", "service": "aegisml"}

    # ── Prometheus metrics endpoint ───────────────────────────────────────────
    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # ── Startup ───────────────────────────────────────────────────────────────
    @app.on_event("startup")
    def startup():
        init_db()
        _seed_initial_data()

    return app


def _seed_initial_data() -> None:
    """
    Seed the database with initial data on first run:
    - Create a baseline model version (v1, PRODUCTION stage)
    - Create baseline monitoring snapshot
    """
    from aegisml.config import get_settings
    from aegisml.database.base import get_session_factory, get_engine
    from aegisml.database.models import (
        ModelStage, ModelVersion, MonitoringSnapshot, ModelDeployment, DeploymentStatus
    )
    from datetime import datetime, timezone

    settings = get_settings()
    engine = get_engine()
    SessionFactory = get_session_factory(engine)
    db = SessionFactory()

    try:
        # Check if production model exists
        existing = (
            db.query(ModelVersion)
            .filter(ModelVersion.stage == ModelStage.PRODUCTION)
            .first()
        )
        settings = get_settings()

        if not existing:
            # Create seed production model with realistic Adult Income / XGBoost metrics
            mv = ModelVersion(
                model_name=settings.mlflow_model_name,
                version=1,
                stage=ModelStage.PRODUCTION,
                f1_score=0.50,        # realistic baseline for Adult Income XGBoost
                accuracy=0.70,
                precision=0.57,
                recall=0.44,
                roc_auc=0.72,
                avg_latency_ms=8.0,
                dataset_version="v1",
                quality_gate_passed=True,
                quality_gate_details={"overall": "PASSED", "gates": []},
                created_at=datetime.now(timezone.utc),
                promoted_at=datetime.now(timezone.utc),
            )
            db.add(mv)
            db.flush()

            # Create production deployment
            dep = ModelDeployment(
                model_version_id=mv.id,
                status=DeploymentStatus.ACTIVE,
                canary_traffic_percent=1.0,
                is_production=True,
                is_canary=False,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            db.add(dep)

            # Seed baseline monitoring snapshot
            snapshot = MonitoringSnapshot(
                snapshot_type="performance",
                model_name=settings.mlflow_model_name,
                model_version=1,
                f1_score=0.50,
                accuracy=0.70,
                precision=0.57,
                recall=0.44,
                roc_auc=0.72,
                avg_latency_ms=8.0,
                p95_latency_ms=15.0,
                error_rate=0.008,
                request_count=1000,
                drift_detected=False,
                drift_score=0.04,
                drifted_features=[],
                data_quality_status="PASSED",
                created_at=datetime.now(timezone.utc),
            )
            db.add(snapshot)
            db.commit()

        # Update routing state from DB
        from aegisml.execution.engine import _PRODUCTION_MODEL
        prod = (
            db.query(ModelVersion)
            .filter(ModelVersion.stage == ModelStage.PRODUCTION)
            .order_by(ModelVersion.version.desc())
            .first()
        )
        if prod:
            _PRODUCTION_MODEL["model_version"] = prod.version
            _PRODUCTION_MODEL["model_version_id"] = prod.id

    except Exception as exc:
        db.rollback()
        logging.warning(f"Seed data failed (non-fatal): {exc}")
    finally:
        db.close()


app = create_app()
