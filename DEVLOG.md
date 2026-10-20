# Devlog

Decisions, experiments and results, newest first. Negative results are recorded too.

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
