import hashlib
import json
from types import SimpleNamespace

import pytest

from evaluation.fetch_papers import fetch
from evaluation.ingest import ensure_paper
from papers.ingestor import IngestResult

PDF_BYTES = b"%PDF-1.4\nhello evaluation paper\n%%EOF"
PDF_SHA = hashlib.sha256(PDF_BYTES).hexdigest()


class FakeRepository:
    def __init__(self):
        self.existing = {}
        self.missing = []

    def find_document_by_sha256(self, user_id, digest):
        return self.existing.get((user_id, digest))

    def chunks_missing_embeddings(self, document_id, model_name):
        return list(self.missing)


class FakeStorage:
    def __init__(self):
        self.repository = FakeRepository()
        self.embedding_provider = SimpleNamespace(model_name="test-model")


class FakeIngestor:
    def __init__(self):
        self.ingest_calls = 0
        self.embed_calls = 0

    def ingest(self, user_id, pdf_path, work_dir, on_stage):
        self.ingest_calls += 1
        return IngestResult(document_id="doc-1", title="T", page_count=1, warnings=())

    def embed(self, document_id, on_stage):
        self.embed_calls += 1
        return 1


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(PDF_BYTES)
    return path


def test_a_new_paper_is_parsed_stored_and_embedded_once(pdf, tmp_path):
    storage, ingestor = FakeStorage(), FakeIngestor()

    document_id = ensure_paper(pdf, "u", storage, ingestor, tmp_path / "work")

    assert document_id == "doc-1"
    assert (ingestor.ingest_calls, ingestor.embed_calls) == (1, 1)


def test_an_already_stored_paper_is_neither_parsed_nor_embedded_again(pdf, tmp_path):
    storage, ingestor = FakeStorage(), FakeIngestor()
    storage.repository.existing[("u", PDF_SHA)] = "doc-9"

    assert ensure_paper(pdf, "u", storage, ingestor, tmp_path / "work") == "doc-9"
    assert (ingestor.ingest_calls, ingestor.embed_calls) == (0, 0)


def test_a_stored_paper_with_missing_embeddings_is_finished_without_parsing_again(pdf, tmp_path):
    storage, ingestor = FakeStorage(), FakeIngestor()
    storage.repository.existing[("u", PDF_SHA)] = "doc-9"
    storage.repository.missing = ["chunk-1"]                     # an earlier run died while embedding

    assert ensure_paper(pdf, "u", storage, ingestor, tmp_path / "work") == "doc-9"
    assert (ingestor.ingest_calls, ingestor.embed_calls) == (0, 1)


def test_papers_are_stored_per_user(pdf, tmp_path):
    storage, ingestor = FakeStorage(), FakeIngestor()
    storage.repository.existing[("someone-else", PDF_SHA)] = "doc-9"

    assert ensure_paper(pdf, "u", storage, ingestor, tmp_path / "work") == "doc-1"
    assert ingestor.ingest_calls == 1


def write_manifest(tmp_path, entries):
    path = tmp_path / "papers.json"
    path.write_text(json.dumps({"papers": entries}), encoding="utf-8")
    return path


def entry(**extra):
    return {"key": "a", "title": "A paper", "url": "https://example.test/a.pdf", **extra}


def test_fetch_checks_the_pdf_header_size_and_pinned_hash(tmp_path):
    with pytest.raises(ValueError, match="hash"):
        fetch(write_manifest(tmp_path, [entry(sha256="0" * 64)]), tmp_path / "dest", download=lambda url: PDF_BYTES)
    with pytest.raises(ValueError, match="PDF"):
        fetch(write_manifest(tmp_path, [entry()]), tmp_path / "dest", download=lambda url: b"<html>not a pdf</html>")
    with pytest.raises(ValueError, match="large"):
        fetch(write_manifest(tmp_path, [entry()]), tmp_path / "dest", download=lambda url: b"%PDF-" + b"0" * (31 * 1024 * 1024))

    assert list((tmp_path / "dest").rglob("paper.pdf")) == []        # nothing bad was kept


def test_fetch_saves_a_good_download_in_its_own_folder(tmp_path):
    paths = fetch(write_manifest(tmp_path, [entry(sha256=PDF_SHA)]), tmp_path / "dest", download=lambda url: PDF_BYTES)

    assert paths == {"a": tmp_path / "dest" / "a" / "paper.pdf"}
    assert paths["a"].read_bytes() == PDF_BYTES


def test_fetch_skips_the_download_when_the_pinned_file_is_already_there(tmp_path):
    calls = []
    manifest = write_manifest(tmp_path, [entry(sha256=PDF_SHA)])

    first = fetch(manifest, tmp_path / "dest", download=lambda url: calls.append(url) or PDF_BYTES)
    again = fetch(manifest, tmp_path / "dest", download=lambda url: calls.append(url) or PDF_BYTES)

    assert first == again and len(calls) == 1


def test_a_pinned_file_that_was_changed_on_disk_is_downloaded_again(tmp_path):
    manifest = write_manifest(tmp_path, [entry(sha256=PDF_SHA)])
    paths = fetch(manifest, tmp_path / "dest", download=lambda url: PDF_BYTES)
    paths["a"].write_bytes(b"%PDF-1.4 tampered")

    again = fetch(manifest, tmp_path / "dest", download=lambda url: PDF_BYTES)

    assert again["a"].read_bytes() == PDF_BYTES


def test_local_path_entries_resolve_when_present_and_are_skipped_when_missing(tmp_path):
    here = tmp_path / "here.pdf"
    here.write_bytes(PDF_BYTES)
    present = fetch(write_manifest(tmp_path, [{"key": "sample", "title": "S", "local_path": str(here)}]),
                    tmp_path / "dest", download=None)
    absent = fetch(write_manifest(tmp_path, [{"key": "sample", "title": "S", "local_path": str(tmp_path / "gone.pdf")}]),
                   tmp_path / "dest", download=None)

    assert present == {"sample": here}
    assert absent == {}
