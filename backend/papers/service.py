"""Uploads, de-duplication and background reading of research-paper PDFs."""

from __future__ import annotations

import hashlib
import shutil
import threading
from pathlib import Path
from typing import BinaryIO, Callable
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from papers.models import FAILED, READY
from papers.repository import PaperRecord, PaperReport, PaperRepository

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
STAGE_DETAILS = {
    "parsing": "Reading the PDF",
    "chunking": "Splitting into passages",
    "storing": "Saving the paper",
    "embedding": "Indexing passages",
}
MAX_DETAIL_LENGTH = 300
_CHUNK_BYTES = 1024 * 1024


class InvalidUpload(ValueError):
    pass


class UploadTooLarge(Exception):
    pass


class CannotRetry(Exception):
    pass


def _one_line(text: str, limit: int = MAX_DETAIL_LENGTH) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _display_name(raw: str) -> str:
    """The client's filename as a harmless label: no directories, no control characters."""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(character for character in name if character.isprintable()).strip()[:255]
    return name or "paper.pdf"


def _human_size(limit: int) -> str:
    return f"{limit // (1024 * 1024)} MB" if limit >= 1024 * 1024 else f"{limit} bytes"


class PaperService:
    def __init__(
        self,
        repository: PaperRepository,
        ingestor,
        upload_dir: Path,
        max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
        max_concurrent: int = 1,
        submit: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.repository = repository
        self.ingestor = ingestor
        self.upload_dir = Path(upload_dir)
        self.max_upload_bytes = max_upload_bytes
        self._custom_submit = submit
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._threads: dict[str, threading.Thread] = {}
        self._threads_lock = threading.Lock()

    # ------------------------------------------------------------------ public API
    def upload(self, user_id: str, filename: str, stream: BinaryIO) -> tuple[PaperRecord, bool]:
        name = _display_name(filename)
        if not name.lower().endswith(".pdf"):
            raise InvalidUpload("Only PDF files are accepted")

        self.upload_dir.mkdir(parents=True, exist_ok=True)
        part = self.upload_dir / f"{uuid4().hex}.part"
        kept = False
        try:
            size, digest = self._save(stream, part)
            existing = self.repository.find_by_hash(user_id, digest)
            if existing is not None:
                if existing.status == FAILED and existing.document_id is None:
                    return self._requeue(existing, part), False       # failed while reading: try again
                return existing, False

            try:
                record = self.repository.create(user_id, name, size, digest)
            except IntegrityError:                                    # lost a race with an identical upload
                return self.repository.find_by_hash(user_id, digest), False
            kept = self._begin(record, part)
            return self.repository.get(record.paper_id, user_id), True
        finally:
            if not kept:
                part.unlink(missing_ok=True)

    def get(self, paper_id: str, user_id: str) -> PaperRecord | None:
        return self.repository.get(paper_id, user_id)

    def list(self, user_id: str) -> list[PaperRecord]:
        return self.repository.list_for_user(user_id)

    def report(self, paper_id: str, user_id: str) -> PaperReport | None:
        record = self.repository.get(paper_id, user_id)
        if record is None or record.document_id is None:
            return None
        return self.repository.report(record.document_id)

    def retry(self, paper_id: str, user_id: str) -> PaperRecord | None:
        record = self.repository.get(paper_id, user_id)
        if record is None:
            return None
        if record.status != FAILED:
            raise CannotRetry("Only failed papers can be retried")
        if record.document_id is None:
            raise CannotRetry("This paper failed while it was being read; please upload it again")
        if not self.repository.claim_for_retry(paper_id):      # another request got there first
            raise CannotRetry("Only failed papers can be retried")
        self._dispatch(paper_id, lambda: self._embed_only(paper_id, record.document_id))
        return self.repository.get(paper_id, user_id)

    def fail_interrupted(self) -> int:
        """Run once at startup: nothing can still be reading, so unfinished papers are failed
        and anything an interrupted read left in the upload folder is removed."""
        self._clear_upload_dir()
        return self.repository.fail_interrupted("The server restarted while this paper was being processed")

    def _clear_upload_dir(self) -> None:
        if not self.upload_dir.is_dir():
            return
        for entry in self.upload_dir.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)

    def wait(self, paper_id: str, timeout: float | None = None) -> None:
        with self._threads_lock:
            thread = self._threads.get(paper_id)
        if thread is not None:
            thread.join(timeout)

    # ------------------------------------------------------------------ upload helpers
    def _save(self, stream: BinaryIO, part: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        head = b""
        with part.open("wb") as out:
            while True:
                chunk = stream.read(_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > self.max_upload_bytes:
                    raise UploadTooLarge(f"The file is larger than the {_human_size(self.max_upload_bytes)} limit")
                if len(head) < 1024:
                    head += chunk[: 1024 - len(head)]
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise InvalidUpload("The file is empty")
        if b"%PDF-" not in head:
            raise InvalidUpload("This file is not a valid PDF")
        return size, digest.hexdigest()

    def _begin(self, record: PaperRecord, part: Path) -> bool:
        """Move the saved upload to its permanent name and start reading it. Returns True if the file is kept."""
        pdf_path = self.upload_dir / f"{record.paper_id}.pdf"
        part.replace(pdf_path)
        self._dispatch(record.paper_id, lambda: self._process(record, pdf_path))
        return True

    def _requeue(self, existing: PaperRecord, part: Path) -> PaperRecord:
        if self.repository.claim_for_reading(existing.paper_id):
            self._begin(existing, part)
        # else: an identical upload already restarted it; this copy is simply dropped by the caller
        return self.repository.get(existing.paper_id, existing.user_id)

    # ------------------------------------------------------------------ background work
    def _dispatch(self, paper_id: str, job: Callable[[], None]) -> None:
        if self._custom_submit is not None:
            self._custom_submit(job)
            return
        thread = threading.Thread(target=job, daemon=True, name=f"paper-{paper_id}")
        with self._threads_lock:
            self._threads[paper_id] = thread
        thread.start()

    def _on_stage(self, paper_id: str) -> Callable[[str, str | None], None]:
        def report(status: str, detail: str | None = None) -> None:
            self.repository.update(paper_id, status=status, detail=detail or STAGE_DETAILS.get(status))

        return report

    def _process(self, record: PaperRecord, pdf_path: Path) -> None:
        paper_id = record.paper_id
        work_dir = self.upload_dir / f"{paper_id}.work"
        try:
            with self._slots:                       # waiting papers stay "queued" until it is their turn
                on_stage = self._on_stage(paper_id)
                result = self.ingestor.ingest(record.user_id, pdf_path, work_dir, on_stage)
                self.repository.update(
                    paper_id, document_id=result.document_id, title=result.title, page_count=result.page_count
                )
                self._finish_embedding(paper_id, result.document_id, on_stage)
        except Exception as exc:
            self.repository.update(paper_id, status=FAILED, detail=_one_line(str(exc) or type(exc).__name__))
        finally:
            pdf_path.unlink(missing_ok=True)
            shutil.rmtree(work_dir, ignore_errors=True)

    def _embed_only(self, paper_id: str, document_id: str) -> None:
        try:
            with self._slots:
                self._finish_embedding(paper_id, document_id, self._on_stage(paper_id))
        except Exception as exc:
            self.repository.update(paper_id, status=FAILED, detail=_one_line(str(exc) or type(exc).__name__))

    def _finish_embedding(self, paper_id: str, document_id: str, on_stage) -> None:
        try:
            self.ingestor.embed(document_id, on_stage)
        except Exception as exc:
            reason = _one_line(str(exc) or type(exc).__name__, MAX_DETAIL_LENGTH - 80)
            self.repository.update(
                paper_id,
                status=FAILED,
                detail=f"The text was saved but indexing failed: {reason}. Press Retry.",
            )
            return
        self.repository.update(paper_id, status=READY, detail=None)
