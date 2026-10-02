#!/usr/bin/env python3
"""
AegisML bootstrap script.

Runs once after docker-compose up to:
  1. Generate the dataset
  2. Run the initial training pipeline
  3. Register the model in MLflow
  4. Seed the AegisML database

Usage:
    python scripts/setup.py
"""
from __future__ import annotations

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

# ── Load env ──────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


def run(cmd: list[str], cwd: Path | None = None, env_extra: dict | None = None) -> int:
    env = {**os.environ, **(env_extra or {})}
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd or ROOT, env=env)
    return result.returncode


def wait_for_backend(url: str = "http://localhost:8000/health", max_wait: int = 60) -> bool:
    import urllib.request
    print(f"Waiting for backend at {url}…")
    for i in range(max_wait):
        try:
            urllib.request.urlopen(url, timeout=2)
            print("  Backend is up.")
            return True
        except Exception:
            time.sleep(1)
    print("  WARNING: Backend did not respond in time.")
    return False


def main():
    print("=" * 60)
    print("AegisML Setup")
    print("=" * 60)

    # Step 1: Generate dataset
    print("\n[1/3] Generating training dataset...")
    rc = run(
        [sys.executable, str(ML_DIR / "data" / "generate_dataset.py"),
         "--version", "v1", "--n-samples", "10000"],
        cwd=ROOT,
    )
    if rc != 0:
        print("ERROR: Dataset generation failed.")
        sys.exit(1)

    # Also generate drift dataset for simulations
    run(
        [sys.executable, str(ML_DIR / "data" / "generate_dataset.py"),
         "--version", "v2_drift", "--drift-type", "income"],
        cwd=ROOT,
    )

    # Step 2: Run training pipeline
    print("\n[2/3] Running initial training pipeline...")
    rc = run(
        [sys.executable, str(ML_DIR / "training" / "train.py"), "--dataset-version", "v1"],
        cwd=BACKEND,
        env_extra={"PYTHONPATH": str(BACKEND)},
    )
    if rc != 0:
        print("WARNING: Training pipeline failed. The backend will use seed data instead.")

    # Step 3: Wait for backend and verify
    print("\n[3/3] Verifying backend...")
    if wait_for_backend():
        import urllib.request, json
        try:
            resp = urllib.request.urlopen("http://localhost:8000/api/dashboard", timeout=5)
            data = json.loads(resp.read())
            print(f"  Dashboard OK — production model: v{data.get('production_model_version', '?')}")
        except Exception as e:
            print(f"  Dashboard check failed: {e}")

    print("\n" + "=" * 60)
    print("Setup complete.")
    print("\nAccess AegisML at:")
    print("  Frontend : http://localhost:5173")
    print("  API Docs : http://localhost:8000/api/docs")
    print("  MLflow   : http://localhost:5001")
    print("  Grafana  : http://localhost:3001  (admin/admin)")
    print("  Prometheus: http://localhost:9090")
    print("=" * 60)


if __name__ == "__main__":
    main()
