"""Ingestion benchmark: how many labeled facts each engine extracts, on the right page.

The labels (evals/ingestion/labels.toml) list, per page, facts a good extraction must
contain. A fact counts as found only if it appears on the labeled page, after both sides
are normalized so that LaTeX and Unicode spellings of the same formula compare equal.
"""

import hashlib
import re
import time
import tomllib
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from alfred.ingest import Document, Engine, IngestError, docling_parser, ingest
from alfred.ingest.vision import VisionCache, VisionReader

Kind = Literal["text", "table", "formula", "diagram"]

# --- Normalization ---------------------------------------------------------------------------

# LaTeX commands that only change appearance: "\mathrm{softmax}" and "softmax" are the same.
_LATEX_STYLING = re.compile(
    r"\\(left|right|mathrm|mathbf|mathit|operatorname|boldsymbol|vec|textbf|text|bf|rm"
    r"|bigl|bigr|Bigl|Bigr|big|Big|cdot)(?![a-zA-Z])"
)
# LaTeX commands that ARE punctuation: "w_{1 \colon k}" means "w_{1:k}".
_LATEX_PUNCTUATION = {"\\colon": ":", "\\mid": "|"}
# Unicode math symbols, spelled as the LaTeX command names a formula model would output.
# Characters that look like ASCII ones are written as escapes, so the table is unambiguous.
_SYMBOL_NAMES = {
    "τ": "tau", "θ": "theta", "∞": "infty", "√": "sqrt", "≤": "leq", "≥": "geq",
    "≈": "approx", "∏": "prod", "∑": "sum",
    "\u00d7": "times",  # multiplication sign
    "\u2212": "-",  # minus sign
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "·": "", "⋅": "", "∙": "", "•": "",  # multiplication dots: dropped, like \cdot
}  # fmt: skip
# Whitespace and notation that differs between extractors without changing the meaning.
_IGNORED = re.compile(r"[\s\\{}_^$|]")


def normalize(text: str) -> str:
    for command, char in _LATEX_PUNCTUATION.items():
        text = text.replace(command, char)
    text = _LATEX_STYLING.sub("", text)
    for symbol, name in _SYMBOL_NAMES.items():
        text = text.replace(symbol, name)
    return _IGNORED.sub("", text.lower())


# --- Labels ----------------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LabeledFile(_Strict):
    name: str
    sha256: str


class LabeledPage(_Strict):
    file: str
    page: int
    kind: Kind
    facts: list[list[str]]  # each fact: accepted spellings, any one counts

    @field_validator("facts")
    @classmethod
    def _facts_are_not_empty(cls, facts: list[list[str]]) -> list[list[str]]:
        for spellings in facts:
            if not spellings or not all(normalize(s) for s in spellings):
                raise ValueError(f"empty fact or spelling: {spellings}")
        return facts

    def found_in(self, page_text: str) -> list[bool]:
        text = normalize(page_text)
        return [any(normalize(s) in text for s in spellings) for spellings in self.facts]


class Labels(_Strict):
    files: list[LabeledFile]
    pages: list[LabeledPage]

    @model_validator(mode="after")
    def _pages_refer_to_known_files(self) -> "Labels":
        known = {f.name for f in self.files}
        for page in self.pages:
            if page.file not in known:
                raise ValueError(f"page {page.page} refers to unknown file {page.file!r}")
        return self


def load_labels(path: Path) -> Labels:
    return Labels.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))


# --- Results ---------------------------------------------------------------------------------


class PageResult(_Strict):
    file: str
    page: int
    kind: Kind
    found: list[bool]


class EngineResult(_Strict):
    engine: Engine
    parsers: list[str]
    seconds: float  # parsing time for all labeled files, models already loaded
    pages_parsed: int
    pages: list[PageResult]
    errors: list[str]
    api_calls: int = 0  # vision model calls; each one costs money
    cached_pages: int = 0  # vision readings reused from the cache, at no cost
    cost_usd: float | None = None  # None when unknown, e.g. a fallback model without a price

    def recall(self, kind: Kind | None = None) -> tuple[int, int]:
        """(facts found, facts labeled), optionally for one kind of page."""
        found = [f for p in self.pages if kind in (None, p.kind) for f in p.found]
        return sum(found), len(found)


class Report(_Strict):
    run_at: datetime
    engines: list[EngineResult]


# --- Running ---------------------------------------------------------------------------------


class BenchmarkError(Exception):
    """The benchmark can't run fairly, e.g. a labeled file is missing or has changed."""


