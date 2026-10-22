from collections.abc import Callable
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
from docx import Document as new_docx

from alfred.ingest import Engine, IngestError, SourceFormat, Unit, docling_parser, ingest
from alfred.ingest.errors import UnsupportedFormatError

MakePdf = Callable[[list[str]], Path]  # the make_pdf fixture from conftest.py

# The docling extra is optional and not installed in CI; these tests run where it is.
needs_docling = pytest.mark.skipif(
    not docling_parser.is_installed(), reason="docling extra not installed"
)


def test_missing_docling_gives_an_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    def not_installed(_name: str) -> str:
        raise PackageNotFoundError("docling")

    monkeypatch.setattr(docling_parser, "version", not_installed)

    with pytest.raises(IngestError, match="uv sync --extra docling"):
        docling_parser.parser_name(formulas=False)


@needs_docling
def test_docling_engine_keeps_text_on_its_page(make_pdf: MakePdf) -> None:
    path = make_pdf(["Tokenization splits text into tokens.", "Embeddings map tokens to vectors."])

    document = ingest(path, engine=Engine.DOCLING)

    assert document.format is SourceFormat.PDF
    assert document.unit is Unit.PAGE
    assert document.parser.startswith("docling-")
    assert "Tokenization splits text" in document.page(1).text
    assert "Embeddings map tokens" in document.page(2).text


@needs_docling
def test_docling_engine_rejects_docx(tmp_path: Path) -> None:
    path = tmp_path / "notes.docx"
    document = new_docx()
    document.add_paragraph("Some notes.")
    document.save(str(path))

    with pytest.raises(UnsupportedFormatError, match="use the baseline engine"):
        ingest(path, engine=Engine.DOCLING)
