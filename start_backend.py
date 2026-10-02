"""
AegisML-Lite Quick-Start — SQLite mode (no PostgreSQL required).

Run from the workspace root:
    python aegisml/start_backend.py
"""
import os
import sys
import subprocess
from pathlib import Path

ROOT    = Path(__file__).parent
BACKEND = ROOT / "backend"

# ── Kill any process on port 8000 before starting ────────────────────────────
try:
    result = subprocess.run(
        ["powershell", "-Command",
         "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | "
         "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
        capture_output=True, timeout=5
    )
except Exception:
    pass

# ── Set ALL env vars BEFORE any aegisml imports ───────────────────────────────
os.environ["DATABASE_URL"]           = f"sqlite:///{ROOT}/aegisml_local.db"
os.environ["MLFLOW_TRACKING_URI"]    = f"sqlite:///{ROOT}/mlruns_local.db"
os.environ["MLFLOW_EXPERIMENT_NAME"] = "aegisml-adult-income"
os.environ["MLFLOW_MODEL_NAME"]      = "income-classifier"
os.environ["AEGISML_ENVIRONMENT"]    = "development"
os.environ["LLM_FALLBACK_MODE"]      = "rule_based"
os.environ["OPENAI_API_KEY"]         = os.environ.get("OPENAI_API_KEY", "")
os.environ["AEGISML_API_KEY"]        = "dev-api-key-change-in-production"
os.environ["AEGISML_SECRET_KEY"]     = "dev-secret-key-local"
os.environ["LOG_LEVEL"]              = "INFO"
os.environ["CORS_ORIGINS"]           = "http://localhost:5173,http://localhost:3000"

# ── Thresholds for Adult Income / XGBoost ────────────────────────────────────
os.environ["DRIFT_THRESHOLD"]        = "0.20"
os.environ["F1_THRESHOLD"]           = "0.45"
os.environ["LATENCY_SLA_MS"]         = "200"
os.environ["ERROR_RATE_THRESHOLD"]   = "0.05"
os.environ["MIN_F1_IMPROVEMENT"]     = "0.005"
os.environ["MISSING_RATE_THRESHOLD"] = "0.20"
os.environ["CONSECUTIVE_WINDOWS_FOR_INCIDENT"] = "3"
os.environ["CANARY_INITIAL_TRAFFIC"] = "0.10"
os.environ["CANARY_STEP_SIZE"]       = "0.15"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "ml"))

import uvicorn

if __name__ == "__main__":
    print("=" * 58)
    print("AegisML-Lite — Adult Income · XGBoost · SQLite")
    print("=" * 58)
    print(f"  DB     : aegisml_local.db")
    print(f"  MLflow : mlruns_local.db")
    print(f"  API    : http://localhost:8000")
    print(f"  Docs   : http://localhost:8000/api/docs")
    print(f"  F1 thr : {os.environ['F1_THRESHOLD']}")
    print("=" * 58)
    uvicorn.run("aegisml.main:app", host="0.0.0.0", port=8000,
                log_level="info", reload=False)
