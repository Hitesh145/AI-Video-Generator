import logging
import os
import struct
import subprocess
from pathlib import Path
from typing import Iterator


logger = logging.getLogger(__name__)


def _top_level_boxes(path: Path) -> Iterator[str]:
    total = path.stat().st_size
    with path.open("rb") as handle:
        offset = 0
        while offset + 8 <= total:
            handle.seek(offset)
            size, kind = struct.unpack(">I4s", handle.read(8))
            if size == 1:                      # 64-bit size follows the type
                size = struct.unpack(">Q", handle.read(8))[0]
            elif size == 0:                    # box runs to the end of the file
                size = total - offset
            if size < 8:
                return
            yield kind.decode("latin-1")
            offset += size


def is_faststart(path: Path) -> bool:
    """True when the moov index comes before the media data (or there is nothing to move)."""
    for kind in _top_level_boxes(path):
        if kind == "moov":
            return True
        if kind == "mdat":
            return False
    return True


def ensure_faststart(path: Path) -> bool:
    """Remux in place so browsers can read duration and seek before the whole file arrives."""
    temp = path.with_name(f"{path.stem}.faststart.tmp{path.suffix}")
    try:
        if is_faststart(path):
            return True
        original = path.stat()
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(temp)],
            check=True,
            capture_output=True,
        )
        os.replace(temp, path)
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        return True
    except Exception as exc:
        logger.warning("Could not make %s fast-start: %s", path, exc)
        temp.unlink(missing_ok=True)
        return False
