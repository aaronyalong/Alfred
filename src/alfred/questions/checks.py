"""Deterministic checks on generated questions: plain code, no model calls.

A question that fails any check is rejected, not repaired: the reasons are kept so a later
step can regenerate it. The most important check is that the cited quote really appears on
the cited page, because the citation is what lets a student verify a question.
"""

import re
from collections.abc import Sequence

from alfred.ingest import Document
from alfred.questions.models import MultipleChoice, Question, Rejected, TrueFalse

MC_OPTIONS = 4
# Shorter quotes ("VPC", "the model") match almost anywhere, so they prove nothing.
MIN_QUOTE_CHARS = 15
# With at least this many true/false questions, a lopsided split becomes a hint to guess.
MIN_TF_FOR_BALANCE = 4
TF_TRUE_SHARE = (0.3, 0.7)

_CATCH_ALL = re.compile(r"\b(all|none) of the above\b", re.IGNORECASE)
# Typographic variants that a model may change when it copies a quote. Written as escapes,
# since several look like ASCII characters.
_EQUIVALENT = str.maketrans(
    {
        "\u2018": "'",  # left single quotation mark
        "\u2019": "'",  # right single quotation mark
        "\u201c": '"',  # left double quotation mark
        "\u201d": '"',  # right double quotation mark
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
    }
)


def normalize(text: str) -> str:
    """For matching: case, whitespace and typographic quotes and dashes don't count."""
    return " ".join(text.translate(_EQUIVALENT).split()).casefold()


def check_question(question: Question, document: Document, topic_ids: set[str]) -> list[str]:
    problems: list[str] = []
    if not question.question.strip():
        problems.append("question text is empty")
    if not question.explanation.strip():
        problems.append("explanation is empty")

    source = question.source
    if len("".join(source.quote.split())) < MIN_QUOTE_CHARS:
        problems.append(f"quote is too short to locate (under {MIN_QUOTE_CHARS} characters)")
    if not 1 <= source.page <= len(document.pages):
        problems.append(f"cites {document.unit} {source.page}, which doesn't exist")
    elif normalize(source.quote) not in normalize(document.page(source.page).text):
        problems.append(f"quote not found on {document.unit} {source.page}")

    if not question.topic_ids:
        problems.append("no topic")
    if unknown := sorted(set(question.topic_ids) - topic_ids):
        problems.append(f"unknown topic(s): {', '.join(unknown)}")

    if isinstance(question, MultipleChoice):
        problems += _check_options(question)
    return problems


def _check_options(question: MultipleChoice) -> list[str]:
    problems: list[str] = []
    options = [normalize(o) for o in question.options]
    if len(options) != MC_OPTIONS:
        problems.append(f"has {len(options)} options, not {MC_OPTIONS}")
    if any(not o for o in options):
        problems.append("an option is empty")
    if len(set(options)) != len(options):
        problems.append("options repeat")
    if not 0 <= question.answer < len(options):
        problems.append("answer is not one of the options")
    if any(_CATCH_ALL.search(o) for o in question.options):
        problems.append('uses "all/none of the above"')
    return problems


def check_set(
    questions: Sequence[Question], document: Document, topic_ids: set[str]
) -> tuple[list[Question], list[Rejected], list[str]]:
    """Split questions into passed and rejected, plus warnings about the set as a whole."""
    passed: list[Question] = []
    rejected: list[Rejected] = []
    seen: set[str] = set()
    for question in questions:
        problems = check_question(question, document, topic_ids)
        text = normalize(question.question)
        if text in seen:
            problems.append("duplicates an earlier question")
        seen.add(text)
        if problems:
            rejected.append(Rejected(question=question, problems=tuple(problems)))
        else:
            passed.append(question)
    return passed, rejected, _balance_warnings(passed)


def _balance_warnings(questions: list[Question]) -> list[str]:
    answers = [q.answer for q in questions if isinstance(q, TrueFalse)]
    if len(answers) < MIN_TF_FOR_BALANCE:
        return []
    share = sum(answers) / len(answers)
    low, high = TF_TRUE_SHARE
    if low <= share <= high:
        return []
    return [f"{sum(answers)} of {len(answers)} true/false answers are true; aim for about half"]
