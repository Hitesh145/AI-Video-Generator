from __future__ import annotations

from rag.chunking import ChunkingConfig, StructureAwareChunker, estimate_tokens
from rag.document_schema import DocumentBlock, NormalizedDocument


def block(
    ordinal: int,
    block_type: str,
    text: str = "",
    *,
    section_path: list[str] | None = None,
    page: int | None = 1,
    caption: str | None = None,
    image_asset_path: str | None = None,
    image_available: bool | None = None,
    is_document_metadata: bool = False,
    block_id: str | None = None,
) -> DocumentBlock:
    values = {
        "ordinal": ordinal,
        "block_type": block_type,
        "source_label": block_type,
        "text": text,
        "section_path": section_path or [],
        "page_number": page,
        "caption": caption,
        "image_asset_path": image_asset_path,
        "image_available": image_available,
        "is_document_metadata": is_document_metadata,
    }
    if block_id:
        values["block_id"] = block_id
    return DocumentBlock(**values)


def document(*blocks: DocumentBlock, document_id: str = "document-test") -> NormalizedDocument:
    return NormalizedDocument(
        document_id=document_id,
        source_filename="sample.pdf",
        title="A Sample Research Paper",
        page_count=5,
        blocks=list(blocks),
    )


def test_short_paragraphs_combine_and_keep_section_and_source_metadata():
    source = document(
        block(0, "heading", "Methodology", section_path=["Methodology"], block_id="heading-1"),
        block(1, "paragraph", "The first short paragraph explains the experimental setup.", section_path=["Methodology"], page=1, block_id="p-1"),
        block(2, "paragraph", "The second short paragraph describes the measurement procedure.", section_path=["Methodology"], page=2, block_id="p-2"),
    )

    chunks = StructureAwareChunker(
        ChunkingConfig(target_chunk_tokens=100, max_chunk_tokens=150, overlap_tokens=10, min_chunk_tokens=1)
    ).chunk(source)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert "experimental setup" in chunk.text
    assert "measurement procedure" in chunk.text
    assert chunk.section_path == ["Methodology"]
    assert chunk.section_title == "Methodology"
    assert chunk.page_start == 1
    assert chunk.page_end == 2
    assert {ref.block_id for ref in chunk.source_refs} == {"heading-1", "p-1", "p-2"}
    assert "Document: A Sample Research Paper" in chunk.retrieval_text
    assert "Section: Methodology" in chunk.retrieval_text


def test_section_boundary_starts_a_new_chunk():
    source = document(
        block(0, "paragraph", "Background facts are explained here.", section_path=["Background"], block_id="b-1"),
        block(1, "paragraph", "The method is explained separately here.", section_path=["Method"], block_id="m-1", page=2),
    )

    chunks = StructureAwareChunker(
        ChunkingConfig(target_chunk_tokens=200, max_chunk_tokens=250, overlap_tokens=10, min_chunk_tokens=1)
    ).chunk(source)

    assert len(chunks) == 2
    assert chunks[0].section_path == ["Background"]
    assert chunks[1].section_path == ["Method"]
    assert chunks[0].next_chunk_id == chunks[1].chunk_id
    assert chunks[1].previous_chunk_id == chunks[0].chunk_id
    assert chunks[0].previous_chunk_id is None
    assert chunks[1].next_chunk_id is None


def test_oversized_paragraph_splits_with_bounded_overlap_and_order():
    sentences = [
        f"Sentence {index:02d} records a distinct scientific observation for chunk ordering validation."
        for index in range(20)
    ]
    source_text = " ".join(sentences)
    source = document(
        block(0, "paragraph", source_text, section_path=["Results"], page=3, block_id="large-paragraph"),
    )
    chunker = StructureAwareChunker(
        ChunkingConfig(target_chunk_tokens=30, max_chunk_tokens=40, overlap_tokens=5, min_chunk_tokens=1)
    )

    chunks = chunker.chunk(source)

    assert len(chunks) > 1
    assert all(chunk.token_count_estimate <= 40 for chunk in chunks)
    assert [chunk.sequence_index for chunk in chunks] == list(range(len(chunks)))
    for index, sentence in enumerate(sentences):
        appearances = [chunk.text.find(sentence) for chunk in chunks]
        assert any(position >= 0 for position in appearances), f"Lost sentence: {sentence}"
    assert all(any(ref.block_id == "large-paragraph" for ref in chunk.source_refs) for chunk in chunks)
    assert all(chunks[i].next_chunk_id == chunks[i + 1].chunk_id for i in range(len(chunks) - 1))



def test_pathological_unbroken_text_still_respects_max_chunk_size():
    long_identifier = "R" * 2400
    source = document(
        block(0, "paragraph", long_identifier, section_path=["Appendix"], block_id="unbroken"),
    )
    chunks = StructureAwareChunker(
        ChunkingConfig(target_chunk_tokens=30, max_chunk_tokens=40, overlap_tokens=5, min_chunk_tokens=1)
    ).chunk(source)

    assert len(chunks) > 1
    assert all(chunk.token_count_estimate <= 40 for chunk in chunks)
    # Overlap is intentional, but the unbroken source token sequence remains represented.
    assert all(any(ref.block_id == "unbroken" for ref in chunk.source_refs) for chunk in chunks)
    assert "R" * 2400 in "".join(chunk.text for chunk in chunks)

