"""Docling adapter that converts parser output to EduGen's document schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rag.document_schema import BlockType, DocumentBlock, NormalizedDocument


class DoclingPDFParser:
    """Parse PDFs and export available figure crops as PNG assets.

    If ``image_output_dir`` is omitted, figures are written to a sibling
    directory named ``<pdf-stem>_assets``. ``image_asset_path`` stores the
    resulting absolute path so downstream code can locate the exported file.

    Docling is imported lazily so validation and tests can run before its
    relatively large dependency set has been installed.
    """

    def __init__(self, image_output_dir: Path | None = None) -> None:
        self._image_output_dir = Path(image_output_dir) if image_output_dir else None

    def parse(self, pdf_path: Path) -> NormalizedDocument:
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:
            raise RuntimeError(
                "PDF parsing requires Docling. Install the backend dependency "
                "`docling` in the active virtual environment, then retry."
            ) from exc

        try:
            pipeline_options = PdfPipelineOptions(generate_picture_images=True)
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pipeline_options
                    )
                }
            )
            result = converter.convert(str(pdf_path))
            document = result.document
            image_output_dir = self._image_output_dir or (
                pdf_path.parent / f"{pdf_path.stem}_assets"
            )
            blocks, title, warnings = self._normalize_items(
                document, image_output_dir=image_output_dir, file_stem=pdf_path.stem
            )
            authors = [
                block.text
                for block in blocks
                if block.metadata.get("document_metadata_role") == "author"
                and block.text
            ]
            affiliations = [
                block.text
                for block in blocks
                if block.metadata.get("document_metadata_role") == "affiliation"
                and block.text
            ]
            warnings.extend(self._conversion_warnings(result))

            return NormalizedDocument(
                source_filename=pdf_path.name,
                title=title,
                authors=authors,
                affiliations=affiliations,
                page_count=self._page_count(document),
                parser_name="docling",
                parser_version=self._docling_version(),
                blocks=blocks,
                warnings=warnings,
            )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Docling could not parse the PDF: {exc}") from exc

    def _normalize_items(
        self,
        document: Any,
        image_output_dir: Path | None = None,
        file_stem: str = "document",
    ) -> tuple[list[DocumentBlock], str | None, list[str]]:
        blocks: list[DocumentBlock] = []
        warnings: list[str] = []
        title: str | None = None
        section_stack: list[tuple[int, str]] = []

        iterator = getattr(document, "iterate_items", None)
        if not callable(iterator):
            raise RuntimeError(
                "The installed Docling document does not expose iterate_items()."
            )

        entries = list(iterator())
        metadata_roles = self._detect_document_metadata_roles(entries)

        for ordinal, entry in enumerate(entries):
            item, tree_level = self._entry_parts(entry)
            source_label = self._label(item)
            text = self._item_text(item)
            label_key = source_label.casefold().replace(" ", "_")
            block_type = self._block_type(label_key)
            metadata_role = metadata_roles.get(ordinal)

            if metadata_role == "title":
                block_type = "title"
                if text and title is None:
                    title = text
            elif metadata_role == "affiliation" and block_type == "heading":
                # Retain the original parser label, but do not let an affiliation
                # become a section heading or contaminate following section paths.
                block_type = "other"

            heading_level = self._positive_int(getattr(item, "level", None))
            if block_type == "heading":
                # Prefer Docling's explicit heading level. The iterator depth is
                # a fallback because some parser versions do not expose one.
                heading_level = heading_level or max(
                    1, self._positive_int(tree_level) or 1
                )
                section_stack = [
                    (level, heading)
                    for level, heading in section_stack
                    if level < heading_level
                ]
                if text:
                    section_stack.append((heading_level, text))

            page_number = self._page_number(item)
            caption = self._caption(item, document)
            image_asset_path: str | None = None
            image_available: bool | None = None
            if block_type == "table":
                text = self._table_text(item, document) or text
            elif block_type == "figure":
                # Image extraction is separate from layout detection. Keep the
                # structural block even when no crop can be exported.
                text = text if text and text != caption else ""
                if image_output_dir is not None:
                    image_available = False
                    image_asset_path = self._save_figure_image(
                        item=item,
                        document=document,
                        output_dir=image_output_dir,
                        filename=f"{file_stem}_figure_{ordinal:04d}.png",
                        warnings=warnings,
                        page_number=page_number,
                        ordinal=ordinal,
                    )
                    image_available = image_asset_path is not None

            if not text.strip() and not (block_type == "figure" and caption):
                # Preserve meaningful structural blocks even when the parser
                # supplies no text, such as a figure without a caption.
                if block_type not in {"figure", "table", "equation"}:
                    continue

            blocks.append(
                DocumentBlock(
                    ordinal=ordinal,
                    block_type=block_type,
                    source_label=source_label,
                    text=text.strip(),
                    caption=caption,
                    image_asset_path=image_asset_path,
                    image_available=image_available,
                    page_number=page_number,
                    section_path=(
                        []
                        if metadata_role is not None
                        else [heading for _, heading in section_stack]
                    ),
                    heading_level=heading_level if block_type == "heading" else None,
                    is_document_metadata=metadata_role is not None,
                    metadata=(
                        {"document_metadata_role": metadata_role}
                        if metadata_role is not None
                        else {}
                    ),
                )
            )

        if not blocks:
            warnings.append(
                "Docling returned no content blocks. The PDF may be scanned, "
                "empty, encrypted, or otherwise difficult to parse."
            )
        return blocks, title, warnings


    @staticmethod
    def _save_figure_image(
        item: Any,
        document: Any,
        output_dir: Path,
        filename: str,
        warnings: list[str],
        page_number: int | None,
        ordinal: int,
    ) -> str | None:
        """Export a Docling figure crop, returning its absolute path on success."""
        get_image = getattr(item, "get_image", None)
        if not callable(get_image):
            warnings.append(
                f"Figure block {ordinal} on page {page_number or 'unknown'} "
                "has no supported image-export method; the figure marker was preserved."
            )
            return None

        try:
            image = get_image(document)
            if image is None:
                warnings.append(
                    f"Figure block {ordinal} on page {page_number or 'unknown'} "
                    "has no image asset available; the figure marker was preserved."
                )
                return None

            output_dir.mkdir(parents=True, exist_ok=True)
            image_path = (output_dir / filename).resolve()
            image.save(image_path, format="PNG")
            return str(image_path)
        except Exception as exc:
            warnings.append(
                f"Could not export figure block {ordinal} on page "
                f"{page_number or 'unknown'}: {exc}. The figure marker was preserved."
            )
            return None

    @staticmethod
    def _entry_parts(entry: Any) -> tuple[Any, int]:
        if isinstance(entry, tuple) and len(entry) >= 2:
            return entry[0], entry[1]
        return entry, 1

    @classmethod
    def _detect_document_metadata_roles(cls, entries: list[Any]) -> dict[int, str]:
        """Identify strong title-author-affiliation clusters without paper-specific rules.

        Docling can label document titles and affiliations as ``section_header``.
        Only reclassify a longer heading when it is immediately followed (ignoring
        empty layout items) by a plausible author line and an institution/department
        line. Ordinary headings are left untouched when that structural pattern is
        absent. Explicit Docling ``title`` items are always treated as metadata.
        """
        roles: dict[int, str] = {}
        parsed = [
            (item, cls._label(item).casefold().replace(" ", "_"), cls._item_text(item).strip())
            for item, _ in (cls._entry_parts(entry) for entry in entries)
        ]

        for index, (item, label_key, text) in enumerate(parsed):
            if not text:
                continue
            if label_key == "title":
                roles[index] = "title"
            elif label_key == "section_header" and len(text.split()) >= 4:
                lookahead = cls._looks_like_title_candidate(text)
                if not lookahead:
                    continue
            else:
                continue

            # Inspect the next two non-empty text items, tolerating intervening
            # image/layout items that do not carry text.
            following: list[tuple[int, str]] = []
            for next_index in range(index + 1, len(parsed)):
                next_text = parsed[next_index][2]
                if next_text:
                    following.append((next_index, next_text))
                if len(following) == 2:
                    break

            if (
                len(following) == 2
                and cls._looks_like_author(following[0][1])
                and cls._looks_like_affiliation(following[1][1])
            ):
                roles[index] = "title"
                roles[following[0][0]] = "author"
                roles[following[1][0]] = "affiliation"

        return roles

    @staticmethod
    def _looks_like_title_candidate(text: str) -> bool:
        # A longer heading is only a candidate; it is classified as metadata
        # only when the following author + affiliation pattern also matches.
        return len(text.split()) >= 4 and len(text) >= 20

    @staticmethod
    def _looks_like_author(text: str) -> bool:
        import re

        value = text.strip()
        value = re.sub(
            r"^(?:(?:prof(?:essor)?|dr|mr|mrs|ms|mx)\.?\s+)",
            "",
            value,
            flags=re.IGNORECASE,
        )
        tokens = value.split()
        if not 2 <= len(tokens) <= 5:
            return False
        return all(
            re.fullmatch(r"(?:[A-Z][A-Za-z'’-]*|[A-Z]\.)", token) is not None
            for token in tokens
        )

    @staticmethod
    def _looks_like_affiliation(text: str) -> bool:
        import re

        return re.search(
            r"\b(department|college|university|institute|faculty|school|"
            r"laborator(?:y|ies)|research\s+cent(?:er|re))\b",
            text,
            flags=re.IGNORECASE,
        ) is not None

    @staticmethod
    def _label(item: Any) -> str:
        label = getattr(item, "label", None)
        if label is None:
            return item.__class__.__name__
        return str(getattr(label, "value", label))

    @staticmethod
    def _item_text(item: Any) -> str:
        value = getattr(item, "text", "")
        return value if isinstance(value, str) else ""

    @staticmethod
    def _block_type(label: str) -> BlockType:
        if label == "title":
            return "title"
        if label in {"section_header", "heading", "header"}:
            return "heading"
        if label in {"text", "paragraph", "formula_text"}:
            return "paragraph"
        if label in {"list_item", "listitem"}:
            return "list_item"
        if label == "table":
            return "table"
        if label in {"picture", "figure"}:
            return "figure"
        if label in {"formula", "equation"}:
            return "equation"
        if label == "caption":
            return "caption"
        if label == "footnote":
            return "footnote"
        if label == "code":
            return "code"
        return "other"

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _page_number(self, item: Any) -> int | None:
        provenance = getattr(item, "prov", None)
        if not provenance:
            return None
        return self._positive_int(getattr(provenance[0], "page_no", None))

    @staticmethod
    def _caption(item: Any, document: Any) -> str | None:
        caption_text = getattr(item, "caption_text", None)
        if callable(caption_text):
            for kwargs in ({"doc": document}, {}):
                try:
                    value = caption_text(**kwargs)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                    if isinstance(value, (list, tuple)):
                        combined = " ".join(
                            str(part).strip() for part in value if part
                        )
                        if combined:
                            return combined
                except (TypeError, AttributeError):
                    continue

        captions = getattr(item, "captions", None)
        if captions:
            values = []
            for caption in captions:
                caption_value = getattr(caption, "text", None)
                if isinstance(caption_value, str) and caption_value.strip():
                    values.append(caption_value.strip())
            if values:
                return " ".join(values)
        return None

    @staticmethod
    def _table_text(item: Any, document: Any) -> str | None:
        export = getattr(item, "export_to_markdown", None)
        if callable(export):
            for kwargs in ({"doc": document}, {}):
                try:
                    value = export(**kwargs)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                except (TypeError, AttributeError):
                    continue
        return None

    @staticmethod
    def _page_count(document: Any) -> int | None:
        pages = getattr(document, "pages", None)
        try:
            count = len(pages)
        except TypeError:
            return None
        return count if count > 0 else None

    @staticmethod
    def _conversion_warnings(result: Any) -> list[str]:
        warnings: list[str] = []
        errors = getattr(result, "errors", None) or []
        for error in errors:
            message = getattr(error, "error_message", None) or str(error)
            if message:
                warnings.append(f"Docling conversion warning: {message}")
        return warnings

    @staticmethod
    def _docling_version() -> str | None:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("docling")
        except PackageNotFoundError:
            return None
