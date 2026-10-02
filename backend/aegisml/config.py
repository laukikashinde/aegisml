"""
AegisML — centralised configuration.
All settings are read from environment variables / .env file.
Never hardcode credentials or thresholds.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ─────────────────────────────────────────────────────────
    aegisml_environment: Literal["development", "staging", "production"] = "development"
    aegisml_api_key: str = "dev-api-key-change-in-production"
    aegisml_secret_key: str = "change-this-secret-key-in-production"
    log_level: str = "INFO"

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql://aegisml:aegisml_secret@localhost:5432/aegisml"

    # ── MLflow ───────────────────────────────────────────────────────────────
    mlflow_tracking_uri: str = "http://localhost:5001"
    mlflow_experiment_name: str = "aegisml-churn"
    mlflow_model_name: str = "churn-classifier"

    # ── LLM ──────────────────────────────────────────────────────────────────
    llm_provider: str = "openai"
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_fallback_mode: Literal["rule_based", "disabled"] = "rule_based"
    llm_timeout_seconds: int = 60

    # ── Monitoring intervals ──────────────────────────────────────────────────
    monitoring_interval_seconds: int = 60
    drift_check_interval_seconds: int = 300
    performance_check_interval_seconds: int = 120

    # ── ML / Policy thresholds ────────────────────────────────────────────────
    drift_threshold: float = 0.20
    f1_threshold: float = 0.82
    latency_sla_ms: float = 200.0
    error_rate_threshold: float = 0.05
    consecutive_windows_for_incident: int = 3
    missing_rate_threshold: float = 0.20
    min_f1_improvement: float = 0.02

    # ── Canary ────────────────────────────────────────────────────────────────
    canary_initial_traffic: float = 0.10
    canary_step_size: float = 0.15
    canary_health_check_interval: int = 30
    auto_promote_threshold: float = 0.95

    # ── Prometheus ────────────────────────────────────────────────────────────
    prometheus_port: int = 9090

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse cors_origins as comma-separated string."""
        origins = self.cors_origins.strip()
        if origins.startswith("["):
            import json
            try:
                return json.loads(origins)
            except Exception:
                pass
        return [o.strip() for o in origins.split(",") if o.strip()]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str | list) -> str:
        if isinstance(v, list):
            return ",".join(v)
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json
                try:
                    items = json.loads(v)
                    return ",".join(items)
                except Exception:
                    pass
        return str(v)

    @property
    def is_production(self) -> bool:
        return self.aegisml_environment == "production"

    @property
    def llm_available(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.startswith("sk-"))


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
