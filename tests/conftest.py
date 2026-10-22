from collections.abc import Callable
from pathlib import Path

import pytest
from fpdf import FPDF

MakePdf = Callable[[list[str]], Path]


@pytest.fixture
def make_pdf(tmp_path: Path) -> MakePdf:
    """Build a small PDF with one page per string; an empty string makes a blank page.

    Tests generate their PDFs instead of using real course files, which can't be committed.
    """

    def build(pages: list[str]) -> Path:
        pdf = FPDF()
        pdf.set_font("helvetica", size=12)
        for text in pages:
            pdf.add_page()
            if text:
                pdf.multi_cell(0, 8, text)
        path = tmp_path / "generated.pdf"
        pdf.output(str(path))
        return path

    return build
