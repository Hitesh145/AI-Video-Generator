"""Store a paper once for evaluation: parse and embed it only if it is not already there."""

from __future__ import annotations

from pathlib import Path

from rag.asset_store import sha256_file
from rag.storage_config import embedding_model_from_env


def _ignore_stage(status: str, detail: str | None = None) -> None:
    pass


def ensure_paper(pdf_path: Path, user_id: str, storage, ingestor, work_dir: Path) -> str:
    """Return the stored document id, reading the PDF only if this user has not stored it yet.

    A paper that is already stored is not parsed again; if an earlier run died while embedding,
    only the missing embeddings are made (a stored, fully embedded paper costs nothing).
    """
    digest = sha256_file(pdf_path)
    existing = storage.repository.find_document_by_sha256(user_id, digest)
    if existing:
        provider = getattr(storage, "embedding_provider", None)
        model_name = provider.model_name if provider is not None else embedding_model_from_env()
        if storage.repository.chunks_missing_embeddings(existing, model_name):
            ingestor.embed(existing, _ignore_stage)
        return existing

    result = ingestor.ingest(user_id, Path(pdf_path), Path(work_dir), _ignore_stage)
    ingestor.embed(result.document_id, _ignore_stage)
    return result.document_id
