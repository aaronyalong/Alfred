"""The normalized document format that every parser produces.

Everything downstream (generation, citation checks, the UI) works with these types only,
never with the original file format.
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class SourceFormat(StrEnum):
    PDF = "pdf"
    PPTX = "pptx"
    DOCX = "docx"


class Unit(StrEnum):
    """What one citable `Page` corresponds to in the original file."""

    PAGE = "page"  # PDF page
    SLIDE = "slide"  # PPTX slide
    SECTION = "section"  # DOCX has no fixed pages, so it is split at headings


class BlockKind(StrEnum):
    TITLE = "title"
    TEXT = "text"
    TABLE = "table"
    FORMULA = "formula"  # LaTeX, when an engine can transcribe formulas
    NOTES = "notes"  # PPTX speaker notes


class _Frozen(BaseModel):
    # Immutable and strict: parsed documents are shared by many steps, none may modify them.
    model_config = ConfigDict(frozen=True, extra="forbid")


class Block(_Frozen):
    kind: BlockKind
    text: str


class Page(_Frozen):
    """One citable unit of a document: a PDF page, a slide, or a DOCX section."""

    number: int  # 1-based, the way a person would cite it
    blocks: tuple[Block, ...] = ()
    issues: tuple[str, ...] = ()  # extraction problems, shown to the user as warnings

    @property
    def text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks)


class Document(_Frozen):
    source_name: str
    source_sha256: str  # identifies the file in eval labels without committing the file
    format: SourceFormat
    unit: Unit
    parser: str  # name and version, so benchmark results stay traceable
    pages: tuple[Page, ...]

    @model_validator(mode="after")
    def _pages_numbered_in_order(self) -> Self:
        numbers = [page.number for page in self.pages]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(f"pages must be numbered 1..n in order, got {numbers[:10]}")
        return self

    def page(self, number: int) -> Page:
        """Look up a page by its 1-based number, as cited in a question."""
        if not 1 <= number <= len(self.pages):
            raise KeyError(f"{self.source_name} has no {self.unit} {number}")
        return self.pages[number - 1]
