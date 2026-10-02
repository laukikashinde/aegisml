"""
SQLAlchemy declarative base and session factory.
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from aegisml.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def _get_engine():
    settings = get_settings()
    db_url = settings.database_url

    # SQLite — used for local dev without PostgreSQL
    if db_url.startswith("sqlite"):
        engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
        )
    else:
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            echo=False,
        )
    return engine


def get_engine():
    return _get_engine()


def get_session_factory(engine=None):
    if engine is None:
        engine = get_engine()
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


# Module-level singletons (initialised lazily)
_engine = None
_SessionFactory = None


def init_db() -> None:
    """Create all tables. Called at application startup."""
    global _engine, _SessionFactory
    _engine = get_engine()
    _SessionFactory = get_session_factory(_engine)

    # Import all models so Base.metadata knows about them
    from aegisml.database import models  # noqa: F401

    Base.metadata.create_all(bind=_engine)


def get_db():
    """FastAPI dependency that yields a database session."""
    global _SessionFactory
    if _SessionFactory is None:
        _engine = get_engine()
        _SessionFactory = get_session_factory(_engine)

    db = _SessionFactory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
