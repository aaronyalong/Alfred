"""Entry point: turn an uploaded file into a Document."""

import hashlib
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from alfred.ingest import docling_parser, docx_parser, pdf_parser, pptx_parser
from alfred.ingest.detect import detect_format
from alfred.ingest.errors import FileTooLargeError
from alfred.ingest.models import Document, Page, SourceFormat, Unit
from alfred.ingest.vision import VisionReader

MB = 1024 * 1024


@dataclass(frozen=True)
class Limits:
    """Caps that protect the parser from oversized or malicious uploads."""

    max_bytes: int = 50 * MB
    max_pages: int = 300
    # PPTX/DOCX are zip archives and are fully unpacked in memory; this stops zip bombs.
    max_unpacked_bytes: int = 200 * MB


class Engine(StrEnum):
    """Which parsers to use. The baseline is the default; the others are compared against it."""

    BASELINE = "baseline"
    DOCLING = "docling"
    DOCLING_FORMULAS = "docling-formulas"  # also transcribes formulas to LaTeX (slower)
    VISION = "vision"  # baseline, plus Claude reading the flagged pages (costs money per page)


@dataclass(frozen=True)
class _Parser:
    name: str
    parse: Callable[[Path, int], tuple[Page, ...]]


_BASELINE_PARSERS = {
    SourceFormat.PDF: _Parser(pdf_parser.PARSER_NAME, pdf_parser.parse_pdf),
    SourceFormat.PPTX: _Parser(pptx_parser.PARSER_NAME, pptx_parser.parse_pptx),
    SourceFormat.DOCX: _Parser(docx_parser.PARSER_NAME, docx_parser.parse_docx),
}

_UNITS = {
    SourceFormat.PDF: Unit.PAGE,
    SourceFormat.PPTX: Unit.SLIDE,
    SourceFormat.DOCX: Unit.SECTION,
}


def ingest(
    path: Path,
    limits: Limits | None = None,
    engine: Engine = Engine.BASELINE,
    vision: VisionReader | None = None,
) -> Document:
    """Parse a file. `vision` configures the vision engine and collects its usage."""
    limits = limits or Limits()

    # Cheap checks first, before any parser touches the file.
    size = path.stat().st_size
    if size > limits.max_bytes:
        raise FileTooLargeError(
            f"{path.name} is {size / MB:.1f} MB; the limit is {limits.max_bytes / MB:.0f} MB"
        )
    source_format = detect_format(path)
    if source_format in (SourceFormat.PPTX, SourceFormat.DOCX):
        _check_unpacked_size(path, limits.max_unpacked_bytes)

    unit = _UNITS[source_format]
    if engine in (Engine.BASELINE, Engine.VISION):
        parser = _BASELINE_PARSERS[source_format]
        name, pages = parser.name, parser.parse(path, limits.max_pages)
        if engine is Engine.VISION:
            vision = vision or VisionReader()
            name += f"+{vision.name}"
            pages = vision.read_flagged(path, source_format, unit, pages)
    else:
        formulas = engine is Engine.DOCLING_FORMULAS
        name = docling_parser.parser_name(formulas=formulas)
        pages = docling_parser.parse_with_docling(
            path, limits.max_pages, source_format=source_format, formulas=formulas
        )

    return Document(
        source_name=path.name,
        source_sha256=_sha256(path),
        format=source_format,
        unit=unit,
        parser=name,
        pages=pages,
    )


def _check_unpacked_size(path: Path, limit: int) -> None:
    # Uses the sizes declared in the zip directory; zipfile never unpacks more than that.
    with zipfile.ZipFile(path) as archive:
        unpacked = sum(info.file_size for info in archive.infolist())
    if unpacked > limit:
        raise FileTooLargeError(
            f"{path.name} unpacks to {unpacked / MB:.0f} MB; the limit is {limit / MB:.0f} MB"
        )


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
