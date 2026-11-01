"""Structure-aware chunking for normalized PDF documents.

This module intentionally has no database, embedding, or LLM dependency. The
built-in token counter is a deterministic estimate (approximately four UTF-8
bytes per token), not an exact tokenizer for any particular embedding model.
A model-specific counter can be introduced later without changing the chunk
schema or the source-traceability contract.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, uuid5

from rag.chunk_schema import CanonicalChunk, ChunkSourceReference, ChunkingSummary
from rag.document_schema import DocumentBlock, NormalizedDocument


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'“‘([{A-Z0-9])")
_WORD_SPAN = re.compile(r"\S+\s*", re.UNICODE)


@dataclass(frozen=True)
class ChunkingConfig:
    """Tunable chunk-size policy; values are estimates, not exact model tokens."""

    target_chunk_tokens: int = 500
    max_chunk_tokens: int = 800
    overlap_tokens: int = 75
    min_chunk_tokens: int = 100

    def __post_init__(self) -> None:
        if self.target_chunk_tokens < 1:
            raise ValueError("target_chunk_tokens must be at least 1")
        if self.max_chunk_tokens < self.target_chunk_tokens:
            raise ValueError("max_chunk_tokens must be >= target_chunk_tokens")
        if self.overlap_tokens < 0:
            raise ValueError("overlap_tokens cannot be negative")
        if self.overlap_tokens >= self.max_chunk_tokens:
            raise ValueError("overlap_tokens must be smaller than max_chunk_tokens")
        if self.min_chunk_tokens < 0:
            raise ValueError("min_chunk_tokens cannot be negative")
        if self.min_chunk_tokens > self.max_chunk_tokens:
            raise ValueError("min_chunk_tokens must be <= max_chunk_tokens")


@dataclass
class _Draft:
    section_path: tuple[str, ...]
    parts: list[tuple[str, str]] = field(default_factory=list)
    blocks: list[DocumentBlock] = field(default_factory=list)

    @property
    def text(self) -> str:
        rendered: list[str] = []
        previous_type: str | None = None
        for value, block_type in self.parts:
            if not value:
                continue
            if rendered:
                separator = "\n" if previous_type == block_type == "list_item" else "\n\n"
                rendered.append(separator)
            rendered.append(value)
            previous_type = block_type
        return "".join(rendered).strip()

    @property
    def token_count(self) -> int:
        return estimate_tokens(self.text)

    def add_block(self, block: DocumentBlock, text: str | None = None) -> None:
        if all(existing.block_id != block.block_id for existing in self.blocks):
            self.blocks.append(block)
        value = _content_text(block) if text is None else text
        if value.strip():
            self.parts.append((value.strip(), block.block_type))


class StructureAwareChunker:
    """Create canonical chunks from ``NormalizedDocument`` blocks."""

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    def chunk(self, document: NormalizedDocument) -> list[CanonicalChunk]:
        """Chunk a normalized document while retaining structure and provenance."""
        if not document.blocks:
            return []

        drafts: list[_Draft] = []
        current: _Draft | None = None
        pending_context_blocks: list[DocumentBlock] = []
        ordered = sorted(document.blocks, key=lambda block: block.ordinal)

        def emit_current() -> None:
            nonlocal current
            if current is not None and current.blocks:
                drafts.append(current)
            current = None

        def add_pending_to(draft: _Draft, next_path: tuple[str, ...]) -> None:
            nonlocal pending_context_blocks
            retained: list[DocumentBlock] = []
            for block in pending_context_blocks:
                pending_path = tuple(block.section_path)
                if not pending_path or _is_prefix(pending_path, next_path):
                    draft.add_block(block, text="")
                else:
                    retained.append(block)
            pending_context_blocks = retained

        for block in ordered:
            # Document metadata is stored on NormalizedDocument and is useful as
            # context (for example, the title), but author/affiliation lines should
            # not become their own retrieval chunks or alter section grouping.
            if block.is_document_metadata:
                continue

            section_path = tuple(block.section_path)

            # Headings are represented as section context, but kept as source
            # references so no source element disappears from the canonical index.
            if block.block_type in {"heading"}:
                emit_current()
                pending_context_blocks.append(block)
                continue

            text = _content_text(block)
            is_structural_only = not text.strip() and block.block_type in {
                "figure",
                "table",
                "equation",
            }

            if current is not None and current.section_path != section_path:
                emit_current()

            if is_structural_only:
                if current is None:
                    current = _Draft(section_path=section_path)
                    add_pending_to(current, section_path)
                current.add_block(block, text="")
                continue

            if not text.strip():
                # Empty, non-structural blocks are not useful retrieval content.
                # Keep headings separately; do not manufacture text for other items.
                continue

            segments = _split_oversized_text(
                text,
                max_tokens=self.config.max_chunk_tokens,
                overlap_tokens=self.config.overlap_tokens,
            )
            for segment_index, segment in enumerate(segments):
                # Split segments must stay in separate chunks so the configured
                # overlap is deliberate and easy to reason about.
                if segment_index > 0:
                    emit_current()
                if current is not None:
                    combined = _join_text(current.text, segment, block.block_type)
                    combined_count = estimate_tokens(combined)
                    should_flush = combined_count > self.config.max_chunk_tokens
                    if (
                        combined_count > self.config.target_chunk_tokens
                        and current.token_count >= self.config.min_chunk_tokens
                    ):
                        should_flush = True
                    if should_flush:
                        emit_current()

                if current is None:
                    current = _Draft(section_path=section_path)
                    add_pending_to(current, section_path)
                current.add_block(block, text=segment)

        emit_current()

        # Preserve a trailing heading that has no following content as a
        # structural-only chunk, rather than silently dropping the source block.
        if pending_context_blocks:
            last = pending_context_blocks[-1]
            trailing_path = tuple(last.section_path)
            structural = _Draft(section_path=trailing_path)
            for block in pending_context_blocks:
                structural.add_block(block, text="")
            # Headings themselves are represented by context_prefix below. A
            # text fallback also keeps terminal headings searchable on their own.
            if not structural.text:
                heading_text = "\n".join(
                    b.text.strip() for b in pending_context_blocks if b.text.strip()
                )
                if heading_text:
                    structural.parts.append((heading_text, "heading"))
            drafts.append(structural)

        return self._materialize(document, drafts)

    def summarize(self, document: NormalizedDocument, chunks: list[CanonicalChunk] | None = None) -> ChunkingSummary:
        """Return counts without forcing callers to recompute chunk metrics."""
        resolved = chunks if chunks is not None else self.chunk(document)
        return ChunkingSummary(
            document_id=document.document_id,
            chunk_count=len(resolved),
            chunks_with_text=sum(bool(chunk.text.strip()) for chunk in resolved),
            structural_only_chunks=sum(not chunk.text.strip() for chunk in resolved),
        )

    def _materialize(
        self, document: NormalizedDocument, drafts: list[_Draft]
    ) -> list[CanonicalChunk]:
        staged: list[dict[str, object]] = []
        for sequence_index, draft in enumerate(drafts):
            refs = _unique_source_refs(draft.blocks)
            text = draft.text
            source_ordinals = ",".join(str(ref.ordinal) for ref in refs)
            content_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            identity = (
                f"edugen-chunk:{document.document_id}:{sequence_index}:"
                f"{source_ordinals}:{content_digest}"
            )
            chunk_id = str(uuid5(NAMESPACE_URL, identity))
            pages = [ref.page_number for ref in refs if ref.page_number is not None]
            section_path = list(draft.section_path)
            section_id = (
                str(uuid5(NAMESPACE_URL, f"edugen-section:{document.document_id}:" + "\x1f".join(section_path)))
                if section_path
                else None
            )
            context_items = []
            if document.title:
                context_items.append(f"Document: {document.title}")
            if section_path:
                context_items.append("Section: " + " > ".join(section_path))

            related_refs = [
                ref for ref in refs if ref.block_type in {"figure", "table", "equation", "caption"}
            ]
            image_paths = list(
                dict.fromkeys(
                    ref.image_asset_path
                    for ref in refs
                    if ref.image_available is True and ref.image_asset_path
                )
            )
            staged.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": document.document_id,
                    "sequence_index": sequence_index,
                    "text": text,
                    "token_count_estimate": estimate_tokens(text),
                    "section_id": section_id,
                    "section_title": section_path[-1] if section_path else None,
                    "section_path": section_path,
                    "page_start": min(pages) if pages else None,
                    "page_end": max(pages) if pages else None,
                    "source_refs": refs,
                    "related_element_ids": [ref.block_id for ref in related_refs],
                    "image_asset_paths": image_paths,
                    "context_prefix": "\n".join(context_items),
                    "previous_chunk_id": None,
                    "next_chunk_id": None,
                }
            )

        chunks: list[CanonicalChunk] = []
        for index, values in enumerate(staged):
            values["previous_chunk_id"] = staged[index - 1]["chunk_id"] if index > 0 else None
            values["next_chunk_id"] = staged[index + 1]["chunk_id"] if index + 1 < len(staged) else None
            chunks.append(CanonicalChunk.model_validate(values))
        return chunks


def estimate_tokens(text: str) -> int:
    """Return a deterministic rough token estimate, not a model tokenizer count."""
    if not text:
        return 0
    byte_count = len(text.encode("utf-8"))
    return max(1, math.ceil(byte_count / 4))


def _content_text(block: DocumentBlock) -> str:
    text = (block.text or "").strip()
    caption = (block.caption or "").strip()
    if block.block_type == "figure":
        # Captions are source text and can aid retrieval; never invent a visual description.
        if caption and caption not in text:
            return caption
        return text
    if block.block_type == "table" and caption and caption not in text:
        return f"Table caption: {caption}\n{text}".strip()
    return text


def _is_prefix(prefix: tuple[str, ...], value: tuple[str, ...]) -> bool:
    return len(prefix) <= len(value) and value[: len(prefix)] == prefix


def _join_text(current: str, incoming: str, incoming_type: str) -> str:
    if not current:
        return incoming
    if incoming_type == "list_item" and current.rstrip().endswith(("\n", "-", "•")):
        return current + incoming
    return current + ("\n" if incoming_type == "list_item" else "\n\n") + incoming


def _unique_source_refs(blocks: list[DocumentBlock]) -> list[ChunkSourceReference]:
    seen: set[str] = set()
    refs: list[ChunkSourceReference] = []
    for block in sorted(blocks, key=lambda item: item.ordinal):
        if block.block_id in seen:
            continue
        seen.add(block.block_id)
        refs.append(
            ChunkSourceReference(
                block_id=block.block_id,
                ordinal=block.ordinal,
                block_type=block.block_type,
                source_label=block.source_label,
                page_number=block.page_number,
                caption=block.caption,
                image_asset_path=block.image_asset_path,
                image_available=block.image_available,
            )
        )
    return refs


def _split_oversized_text(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Split oversized text by sentences first, then whitespace spans if needed.

    Overlap is added only to these split segments, not every ordinary chunk
    boundary. This avoids needless duplicate text for short, paragraph-aligned
    chunks. The character-based estimator makes this bounded and deterministic.
    """
    if estimate_tokens(text) <= max_tokens:
        return [text.strip()]

    later_budget = max(1, max_tokens - overlap_tokens)
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(text.strip()) if part.strip()]
    if not sentences:
        sentences = [text.strip()]

    raw_pieces: list[str] = []
    current = ""
    for sentence in sentences:
        budget = max_tokens if not raw_pieces else later_budget
        candidate = _join_text(current, sentence, "paragraph") if current else sentence
        if estimate_tokens(candidate) <= budget:
            current = candidate
            continue
        if current:
            raw_pieces.append(current)
            current = ""
            budget = later_budget
        if estimate_tokens(sentence) <= budget:
            current = sentence
            continue
        # Very long single sentence: split on whitespace, preserving word text.
        spans = _split_by_words(sentence, budget)
        if spans:
            raw_pieces.extend(spans[:-1])
            current = spans[-1]

    if current:
        raw_pieces.append(current)
    if len(raw_pieces) <= 1:
        # Defensive fallback for pathological text with no useful separators.
        raw_pieces = _split_by_words(text.strip(), max_tokens)

    if overlap_tokens <= 0 or len(raw_pieces) <= 1:
        return raw_pieces

    overlapped: list[str] = [raw_pieces[0]]
    for piece in raw_pieces[1:]:
        prefix = _suffix_for_overlap(overlapped[-1], overlap_tokens)
        candidate = f"{prefix}\n{piece}" if prefix else piece
        # Keep the estimate within the configured cap without trimming source
        # content: shorten only the duplicated prefix when rounding pushes it over.
        while prefix and estimate_tokens(candidate) > max_tokens:
            prefix = prefix[1:]
            candidate = f"{prefix}\n{piece}" if prefix else piece
        overlapped.append(candidate)
    return overlapped


