# Devlog

Decisions, experiments and results, newest first. Negative results are recorded too.

---

## 2026-10-25: Vision engine: Claude reads the flagged pages

**Setup:** the new `vision` engine runs the baseline everywhere and sends only the pages it
flagged to Claude (Opus 5.5, effort `medium`): a PDF page rendered as an image, or a slide's
large pictures, plus the text already extracted. Claude returns only what's missing, as
structured blocks: formulas in LaTeX, diagrams as a description followed by their labels.
Same 37 facts and scorer as before. The prompt was written without looking at the facts.

| engine | all facts | text | table | formula | diagram | time (79 pages) | cost |
|---|---|---|---|---|---|---|---|
| baseline | 10/37 (27%) | 5/5 | 3/3 | 1/13 | 1/16 | **0.2 s** | 0 |
| docling-formulas | 21/37 (57%) | 5/5 | 3/3 | 10/13 | 3/16 | 143 s | 0 |
| vision | **37/37 (100%)** | 5/5 | 3/3 | **13/13** | **16/16** | 42 s | $0.47 |

29 pages were flagged (13 PDF pages, 16 slides), so 29 calls: **1.6¢ per flagged page**,
about 0.6¢ per page over both files. Four calls run in parallel, so the time is wall-clock,
not compute. All 29 were answered by Opus 5.5 (no refusals, no fallbacks).

**100% made me suspicious, so I checked by eye.** The scorer only checks that a fact is
present; it can't see a wrong formula next to it. A second run, saved outside the repo,
also scored 37/37. On that run I compared the output against the page images:

- **Formulas were exact**, including the attention-mask slide where docling had produced
  `\max` instead of `\text{mask}`.
- **Diagrams were described by structure, not just labels.** The blue/green deployment
  slide came back as "Service CNAME routes the live deployment to Blue, the pending one to
  Green; Chef provisions both AMIs". The vector-angle exercise had angles within a few
  degrees. The LSTM diagram's gates were described correctly.
- **One completion beyond what's printed:** a label cut off as "SSH Basi" in the image came
  back as "SSH Bastion". It's right, but it isn't verbatim.
- **Jokes are transcribed as content.** Page 2's comic and "Final Exams" Venn diagram came
  back as diagram blocks. Question generation will have to ignore decoration.

**Decision: vision is the extractor for flagged pages.** It beats docling-formulas on every
kind of page, at 1/3 of the time, for about half a cent per page. docling stays an optional
extra for now, but nothing depends on it.

**What this doesn't show:** the benchmark is now saturated, so it can't tell vision
configurations apart (a cheaper model, lower effort). It needs harder pages: a scan, a
math-heavy deck, and a review of the labels themselves. Each run costs money and re-reads
every file, so results should be cached by file hash before this is used outside the
benchmark.

---

## 2026-10-22: Ingestion benchmark: first results

**Setup:** `alfred eval ingestion` scores each engine on the 37 hand-written facts
(13 pages: an NLP review PDF and a cloud architecture PPTX). A fact counts only if it is
found on its labeled page. Models are loaded before timing starts. Scores are in
`evals/ingestion/results.json` (no course text, just found/missed per fact).

| engine | all facts | text | table | formula | diagram | time (79 pages) |
|---|---|---|---|---|---|---|
| baseline | 10/37 (27%) | 5/5 | 3/3 | 1/13 | 1/16 | **0.4 s** |
| docling | 14/37 (38%) | 5/5 | 3/3 | 3/13 | 3/16 | 61 s |
| docling-formulas | **21/37 (57%)** | 5/5 | 3/3 | **10/13** | 3/16 | 154 s |

Per PDF page, docling takes ~1.0 s and docling-formulas ~2.5 s (PPTX takes under 1 s
in total), and docling needs ~3 GB of RAM.

**Scorer fix after the first run, disclosed.** The first run gave docling-formulas 9/13
on formulas. One miss was the scorer's fault: the model wrote `w_{1 \colon k-1}`, and
`\colon` *is* a colon in LaTeX. The normalizer now maps `\colon` → `:` (and `\mid` → `|`,
the same kind of equivalence). The fix applies to all engines, and only this one fact
changed. Other near misses were deliberately **not** "fixed", e.g. `\cos` where the slide
says "cosine".

**What the numbers say:**

1. **Text and tables: the baseline is already perfect** (8/8 facts, about 400× faster).
   docling adds nothing on these pages.
2. **Formulas: docling-formulas is the clear winner (10/13 vs 1/13),** but its errors
   change meaning. On the attention-mask slide it read `\text{mask}` as `\max`, giving
   `softmax(max(QKᵀ/√d_k))`. A question generated from that would teach something wrong.
   Every formula extraction will need verification downstream.
