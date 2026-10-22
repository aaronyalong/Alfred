"""Entry point: turn an uploaded file into a Document."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from alfred.ingest import pdf
from alfred.ingest.detect import detect_format
from alfred.ingest.errors import FileTooLargeError, UnsupportedFormatError
from alfred.ingest.models import Document, SourceFormat, Unit


@dataclass(frozen=True)
class Limits:
    """Caps that protect the parser from oversized or malicious uploads."""

    max_bytes: int = 50 * 1024 * 1024
    max_pages: int = 300


def ingest(path: Path, limits: Limits | None = None) -> Document:
    limits = limits or Limits()

    # Cheap checks first, before any parser touches the file.
    size = path.stat().st_size
    if size > limits.max_bytes:
        raise FileTooLargeError(
            f"{path.name} is {size / 1e6:.1f} MB; the limit is {limits.max_bytes / 1e6:.0f} MB"
        )
    source_format = detect_format(path)
    if source_format is not SourceFormat.PDF:
        raise UnsupportedFormatError(f"{source_format.upper()} files are not supported yet")

    pages = pdf.parse_pdf(path, max_pages=limits.max_pages)
    return Document(
        source_name=path.name,
        source_sha256=_sha256(path),
        format=source_format,
        unit=Unit.PAGE,
        parser=pdf.PARSER_NAME,
        pages=pages,
    )


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
