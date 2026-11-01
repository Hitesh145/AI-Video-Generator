"""Content-addressed, private file storage for source PDFs and extracted figures."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from rag.document_schema import NormalizedDocument


@dataclass(frozen=True)
class StoredAsset:
    """Metadata for a file copied into the managed asset directory."""

    asset_key: str
    asset_type: str
    sha256: str
    mime_type: str
    size_bytes: int
    page_number: int | None = None
    source_block_id: str | None = None


@dataclass
class AssetBundle:
    """Copy result, including relative keys and files created by this operation."""

    source_pdf_key: str
    assets: list[StoredAsset] = field(default_factory=list)
    image_keys_by_block_id: dict[str, str] = field(default_factory=dict)
    source_path_to_key: dict[str, str] = field(default_factory=dict)
    created_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def sha256_file(path: str | Path) -> str:
    """Hash a file in bounded memory chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_source_path(path: str | Path) -> str:
    """Normalize paths for matching parser output to stored asset keys."""
    return os.path.normcase(str(Path(path).expanduser().resolve()))


class ManagedAssetStore:
    """Store PDFs/figures under content-addressed directories with relative keys.

    The database receives only POSIX-style relative keys, never absolute paths
    from the developer's computer. Files are not served publicly by this class.
    """

    _SAFE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def store_bundle(
        self,
        source_pdf: str | Path,
        document: NormalizedDocument,
        source_sha256: str,
    ) -> AssetBundle:
        source_path = Path(source_pdf).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Source PDF not found: {source_path}")
        if sha256_file(source_path) != source_sha256:
            raise ValueError("Source PDF content changed while it was being ingested.")

        bundle = AssetBundle(source_pdf_key="")
        object_prefix = f"objects/{source_sha256[:2]}/{source_sha256}"
        pdf_key = f"{object_prefix}/source.pdf"
        pdf_record, created = self._store_one(source_path, pdf_key, "source_pdf")
        bundle.source_pdf_key = pdf_record.asset_key
        bundle.assets.append(pdf_record)
        if created:
            bundle.created_paths.append(self.root / pdf_record.asset_key)

        for block in document.blocks:
            if block.block_type != "figure" or not block.image_asset_path:
                continue

            figure_source = Path(block.image_asset_path).expanduser()
            if not figure_source.is_file():
                bundle.warnings.append(
                    f"Figure block {block.block_id} has an image path that is unavailable; "
                    "the figure marker will be retained without a stored image asset."
                )
                continue

            image_digest = sha256_file(figure_source)
            suffix = figure_source.suffix.lower()
            if suffix not in self._SAFE_SUFFIXES:
                suffix = mimetypes.guess_extension(mimetypes.guess_type(figure_source.name)[0] or "") or ".bin"
            figure_key = f"{object_prefix}/figures/figure_{block.ordinal:04d}_{image_digest[:12]}{suffix}"
            figure_record, created = self._store_one(
                figure_source,
                figure_key,
                "figure",
                page_number=block.page_number,
                source_block_id=block.block_id,
                expected_sha256=image_digest,
            )
            bundle.assets.append(figure_record)
            bundle.image_keys_by_block_id[block.block_id] = figure_record.asset_key
            bundle.source_path_to_key[canonical_source_path(figure_source)] = figure_record.asset_key
            if created:
                bundle.created_paths.append(self.root / figure_record.asset_key)

        return bundle

    def cleanup_created_files(self, bundle: AssetBundle) -> None:
        """Best-effort cleanup after a failed database transaction."""
        for path in reversed(bundle.created_paths):
            try:
                path.unlink(missing_ok=True)
                parent = path.parent
                while parent != self.root and self.root in parent.parents:
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
            except OSError:
                # Leave an orphan rather than hide the original database error.
                continue

    def _store_one(
        self,
        source: Path,
        asset_key: str,
        asset_type: str,
        page_number: int | None = None,
        source_block_id: str | None = None,
        expected_sha256: str | None = None,
    ) -> tuple[StoredAsset, bool]:
        digest = expected_sha256 or sha256_file(source)
        destination = self.root.joinpath(*Path(asset_key).parts).resolve()
        if self.root not in destination.parents:
            raise ValueError("Generated asset key escaped the configured asset root.")

        if destination.exists():
            if not destination.is_file() or sha256_file(destination) != digest:
                raise OSError(f"Existing managed asset failed checksum validation: {asset_key}")
            created = False
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    prefix=".rag-asset-", suffix=".tmp", dir=destination.parent, delete=False
                ) as temp_handle:
                    temporary_path = Path(temp_handle.name)
                    with source.open("rb") as source_handle:
                        shutil.copyfileobj(source_handle, temp_handle)
                if sha256_file(temporary_path) != digest:
                    raise OSError(f"Checksum mismatch while copying asset: {asset_key}")
                os.replace(temporary_path, destination)
                created = True
            finally:
                if temporary_path and temporary_path.exists():
                    temporary_path.unlink(missing_ok=True)

        mime_type = mimetypes.guess_type(destination.name)[0] or "application/octet-stream"
        record = StoredAsset(
            asset_key=Path(asset_key).as_posix(),
            asset_type=asset_type,
            sha256=digest,
            mime_type=mime_type,
            size_bytes=destination.stat().st_size,
            page_number=page_number,
            source_block_id=source_block_id,
        )
        return record, created
