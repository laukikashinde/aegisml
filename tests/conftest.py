"""
Test configuration and fixtures.
Uses SQLite so tests run without PostgreSQL.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add both backend and ml directories to sys.path
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "ml"))

# Override settings before importing anything from aegisml
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_aegisml.db")
os.environ.setdefault("MLFLOW_TRACKING_URI", "sqlite:///./test_mlruns.db")
os.environ.setdefault("AEGISML_ENVIRONMENT", "development")
os.environ.setdefault("LLM_FALLBACK_MODE", "rule_based")
os.environ.setdefault("OPENAI_API_KEY", "")

from aegisml.database.base import Base, get_db
from aegisml.database import models  # noqa: F401 — register all models


# ── SQLite-compatible engine ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def engine():
    # Use a file-based SQLite so session fixtures can share state
    db_path = "test_aegisml.db"
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    # Patch enums to use String in SQLite
    from sqlalchemy import event as sa_event
    from sqlalchemy.engine import Engine
    import sqlite3

    @sa_event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        if isinstance(dbapi_conn, sqlite3.Connection):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()
    import gc
    gc.collect()
    import time
    time.sleep(0.2)
    for f in ("test_aegisml.db", "test_mlruns.db"):
        try:
            Path(f).unlink(missing_ok=True)
        except PermissionError:
            pass  # Windows file lock — harmless, file will be reused next run


@pytest.fixture(scope="function")
def db(engine):
    """Function-scoped session — each test gets a clean rollback."""
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="session")
def client(engine):
    """FastAPI test client with DB override."""
    from fastapi.testclient import TestClient
    from aegisml.main import app

    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        s = TestSession()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
