"""Entry point: turn an uploaded file into a Document."""

import hashlib
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from alfred.ingest import pdf_parser, pptx_parser
from alfred.ingest.detect import detect_format
from alfred.ingest.errors import FileTooLargeError, UnsupportedFormatError
from alfred.ingest.models import Document, Page, SourceFormat, Unit

MB = 1024 * 1024


@dataclass(frozen=True)
class Limits:
    """Caps that protect the parser from oversized or malicious uploads."""

    max_bytes: int = 50 * MB
    max_pages: int = 300
    # PPTX/DOCX are zip archives and are fully unpacked in memory; this stops zip bombs.
    max_unpacked_bytes: int = 200 * MB


@dataclass(frozen=True)
class _Parser:
    name: str
    unit: Unit
    parse: Callable[[Path, int], tuple[Page, ...]]


_PARSERS = {
    SourceFormat.PDF: _Parser(pdf_parser.PARSER_NAME, Unit.PAGE, pdf_parser.parse_pdf),
    SourceFormat.PPTX: _Parser(pptx_parser.PARSER_NAME, Unit.SLIDE, pptx_parser.parse_pptx),
}


def ingest(path: Path, limits: Limits | None = None) -> Document:
    limits = limits or Limits()

    # Cheap checks first, before any parser touches the file.
    size = path.stat().st_size
    if size > limits.max_bytes:
        raise FileTooLargeError(
            f"{path.name} is {size / MB:.1f} MB; the limit is {limits.max_bytes / MB:.0f} MB"
        )
    source_format = detect_format(path)
    parser = _PARSERS.get(source_format)
    if parser is None:
        raise UnsupportedFormatError(f"{source_format.upper()} files are not supported yet")
    if source_format in (SourceFormat.PPTX, SourceFormat.DOCX):
        _check_unpacked_size(path, limits.max_unpacked_bytes)

    return Document(
        source_name=path.name,
        source_sha256=_sha256(path),
        format=source_format,
        unit=parser.unit,
        parser=parser.name,
        pages=parser.parse(path, limits.max_pages),
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
