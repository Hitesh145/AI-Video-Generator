from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from rag.document_ingestion import (
    PDFIngestionService,
    PDFParsingError,
    PDFValidationError,
)
from rag.document_schema import NormalizedDocument
from rag.docling_parser import DoclingPDFParser


class StubParser:
    def __init__(self, document=None, error=None):
        self.document = document or NormalizedDocument(source_filename="old-name.pdf")
        self.error = error
        self.called_with = None

    def parse(self, pdf_path: Path) -> NormalizedDocument:
        self.called_with = pdf_path
        if self.error:
            raise self.error
        return self.document


def make_pdf(path: Path, content: bytes = b"%PDF-1.7\nexample") -> Path:
    path.write_bytes(content)
    return path


def test_ingestion_validates_pdf_and_returns_normalized_document(tmp_path):
    pdf_path = make_pdf(tmp_path / "paper.pdf")
    parser = StubParser()
    result = PDFIngestionService(parser).ingest(pdf_path)

    assert result.source_filename == "paper.pdf"
    assert parser.called_with == pdf_path.resolve()


def test_ingestion_rejects_non_pdf_extension(tmp_path):
    source = tmp_path / "paper.txt"
    source.write_text("not a PDF", encoding="utf-8")

    with pytest.raises(PDFValidationError, match="Only .pdf"):
        PDFIngestionService(StubParser()).ingest(source)


def test_ingestion_rejects_missing_pdf(tmp_path):
    with pytest.raises(PDFValidationError, match="does not exist"):
        PDFIngestionService(StubParser()).ingest(tmp_path / "missing.pdf")


def test_ingestion_rejects_invalid_pdf_header(tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"not actually a PDF")

    with pytest.raises(PDFValidationError, match="valid PDF header"):
        PDFIngestionService(StubParser()).ingest(source)


def test_ingestion_wraps_parser_failure(tmp_path):
    source = make_pdf(tmp_path / "paper.pdf")
    parser = StubParser(error=RuntimeError("parser failed"))

    with pytest.raises(PDFParsingError, match="parser failed"):
        PDFIngestionService(parser).ingest(source)


def test_docling_adapter_preserves_structure_and_page_references(
    tmp_path, monkeypatch
):
    source = make_pdf(tmp_path / "research.pdf")

    class Item:
        def __init__(self, label, text="", page_no=1, level=None):
            self.label = label
            self.text = text
            self.prov = [SimpleNamespace(page_no=page_no)]
            if level is not None:
                self.level = level

    class TableItem(Item):
        def export_to_markdown(self, doc=None):
            return "| A | B |\n|---|---|\n| 1 | 2 |"

    class PictureItem(Item):
        def caption_text(self, doc=None):
            return "Figure 1: System overview"

        def get_image(self, doc):
            return FakeImage()

    class FakeImage:
        def save(self, path, format=None):
            Path(path).write_bytes(b"fake-png")

    class FakeDocument:
        pages = {1: object(), 2: object()}

        def iterate_items(self):
            return iter(
                [
                    (Item("title", "A Research Paper", 1), 0),
                    (Item("section_header", "Methods", 1, level=1), 1),
                    (Item("paragraph", "We evaluated the method.", 1), 2),
                    (TableItem("table", "", 2), 2),
                    (PictureItem("picture", "", 2), 2),
                    (Item("formula", "x = y + 1", 2), 2),
                ]
            )

    fake_document = FakeDocument()

    class FakeConverter:
        def __init__(self, format_options=None):
            assert format_options is not None
            pdf_options = format_options["pdf"].pipeline_options
            assert pdf_options.generate_picture_images is True

        def convert(self, path):
            assert path == str(source)
            return SimpleNamespace(document=fake_document, errors=[])

    docling_module = types.ModuleType("docling")
    docling_module.__path__ = []
    datamodel_module = types.ModuleType("docling.datamodel")
    datamodel_module.__path__ = []
    base_models_module = types.ModuleType("docling.datamodel.base_models")
    base_models_module.InputFormat = SimpleNamespace(PDF="pdf")
    pipeline_options_module = types.ModuleType("docling.datamodel.pipeline_options")
    pipeline_options_module.PdfPipelineOptions = lambda **kwargs: SimpleNamespace(**kwargs)
    converter_module = types.ModuleType("docling.document_converter")
    converter_module.DocumentConverter = lambda **kwargs: FakeConverter(**kwargs)
    converter_module.PdfFormatOption = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "docling", docling_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel", datamodel_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", pipeline_options_module)
    monkeypatch.setitem(
        sys.modules, "docling.document_converter", converter_module
    )

    result = PDFIngestionService(DoclingPDFParser()).ingest(source)

    assert result.title == "A Research Paper"
    assert result.page_count == 2
    assert result.source_filename == "research.pdf"
    assert [block.block_type for block in result.blocks] == [
        "title",
        "heading",
        "paragraph",
        "table",
        "figure",
        "equation",
    ]
    assert result.blocks[2].page_number == 1
    assert result.blocks[2].section_path == ["Methods"]
    assert "| A | B |" in result.blocks[3].text
    assert result.blocks[4].caption == "Figure 1: System overview"
    assert result.blocks[4].image_available is True
    assert result.blocks[4].image_asset_path is not None
    assert Path(result.blocks[4].image_asset_path).read_bytes() == b"fake-png"
    assert result.blocks[5].text == "x = y + 1"