def _split_by_words(text: str, token_budget: int) -> list[str]:
    spans = _WORD_SPAN.findall(text)
    pieces: list[str] = []
    current = ""
    for span in spans:
        if not current:
            if estimate_tokens(span) <= token_budget:
                current = span
            else:
                # A single pathological span (for example a minified URL or a
                # long unbroken identifier) must also respect the configured cap.
                broken = _split_by_characters(span, token_budget)
                pieces.extend(broken[:-1])
                current = broken[-1]
            continue

        candidate = current + span
        if estimate_tokens(candidate) <= token_budget:
            current = candidate
            continue

        pieces.append(current.rstrip())
        if estimate_tokens(span) <= token_budget:
            current = span
        else:
            broken = _split_by_characters(span, token_budget)
            pieces.extend(broken[:-1])
            current = broken[-1]

    if current.strip():
        pieces.append(current.rstrip())
    return pieces


def _split_by_characters(text: str, token_budget: int) -> list[str]:
    max_bytes = max(4, token_budget * 4)
    pieces: list[str] = []
    current = ""
    for character in text:
        if current and len((current + character).encode("utf-8")) > max_bytes:
            pieces.append(current)
            current = character
        else:
            current += character
    if current:
        pieces.append(current)
    return pieces


def _suffix_for_overlap(text: str, overlap_tokens: int) -> str:
    max_bytes = max(0, overlap_tokens * 4 - 2)
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    suffix = encoded[-max_bytes:].decode("utf-8", errors="ignore") if max_bytes else ""
    # Prefer a word boundary where one exists, but retain characters for languages
    # whose word spacing differs from English.
    first_space = suffix.find(" ")
    if first_space >= 0 and first_space < min(32, len(suffix) // 2):
        suffix = suffix[first_space + 1 :]
    return suffix.strip()
