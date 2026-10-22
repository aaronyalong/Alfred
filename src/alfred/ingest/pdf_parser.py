"""Baseline PDF parser: the text layer of each page, read with pypdfium2.

pypdfium2 wraps PDFium, Chrome's PDF engine (permissive license, unlike AGPL PyMuPDF).
This parser is deliberately simple: one text block per page, no layout analysis, no OCR.
It is the baseline that richer parsers have to beat in the ingestion benchmark.
"""

from importlib.metadata import version
from pathlib import Path

import pypdfium2 as pdfium

from alfred.ingest.errors import IngestError, TooManyPagesError
from alfred.ingest.models import Block, BlockKind, Page
from alfred.ingest.text import clean_text, has_real_text

PARSER_NAME = f"pypdfium2-{version('pypdfium2')}"

NO_TEXT_ISSUE = "little or no text layer (scanned or image-only page?)"


def parse_pdf(path: Path, max_pages: int) -> tuple[Page, ...]:
    try:
        pdf = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as e:  # damaged, encrypted, or not really a PDF
        raise IngestError(f"Could not open {path.name}: {e}") from e

    try:
        if len(pdf) > max_pages:
            raise TooManyPagesError(f"{path.name} has {len(pdf)} pages; the limit is {max_pages}")
        return tuple(_parse_page(pdf[i], number=i + 1) for i in range(len(pdf)))
    finally:
        pdf.close()


def _parse_page(page: pdfium.PdfPage, *, number: int) -> Page:
    textpage = page.get_textpage()
    try:
        text = clean_text(textpage.get_text_range())
    finally:
        textpage.close()
        page.close()

    blocks = (Block(kind=BlockKind.TEXT, text=text),) if text else ()
    issues = () if has_real_text(text) else (NO_TEXT_ISSUE,)
    return Page(number=number, blocks=blocks, issues=issues)
