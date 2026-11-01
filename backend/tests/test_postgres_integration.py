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

from accounts.service import AccountService
from rag.asset_store import ManagedAssetStore
from papers.ingestor import PaperIngestor
from papers.repository import PaperRepository
from pdf_helpers import make_text_pdf
from rag.database import build_engine, build_session_factory, check_database
from rag.pg_repository import PostgresRAGRepository
from rag.storage_config import EMBEDDING_DIMENSIONS
from rag.storage_service import RAGStorageService
from test_rag_storage import make_fixture

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("RAG_TEST_DATABASE_URL"), reason="RAG_TEST_DATABASE_URL is not set"),
]

BACKEND_DIR = Path(__file__).resolve().parents[1]


def reset_to_base(config):
    """Empty the tables, then downgrade: earlier runs may have left data that a downgrade cannot keep.

    (For example two users holding the same PDF cannot satisfy the old one-copy-per-PDF constraint.)
    """
    engine = build_engine()
    try:
        with engine.begin() as connection:
            for table in ("users", "rag_documents"):
                if connection.execute(text("SELECT to_regclass(:name)"), {"name": f"public.{table}"}).scalar_one():
                    connection.execute(text(f"DELETE FROM {table}"))
    finally:
        engine.dispose()
    command.downgrade(config, "base")


@pytest.fixture
def migrated_engine(monkeypatch):
    monkeypatch.setenv("RAG_DATABASE_URL", os.environ["RAG_TEST_DATABASE_URL"])
    monkeypatch.chdir(BACKEND_DIR)
    config = Config("alembic.ini")
    reset_to_base(config)
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
    reset_to_base(config)
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


class ConstantEmbedder:
    """Every text gets the same vector: these tests check who can see what, not ranking."""

    model_name = "test-embedding"
    dimensions = EMBEDDING_DIMENSIONS

    def _vector(self):
        return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)

    def embed_prepared_text(self, formatted_text):
        return self._vector()

    def embed_query(self, query):
        return self._vector()


def test_two_users_store_the_same_paper_and_search_stays_private(migrated_engine, tmp_path):
    factory = build_session_factory(migrated_engine)
    accounts = AccountService(factory)
    alice, _ = accounts.signup("alice@example.com", "password1")
    bob, _ = accounts.signup("bob@example.com", "password1")
    carol, _ = accounts.signup("carol@example.com", "password1")
    service = RAGStorageService(
        PostgresRAGRepository(factory), ManagedAssetStore(tmp_path / "assets"), ConstantEmbedder()
    )

    document_ids = {}
    stored = {}
    for name, user in (("alice", alice), ("bob", bob)):
        (tmp_path / name).mkdir()
        pdf_path, _, document, chunk = make_fixture(tmp_path / name)     # identical PDF bytes for both
        result = service.persist_document(user.user_id, pdf_path, document, [chunk])
        assert result.already_exists is False
        assert service.generate_missing_embeddings(result.document_id) == 1
        document_ids[name] = result.document_id
        stored[name] = (user, pdf_path, document, chunk)

    assert document_ids["alice"] != document_ids["bob"]
    user, pdf_path, document, chunk = stored["alice"]
    again = service.persist_document(user.user_id, pdf_path, document, [chunk])
    assert again.already_exists is True and again.document_id == document_ids["alice"]

    for name, user in (("alice", alice), ("bob", bob)):
        hits = service.search_similar(user.user_id, "anything", limit=10)
        assert {hit.document_id for hit in hits} == {document_ids[name]}
    assert service.search_similar(alice.user_id, "anything", document_id=document_ids["alice"])
    assert service.search_similar(alice.user_id, "anything", document_id=document_ids["bob"]) == []
    assert service.search_similar(carol.user_id, "anything") == []


def test_papers_table_exists_with_its_constraints(migrated_engine, tmp_path):
    factory = build_session_factory(migrated_engine)
    owner, _ = AccountService(factory).signup("owner@example.com", "password1")
    service = RAGStorageService(PostgresRAGRepository(factory), ManagedAssetStore(tmp_path / "assets"), ConstantEmbedder())
    pdf_path, _, document, chunk = make_fixture(tmp_path)
    stored = service.persist_document(owner.user_id, pdf_path, document, [chunk])
    papers = PaperRepository(factory)
    paper = papers.create(owner.user_id, "paper.pdf", 10, "c" * 64)
    papers.update(paper.paper_id, document_id=stored.document_id)

    with migrated_engine.connect() as connection:
        constraints = connection.execute(
            text("SELECT conname FROM pg_constraint WHERE conrelid = 'papers'::regclass")
        ).scalars().all()
    assert "uq_papers_user_sha256" in constraints

    with migrated_engine.begin() as connection:             # removing the stored document keeps the library row
        connection.execute(text("DELETE FROM rag_documents"))
    assert papers.get(paper.paper_id, owner.user_id).document_id is None

    with migrated_engine.begin() as connection:             # removing the user removes their papers
        connection.execute(text("DELETE FROM users"))
    assert papers.list_for_user(owner.user_id) == []


def test_report_counts_chunks_figures_and_warnings(migrated_engine, tmp_path):
    factory = build_session_factory(migrated_engine)
    owner, _ = AccountService(factory).signup("owner@example.com", "password1")
    service = RAGStorageService(PostgresRAGRepository(factory), ManagedAssetStore(tmp_path / "assets"), ConstantEmbedder())
    pdf_path, _, document, chunk = make_fixture(tmp_path)
    stored = service.persist_document(owner.user_id, pdf_path, document, [chunk])

    report = PaperRepository(factory).report(stored.document_id)

    assert (report.title, report.authors, report.page_count) == ("Test paper", ["Example Author"], 1)
    assert (report.chunk_count, report.figure_count) == (1, 1)
    assert report.warnings == []


@pytest.mark.slow
def test_the_real_ingestor_reads_a_text_pdf_into_postgres(migrated_engine, tmp_path):
    factory = build_session_factory(migrated_engine)
    owner, _ = AccountService(factory).signup("owner@example.com", "password1")
    storage = RAGStorageService(PostgresRAGRepository(factory), ManagedAssetStore(tmp_path / "assets"), ConstantEmbedder())
    pdf = make_text_pdf(tmp_path / "small.pdf", [
        "Binary Search",
        "Binary search finds a value in a sorted list.",
        "It halves the search range at every step.",
    ])
    stages = []
    ingestor = PaperIngestor(storage)

    result = ingestor.ingest(owner.user_id, pdf, tmp_path / "work", lambda status, detail=None: stages.append(status))

    assert stages == ["parsing", "chunking", "storing"]
    report = PaperRepository(factory).report(result.document_id)
    assert report.chunk_count >= 1
    embedded = ingestor.embed(result.document_id, lambda status, detail=None: stages.append(status))
    assert embedded >= 1
    assert stages[-1] == "embedding"


def test_claims_are_atomic_on_postgres(migrated_engine):
    factory = build_session_factory(migrated_engine)
    owner, _ = AccountService(factory).signup("owner@example.com", "password1")
    papers = PaperRepository(factory)
    paper = papers.create(owner.user_id, "paper.pdf", 10, "d" * 64)
    papers.update(paper.paper_id, status="failed")

    assert papers.claim_for_reading(paper.paper_id) is True
    assert papers.claim_for_reading(paper.paper_id) is False
    assert papers.get(paper.paper_id, owner.user_id).status == "queued"
