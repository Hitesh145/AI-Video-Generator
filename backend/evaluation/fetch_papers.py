"""Download the evaluation papers. Downloads are untrusted data: size-limited, header-checked, hash-pinned."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Callable

MAX_PDF_BYTES = 30 * 1024 * 1024
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "EduGenEvaluation/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(MAX_PDF_BYTES + 1)             # one byte over the limit is enough to refuse it


def fetch(
    manifest_path: Path,
    dest_dir: Path,
    download: Callable[[str], bytes] | None = None,
) -> dict[str, Path]:
    """Return {key: pdf path} for every manifest paper that is available.

    Papers with a `url` are saved to dest_dir/<key>/paper.pdf (re-downloaded when the file is missing or
    no longer matches the pinned `sha256`). Papers with a `local_path` are used where they are, and skipped
    if the file does not exist. A bad download raises ValueError and nothing is kept.
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    results: dict[str, Path] = {}
    for entry in manifest["papers"]:
        key = entry["key"]
        if "local_path" in entry:
            local = BACKEND_DIR / entry["local_path"]            # an absolute path stays absolute
            if local.is_file():
                results[key] = local
            continue

        pinned = entry.get("sha256")
        target = Path(dest_dir) / key / "paper.pdf"
        if target.is_file() and pinned and hashlib.sha256(target.read_bytes()).hexdigest() == pinned:
            results[key] = target
            continue

        data = (download or _download)(entry["url"])
        if len(data) > MAX_PDF_BYTES:
            raise ValueError(f"{key}: the download is too large (limit {MAX_PDF_BYTES // (1024 * 1024)} MB)")
        if not data.startswith(b"%PDF-"):
            raise ValueError(f"{key}: the download is not a PDF")
        digest = hashlib.sha256(data).hexdigest()
        if pinned and digest != pinned:
            raise ValueError(f"{key}: hash mismatch (expected {pinned}, got {digest})")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        results[key] = target
    return results