def test_image_only_figure_is_preserved_as_a_structural_chunk():
    source = document(
        block(
            7,
            "figure",
            section_path=["Architecture"],
            page=4,
            image_asset_path="sample_assets/figure_7.png",
            image_available=True,
            block_id="fig-7",
        ),
    )

    chunks = StructureAwareChunker().chunk(source)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.text == ""
    assert chunk.token_count_estimate == 0
    assert chunk.related_element_ids == ["fig-7"]
    assert chunk.image_asset_paths == ["sample_assets/figure_7.png"]
    assert chunk.source_refs[0].image_available is True
    assert chunk.page_start == chunk.page_end == 4


def test_figure_is_attached_to_nearby_section_chunk():
    source = document(
        block(0, "paragraph", "The system contains several processing stages.", section_path=["Architecture"], page=1, block_id="p-before"),
        block(1, "figure", section_path=["Architecture"], page=1, image_asset_path="assets/figure.png", image_available=True, block_id="figure-1"),
        block(2, "paragraph", "These stages communicate through explicit interfaces.", section_path=["Architecture"], page=2, block_id="p-after"),
    )

    chunks = StructureAwareChunker(
        ChunkingConfig(target_chunk_tokens=200, max_chunk_tokens=250, overlap_tokens=10, min_chunk_tokens=1)
    ).chunk(source)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert "processing stages" in chunk.text
    assert "explicit interfaces" in chunk.text
    assert "figure-1" in chunk.related_element_ids
    assert chunk.image_asset_paths == ["assets/figure.png"]
    assert {ref.block_id for ref in chunk.source_refs} == {"p-before", "figure-1", "p-after"}


def test_table_caption_is_retained_in_searchable_text():
    source = document(
        block(
            0,
            "table",
            "| Model | Accuracy |\n|---|---|\n| A | 0.91 |",
            caption="Table 1. Model evaluation results",
            section_path=["Experiments"],
            page=3,
            block_id="table-1",
        ),
    )

    chunks = StructureAwareChunker().chunk(source)

    assert len(chunks) == 1
    assert "Table caption: Table 1. Model evaluation results" in chunks[0].text
    assert "0.91" in chunks[0].text
    assert "table-1" in chunks[0].related_element_ids


def test_ids_are_deterministic_for_the_same_normalized_document():
    source = document(
        block(0, "paragraph", "Stable text with stable source identity.", section_path=["Overview"], block_id="stable-block"),
    )
    chunker = StructureAwareChunker()

    first = chunker.chunk(source)
    second = chunker.chunk(source)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert first[0].chunk_id


def test_empty_document_produces_no_chunks():
    source = document()

    assert StructureAwareChunker().chunk(source) == []
    summary = StructureAwareChunker().summarize(source)
    assert summary.chunk_count == 0
    assert summary.structural_only_chunks == 0


def test_config_rejects_invalid_limits():
    try:
        ChunkingConfig(target_chunk_tokens=100, max_chunk_tokens=50)
    except ValueError as exc:
        assert "max_chunk_tokens" in str(exc)
    else:
        raise AssertionError("Expected invalid config to raise ValueError")


def test_chunk_summary_distinguishes_text_and_structural_chunks():
    source = document(
        block(0, "paragraph", "Some extractable text.", section_path=["Overview"], block_id="paragraph-1"),
        block(1, "figure", section_path=["Overview"], image_available=False, block_id="figure-1"),
    )
    chunker = StructureAwareChunker(
        ChunkingConfig(target_chunk_tokens=100, max_chunk_tokens=120, overlap_tokens=10, min_chunk_tokens=1)
    )
    chunks = chunker.chunk(source)
    summary = chunker.summarize(source, chunks)

    assert summary.chunk_count == len(chunks)
    assert summary.chunks_with_text == 1
    assert summary.structural_only_chunks == 0  # The figure is attached to the paragraph chunk.
    assert estimate_tokens("abcd") == 1


def test_document_metadata_does_not_become_retrieval_content_or_break_body_chunks():
    source = NormalizedDocument(
        document_id="metadata-test",
        source_filename="sample.pdf",
        title="A Long Research Paper Title",
        authors=["Dr. Alex Rivera"],
        affiliations=["Department of Computer Science, Example University"],
        blocks=[
            block(0, "paragraph", "The first part of the section explains the setup.", section_path=["Automation"], block_id="body-before"),
            block(1, "title", "A Long Research Paper Title", is_document_metadata=True, block_id="document-title"),
            block(2, "paragraph", "Dr. Alex Rivera", is_document_metadata=True, block_id="author-metadata"),
            block(3, "other", "Department of Computer Science, Example University", is_document_metadata=True, block_id="affiliation-metadata"),
            block(4, "paragraph", "The continuation explains the process.", section_path=["Automation"], block_id="body-after"),
        ],
    )

    chunks = StructureAwareChunker(
        ChunkingConfig(target_chunk_tokens=250, max_chunk_tokens=300, overlap_tokens=10, min_chunk_tokens=1)
    ).chunk(source)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert "first part of the section" in chunk.text
    assert "continuation explains the process" in chunk.text
    assert "Dr. Alex Rivera" not in chunk.text
    assert "Department of Computer Science" not in chunk.text
    assert "Document: A Long Research Paper Title" in chunk.context_prefix
    assert {ref.block_id for ref in chunk.source_refs} == {"body-before", "body-after"}