def locate_files(labels: Labels, data_dir: Path) -> dict[str, Path]:
    """Find each labeled file in data_dir and check it is the exact version that was labeled."""
    located: dict[str, Path] = {}
    for labeled in labels.files:
        matches = [p for p in data_dir.rglob(labeled.name) if p.is_file()]
        if not matches:
            raise BenchmarkError(f"{labeled.name} not found in {data_dir}")
        with matches[0].open("rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
        if digest != labeled.sha256:
            raise BenchmarkError(
                f"{labeled.name} has changed since it was labeled (sha256 differs)"
            )
        located[labeled.name] = matches[0]
    return located


def run_engine(
    engine: Engine, labels: Labels, files: dict[str, Path], cache: VisionCache | None = None
) -> EngineResult:
    vision = VisionReader(cache=cache) if engine is Engine.VISION else None
    if engine in (Engine.DOCLING, Engine.DOCLING_FORMULAS):
        docling_parser.warm_up(formulas=engine is Engine.DOCLING_FORMULAS)

    documents: dict[str, Document] = {}
    errors: list[str] = []
    started = time.perf_counter()
    for name, path in files.items():
        try:
            documents[name] = ingest(path, engine=engine, vision=vision)
        except IngestError as e:
            errors.append(f"{name}: {e}")
    seconds = time.perf_counter() - started

    pages: list[PageResult] = []
    for labeled in labels.pages:
        document = documents.get(labeled.file)
        text = document.page(labeled.page).text if document else ""
        found = labeled.found_in(text) if document else [False] * len(labeled.facts)
        pages.append(
            PageResult(file=labeled.file, page=labeled.page, kind=labeled.kind, found=found)
        )

    return EngineResult(
        engine=engine,
        parsers=sorted({d.parser for d in documents.values()}),
        seconds=round(seconds, 2),
        pages_parsed=sum(len(d.pages) for d in documents.values()),
        pages=pages,
        errors=errors,
        api_calls=vision.usage.calls if vision else 0,
        cached_pages=vision.usage.cached if vision else 0,
        cost_usd=round(vision.usage.cost_usd, 4) if vision and vision.usage.cost_usd else None,
    )


def run(
    labels: Labels, data_dir: Path, engines: list[Engine], cache: VisionCache | None = None
) -> Report:
    files = locate_files(labels, data_dir)
    return Report(
        run_at=datetime.now(UTC).replace(microsecond=0),
        engines=[run_engine(engine, labels, files, cache) for engine in engines],
    )


# --- Reporting -------------------------------------------------------------------------------

KINDS: tuple[Kind, ...] = ("text", "table", "formula", "diagram")


def render(report: Report) -> str:
    """A summary table per engine, then facts found per labeled page."""

    def ratio(found: int, total: int) -> str:
        return f"{found}/{total}" if total else "-"

    header = f"{'engine':<18}{'all facts':>14}" + "".join(f"{k:>10}" for k in KINDS)
    lines = [header + f"{'s/page':>9}", "-" * (len(header) + 9)]
    for result in report.engines:
        found, total = result.recall()
        overall = f"{ratio(found, total)} {100 * found / total:.0f}%" if total else "-"
        per_kind = "".join(f"{ratio(*result.recall(k)):>10}" for k in KINDS)
        per_page = result.seconds / result.pages_parsed if result.pages_parsed else 0
        lines.append(f"{result.engine:<18}{overall:>14}{per_kind}{per_page:>9.2f}")

    lines += ["", f"{'page':<44}{'kind':<9}" + "".join(f"{e.engine:>18}" for e in report.engines)]
    by_page: dict[tuple[str, int], list[PageResult]] = defaultdict(list)
    for result in report.engines:
        for page in result.pages:
            by_page[(page.file, page.page)].append(page)
    for (file, number), results in by_page.items():
        cells = "".join(f"{ratio(sum(r.found), len(r.found)):>18}" for r in results)
        lines.append(f"{file[:36] + ' p.' + str(number):<44}{results[0].kind:<9}{cells}")

    for result in report.engines:
        if not (result.api_calls or result.cached_pages):
            continue
        if not result.api_calls:
            cost = "$0.00"
        elif result.cost_usd is None:
            cost = "unknown cost"
        else:
            cost = f"${result.cost_usd:.2f}, ${result.cost_usd / result.api_calls:.3f} per call"
        cached = f" ({result.cached_pages} pages from cache)" if result.cached_pages else ""
        lines += ["", f"{result.engine}: {result.api_calls} API calls, {cost}{cached}"]
    for result in report.engines:
        lines += [f"error ({result.engine}): {error}" for error in result.errors]
    return "\n".join(lines)
