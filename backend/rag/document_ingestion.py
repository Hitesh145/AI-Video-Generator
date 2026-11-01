"""Validated PDF ingestion entry point for the RAG pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from rag.document_schema import NormalizedDocument
from rag.docling_parser import DoclingPDFParser


class PDFIngestionError(ValueError):
    """Base error for a PDF that cannot be ingested."""


class PDFValidationError(PDFIngestionError):
    """Raised when the provided path is not a readable PDF."""


class PDFParsingError(PDFIngestionError):
    """Raised when the parser cannot convert a valid PDF."""


class PDFParser(Protocol):
    def parse(self, pdf_path: Path) -> NormalizedDocument:
        """Parse and normalize a validated PDF."""
        ...


class PDFIngestionService:
    """Validate a PDF and delegate extraction to a replaceable parser."""

    def __init__(self, parser: PDFParser | None = None) -> None:
        self._parser = parser or DoclingPDFParser()

    def ingest(self, source: str | Path) -> NormalizedDocument:
        pdf_path = self._validate_pdf_path(source)

        try:
            document = self._parser.parse(pdf_path)
        except Exception as exc:
            if isinstance(exc, PDFIngestionError):
                raise
            raise PDFParsingError(
                f"Could not parse '{pdf_path.name}': {exc}"
            ) from exc

        if document.source_filename != pdf_path.name:
            document = document.model_copy(update={"source_filename": pdf_path.name})
        return document

    @staticmethod
    def _validate_pdf_path(source: str | Path) -> Path:
        try:
            path = Path(source).expanduser()
        except (TypeError, ValueError) as exc:
            raise PDFValidationError(
                "PDF source must be a valid filesystem path."
            ) from exc

        if path.suffix.casefold() != ".pdf":
            raise PDFValidationError("Only .pdf files are accepted.")
        if not path.exists():
            raise PDFValidationError(f"PDF file does not exist: {path}")
        if not path.is_file():
            raise PDFValidationError(f"PDF path is not a file: {path}")

        try:
            with path.open("rb") as handle:
                header = handle.read(1024)
        except OSError as exc:
            raise PDFValidationError(f"PDF file cannot be read: {path}") from exc

        if b"%PDF-" not in header:
            raise PDFValidationError(
                f"File does not have a valid PDF header: {path.name}"
            )
        return path.resolve()
