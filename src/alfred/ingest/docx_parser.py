"""Baseline DOCX parser: paragraphs, lists and tables in document order, via python-docx.

A DOCX file has no fixed pages: where page breaks fall depends on the viewer. So the
document is split into sections instead. A new section starts at every heading, and also
whenever a section would grow past about one printed page. Many real documents use no
heading styles at all (headings are just bold or plain text), so without the size cap the
whole file would become one section, and every citation would read "section 1".
"""

import re
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from docx import Document as open_docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from alfred.ingest.errors import IngestError, TooManyPagesError
from alfred.ingest.issues import MATH_NS, equation_issue, visual_issue
from alfred.ingest.models import Block, BlockKind, Page
from alfred.ingest.text import clean_text

PARSER_NAME = f"python-docx-{version('python-docx')}"

# About one printed page. Sections are only ever split between paragraphs, so a single
# longer paragraph or table stays whole (quotes used in citations must not be cut).
MAX_SECTION_CHARS = 3000

_TRAILING_NUMBER = re.compile(r"(\d+)$")


@dataclass(frozen=True)
class _Piece:
    """One paragraph or table, with what it contains that can't be extracted."""

    block: Block | None
    visuals: int = 0
    equations: int = 0

    @property
    def size(self) -> int:
        return len(self.block.text) if self.block else 0


def parse_docx(path: Path, max_pages: int) -> tuple[Page, ...]:
    try:
        document = open_docx(str(path))
    except Exception as e:  # untrusted input: any failure to parse becomes a user-facing error
        raise IngestError(f"Could not open {path.name}: {e}") from e

    pieces = [_to_piece(item) for item in document.iter_inner_content()]
    sections = _split_into_sections(pieces)
    if len(sections) > max_pages:
        raise TooManyPagesError(
            f"{path.name} splits into {len(sections)} sections; the limit is {max_pages}"
        )
    return tuple(_to_page(n, section) for n, section in enumerate(sections, start=1))


def _split_into_sections(pieces: list[_Piece]) -> list[list[_Piece]]:
    sections: list[list[_Piece]] = []
    current: list[_Piece] = []
    for piece in pieces:
        is_heading = piece.block is not None and piece.block.kind is BlockKind.TITLE
        too_long = sum(p.size for p in current) + piece.size > MAX_SECTION_CHARS
        if current and is_heading:
            sections.append(current)
            current = []
        elif current and too_long:
            # "Keep with next": a heading-like last line moves along with its content.
            carried = (
                [current.pop()] if len(current) > 1 and _looks_like_heading(current[-1]) else []
            )
            sections.append(current)
            current = carried
        current.append(piece)
    if current:
        sections.append(current)
    return sections


def _looks_like_heading(piece: _Piece) -> bool:
    """A short, unstyled line such as "Part III: Application Problems (30%)"."""
    if piece.block is None or piece.block.kind is not BlockKind.TEXT:
        return False
    text = piece.block.text
    return len(text) < 80 and not text.lstrip().startswith("- ") and not text.endswith(".")


def _to_page(number: int, section: list[_Piece]) -> Page:
    issues: list[str] = []
    if visuals := sum(p.visuals for p in section):
        issues.append(visual_issue(visuals))
    if equations := sum(p.equations for p in section):
        issues.append(equation_issue(equations))
    blocks = tuple(p.block for p in section if p.block)
    return Page(number=number, blocks=blocks, issues=tuple(issues))


def _to_piece(item: Paragraph | Table) -> _Piece:
    element = item._element  # the underlying XML, for what python-docx has no API for
    visuals = sum(1 for _ in element.iter(qn("w:drawing"), qn("w:pict")))
    equations = len(element.findall(f".//{{{MATH_NS}}}oMath"))
    block = _table_block(item) if isinstance(item, Table) else _paragraph_block(item)
    return _Piece(block=block, visuals=visuals, equations=equations)


def _paragraph_block(paragraph: Paragraph) -> Block | None:
    text = clean_text(paragraph.text)
    if not text:
        return None
    if _is_heading(paragraph):
        return Block(kind=BlockKind.TITLE, text=text)
    level = _list_level(paragraph)
    if level is not None:
        text = "  " * level + "- " + text
    return Block(kind=BlockKind.TEXT, text=text)


def _table_block(table: Table) -> Block | None:
    rows: list[str] = []
    for row in table.rows:
        cells = []
        previous = None
        for cell in row.cells:
            if previous is not None and cell._tc is previous._tc:
                continue  # a merged cell is returned once per grid column it spans
            cells.append(" ".join(cell.text.split()))
            previous = cell
        rows.append(" | ".join(cells))
    text = clean_text("\n".join(rows))
    return Block(kind=BlockKind.TABLE, text=text) if text else None


def _style_name(paragraph: Paragraph) -> str:
    return (paragraph.style.name if paragraph.style else None) or ""


def _is_heading(paragraph: Paragraph) -> bool:
    # Built-in style names; documents created in a localized Word may use other names.
    name = _style_name(paragraph)
    return name == "Title" or name.startswith("Heading")


def _list_level(paragraph: Paragraph) -> int | None:
    """Nesting level of a list item (0 = top level), or None if it isn't one."""
    if paragraph._p.xpath("./w:pPr/w:numPr"):  # numbering set on the paragraph itself
        levels = paragraph._p.xpath("./w:pPr/w:numPr/w:ilvl/@w:val")
        return int(levels[0]) if levels else 0
    name = _style_name(paragraph)
    if name.startswith("List"):  # numbering inherited from a style like "List Bullet 2"
        match = _TRAILING_NUMBER.search(name)
        return int(match.group(1)) - 1 if match else 0
    return None
