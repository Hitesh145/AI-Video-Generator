"""Reads one PDF into the RAG store in reportable stages (parse, chunk, store; embed separately)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from papers.models import CHUNKING, EMBEDDING, PARSING, STORING
from rag.chunking import StructureAwareChunker
from rag.docling_parser import DoclingPDFParser
from rag.document_ingestion import PDFIngestionService

# (status, detail): the service turns the status into a human sentence.
StageReporter = Callable[[str, str | None], None]


class NoReadableText(ValueError):
    """The PDF parsed, but nothing in it could be read as text."""


@dataclass(frozen=True)
class IngestResult:
    document_id: str
    title: str | None
    page_count: int | None
    warnings: tuple[str, ...]


class Storage(Protocol):
    def persist_document(self, user_id, pdf_path, document, chunks): ...

    def generate_missing_embeddings(self, document_id: str) -> int: ...


def _docling_service(work_dir: Path) -> PDFIngestionService:
    return PDFIngestionService(DoclingPDFParser(image_output_dir=work_dir / "figures"))


class PaperIngestor:
    def __init__(
        self,
        storage: Storage,
        parser_factory: Callable[[Path], PDFIngestionService] | None = None,
        chunker: StructureAwareChunker | None = None,
    ) -> None:
        self.storage = storage
        self.parser_factory = parser_factory or _docling_service
        self.chunker = chunker or StructureAwareChunker()

    def ingest(self, user_id: str, pdf_path: Path, work_dir: Path, on_stage: StageReporter) -> IngestResult:
        on_stage(PARSING, None)
        document = self.parser_factory(work_dir).ingest(pdf_path)

        on_stage(CHUNKING, None)
        chunks = self.chunker.chunk(document)
        if not any(chunk.text.strip() for chunk in chunks):
            raise NoReadableText(
                "No readable text was found in this PDF. It may be a scan; "
                "text recognition for scanned pages is not available yet."
            )

        on_stage(STORING, None)
        stored = self.storage.persist_document(user_id, pdf_path, document, chunks)
        return IngestResult(
            document_id=stored.document_id,
            title=document.title,
            page_count=document.page_count,
            warnings=tuple(stored.warnings),
        )

    def embed(self, document_id: str, on_stage: StageReporter) -> int:
        on_stage(EMBEDDING, None)
        return self.storage.generate_missing_embeddings(document_id)
