"""Identify a file's real format from its content, not its extension.

Extensions are chosen by whoever uploads the file, so they can't be trusted.
"""

import zipfile
from pathlib import Path

from alfred.ingest.errors import UnsupportedFormatError
from alfred.ingest.models import SourceFormat

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"  # PPTX and DOCX are zip archives of XML files
_OLE_MAGIC = b"\xd0\xcf\x11\xe0"  # legacy binary .ppt / .doc


def detect_format(path: Path) -> SourceFormat:
    with path.open("rb") as f:
        head = f.read(1024)

    # The PDF spec allows junk before the header, as long as it starts in the first 1024 bytes.
    if _PDF_MAGIC in head:
        return SourceFormat.PDF
    if head.startswith(_ZIP_MAGIC):
        return _detect_office_format(path)
    if head.startswith(_OLE_MAGIC):
        raise UnsupportedFormatError(
            f"{path.name} is a legacy .ppt/.doc file; save it as .pptx/.docx and upload again"
        )
    raise UnsupportedFormatError(f"{path.name} is not a PDF, PPTX or DOCX file")


def _detect_office_format(path: Path) -> SourceFormat:
    # Reading the list of entries doesn't decompress anything, so this is safe on zip bombs.
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile as e:
        raise UnsupportedFormatError(f"{path.name} is a damaged zip archive") from e

    if "ppt/presentation.xml" in names:
        return SourceFormat.PPTX
    if "word/document.xml" in names:
        return SourceFormat.DOCX
    raise UnsupportedFormatError(f"{path.name} is a zip archive, but not a PPTX or DOCX file")