3. **Diagrams: nobody solves them (≤3/16).** On the PPTX, all engines score 1/13, because
   docling doesn't OCR images in PPTX at all. On the PDF attention diagram, docling's OCR
   recovers some labels but mixed with garbage (`ndut`, `Inpdut`, `二`, `N×4p`). For the
   cloud course, where diagrams *are* the content, this is the biggest gap.

**Decision: route pages, don't pick one parser.** Running docling-formulas on every page
costs ~400× the baseline, for no gain on text and tables. The baseline's own page flags
(vector drawings, large images) mark exactly the pages where it fails: 13 of 60 in the
NLP PDF. So: baseline everywhere, and a heavier extractor only on flagged pages.

**Which heavier extractor isn't decided yet.** docling-formulas handles formulas but not
diagrams. Next experiment: render flagged pages and slide pictures to images and have
Claude read them, scored on the same labels. It may handle both formulas and diagrams,
and it can describe a diagram's *structure* (e.g. blue/green deployment), not just its
labels. It costs money per page, which the benchmark will measure.

**Caveats:** 13 pages, 37 facts, two files from two courses. The numbers show direction,
not precise rates. More files are needed, especially a scan, a math-heavy ML deck, and
a deck with real speaker notes.

---

## 2026-10-22: docling as a second ingestion engine

**Done:** `ingest(..., engine=...)` and `alfred ingest --engine` select `baseline` (default),
`docling`, or `docling-formulas`. All three produce the same `Document`, which is what makes
them comparable. docling is an optional extra (`uv sync --extra docling`), imported only
when used, so CI and the core install never load PyTorch.

**Setup lesson: CPU-only PyTorch.** No CUDA GPU here (AMD integrated graphics), but on
Linux the default PyTorch wheels bundle NVIDIA CUDA libraries. The first attempt pointed
torch at PyTorch's CPU index via `[tool.uv.sources]`, and uv downloaded the CUDA build anyway.
Reason: **uv only applies sources to direct dependencies**, and torch was transitive
(docling → torch). Listing `torch` and `torchvision` directly in the extra fixed it: 0
NVIDIA packages in the lockfile, and a 1.5 GB environment.

**First observations, before the benchmark:**

- **PDF:** a layout model per page finds titles (as section headers), tables, formulas,
  pictures, and running headers/footers (dropped as noise). Full 60-page PDF: **70 s and
  3.1 GB RAM**, vs. 0.5 s for the baseline. A deployed docling worker needs ≥4 GB RAM.
- **Formulas are located but empty by default.** Transcribing them needs a second model
  (`docling-formulas`): page 30 went from 2.1 s to 13.9 s, and the cosine formula came back
  as LaTeX. One transcription error: `\cos` where the slide says "cosine".
- **docling flags formulas on 6 pages the baseline never flagged** (20, 23, 25, 28, 38,
  44). The baseline extracts those as text, possibly garbled; the benchmark will tell.
- **PPTX: no gain (negative result).** 0.4 s, slide numbers kept, but all 16 diagrams come
  back as empty pictures (no OCR outside the PDF pipeline), and no titles are detected.
- **DOCX: unsupported.** docling's DOCX output has no page or position information on any
  of its 131 items, so nothing it extracts could be cited. DOCX stays with the baseline.

**Benchmark labels committed before any benchmark run.** `evals/ingestion/labels.toml`
lists 37 facts across 13 pages (text, table, formula and diagram pages), written from
rendered page images. Committing them before the results exist means the git history
shows they weren't tuned to any engine's output.

---

## 2026-10-22: PDF pages with images and vector drawings are flagged

**Problem:** on the 60-page NLP review PDF, the baseline flagged **0 pages**, yet formulas and
diagrams were clearly missing (e.g. a cosine-similarity slide kept its sentence but lost
the formula).

**Measured first.** Counting the PDF objects on each page showed two kinds of hidden content:

- **Raster images:** 8 pages have an image covering ≥10% of the page.
- **Vector drawings:** 6 pages each draw **2,381–5,797 path objects**. All 6 turned out to
  be formulas or diagrams drawn as outline shapes instead of text: the bigram
  approximation, log probabilities, the cosine formula, the attention mask matrix, an
  attention diagram exercise, and the temperature formula. Every other page draws at most
  ~60 paths (lines, boxes, underlines).

**Rules:** flag images covering ≥10% of the page (the same threshold as PPTX, now shared),
and flag pages with ≥500 vector paths. With a 40× gap between ordinary pages and
formula pages, 500 sits safely in between. **Result: 13 of 60 pages flagged, up from 0**,
including the photo-credit-only slide the earlier character-count check missed. The 6
vector pages were checked by hand; the image pages weren't, individually.

**Bug found on the way:** PDFium marks a hyphen at a line break with the non-character
U+FFFE ("n￾grams"). Both occurrences in the file were real hyphens ("n-grams",
"low-probability"), so U+FFFE now becomes "-". Dropping it would produce "ngrams", which
also breaks quote matching later.

**What this means for the benchmark:** about 1 in 5 pages of an NLP lecture has content
that text extraction can't see. The question for docling and for the vision experiment is
how much of that they recover, and at what cost.

---

## 2026-10-21: Baseline DOCX parser

**Done:** DOCX files parse into sections, with paragraphs, nested list items (`- `, indented
by level) and tables, in document order. Images and equations are flagged per section.

**The plan didn't survive the first real file.** The plan was to split DOCX at headings,
because Word documents have no fixed pages. The first real file (a 3-page exam review)
uses **no heading styles at all**: 83 "Normal" and 45 "List Paragraph" paragraphs. Its
headings are plain or bold text, with no page breaks. Splitting at headings would have made
the whole file one section, and every citation would have read "section 1".

**Decision: headings when present, plus a size cap.** A new section starts at every heading
*and* whenever a section would grow past ~3,000 characters (about one printed page),
always between paragraphs, so quotes are never cut. One rule covers both well-structured
and hand-formatted documents. Alternatives rejected:

- *Bold short lines as headings:* fragile. It would have picked the letterhead ("San Jose
  State University") and missed the "Part II" and "Part III" headings, which aren't bold.
- *Converting to PDF via LibreOffice for real page numbers:* a ~500 MB dependency, and its
  page breaks don't match Word's anyway.

The citation's quote, not the section number, is what a student uses to find the spot.

**"Keep with next."** The size split first ended section 2 with the line "Part III:
Application Problems and Solutions (30%)" and started section 3 with that part's content.
Now a short, heading-like last line (under 80 chars, not a list item, no final period) moves
into the next section. Result on the real file: 3 sections, each starting where a reader
would expect.

**Product insight: this document isn't lecture content, it's an exam scope.** It lists
which subjects the final covers and how much each part weighs. Generating questions *from*
it would produce questions about the exam format. It is far more useful as *guidance*,
steering which lecture topics get questions and with what weight. Files may therefore need
a role, *course material* vs. *exam scope / instructions*. To be designed in Phase 2/3.

---

## 2026-10-21: `alfred ingest` command, and the first real PPTX

**Done:** `alfred ingest <file> [--page N] [--json]` prints a summary, page issues and every
block, or the full `Document` as JSON (useful for saving and diffing parser output later).
It uses argparse from the standard library; a CLI framework isn't worth a dependency for
one command.

**First real deck** (19-slide cloud architecture lecture, parsed in under 0.5 s):

- **The "image-only slide" rule was wrong: it flagged 1 of 16 diagram slides.** It only fired
  when a slide had almost no text, but most diagram slides also have a sentence or two of
  text. Measured: every picture in the deck covers 27–60% of its slide, and these diagrams
  *are* the lecture content.
  **Fix:** flag every picture or chart covering at least 10% of the slide, whatever the amount
  of text. Result: 16 of 16 diagram slides flagged, and small icons are still ignored.
- **No title blocks were found.** The deck uses no title placeholders: every slide is a blank
  layout with text boxes, and the title is just the first line of the first box. Detecting
  titles from placeholders only works for decks built from the template's layouts. I'm not
  adding a heuristic (e.g. font size) yet. Generation sees the text either way, and the
  docling comparison will show whether layout-based title detection does better.
- **No speaker notes in this deck**, so that feature is still untested on real data.

**Takeaway for the course:** in this deck, most of the content is diagrams. For cloud
lectures, extracting text alone loses most of what matters, so the vision experiment
(sending slide images to Claude) matters more than expected.

---

## 2026-10-21: Baseline PPTX parser

**Done:** PPTX files parse into one `Page` per slide, with titles, nested bullets, tables
and speaker notes kept as separate blocks. This structure is lost when a deck is exported to PDF.

**Decisions**

- **Reading order is reconstructed.** PowerPoint stores shapes in stacking order (the order
  they were added), not reading order. Blocks are sorted title first, then top to bottom and
  left to right.
- **Hidden slides are kept and flagged, not dropped.** Dropping them would shift every later
  slide number, and citations would point at the wrong slide.
- **Speaker notes are their own block kind.** Lecturers often explain the slide there, so they
  are useful context. Keeping them separate lets later steps decide whether a question may be
  based on notes the student never saw on the slide.
- **What isn't extracted is flagged, not silently dropped.** Equations (stored as Office
  Math), charts, SmartArt and images produce page issues instead of missing content.
  PowerPoint equations are structured XML, so unlike in a PDF export they *can* be
  extracted. That is a candidate improvement once a real deck with formulas is available.
- **Unpacked-size limit for PPTX/DOCX.** Both are zip archives, and python-pptx loads every
  part into memory. A 200 MB cap on the total unpacked size stops zip bombs before parsing.

**Not yet validated on a real deck.** All tests use generated presentations.

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
