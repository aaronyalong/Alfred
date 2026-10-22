# Devlog

Decisions, experiments and results, newest first. Negative results are recorded too.

---

## 2026-10-21: Normalized document format and baseline PDF parser

**Done:** every parser now outputs the same immutable `Document → Page → Block` structure.
File types are detected from their content rather than the extension. Size and page limits are
checked before parsing. A baseline PDF parser reads each page's text layer.

**Decisions**

- **pypdfium2 instead of PyMuPDF.** Both are fast and accurate, but PyMuPDF is AGPL-licensed,
  which would impose its terms on the whole deployed web app. pypdfium2 (Chrome's PDFium) is
  Apache/BSD-licensed.
- **"Page" means one citable unit:** a PDF page, a slide, or, for DOCX (which has no fixed
  pages), a section split at headings. `Document.unit` records which, so citations can read
  "slide 12" or "section 3".
- **No Unicode normalization.** NFKC would clean up ligatures but also turn `x²` into `x2`.
  Only whitespace is normalized.
- **Tests generate their own PDFs.** Real course files can't be committed, so CI couldn't run
  tests that depend on them.

**First look at a real file** (a 60-page NLP review deck, exported to PDF):

- Text was extracted from all 60 pages in well under a second, and no page was flagged as
  missing a text layer.
- **Formulas are lost.** A slide on cosine similarity keeps its sentence ("based on the
  definition of the dot product…") but not the formula, which is drawn as an image or
  vector graphic. This is the main thing the docling and vision comparisons need to measure.
- **The "no text" check has a blind spot.** An image-only slide whose only text is a photo
  credit (58 characters) passes the 20-character threshold. Character count alone can't tell
  real content from a caption.
- **Repeated text is minor.** Only section labels like "BLOCK 2 · N-GRAM LANGUAGE MODELS"
  repeat, and they're useful topic context, not noise. No header/footer stripping is needed
  for now.

---

## 2026-10-20: Project setup

**Done:** repository tooling. uv for environments and locking, ruff for lint and formatting,
pyright for type checking, pytest, pre-commit hooks, and GitHub Actions CI running all of them.

**Decisions**

- **Python 3.13, not 3.14.** Document-parsing and ML libraries ship wheels for new Python
  versions late. 3.13 avoids building them from source. Revisit once the parsing stack is chosen.
- **Single Python package at the repo root (`src/alfred`), frontend later in its own folder.**
  The Python core is most of the project, and keeping it at the root keeps CI and hooks simple.
  The alternative, `backend/` + `frontend/` folders, mainly helps when both sides are equally large.
- **Safety checks in pre-commit *and* CI.** Hooks block Anthropic API keys and course files
  (PDF/PPTX/DOCX) from being committed. CI re-runs them, because local hooks can be skipped.
- **Settings via pydantic-settings with `SecretStr`.** The API key comes from the environment or a
  git-ignored `.env`, and is masked whenever settings are printed or logged.

---

## 2026-10-20: Scope and architecture

**Goal:** generate practice questions from course files, where every question is schema-valid,
cites its source page and quote, and has an answer key that can be checked.

**Decisions**

- **Functional core, thin shells.** All logic (ingestion, generation, checks, scoring) lives in a
  plain Python library. The API, background worker and evaluation scripts only call into it, so
  the evaluation runs exactly the code that production runs.
- **No retrieval (RAG) to start.** A lecture deck is ~10–20K tokens and fits in context. Prompt
  caching makes reusing it cheap. Retrieval will be added only if whole-course inputs show a
  measured quality or cost problem.
- **Structured outputs + our own citation check.** The Claude API's built-in citations can't be
  combined with structured (schema-constrained) outputs. So the model returns `{page, quote}` as
  schema fields, and plain code checks that the quote really appears on that page.
- **Difficulty as three Bloom bands:** remember, understand/apply, analyze/evaluate. Even human
  labelers disagree a lot on the full six-level scale, and a label that can't be applied
  consistently can't be evaluated.
- **Command-line pipeline and evaluation before the web UI.** Question quality gets measured
  before a UI is built around it.
- **Job queue as a Postgres table, not Celery + Redis.** Generation takes too long for a request,
  but at this scale an extra queue service adds infrastructure without benefit.

**Open questions, to be answered with measurements**

- Ingestion: docling vs. a PyMuPDF/python-pptx baseline vs. sending PDFs to Claude directly.
- Model choice for generation and for the LLM judge, on quality vs. cost.
- Whether a verification step improves answer-key accuracy enough to justify its cost.
