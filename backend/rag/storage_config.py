"""Configuration for EduGen AI's PostgreSQL/pgvector RAG storage."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_EMBEDDING_MODEL = "gemini-embedding-2"
# The initial migration defines VECTOR(1536). Changing this requires a migration
# and a complete rebuild of embeddings; do not change it through an env var.
EMBEDDING_DIMENSIONS = 1536


def database_url_from_env() -> str:
    """Return a PostgreSQL URL, loading backend .env without printing secrets.

    RAG_DATABASE_URL takes precedence over DATABASE_URL so this feature can use
    a dedicated database while the rest of the application remains unchanged.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    url = os.getenv("RAG_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Database URL is missing. Set RAG_DATABASE_URL (recommended) or "
            "DATABASE_URL in your environment/.env file."
        )

    normalized = url.strip()
    if normalized.startswith("postgres://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgres://") :]
    elif normalized.startswith("postgresql://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgresql://") :]
    elif normalized.startswith("postgresql+psycopg2://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgresql+psycopg2://") :]

    if not normalized.startswith("postgresql+psycopg://"):
        raise RuntimeError(
            "EduGen RAG storage requires PostgreSQL with the psycopg 3 driver. "
            "Use a postgresql:// URL; SQLite is not supported for this schema."
        )
    return normalized


def asset_root_from_env() -> Path:
    """Resolve the private file-asset directory for PDFs and extracted figures."""
    configured = os.getenv("RAG_ASSET_DIR")
    if configured and configured.strip():
        return Path(configured).expanduser().resolve()
    # backend/rag/storage_config.py -> backend/data/rag_assets
    return (Path(__file__).resolve().parents[1] / "data" / "rag_assets").resolve()


def embedding_model_from_env() -> str:
    """Return the configured Gemini embedding model name."""
    return os.getenv("RAG_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL
