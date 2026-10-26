# Alfred

Alfred turns course materials (lecture slides, PDFs, Word documents, scanned handouts) into
practice material: multiple-choice and true/false quizzes, short-answer questions, flashcards and
full practice tests. Every question comes with an answer key, an explanation, a difficulty level
and the exact page and quote it was generated from.

## How it works

```
upload ─▶ ingest ─▶ topic map ─▶ generate ─▶ check ─▶ verify ─▶ quiz ─▶ track mistakes
          (PDF,      (per         (schema-     (code:     (LLM:
          PPTX,      document)    validated    quotes,    answers
          DOCX,                   JSON)        options)   independently)
          OCR)
```

1. **Ingest:** every file format is normalized into the same page-anchored document structure,
   so everything downstream is format-agnostic.
2. **Topic map:** a fixed list of topics per document, so questions are tagged consistently and
   mistakes can be tracked per topic.
3. **Generate:** questions are produced as JSON validated against Pydantic models, never parsed
   from free text.
4. **Check:** deterministic code verifies that each cited quote actually appears on the cited page
   and that options are well-formed.
5. **Verify:** a second model call answers each question from the cited page alone; questions
   whose answer key it cannot confirm are regenerated.

## Tech stack

Python 3.13 · Pydantic · Claude API · FastAPI · PostgreSQL · React + TypeScript · Docker

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                          # create .venv and install dependencies
uv sync --extra docling          # optional: the docling ingestion engine (PyTorch, CPU-only)
uv run pre-commit install        # run lint and safety checks on every commit
cp .env.example .env             # then add your Anthropic API key
uv run pytest                    # tests
uv run ruff check . && uv run pyright
```

Course materials go in `data/private/`, which is git-ignored. A pre-commit hook blocks
committing PDF, PPTX and DOCX files anywhere else.

## Academic integrity

Alfred is a study tool for practicing on your own course materials. It is not meant for graded
work, and its output should not be submitted as such.
