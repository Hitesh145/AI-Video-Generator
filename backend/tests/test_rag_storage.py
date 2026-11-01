from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from rag.asset_store import ManagedAssetStore, canonical_source_path
from rag.chunk_schema import CanonicalChunk, ChunkSourceReference
from rag.document_schema import DocumentBlock, NormalizedDocument
from rag.embedding_service import (
    EmbeddingError,
    GeminiEmbeddingService,
    prepare_document_embedding_text,
    prepare_query_embedding_text,
)
from rag.storage_config import EMBEDDING_DIMENSIONS, database_url_from_env
from rag.storage_schema import EmbeddingToStore, EmbeddingWorkItem, SimilarityHit
from rag.storage_service import RAGStorageService


def make_fixture(tmp_path: Path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nminimal test fixture\n%%EOF")
    image_path = tmp_path / "figure.png"
    image_path.write_bytes(b"fake png bytes")
    document_id = str(uuid4())
    block_id = str(uuid4())
    block = DocumentBlock(
        block_id=block_id,
        ordinal=0,
        block_type="figure",
        source_label="picture",
        text="",
        caption="Example figure",
        image_asset_path=str(image_path),
        image_available=True,
        page_number=1,
        section_path=["Example"],
    )
    document = NormalizedDocument(
        document_id=document_id,
        source_filename=pdf_path.name,
        title="Test paper",
        authors=["Example Author"],
        affiliations=["Example University"],
        page_count=1,
        blocks=[block],
    )
    chunk = CanonicalChunk(
        chunk_id=str(uuid4()),
        document_id=document_id,
        sequence_index=0,
        text="Example figure caption",
        token_count_estimate=6,
        section_id=str(uuid4()),
        section_title="Example",
        section_path=["Example"],
        page_start=1,
        page_end=1,
        source_refs=[
            ChunkSourceReference(
                block_id=block_id,
                ordinal=0,
                block_type="figure",
                source_label="picture",
                page_number=1,
                caption="Example figure",
                image_asset_path=str(image_path),
                image_available=True,
            )
        ],
        related_element_ids=[block_id],
        image_asset_paths=[str(image_path)],
        context_prefix="Document: Test paper\nSection: Example",
    )
    return pdf_path, image_path, document, chunk


class FakeRepository:
    def __init__(self):
        self.existing_by_hash: dict[tuple[str, str], str] = {}
        self.last_search: tuple | None = None
        self.persisted: list[tuple] = []
        self.work_items: list[EmbeddingWorkItem] = []
        self.saved_embeddings: list[tuple[str, list[EmbeddingToStore]]] = []
        self.hits: list[SimilarityHit] = []

    def find_document_by_sha256(self, user_id, digest):
        return self.existing_by_hash.get((user_id, digest))

    def persist_bundle(self, user_id, document, chunks, source_sha256, asset_bundle):
        self.persisted.append((user_id, document, chunks, source_sha256, asset_bundle))
        self.existing_by_hash[(user_id, source_sha256)] = document.document_id
        return document.document_id, True

    def chunks_missing_embeddings(self, document_id, model_name):
        return list(self.work_items)

    def save_embeddings(self, model_name, embeddings):
        self.saved_embeddings.append((model_name, list(embeddings)))
        return len(embeddings)

    def search_similar(self, user_id, query_vector, model_name, limit=5, document_id=None):
        self.last_search = (user_id, document_id, limit)
        return self.hits[:limit]


class FakeEmbedder:
    model_name = "fake-embedding-model"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self):
        self.inputs = []

    def embed_prepared_text(self, formatted_text):
        self.inputs.append(formatted_text)
        return [0.125] * self.dimensions

    def embed_query(self, query):
        self.inputs.append(query)
        return [0.25] * self.dimensions


def test_database_url_normalizes_postgres_scheme(monkeypatch):
    monkeypatch.setenv("RAG_DATABASE_URL", "postgresql://user:pass@localhost:5432/edugen")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url_from_env() == "postgresql+psycopg://user:pass@localhost:5432/edugen"


def test_database_url_requires_postgresql(monkeypatch):
    monkeypatch.setenv("RAG_DATABASE_URL", "sqlite:///test.db")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        database_url_from_env()


