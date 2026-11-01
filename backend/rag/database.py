"""PostgreSQL engine/session factories; no connection is opened at import time."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from rag.storage_config import database_url_from_env


def build_engine(database_url: str | None = None) -> Engine:
    """Create a PostgreSQL engine without performing a connection check."""
    url = database_url or database_url_from_env()
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("build_engine requires a postgresql+psycopg:// URL")
    return create_engine(url, pool_pre_ping=True, future=True)


def build_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Create a SQLAlchemy 2.x session factory for the given engine."""
    resolved_engine = engine or build_engine()
    return sessionmaker(
        bind=resolved_engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


def check_database(engine: Engine) -> dict[str, str | None]:
    """Verify PostgreSQL connectivity and the installed pgvector extension."""
    with engine.connect() as connection:
        database_name = connection.execute(text("SELECT current_database()")).scalar_one()
        vector_version = connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
    if not vector_version:
        raise RuntimeError(
            "PostgreSQL is reachable, but the pgvector extension is not installed "
            "or is not enabled for this database. Install/enable it, then run the migration."
        )
    return {"database": str(database_name), "pgvector_version": str(vector_version)}
