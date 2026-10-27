# Question rubric

How a generated question is judged by hand. These labels are the ground truth for comparing
prompts and models, and later for calibrating an LLM judge (Phase 4), so each criterion is a
yes/no call that two people would usually agree on.

Only questions that passed the code checks are labeled. Those checks already confirm the
quote is on the cited page, there are 4 distinct options, and so on. The rubric covers what
code can't judge.

## Criteria

Judge against the cited page as it looks (the slide or PDF page itself), not the extracted
text: a question built on a misread page is wrong even if it matches the text.

1. **correct**: the answer key is right according to the cited page.
2. **supported**: a student who reads the cited page can confirm the answer from it,
   without outside knowledge. The quote must be on the page (code checks that) and also be
   what the answer depends on (code can't check that).
3. **unambiguous**: exactly one answer is defensible. For true/false, the statement is
   clearly true or clearly false, not "true except for ...". No trick wording or double
   negatives.
4. **distractors** (multiple choice only): every wrong option is plausible to someone who
   hasn't learned the material, and none gives itself away (much shorter or longer than the
   answer, a different type of thing, or a joke).
5. **worth studying**: it tests something the course expects a student to know, not
   trivia: slide titles, exact wording, image credits, logistics or the instructor's jokes.
6. **bloom**: your own band, chosen before you look at the model's:
   - remember: recall a fact or definition.
   - understand_apply: explain a concept, or use it on a new example.
   - analyze_evaluate: compare, find causes, or judge between options.

**Verdict:** a question is **good** when criteria 1 to 5 all pass. A question that fails
correct or supported is a **bad** question, the kind a student must never see. Any other
failure makes it **weak**.

## Tags

Tags are optional and explain a failure or something worth counting. Add new ones when a
pattern comes up.

- `outdated`: faithful to the page, but the page is no longer true.
- `diagram`: the answer comes from a diagram, chart or formula image.
- `answer-in-stem`: the question gives away its own answer.
- `too-easy`: answerable by common sense, without the course.
- `off-topic-tag`: the topic_ids don't match what the question tests.

## How to label

```bash
uv run alfred generate data/private/lecture.pptx --out data/private/lecture-questions.json
uv run alfred label data/private/lecture-questions.json    # resumable: q stops, labels are kept
uv run alfred eval questions                             # summary of all labels so far
```

- Label about 100 questions, from at least 3 documents and both question types.
- Label every question in a generated set, not only the interesting ones, so the rates are
  honest.
- Open the cited page next to the question. It takes about a minute per question.
- Write a note for every failure: one line saying what's wrong.

## What's stored

Course files and generated questions stay in `data/private/` (git-ignored), because the
questions quote the course. `labels.jsonl` in this folder holds only judgments. Each label
points to its question by an id derived from the question text and the document's
SHA-256, so the repo never contains course text.
