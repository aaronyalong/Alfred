import zipfile
from pathlib import Path

import pytest

from alfred.ingest import SourceFormat
from alfred.ingest.detect import detect_format
from alfred.ingest.errors import UnsupportedFormatError


def write_zip(path: Path, entries: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name in entries:
            archive.writestr(name, "<xml/>")
    return path


def test_detects_pdf_by_content_not_extension(tmp_path: Path) -> None:
    disguised = tmp_path / "slides.pptx"
    disguised.write_bytes(b"%PDF-1.7\n...")

    assert detect_format(disguised) is SourceFormat.PDF


def test_detects_pptx_and_docx_from_zip_contents(tmp_path: Path) -> None:
    pptx = write_zip(tmp_path / "a.zip", ["[Content_Types].xml", "ppt/presentation.xml"])
    docx = write_zip(tmp_path / "b.zip", ["[Content_Types].xml", "word/document.xml"])

    assert detect_format(pptx) is SourceFormat.PPTX
    assert detect_format(docx) is SourceFormat.DOCX


def test_rejects_zip_that_is_not_an_office_file(tmp_path: Path) -> None:
    other = write_zip(tmp_path / "notes.docx", ["readme.txt"])

    with pytest.raises(UnsupportedFormatError, match="not a PPTX or DOCX"):
        detect_format(other)


def test_rejects_legacy_office_files_with_a_hint(tmp_path: Path) -> None:
    legacy = tmp_path / "old.ppt"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 100)

    with pytest.raises(UnsupportedFormatError, match=r"save it as \.pptx"):
        detect_format(legacy)


def test_rejects_unknown_content(tmp_path: Path) -> None:
    text_file = tmp_path / "lecture.pdf"
    text_file.write_text("just some text")

    with pytest.raises(UnsupportedFormatError):
        detect_format(text_file)