def test_asset_store_creates_relative_keys_and_copies_pdf_and_figure(tmp_path):
    pdf_path, image_path, document, _ = make_fixture(tmp_path)
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    store = ManagedAssetStore(tmp_path / "managed")

    bundle = store.store_bundle(pdf_path, document, digest)

    assert not Path(bundle.source_pdf_key).is_absolute()
    assert bundle.source_pdf_key.endswith("/source.pdf")
    assert (store.root / bundle.source_pdf_key).read_bytes() == pdf_path.read_bytes()
    block = document.blocks[0]
    image_key = bundle.image_keys_by_block_id[block.block_id]
    assert (store.root / image_key).read_bytes() == image_path.read_bytes()
    assert bundle.source_path_to_key[canonical_source_path(image_path)] == image_key
    assert len(bundle.assets) == 2
    assert all(".." not in Path(asset.asset_key).parts for asset in bundle.assets)


def test_asset_store_warns_when_figure_file_is_missing(tmp_path):
    pdf_path, _, document, _ = make_fixture(tmp_path)
    document.blocks[0].image_asset_path = str(tmp_path / "missing.png")
    bundle = ManagedAssetStore(tmp_path / "managed").store_bundle(
        pdf_path, document, hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    )
    assert len(bundle.assets) == 1
    assert not bundle.image_keys_by_block_id
    assert any("unavailable" in warning for warning in bundle.warnings)


def test_asset_store_refuses_changed_source_hash(tmp_path):
    pdf_path, _, document, _ = make_fixture(tmp_path)
    with pytest.raises(ValueError, match="content changed"):
        ManagedAssetStore(tmp_path / "managed").store_bundle(pdf_path, document, "0" * 64)


def test_persist_document_copies_assets_and_is_idempotent(tmp_path):
    pdf_path, _, document, chunk = make_fixture(tmp_path)
    repo = FakeRepository()
    service = RAGStorageService(repo, ManagedAssetStore(tmp_path / "managed"))

    first = service.persist_document("user-1", pdf_path, document, [chunk])
    second = service.persist_document("user-1", pdf_path, document, [chunk])

    assert first.already_exists is False
    assert first.block_count == 1 and first.chunk_count == 1 and first.asset_count == 2
    assert second.already_exists is True
    assert len(repo.persisted) == 1


def test_persist_document_rejects_chunk_for_different_document(tmp_path):
    pdf_path, _, document, chunk = make_fixture(tmp_path)
    chunk.document_id = str(uuid4())
    service = RAGStorageService(FakeRepository(), ManagedAssetStore(tmp_path / "managed"))
    with pytest.raises(ValueError, match="belongs to"):
        service.persist_document("user-1", pdf_path, document, [chunk])


def test_persist_document_rejects_missing_source_block(tmp_path):
    pdf_path, _, document, chunk = make_fixture(tmp_path)
    chunk.source_refs[0].block_id = str(uuid4())
    service = RAGStorageService(FakeRepository(), ManagedAssetStore(tmp_path / "managed"))
    with pytest.raises(ValueError, match="absent from the document"):
        service.persist_document("user-1", pdf_path, document, [chunk])


def test_embedding_input_format_for_gemini_embedding_2():
    assert prepare_document_embedding_text("Paper", "The chunk") == "title: Paper | text: The chunk"
    assert prepare_document_embedding_text(None, "Content") == "title: none | text: Content"
    assert prepare_query_embedding_text("What is AI?") == "task: question answering | query: What is AI?"
    with pytest.raises(ValueError, match="empty"):
        prepare_query_embedding_text("  ")


def test_gemini_embedding_service_passes_dimension_and_validates_vector():
    recorded = {}

    class FakeConfig:
        def __init__(self, output_dimensionality):
            recorded["dimensions"] = output_dimensionality

    class FakeClient:
        class Models:
            @staticmethod
            def embed_content(**kwargs):
                recorded.update(kwargs)
                return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.5] * EMBEDDING_DIMENSIONS)])
        models = Models()

    service = GeminiEmbeddingService(
        model_name="gemini-embedding-2",
        client=FakeClient(),
        config_factory=FakeConfig,
    )
    vector = service.embed_document("A paragraph", "Paper")
    assert len(vector) == EMBEDDING_DIMENSIONS
    assert recorded["model"] == "gemini-embedding-2"
    assert recorded["contents"] == "title: Paper | text: A paragraph"
    assert recorded["dimensions"] == EMBEDDING_DIMENSIONS


