"""Ingest a research PDF into PostgreSQL and optionally embed its chunks.

Run from backend/ with:
    python -m scripts.ingest_research_pdf path/to/paper.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rag.chunking import StructureAwareChunker
from rag.document_ingestion import PDFIngestionService
from rag.storage_service import RAGStorageService


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist a research PDF for EduGen AI RAG.")
    parser.add_argument("pdf", type=Path, help="Path to the source research-paper PDF")
    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Persist canonical content only; skip calls to the Gemini embedding API.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Number of chunk vectors to commit per batch (default: 8).",
    )
    args = parser.parse_args()

    document = PDFIngestionService().ingest(args.pdf)
    chunks = StructureAwareChunker().chunk(document)
    storage = RAGStorageService.from_env()
    result = storage.persist_document(args.pdf, document, chunks)

    print("Document ID:", result.document_id)
    print("Source SHA-256:", result.source_sha256)
    print("Already stored:", result.already_exists)
    print("Normalized blocks:", result.block_count)
    print("Chunks:", result.chunk_count)
    print("Assets stored this run:", result.asset_count)
    for warning in result.warnings:
        print("Warning:", warning)

    if not args.no_embeddings:
        embedded = storage.generate_missing_embeddings(
            result.document_id, batch_size=args.batch_size
        )
        print("New embeddings stored:", embedded)
    else:
        print("Embedding generation skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
