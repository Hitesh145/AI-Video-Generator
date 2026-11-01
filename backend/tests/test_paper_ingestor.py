import pytest
from test_rag_storage import make_fixture

from papers.ingestor import NoReadableText, PaperIngestor
from rag.document_ingestion import PDFParsingError
from rag.storage_schema import PersistenceResult


class Stages:
    def __init__(self):
        self.calls: list[tuple[str, str | None]] = []

    def append_call(self, status, detail=None):
        self.calls.append((status, detail))

    @property
    def names(self):
        return [name for name, _ in self.calls]


class FakeStorage:
    document_id = "doc-1"

    def __init__(self):
        self.persisted = []
        self.embedded = []

    def persist_document(self, user_id, pdf_path, document, chunks):
        self.persisted.append((user_id, pdf_path, document, chunks))
        return PersistenceResult(
            document_id=self.document_id, source_sha256="s" * 64, already_exists=False,
            block_count=len(document.blocks), chunk_count=len(chunks), asset_count=1,
            warnings=("Figure 2 image unavailable",),
        )

    def generate_missing_embeddings(self, document_id):
        self.embedded.append(document_id)
        return 3


class FakeParser:
    def __init__(self, document, error=None):
        self.document, self.error = document, error

    def ingest(self, pdf_path):
        if self.error:
            raise self.error
        return self.document


class FakeChunker:
    def __init__(self, chunks):
        self.chunks = chunks

    def chunk(self, document):
        return list(self.chunks)


@pytest.fixture
def parts(tmp_path):
    pdf_path, _, document, chunk = make_fixture(tmp_path)
    storage, stages = FakeStorage(), Stages()
    factory_calls = []

    def make(parser=None, chunks=None):
        def parser_factory(work_dir):
            factory_calls.append(work_dir)
            return parser or FakeParser(document)

        return PaperIngestor(storage, parser_factory=parser_factory, chunker=FakeChunker([chunk] if chunks is None else chunks))

    return make, storage, stages, pdf_path, document, chunk, factory_calls


def test_ingest_reports_the_stages_in_order_and_returns_the_ids(parts, tmp_path):
    make, storage, stages, pdf_path, *_ = parts

    result = make().ingest("user-1", pdf_path, tmp_path / "work", stages.append_call)

    assert stages.names == ["parsing", "chunking", "storing"]
    assert result.document_id == "doc-1"
    assert (result.title, result.page_count) == ("Test paper", 1)
    assert result.warnings == ("Figure 2 image unavailable",)


def test_the_parser_gets_a_work_directory_for_figure_images(parts, tmp_path):
    make, _, stages, pdf_path, _, _, factory_calls = parts

    make().ingest("user-1", pdf_path, tmp_path / "work", stages.append_call)

    assert factory_calls == [tmp_path / "work"]


def test_storage_receives_the_owner_and_the_chunks(parts, tmp_path):
    make, storage, stages, pdf_path, document, chunk, _ = parts

    make().ingest("user-1", pdf_path, tmp_path / "work", stages.append_call)

    user_id, stored_path, stored_document, stored_chunks = storage.persisted[0]
    assert (user_id, stored_path, stored_document) == ("user-1", pdf_path, document)
    assert stored_chunks == [chunk]


def test_embed_reports_embedding_and_returns_the_count(parts):
    make, storage, stages, *_ = parts

    assert make().embed("doc-1", stages.append_call) == 3

    assert stages.names == ["embedding"]
    assert storage.embedded == ["doc-1"]


def test_a_parser_failure_propagates_after_reporting_parsing_only(parts, tmp_path):
    make, storage, stages, pdf_path, *_ = parts
    ingestor = make(parser=FakeParser(None, error=PDFParsingError("Could not parse 'a.pdf': broken")))

    with pytest.raises(PDFParsingError):
        ingestor.ingest("user-1", pdf_path, tmp_path / "work", stages.append_call)

    assert stages.names == ["parsing"]
    assert storage.persisted == []


def test_a_pdf_without_readable_text_fails_before_anything_is_stored(parts, tmp_path):
    make, storage, stages, pdf_path, _, chunk, _ = parts
    empty = chunk.model_copy(update={"text": "   "})

    with pytest.raises(NoReadableText, match="scan"):
        make(chunks=[empty]).ingest("user-1", pdf_path, tmp_path / "work", stages.append_call)
    with pytest.raises(NoReadableText):
        make(chunks=[]).ingest("user-1", pdf_path, tmp_path / "work", stages.append_call)

    assert storage.persisted == []