def test_gemini_embedding_service_rejects_wrong_vector_length():
    class FakeConfig:
        def __init__(self, output_dimensionality):
            self.output_dimensionality = output_dimensionality

    class FakeClient:
        class Models:
            @staticmethod
            def embed_content(**kwargs):
                return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2])])
        models = Models()

    service = GeminiEmbeddingService(client=FakeClient(), config_factory=FakeConfig)
    with pytest.raises(EmbeddingError, match="Expected 1536 dimensions"):
        service.embed_query("What is AI?")


def test_storage_service_generates_missing_embeddings_in_batches(tmp_path):
    pdf_path, _, document, chunk = make_fixture(tmp_path)
    repo = FakeRepository()
    repo.work_items = [
        EmbeddingWorkItem(chunk_id=chunk.chunk_id, formatted_text=f"input {i}", content_sha256=f"{i:064d}")
        for i in range(3)
    ]
    embedder = FakeEmbedder()
    service = RAGStorageService(repo, ManagedAssetStore(tmp_path / "managed"), embedder)
    count = service.generate_missing_embeddings(document.document_id, batch_size=2)

    assert count == 3
    assert len(embedder.inputs) == 3
    assert [len(batch[1]) for batch in repo.saved_embeddings] == [2, 1]
    assert all(row.vector == [0.125] * EMBEDDING_DIMENSIONS for _, batch in repo.saved_embeddings for row in batch)


def test_storage_service_search_uses_query_embedding(tmp_path):
    repo = FakeRepository()
    embedder = FakeEmbedder()
    repo.hits = [SimilarityHit(
        chunk_id="chunk-1", document_id="doc-1", title="Title", source_filename="p.pdf",
        text="AI", context_prefix="Section: AI", page_start=2, page_end=2,
        section_path=["AI"], cosine_distance=0.1,
    )]
    service = RAGStorageService(repo, ManagedAssetStore(tmp_path / "managed"), embedder)
    hits = service.search_similar("user-1", "what is AI?", limit=1)
    assert len(hits) == 1 and hits[0].similarity_score == pytest.approx(0.9)
    assert embedder.inputs == ["what is AI?"]


def test_storage_service_rejects_embedding_dimension_mismatch(tmp_path):
    repo = FakeRepository()
    embedder = FakeEmbedder()
    embedder.dimensions = 768
    service = RAGStorageService(repo, ManagedAssetStore(tmp_path / "managed"), embedder)
    with pytest.raises(ValueError, match="schema uses 1536 dimensions"):
        service.generate_missing_embeddings("doc-id")


def test_similarity_hit_score_is_one_minus_cosine_distance():
    hit = SimilarityHit(
        chunk_id="c", document_id="d", title=None, source_filename="paper.pdf",
        text="x", context_prefix="", page_start=None, page_end=None,
        section_path=[], cosine_distance=0.25,
    )
    assert hit.similarity_score == pytest.approx(0.75)


def test_vector_model_schema_is_available_when_pgvector_is_installed():
    pytest.importorskip("pgvector")
    from rag.db_models import Base, RAGChunkEmbedding

    assert "rag_documents" in Base.metadata.tables
    assert "rag_document_blocks" in Base.metadata.tables
    assert "rag_document_assets" in Base.metadata.tables
    assert "rag_document_chunks" in Base.metadata.tables
    assert "rag_chunk_source_blocks" in Base.metadata.tables
    assert RAGChunkEmbedding.__table__.c.embedding.type.dim == EMBEDDING_DIMENSIONS


def test_the_same_pdf_is_stored_separately_for_each_user(tmp_path):
    pdf_path, _, document, chunk = make_fixture(tmp_path)
    repo = FakeRepository()
    service = RAGStorageService(repo, ManagedAssetStore(tmp_path / "managed"))

    first = service.persist_document("user-1", pdf_path, document, [chunk])
    second = service.persist_document("user-2", pdf_path, document, [chunk])
    again = service.persist_document("user-1", pdf_path, document, [chunk])

    assert first.already_exists is False
    assert second.already_exists is False
    assert again.already_exists is True
    assert [entry[0] for entry in repo.persisted] == ["user-1", "user-2"]


def test_search_passes_the_user_and_document_scope_through(tmp_path):
    repo = FakeRepository()
    service = RAGStorageService(repo, ManagedAssetStore(tmp_path / "managed"), FakeEmbedder())

    service.search_similar("user-1", "what is AI?", limit=3, document_id="doc-9")

    assert repo.last_search == ("user-1", "doc-9", 3)