def test_empty_docling_result_returns_warning(tmp_path, monkeypatch):
    source = make_pdf(tmp_path / "empty.pdf")

    class FakeDocument:
        pages = {1: object()}

        def iterate_items(self):
            return iter([])

    class FakeConverter:
        def convert(self, path):
            return SimpleNamespace(document=FakeDocument(), errors=[])

    docling_module = types.ModuleType("docling")
    docling_module.__path__ = []
    datamodel_module = types.ModuleType("docling.datamodel")
    datamodel_module.__path__ = []
    base_models_module = types.ModuleType("docling.datamodel.base_models")
    base_models_module.InputFormat = SimpleNamespace(PDF="pdf")
    pipeline_options_module = types.ModuleType("docling.datamodel.pipeline_options")
    pipeline_options_module.PdfPipelineOptions = lambda **kwargs: SimpleNamespace(**kwargs)
    converter_module = types.ModuleType("docling.document_converter")
    converter_module.DocumentConverter = lambda **kwargs: FakeConverter()
    converter_module.PdfFormatOption = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "docling", docling_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel", datamodel_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", pipeline_options_module)
    monkeypatch.setitem(
        sys.modules, "docling.document_converter", converter_module
    )

    result = DoclingPDFParser().parse(source)

    assert result.blocks == []
    assert any("no content blocks" in warning for warning in result.warnings)


def test_figure_without_caption_or_image_is_preserved_with_status_and_warning():
    class PictureItem:
        label = "picture"
        text = ""
        prov = [SimpleNamespace(page_no=3)]

        def get_image(self, doc):
            return None

        def caption_text(self, doc=None):
            return None

    class FakeDocument:
        pages = {1: object(), 2: object(), 3: object()}

        def iterate_items(self):
            return iter([(PictureItem(), 1)])

    parser = DoclingPDFParser(image_output_dir=None)
    blocks, title, warnings = parser._normalize_items(
        FakeDocument(), image_output_dir=Path("unused-assets"), file_stem="paper"
    )

    assert title is None
    assert len(blocks) == 1
    assert blocks[0].block_type == "figure"
    assert blocks[0].text == ""
    assert blocks[0].caption is None
    assert blocks[0].image_available is False
    assert blocks[0].image_asset_path is None
    assert blocks[0].page_number == 3
    assert any("no image asset available" in warning for warning in warnings)


def test_non_figure_blocks_have_no_image_availability_value():
    from rag.document_schema import DocumentBlock

    block = DocumentBlock(
        ordinal=0, block_type="paragraph", source_label="text", text="Hello"
    )

    assert block.image_asset_path is None
    assert block.image_available is None


def test_title_author_affiliation_cluster_is_metadata_not_section_hierarchy(
    tmp_path, monkeypatch
):
    source = make_pdf(tmp_path / "metadata-paper.pdf")

    class Item:
        def __init__(self, label, text="", page_no=1, level=None):
            self.label = label
            self.text = text
            self.prov = [SimpleNamespace(page_no=page_no)]
            if level is not None:
                self.level = level

    class FakeDocument:
        pages = {1: object(), 2: object()}

        def iterate_items(self):
            return iter(
                [
                    (Item("section_header", "ADVANCED METHODS FOR DATA PIPELINES", 1, 1), 1),
                    (Item("paragraph", "This genuine section heading must remain a heading.", 1), 2),
                    (Item("section_header", "A GENERAL TITLE FOR A RESEARCH PAPER", 1, 1), 1),
                    (Item("paragraph", "Dr. Alex Rivera", 1), 2),
                    (Item("section_header", "Department of Computer Science, Example University", 1, 1), 1),
                    (Item("section_header", "Methods", 2, 1), 1),
                    (Item("paragraph", "The methods section begins here.", 2), 2),
                ]
            )

    fake_document = FakeDocument()

    class FakeConverter:
        def __init__(self, format_options=None):
            assert format_options is not None

        def convert(self, path):
            assert path == str(source)
            return SimpleNamespace(document=fake_document, errors=[])

    docling_module = types.ModuleType("docling")
    docling_module.__path__ = []
    datamodel_module = types.ModuleType("docling.datamodel")
    datamodel_module.__path__ = []
    base_models_module = types.ModuleType("docling.datamodel.base_models")
    base_models_module.InputFormat = SimpleNamespace(PDF="pdf")
    pipeline_options_module = types.ModuleType("docling.datamodel.pipeline_options")
    pipeline_options_module.PdfPipelineOptions = lambda **kwargs: SimpleNamespace(**kwargs)
    converter_module = types.ModuleType("docling.document_converter")
    converter_module.DocumentConverter = lambda **kwargs: FakeConverter(**kwargs)
    converter_module.PdfFormatOption = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "docling", docling_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel", datamodel_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", pipeline_options_module)
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter_module)

    result = DoclingPDFParser().parse(source)

    assert result.title == "A GENERAL TITLE FOR A RESEARCH PAPER"
    assert result.authors == ["Dr. Alex Rivera"]
    assert result.affiliations == ["Department of Computer Science, Example University"]

    genuine_heading = next(
        block for block in result.blocks if block.text == "ADVANCED METHODS FOR DATA PIPELINES"
    )
    title_block = next(
        block for block in result.blocks if block.text == result.title
    )
    author_block = next(
        block for block in result.blocks if block.text == "Dr. Alex Rivera"
    )
    affiliation_block = next(
        block for block in result.blocks if block.text == result.affiliations[0]
    )
    methods_body = next(
        block for block in result.blocks if block.text == "The methods section begins here."
    )

    assert genuine_heading.block_type == "heading"
    assert genuine_heading.is_document_metadata is False
    assert title_block.block_type == "title"
    assert title_block.is_document_metadata is True
    assert author_block.is_document_metadata is True
    assert affiliation_block.block_type == "other"
    assert affiliation_block.is_document_metadata is True
    assert methods_body.section_path == ["Methods"]
