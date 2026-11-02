"""Keyword search needs real PostgreSQL full-text search, so these run against the disposable test database."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_postgres_integration import ConstantEmbedder, migrated_engine  # noqa: F401  (fixture re-used)
from test_rag_storage import make_fixture

from accounts.service import AccountService
from rag.asset_store import ManagedAssetStore
from rag.database import build_session_factory
from rag.pg_repository import PostgresRAGRepository
from rag.storage_service import RAGStorageService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("RAG_TEST_DATABASE_URL"), reason="RAG_TEST_DATABASE_URL is not set"),
]

BINARY = "Binary search halves the sorted array each step"
PHOTO = "Photosynthesis converts light into chemical energy"
LEARNING = "The learning rate controls the step size of gradient descent"


class World:
    """Users, a repository and a helper that stores a paper made of the given passages."""

    def __init__(self, engine, tmp_path):
        self.factory = build_session_factory(engine)
        self.repository = PostgresRAGRepository(self.factory)
        self.service = RAGStorageService(self.repository, ManagedAssetStore(tmp_path / "assets"), ConstantEmbedder())
        self.accounts = AccountService(self.factory)
        self.tmp_path = tmp_path

    def user(self, name):
        user, _ = self.accounts.signup(f"{name}@example.com", "password1")
        return user.user_id

    def paper(self, user_id, passages, name=None):
        name = name or uuid4().hex[:8]
        folder = self.tmp_path / name
        folder.mkdir()
        pdf_path, _, document, template = make_fixture(folder)
        pdf_path.write_bytes(b"%PDF-1.4\n" + name.encode())               # a different file, so a different hash
        chunks = [
            template.model_copy(update={
                "chunk_id": str(uuid4()), "sequence_index": index, "text": passage,
                "previous_chunk_id": None, "next_chunk_id": None,
            })
            for index, passage in enumerate(passages)
        ]
        return self.service.persist_document(user_id, pdf_path, document, chunks).document_id


@pytest.fixture
def world(migrated_engine, tmp_path):  # noqa: F811
    return World(migrated_engine, tmp_path)


def test_the_passage_that_mentions_the_words_ranks_first(world):
    owner = world.user("owner")
    document_id = world.paper(owner, [PHOTO, BINARY, LEARNING])

    hits = world.repository.keyword_search(owner, document_id, "how does binary search halve the array")

    assert hits[0].text.startswith("Binary search halves")
    assert hits[0].page_start == 1 and hits[0].document_id == document_id


def test_questions_are_matched_word_by_word_not_as_one_phrase(world):
    owner = world.user("owner")
    document_id = world.paper(owner, [PHOTO, BINARY, LEARNING])

    hits = world.repository.keyword_search(owner, document_id, "What is the learning rate used for?")

    assert hits and hits[0].text.startswith("The learning rate")


@pytest.mark.parametrize("query", ["", "   ", "the of and", "?!...", "'' \"\""])
def test_a_query_with_no_usable_words_returns_nothing(world, query):
    owner = world.user("owner")
    document_id = world.paper(owner, [BINARY])

    assert world.repository.keyword_search(owner, document_id, query) == []


def test_sql_looking_and_very_long_queries_are_just_words(world):
    owner = world.user("owner")
    document_id = world.paper(owner, [BINARY])

    assert isinstance(world.repository.keyword_search(owner, document_id, "'; DROP TABLE rag_documents; --"), list)
    assert isinstance(world.repository.keyword_search(owner, document_id, "binary " * 800), list)
    assert isinstance(world.repository.keyword_search(owner, document_id, " ".join(f"word{i}" for i in range(500))), list)
    assert world.repository.keyword_search(owner, document_id, "binary search")          # the table still exists


def test_only_the_callers_passages_in_the_named_paper_are_searched(world):
    alice = world.user("alice")
    bob = world.user("bob")
    alices = world.paper(alice, [BINARY, PHOTO])
    alices_other = world.paper(alice, ["Binary search binary search binary search on a sorted array"])
    bobs = world.paper(bob, ["Binary binary binary search search search of the array array"])

    hits = world.repository.keyword_search(alice, alices, "binary search of the array")

    assert {hit.document_id for hit in hits} == {alices}                 # not her other paper, not Bob's
    assert world.repository.keyword_search(alice, bobs, "binary search") == []
    assert world.repository.keyword_search(bob, alices, "binary search") == []
    assert world.repository.keyword_search(bob, bobs, "binary search")
    assert alices_other != alices


def test_limit_is_validated_and_respected(world):
    owner = world.user("owner")
    document_id = world.paper(owner, [LEARNING, "the step of the algorithm", "another step here"])

    with pytest.raises(ValueError):
        world.repository.keyword_search(owner, document_id, "step", limit=0)
    with pytest.raises(ValueError):
        world.repository.keyword_search(owner, document_id, "step", limit=101)
    assert len(world.repository.keyword_search(owner, document_id, "step", limit=1)) == 1
    assert len(world.repository.keyword_search(owner, document_id, "step", limit=10)) == 3


def test_the_search_expression_is_covered_by_the_index(world):
    with world.factory.begin() as session:
        session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(session.execute(text(
            "EXPLAIN SELECT chunk_id FROM rag_document_chunks "
            "WHERE to_tsvector('english', context_prefix || ' ' || text) @@ to_tsquery('english', 'binary')"
        )).scalars())

    assert "ix_rag_chunks_fts" in plan
