import mimetypes
import re
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response, StreamingResponse


mimetypes.add_type("video/mp4", ".mp4")

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CHUNK_BYTES = 1024 * 1024


class RangeNotSatisfiable(Exception):
    pass


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Inclusive (start, end) for a single byte range; None means serve the whole file."""
    if not header:
        return None
    match = _RANGE.match(header.strip())
    if match is None:
        return None                     # multiple ranges or other units: ignore the header
    first, last = match.groups()
    if first == "" and last == "":
        return None

    if first == "":                     # suffix range: the last N bytes
        length = int(last)
        if length == 0:
            raise RangeNotSatisfiable
        start, end = max(size - length, 0), size - 1
    else:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1

    if size == 0 or start >= size or start > end:
        raise RangeNotSatisfiable
    return start, end


def _iter_file(path: Path, start: int, end: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(_CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def create_media_router(output_root: Path) -> APIRouter:
    router = APIRouter()
    root = Path(output_root).resolve()

    @router.get("/media/{relative_path:path}")
    def serve_media(relative_path: str, range_header: str | None = Header(default=None, alias="range")):
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise HTTPException(status_code=404, detail="Not found")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Not found")

        size = target.stat().st_size
        media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if size == 0:
            return Response(content=b"", media_type=media_type, headers={"Accept-Ranges": "bytes"})

        try:
            byte_range = parse_range(range_header, size)
        except RangeNotSatisfiable:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})

        if byte_range is None:
            start, end, status = 0, size - 1, 200
        else:
            (start, end), status = byte_range, 206

        headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1)}
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(_iter_file(target, start, end), status_code=status, media_type=media_type, headers=headers)

    return router
