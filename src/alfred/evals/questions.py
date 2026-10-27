"""Question labels: hand judgments of generated questions, by the rubric in evals/questions.

Labels hold only judgments, never course text: each points to its question by an id hashed
from the question, and the questions themselves stay in data/private. A labeling session
appends each label as soon as it's made, so it can be stopped and resumed at any time.
"""

import hashlib
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Literal, TextIO

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from alfred.questions import Bloom, MultipleChoice, Question, QuestionSet
from alfred.questions.checks import normalize

Verdict = Literal["good", "weak", "bad"]
CRITERIA = ("correct", "supported", "unambiguous", "distractors", "worth_studying")


class LabelError(Exception):
    """The labels file can't be read. Messages are written to be shown as-is."""


def question_id(document_sha256: str, question: Question) -> str:
    """Stable across runs: the same question about the same file always gets the same id."""
    options = question.options if isinstance(question, MultipleChoice) else ()
    parts = [document_sha256, question.type, normalize(question.question)]
    parts += [normalize(o) for o in options]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


class Label(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    document_sha256: str
    model: str  # the model that wrote the question
    type: Literal["multiple_choice", "true_false"]
    correct: bool
    supported: bool
    unambiguous: bool
    distractors: bool | None  # multiple choice only
    worth_studying: bool
    bloom: Bloom  # the labeler's band
    model_bloom: Bloom  # the band the model gave, chosen without seeing it
    tags: tuple[str, ...] = ()
    note: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> "Label":
        if (self.distractors is None) != (self.type == "true_false"):
            raise ValueError("distractors is judged for multiple choice, and only there")
        if self.verdict != "good" and not self.note.strip():
            raise ValueError("a failed check needs a note saying what's wrong")
        return self

    @property
    def verdict(self) -> Verdict:
        """bad: a student must never see it. weak: correct and supported, but flawed."""
        if not (self.correct and self.supported):
            return "bad"
        if self.unambiguous and self.distractors is not False and self.worth_studying:
            return "good"
        return "weak"


def load_labels(path: Path) -> dict[str, Label]:
    """Labels by question id, from a JSON Lines file; a missing file means none yet."""
    if not path.exists():
        return {}
    labels: dict[str, Label] = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            label = Label.model_validate_json(line)
        except ValidationError as e:
            raise LabelError(f"{path}, line {n}: {e}") from e
        labels[label.id] = label  # a later label of the same question replaces the earlier
    return labels


def append_label(path: Path, label: Label) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(label.model_dump_json() + "\n")


# --- Labeling session ------------------------------------------------------------------------


class _Quit(Exception):
    pass


class _Skip(Exception):
    pass


_BLOOM_CHOICES = {"1": Bloom.REMEMBER, "2": Bloom.UNDERSTAND_APPLY, "3": Bloom.ANALYZE_EVALUATE}


def label_set(
    questions: QuestionSet,
    labels_path: Path,
    *,
    ask: Callable[[str], str] = input,
    out: TextIO,
) -> int:
    """Ask about every question not labeled yet; returns how many were labeled."""
    done = load_labels(labels_path)
    todo = [q for q in questions.questions if question_id(questions.document_sha256, q) not in done]
    print(
        f"{questions.source_name}: {len(todo)} of {len(questions.questions)} questions to "
        "label. Open the file next to this; judge against the page itself.\n"
        "Answer y/n. Type s to skip a question, q to stop (labels so far are saved).",
        file=out,
    )
    labeled = 0
    for n, question in enumerate(todo, start=1):
        print(f"\n[{n}/{len(todo)}] " + render_question(question, questions.unit), file=out)
        try:
            label = _ask_label(question, questions, ask)
        except _Skip:
            continue
        except (_Quit, EOFError, KeyboardInterrupt):
            print("\nstopped", file=out)
            break
        append_label(labels_path, label)
        labeled += 1
    return labeled


def _ask_label(question: Question, questions: QuestionSet, ask: Callable[[str], str]) -> Label:
    def answer(prompt: str) -> str:
        reply = ask(prompt).strip()
        if reply.lower() == "q":
            raise _Quit
        if reply.lower() == "s":
            raise _Skip
        return reply

    def yes_no(prompt: str) -> bool:
        while True:
            reply = answer(f"{prompt} [y/n] ").lower()
            if reply in ("y", "yes", "n", "no"):
                return reply.startswith("y")

    def bloom() -> Bloom:
        while True:
            reply = answer("bloom? [1 remember, 2 understand/apply, 3 analyze/evaluate] ")
            if reply in _BLOOM_CHOICES:
                return _BLOOM_CHOICES[reply]

    multiple_choice = isinstance(question, MultipleChoice)
    checks = {
        "correct": yes_no("correct: is the answer key right?"),
        "supported": yes_no("supported: can the cited page alone confirm it?"),
        "unambiguous": yes_no("unambiguous: exactly one defensible answer?"),
        "distractors": (
            yes_no("distractors: are the wrong options plausible?") if multiple_choice else None
        ),
        "worth_studying": yes_no("worth studying: course content, not trivia?"),
    }
    band = bloom()
    tags = tuple(t.strip() for t in answer("tags (comma-separated, optional): ").split(","))
    failed = any(value is False for value in checks.values())
    while not (note := answer("note (what's wrong): " if failed else "note (optional): ")):
        if not failed:
            break
    return Label(
        id=question_id(questions.document_sha256, question),
        document_sha256=questions.document_sha256,
        model=questions.model,
        type=question.type,
        **checks,
        bloom=band,
        model_bloom=question.bloom,
        tags=tuple(t for t in tags if t),
        note=note,
    )


def render_question(question: Question, unit: str) -> str:
    """The question as the labeler sees it: everything but the model's bloom band."""
    kind = "multiple choice" if isinstance(question, MultipleChoice) else "true/false"
    lines = [
        f"{kind} · {unit} {question.source.page} · topics: {', '.join(question.topic_ids)}",
        question.question,
    ]
    if isinstance(question, MultipleChoice):
        lines += [
            f"{'*' if i == question.answer else ' '} {'abcdefgh'[i]}) {option}"
            for i, option in enumerate(question.options)
        ]
    else:
        lines.append(f"answer: {'true' if question.answer else 'false'}")
    lines += [f"why: {question.explanation}", f'quote: "{question.source.quote}"']
    return "\n".join(lines)


# --- Summary ---------------------------------------------------------------------------------


def summarize(labels: Iterable[Label]) -> str:
    labels = list(labels)
    if not labels:
        return "no labels yet"
    verdicts = Counter(label.verdict for label in labels)
    documents = len({label.document_sha256 for label in labels})
    lines = [
        f"{len(labels)} questions from {documents} document(s): "
        + ", ".join(f"{verdicts[v]} {v}" for v in ("good", "weak", "bad"))
    ]
    for criterion in CRITERIA:
        values = [getattr(label, criterion) for label in labels]
        judged = [v for v in values if v is not None]
        if judged:
            lines.append(f"  {criterion}: {sum(judged)}/{len(judged)}")
    agree = sum(label.bloom == label.model_bloom for label in labels)
    lines.append(f"  bloom agrees with the model: {agree}/{len(labels)}")
    tags = Counter(tag for label in labels for tag in label.tags)
    if tags:
        lines.append("  tags: " + ", ".join(f"{t} {n}" for t, n in tags.most_common()))
    return "\n".join(lines)


def load_question_set(path: Path) -> QuestionSet:
    try:
        return QuestionSet.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise LabelError(f"{path} is not a question set from `alfred generate --out`: {e}") from e
