"""Tests that need a real, disposable PostgreSQL database with pgvector installed.

Set RAG_TEST_DATABASE_URL (in the environment or backend/.env) to a database that
may be wiped: the fixture downgrades to base and upgrades to head. Never point it
at the development database.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import text

from rag.database import build_engine, check_database

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("RAG_TEST_DATABASE_URL"), reason="RAG_TEST_DATABASE_URL is not set"),
]

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def migrated_engine(monkeypatch):
    monkeypatch.setenv("RAG_DATABASE_URL", os.environ["RAG_TEST_DATABASE_URL"])
    monkeypatch.chdir(BACKEND_DIR)
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = build_engine()
    try:
        yield engine
    finally:
        engine.dispose()


def test_vector_extension_and_column_exist(migrated_engine):
    with migrated_engine.connect() as connection:
        extensions = connection.execute(text("SELECT extname FROM pg_extension")).scalars().all()
        column_type = connection.execute(
            text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_name = 'rag_chunk_embeddings' AND column_name = 'embedding'"
            )
        ).scalar_one()
    assert "vector" in extensions
    assert column_type == "vector"


def test_cosine_distance_operator_orders_vectors(migrated_engine):
    with migrated_engine.connect() as connection:
        same = connection.execute(text("SELECT '[1,0]'::vector <=> '[2,0]'::vector")).scalar_one()
        orthogonal = connection.execute(text("SELECT '[1,0]'::vector <=> '[0,1]'::vector")).scalar_one()
    assert same == pytest.approx(0.0)
    assert orthogonal == pytest.approx(1.0)


def test_check_database_reports_the_pgvector_version(migrated_engine):
    assert check_database(migrated_engine)["pgvector_version"]


def test_accounts_tables_exist_and_documents_are_owned(migrated_engine):
    with migrated_engine.connect() as connection:
        tables = connection.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        ).scalars().all()
        user_id_nullable = connection.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'rag_documents' AND column_name = 'user_id'"
            )
        ).scalar_one()
        constraints = connection.execute(
            text("SELECT conname FROM pg_constraint WHERE conrelid = 'rag_documents'::regclass")
        ).scalars().all()
    assert {"users", "auth_sessions", "videos"} <= set(tables)
    assert user_id_nullable == "NO"
    assert "uq_rag_documents_user_source_sha256" in constraints
    assert "uq_rag_documents_source_sha256" not in constraints


def test_upgrade_refuses_to_guess_an_owner_for_existing_documents(monkeypatch):
    monkeypatch.setenv("RAG_DATABASE_URL", os.environ["RAG_TEST_DATABASE_URL"])
    monkeypatch.chdir(BACKEND_DIR)
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "0001_rag_storage")
    engine = build_engine()
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO rag_documents (document_id, source_sha256, source_filename, source_asset_key, parser_name) "
                "VALUES ('d1', 'abc', 'paper.pdf', 'k', 'docling')"
            ))
        with pytest.raises(Exception, match="rag_documents is not empty"):
            command.upgrade(config, "head")
        with engine.connect() as connection:
            users_exist = connection.execute(text("SELECT to_regclass('public.users')")).scalar_one()
        assert users_exist is None            # the failed upgrade rolled back completely
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM rag_documents"))
        engine.dispose()
