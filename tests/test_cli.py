from collections.abc import Callable
from pathlib import Path

import pytest

from alfred.cli import main
from alfred.ingest import Document

MakePdf = Callable[[list[str]], Path]  # the make_pdf fixture from conftest.py


def test_ingest_prints_summary_issues_and_pages(
    make_pdf: MakePdf, capsys: pytest.CaptureFixture[str]
) -> None:
    path = make_pdf(["Backpropagation computes gradients layer by layer.", ""])

    assert main(["ingest", str(path)]) == 0

    out = capsys.readouterr().out
    assert "PDF · 2 pages" in out
    assert "1 page(s) with issues" in out
    assert "[text] Backpropagation computes gradients" in out
    assert "(no text)" in out


def test_ingest_page_option_shows_one_page(
    make_pdf: MakePdf, capsys: pytest.CaptureFixture[str]
) -> None:
    path = make_pdf(["first page text", "second page text"])

    assert main(["ingest", str(path), "--page", "2"]) == 0

    out = capsys.readouterr().out
    assert "second page text" in out
    assert "first page text" not in out


def test_ingest_json_round_trips_to_a_document(
    make_pdf: MakePdf, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["ingest", str(make_pdf(["some text"])), "--json"]) == 0

    document = Document.model_validate_json(capsys.readouterr().out)
    assert len(document.pages) == 1


def test_ingest_reports_errors_with_exit_code_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    not_a_pdf = tmp_path / "notes.pdf"
    not_a_pdf.write_text("plain text")

    assert main(["ingest", str(not_a_pdf)]) == 1
    assert "error: notes.pdf is not a PDF" in capsys.readouterr().err


def test_ingest_rejects_page_numbers_that_do_not_exist(
    make_pdf: MakePdf, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["ingest", str(make_pdf(["only page"])), "--page", "5"]) == 1
    assert "has no page 5" in capsys.readouterr().err
