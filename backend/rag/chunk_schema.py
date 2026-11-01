"""Project-owned models for structure-aware, source-traceable chunks."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from rag.document_schema import BlockType


class ChunkSourceReference(BaseModel):
    """Reference from a canonical chunk to one normalized source block."""

    block_id: str
    ordinal: int = Field(ge=0)
    block_type: BlockType
    source_label: str
    page_number: int | None = Field(default=None, ge=1)
    caption: str | None = None
    image_asset_path: str | None = None
    image_available: bool | None = None


class CanonicalChunk(BaseModel):
    """A retrieval-ready text unit with provenance back to its source blocks.

    ``text`` contains extracted source content only. ``context_prefix`` supplies
    document and section context for retrieval without modifying the source text.
    Structural-only chunks are allowed when a figure or heading has no text.
    """

    chunk_id: str
    document_id: str
    sequence_index: int = Field(ge=0)
    text: str = ""
    token_count_estimate: int = Field(ge=0)
    section_id: str | None = None
    section_title: str | None = None
    section_path: list[str] = Field(default_factory=list)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    source_refs: list[ChunkSourceReference] = Field(default_factory=list)
    related_element_ids: list[str] = Field(default_factory=list)
    image_asset_paths: list[str] = Field(default_factory=list)
    context_prefix: str = ""
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None

    @property
    def retrieval_text(self) -> str:
        """Text to embed/search, enriched with document and section context."""
        if self.context_prefix and self.text:
            return f"{self.context_prefix}\n\n{self.text}"
        return self.context_prefix or self.text


class ChunkingSummary(BaseModel):
    """Small deterministic summary useful for tests and ingestion diagnostics."""

    document_id: str
    chunk_count: int = Field(ge=0)
    chunks_with_text: int = Field(ge=0)
    structural_only_chunks: int = Field(ge=0)
    token_estimator: Literal["utf8_chars_approx_4_per_token"] = (
        "utf8_chars_approx_4_per_token"
    )
