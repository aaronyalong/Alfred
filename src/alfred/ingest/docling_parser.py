"""Alternative engine: docling, a converter that runs layout models on PDF pages.

On PDFs, docling detects titles, tables, formulas, pictures and running headers/footers, and
can optionally transcribe formulas to LaTeX with a second model (much slower). On PPTX it
reads the slides directly, much like the baseline. DOCX is not supported: docling's DOCX
output carries no page or position information, so its content couldn't be cited.

docling pulls in PyTorch, so it's an optional extra (`uv sync --extra docling`) and is
imported only when this engine is actually used.
"""

from collections import Counter
from functools import cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from alfred.ingest.errors import IngestError, TooManyPagesError, UnsupportedFormatError
from alfred.ingest.issues import MIN_VISUAL_SHARE, NO_TEXT_ISSUE, equation_issue, visual_issue
from alfred.ingest.models import Block, BlockKind, Page, SourceFormat
from alfred.ingest.text import clean_text, has_real_text

INSTALL_HINT = "the docling engine needs the optional extra: uv sync --extra docling"

_SKIPPED_LABELS = {"page_header", "page_footer"}  # running headers/footers repeat on every page
_TITLE_LABELS = {"title", "section_header"}
_VISUAL_LABELS = {"picture", "chart"}


def is_installed() -> bool:
    try:
        version("docling")
    except PackageNotFoundError:
        return False
    return True


def parser_name(*, formulas: bool) -> str:
    try:
        name = f"docling-{version('docling')}"
    except PackageNotFoundError as e:
        raise IngestError(INSTALL_HINT) from e
    return name + ("+formulas" if formulas else "")


def parse_with_docling(
    path: Path, max_pages: int, *, source_format: SourceFormat, formulas: bool
) -> tuple[Page, ...]:
    if source_format is SourceFormat.DOCX:
        raise UnsupportedFormatError(
            "the docling engine doesn't support DOCX (no page positions); use the baseline engine"
        )
    result = _converter(formulas).convert(path, max_num_pages=max_pages, raises_on_error=False)
    if result.status.value not in ("success", "partial_success"):
        message = "; ".join(e.error_message for e in result.errors) or result.status.value
        if "max_num_pages" in message:
            raise TooManyPagesError(f"{path.name}: {message}")
        raise IngestError(f"docling could not convert {path.name}: {message}")
    return _to_pages(result.document)


@cache
def _converter(formulas: bool) -> Any:
    """Build a converter once per setting: loading the models takes seconds."""
    try:
        from docling.datamodel.base_models import InputFormat  # pyright: ignore[reportMissingImports]
        from docling.datamodel.pipeline_options import (  # pyright: ignore[reportMissingImports]
            PdfPipelineOptions,
        )
        from docling.document_converter import (  # pyright: ignore[reportMissingImports]
            DocumentConverter,
            PdfFormatOption,
        )
    except ImportError as e:
        raise IngestError(INSTALL_HINT) from e

    options = PdfPipelineOptions(do_formula_enrichment=formulas)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def _to_pages(document: Any) -> tuple[Page, ...]:
    """Group docling's items by page number and translate them into our blocks and issues."""
    page_numbers = range(1, len(document.pages) + 1)
    blocks: dict[int, list[Block]] = {n: [] for n in page_numbers}
    visuals: Counter[int] = Counter()
    unread_formulas: Counter[int] = Counter()

    # traverse_pictures: also visit text that OCR found inside pictures (e.g. diagram labels).
    for item, _level in document.iterate_items(traverse_pictures=True):
        if not item.prov:
            continue
        location = item.prov[0]
        number, label = location.page_no, item.label.value
        if label in _SKIPPED_LABELS:
            continue
        if label in _VISUAL_LABELS:
            size = document.pages[number].size
            page_area = size.width * size.height
            if page_area and location.bbox.area() / page_area >= MIN_VISUAL_SHARE:
                visuals[number] += 1
            continue

        if label == "table":
            kind, text = BlockKind.TABLE, item.export_to_markdown(doc=document)
        elif label == "formula":
            kind, text = BlockKind.FORMULA, item.text
            if not text.strip():  # located, but not transcribed (formula model off)
                unread_formulas[number] += 1
        else:
            kind = BlockKind.TITLE if label in _TITLE_LABELS else BlockKind.TEXT
            text = getattr(item, "text", "")

        text = clean_text(text)
        if text:
            blocks[number].append(Block(kind=kind, text=text))

    pages: list[Page] = []
    for number in page_numbers:
        page_text = " ".join(block.text for block in blocks[number])
        issues: list[str] = []
        if not has_real_text(page_text):
            issues.append(NO_TEXT_ISSUE)
        if visuals[number]:
            issues.append(visual_issue(visuals[number]))
        if unread_formulas[number]:
            issues.append(equation_issue(unread_formulas[number]))
        pages.append(Page(number=number, blocks=tuple(blocks[number]), issues=tuple(issues)))
    return tuple(pages)
