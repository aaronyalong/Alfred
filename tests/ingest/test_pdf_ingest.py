import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest
from fpdf import FPDF
from PIL import Image

from alfred.ingest import IngestError, Limits, SourceFormat, Unit, ingest
from alfred.ingest.errors import FileTooLargeError, TooManyPagesError
from alfred.ingest.issues import NO_TEXT_ISSUE, visual_issue
from alfred.ingest.pdf_parser import MIN_VECTOR_PATHS, VECTOR_ISSUE
from alfred.ingest.text import clean_text

MakePdf = Callable[[list[str]], Path]  # the make_pdf fixture from conftest.py


def test_extracts_text_per_page_with_one_based_numbers(make_pdf: MakePdf) -> None:
    path = make_pdf(["Gradient descent minimizes the loss.", "The learning rate sets the step."])

    document = ingest(path)

    assert document.format is SourceFormat.PDF
    assert document.unit is Unit.PAGE
    assert [page.number for page in document.pages] == [1, 2]
    assert "Gradient descent minimizes the loss." in document.page(1).text
    assert "learning rate" in document.page(2).text


def test_flags_pages_without_a_text_layer(make_pdf: MakePdf) -> None:
    document = ingest(make_pdf(["A page with enough text to count as real text.", ""]))

    assert document.page(1).issues == ()
    assert document.page(2).issues == (NO_TEXT_ISSUE,)
    assert document.page(2).blocks == ()


def test_records_file_hash_and_parser(make_pdf: MakePdf) -> None:
    path = make_pdf(["Some text on the only page."])

    document = ingest(path)

    assert document.source_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert document.parser.startswith("pypdfium2-")


def test_rejects_files_over_the_size_limit(make_pdf: MakePdf) -> None:
    with pytest.raises(FileTooLargeError):
        ingest(make_pdf(["text"]), Limits(max_bytes=100))


def test_rejects_documents_over_the_page_limit(make_pdf: MakePdf) -> None:
    with pytest.raises(TooManyPagesError):
        ingest(make_pdf(["one", "two", "three"]), Limits(max_pages=2))


def test_damaged_pdf_raises_ingest_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 this is not a real pdf")

    with pytest.raises(IngestError, match="Could not open"):
        ingest(broken)


def test_clean_text_normalizes_whitespace_but_keeps_characters() -> None:
    raw = "Loss  \r\nL(x) = x²   \r\n\r\n\r\n\r\nNext line\r\n"

    assert clean_text(raw) == "Loss\nL(x) = x²\n\nNext line"


def test_clean_text_turns_pdfium_hyphen_markers_into_hyphens() -> None:
    assert clean_text("large n￾grams") == "large n-grams"


def pdf_page_with(path: Path, draw: Callable[[FPDF], object]) -> Path:
    """Write a one-page PDF with real text, plus whatever `draw` adds."""
    pdf = FPDF()  # A4: 210 x 297 mm
    pdf.set_font("helvetica", size=12)
    pdf.add_page()
    pdf.multi_cell(0, 8, "This page has enough text to count as a real page of content.")
    draw(pdf)
    pdf.output(str(path))
    return path


def test_flags_large_images_but_not_small_ones(tmp_path: Path) -> None:
    image = Image.new("RGB", (8, 8))  # A4 page area is 62,370 mm²
    large = pdf_page_with(  # 15,000 mm² = 24% of the page
        tmp_path / "large.pdf", lambda pdf: pdf.image(image, x=10, y=40, w=150, h=100)
    )
    small = pdf_page_with(  # 400 mm² = 0.6% of the page
        tmp_path / "small.pdf", lambda pdf: pdf.image(image, x=10, y=40, w=20, h=20)
    )

    assert ingest(large).page(1).issues == (visual_issue(1),)
    assert ingest(small).page(1).issues == ()


def draw_lines(count: int) -> Callable[[FPDF], None]:
    def draw(pdf: FPDF) -> None:
        for i in range(count):
            pdf.line(10, 40 + i * 0.3, 100, 40 + i * 0.3)

    return draw


def test_flags_pages_drawn_with_many_vector_paths(tmp_path: Path) -> None:
    formula_page = pdf_page_with(tmp_path / "formula.pdf", draw_lines(MIN_VECTOR_PATHS))
    table_page = pdf_page_with(tmp_path / "table.pdf", draw_lines(20))

    assert ingest(formula_page).page(1).issues == (VECTOR_ISSUE,)
    assert ingest(table_page).page(1).issues == ()
