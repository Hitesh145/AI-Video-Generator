"""A paper that Docling only partly read must fail loudly, never be stored as if it were complete."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from rag.docling_parser import DoclingPDFParser, find_unread_pages


class Item:
    def __init__(self, label, text, page_no):
        self.label = label
        self.text = text
        self.prov = [SimpleNamespace(page_no=page_no)]


def install_fake_docling(monkeypatch, items, *, errors=(), status="success"):
    class FakeDocument:
        pages = {1: object(), 2: object()}

        def iterate_items(self):
            return iter([(item, 1) for item in items])

    class FakeConverter:
        def __init__(self, format_options=None):
            pass

        def convert(self, path):
            return SimpleNamespace(document=FakeDocument(), errors=list(errors), status=status)

    modules = {
        "docling": types.ModuleType("docling"),
        "docling.datamodel": types.ModuleType("docling.datamodel"),
        "docling.datamodel.base_models": types.ModuleType("docling.datamodel.base_models"),
        "docling.datamodel.pipeline_options": types.ModuleType("docling.datamodel.pipeline_options"),
        "docling.document_converter": types.ModuleType("docling.document_converter"),
    }
    modules["docling"].__path__ = []
    modules["docling.datamodel"].__path__ = []
    modules["docling.datamodel.base_models"].InputFormat = SimpleNamespace(PDF="pdf")
    modules["docling.datamodel.pipeline_options"].PdfPipelineOptions = lambda **kw: SimpleNamespace(**kw)
    modules["docling.document_converter"].DocumentConverter = lambda **kw: FakeConverter(**kw)
    modules["docling.document_converter"].PdfFormatOption = lambda **kw: SimpleNamespace(**kw)
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.7\nexample")
    return path


PAGE_TEXT = "word " * 400   # about 1600 letters on a page


def both_pages():
    return [Item("paragraph", PAGE_TEXT, 1), Item("paragraph", PAGE_TEXT, 2)]


def test_a_conversion_with_errors_is_refused_not_stored(tmp_path, monkeypatch):
    error = SimpleNamespace(error_message="bad allocation")
    install_fake_docling(monkeypatch, both_pages(), errors=[error], status="partial_success")

    with pytest.raises(RuntimeError) as raised:
        DoclingPDFParser(text_layer_reader=lambda path: None).parse(pdf(tmp_path))

    assert "could not be read completely" in str(raised.value)
    assert "bad allocation" in str(raised.value)


def test_a_partial_success_status_without_error_messages_is_refused(tmp_path, monkeypatch):
    install_fake_docling(monkeypatch, both_pages(), status="partial_success")

    with pytest.raises(RuntimeError, match="could not be read completely"):
        DoclingPDFParser(text_layer_reader=lambda path: None).parse(pdf(tmp_path))


def test_a_page_whose_text_was_lost_is_refused_and_named(tmp_path, monkeypatch):
    # The PDF itself has text on both pages, but Docling returned nothing for page 2 and reported no error.
    install_fake_docling(monkeypatch, [Item("paragraph", PAGE_TEXT, 1)])

    with pytest.raises(RuntimeError) as raised:
        DoclingPDFParser(text_layer_reader=lambda path: {1: 1600, 2: 1600}).parse(pdf(tmp_path))

    assert "could not be read completely" in str(raised.value)
    assert "page 2" in str(raised.value)


def test_a_complete_conversion_passes(tmp_path, monkeypatch):
    install_fake_docling(monkeypatch, both_pages())

    document = DoclingPDFParser(text_layer_reader=lambda path: {1: 1600, 2: 1600}).parse(pdf(tmp_path))

    assert len(document.blocks) == 2


def test_find_unread_pages_ignores_pages_with_little_text_and_pages_that_are_mostly_read():
    layer = {1: 2000, 2: 2000, 3: 100, 4: 0, 5: 600}
    extracted = {1: 1900, 2: 100, 3: 0, 5: 250}      # 2: lost; 3, 4: too little text to judge; 5: figure labels, 42%

    assert find_unread_pages(layer, extracted) == [2]


def test_find_unread_pages_flags_a_page_with_no_extracted_text_at_all():
    assert find_unread_pages({1: 1500}, {}) == [1]
