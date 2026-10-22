"""Baseline PDF parser: the text layer of each page, read with pypdfium2.

pypdfium2 wraps PDFium, Chrome's PDF engine (permissive license, unlike AGPL PyMuPDF).
This parser is deliberately simple: one text block per page, no layout analysis, no OCR.
It is the baseline that richer parsers have to beat in the ingestion benchmark.
Pages whose content is images or vector drawings are flagged, so the gap is visible.
"""

from importlib.metadata import version
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from alfred.ingest.errors import IngestError, TooManyPagesError
from alfred.ingest.issues import MIN_VISUAL_SHARE, NO_TEXT_ISSUE, visual_issue
from alfred.ingest.models import Block, BlockKind, Page
from alfred.ingest.text import clean_text, has_real_text

PARSER_NAME = f"pypdfium2-{version('pypdfium2')}"

VECTOR_ISSUE = "formula, chart or diagram drawn as vector graphics; not extracted"

# Formulas and diagrams exported from slides are often drawn as thousands of outline shapes
# instead of text. Measured on a 60-page lecture PDF: ordinary pages draw at most ~60 vector
# paths (lines, boxes, underlines); every page with a formula or diagram drew 2,381 or more.
MIN_VECTOR_PATHS = 500


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
        images, paths = _count_visuals(page)
    finally:
        textpage.close()
        page.close()

    issues: list[str] = []
    if not has_real_text(text):
        issues.append(NO_TEXT_ISSUE)
    if images:
        issues.append(visual_issue(images))
    if paths >= MIN_VECTOR_PATHS:
        issues.append(VECTOR_ISSUE)
    blocks = (Block(kind=BlockKind.TEXT, text=text),) if text else ()
    return Page(number=number, blocks=blocks, issues=tuple(issues))


def _count_visuals(page: pdfium.PdfPage) -> tuple[int, int]:
    """Count large raster images, and vector path objects, on a page."""
    width, height = page.get_size()
    page_area = width * height
    images = paths = 0
    for obj in page.get_objects():
        kind = pdfium_c.FPDFPageObj_GetType(obj.raw)
        if kind == pdfium_c.FPDF_PAGEOBJ_IMAGE:
            left, bottom, right, top = obj.get_bounds()
            if page_area and (right - left) * (top - bottom) / page_area >= MIN_VISUAL_SHARE:
                images += 1
        elif kind == pdfium_c.FPDF_PAGEOBJ_PATH:
            paths += 1
    return images, paths
