#!/usr/bin/env python3
"""
AegisML — Local runner script.

Usage:
    python scripts/run_local.py --pg-password YOUR_PASSWORD
    python scripts/run_local.py --pg-password YOUR_PASSWORD --pg-user postgres

What it does:
  1. Creates the aegisml database in your local PostgreSQL
  2. Starts MLflow tracking server (SQLite backend)
  3. Runs the initial training pipeline
  4. Starts the FastAPI backend
  5. Prints frontend start instructions
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
ML_DIR = ROOT / "ml"

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ML_DIR))


def create_database(pg_user: str, pg_password: str, pg_host: str, dbname: str) -> bool:
    """Create the aegisml database if it doesn't exist."""
    try:
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

        conn = psycopg2.connect(
            host=pg_host, user=pg_user, password=pg_password,
            dbname="postgres", connect_timeout=5,
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM pg_database WHERE datname='{dbname}'")
        if not cur.fetchone():
            cur.execute(f"CREATE DATABASE {dbname}")
            print(f"  ✓ Created database '{dbname}'")
        else:
            print(f"  ✓ Database '{dbname}' already exists")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"  ✗ Database setup failed: {e}")
        return False


def write_env(pg_user: str, pg_password: str, pg_host: str, dbname: str) -> None:
    """Write .env with correct DATABASE_URL."""
    env_path = ROOT / ".env"
    content = env_path.read_text()
    new_url = f"postgresql://{pg_user}:{pg_password}@{pg_host}:5432/{dbname}"
    lines = []
    for line in content.splitlines():
        if line.startswith("DATABASE_URL="):
            lines.append(f"DATABASE_URL={new_url}")
        else:
            lines.append(line)
    env_path.write_text("\n".join(lines) + "\n")
    print(f"  ✓ Updated DATABASE_URL in .env")


def start_mlflow() -> subprocess.Popen:
    """Start MLflow tracking server in background."""
    print("\n[2/4] Starting MLflow server (port 5001)...")
    p = subprocess.Popen(
        [sys.executable, "-m", "mlflow", "server",
         "--backend-store-uri", f"sqlite:///{ROOT}/mlruns.db",
         "--host", "0.0.0.0", "--port", "5001"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    print("  ✓ MLflow started → http://localhost:5001")
    return p


def run_training() -> bool:
    """Run initial training pipeline."""
    print("\n[3/4] Running training pipeline (this takes ~60s)...")
    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND),
        "MLFLOW_TRACKING_URI": f"sqlite:///{ROOT}/mlruns.db",
    }
    result = subprocess.run(
        [sys.executable, str(ML_DIR / "training" / "train.py"), "--dataset-version", "v1"],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300,
    )
    if result.returncode == 0:
        print("  ✓ Training complete")
        return True
    else:
        print(f"  ⚠ Training failed (non-fatal, backend will use seed data)")
        print(f"    {result.stderr[-300:]}")
        return False


def start_backend(pg_user: str, pg_password: str, pg_host: str, dbname: str) -> subprocess.Popen:
    """Start FastAPI backend."""
    print("\n[4/4] Starting AegisML backend (port 8000)...")
    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND),
        "DATABASE_URL": f"postgresql://{pg_user}:{pg_password}@{pg_host}:5432/{dbname}",
        "MLFLOW_TRACKING_URI": f"sqlite:///{ROOT}/mlruns.db",
        "MLFLOW_EXPERIMENT_NAME": "aegisml-churn",
        "MLFLOW_MODEL_NAME": "churn-classifier",
        "AEGISML_ENVIRONMENT": "development",
        "LLM_FALLBACK_MODE": "rule_based",
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "CORS_ORIGINS": "http://localhost:5173,http://localhost:3000",
    }
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "aegisml.main:app",
         "--host", "0.0.0.0", "--port", "8000", "--reload"],
        cwd=BACKEND, env=env,
    )
    return p


def wait_for_url(url: str, max_wait: int = 30) -> bool:
    import urllib.request
    for _ in range(max_wait):
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-password", required=True, help="PostgreSQL password")
    parser.add_argument("--pg-user", default="postgres", help="PostgreSQL user")
    parser.add_argument("--pg-host", default="localhost", help="PostgreSQL host")
    parser.add_argument("--dbname", default="aegisml", help="Database name")
    parser.add_argument("--skip-training", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("AegisML — Local Startup")
    print("=" * 60)

    # Step 1: Database
    print("\n[1/4] Setting up database...")
    if not create_database(args.pg_user, args.pg_password, args.pg_host, args.dbname):
        print("Cannot continue without database. Check your PostgreSQL credentials.")
        sys.exit(1)
    write_env(args.pg_user, args.pg_password, args.pg_host, args.dbname)

    # Step 2: MLflow
    mlflow_proc = start_mlflow()

    # Step 3: Training
    if not args.skip_training:
        run_training()
    else:
        print("\n[3/4] Skipping training (--skip-training)")

    # Step 4: Backend
    backend_proc = start_backend(args.pg_user, args.pg_password, args.pg_host, args.dbname)

    print("\nWaiting for backend to start...")
    if wait_for_url("http://localhost:8000/health", max_wait=30):
        print("  ✓ Backend ready → http://localhost:8000/health")
    else:
        print("  ⚠ Backend may still be starting...")

    print("\n" + "=" * 60)
    print("AegisML is running!")
    print()
    print("  Backend API  → http://localhost:8000")
    print("  API Docs     → http://localhost:8000/api/docs")
    print("  MLflow       → http://localhost:5001")
    print()
    print("  To start the frontend (open a NEW terminal):")
    print(f"    cd aegisml/frontend")
    print(f"    npm install")
    print(f"    npm run dev")
    print()
    print("  Then open: http://localhost:5173")
    print()
    print("  Press Ctrl+C to stop backend + MLflow")
    print("=" * 60)

    try:
        backend_proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        backend_proc.terminate()
        mlflow_proc.terminate()


if __name__ == "__main__":
    main()
