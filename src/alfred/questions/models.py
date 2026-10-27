"""The question format: what generation produces and what checks, the UI and scoring use.

Every question cites the page and an exact quote it was written from, so a student can find
the source and code can check that the quote is really there.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from alfred.ingest import Unit


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Bloom(StrEnum):
    """Difficulty, as three bands of Bloom's taxonomy. The full six levels can't be labeled
    consistently, even by people, so they couldn't be evaluated either."""

    REMEMBER = "remember"
    UNDERSTAND_APPLY = "understand_apply"
    ANALYZE_EVALUATE = "analyze_evaluate"


class Topic(_Frozen):
    id: str  # short slug, used to tag questions and to track mistakes per topic
    name: str
    pages: tuple[int, ...]


class TopicMap(_Frozen):
    """A fixed list of topics per document, so questions are tagged consistently."""

    document_sha256: str
    topics: tuple[Topic, ...]


class Source(_Frozen):
    page: int  # the Document's 1-based page, slide or section number
    quote: str  # copied exactly from that page's text


class _Question(_Frozen):
    question: str
    explanation: str  # why the answer is right, grounded in the source
    bloom: Bloom
    topic_ids: tuple[str, ...]
    source: Source


class MultipleChoice(_Question):
    type: Literal["multiple_choice"] = "multiple_choice"
    options: tuple[str, ...]
    answer: int  # index into options


class TrueFalse(_Question):
    type: Literal["true_false"] = "true_false"
    answer: bool


Question = Annotated[MultipleChoice | TrueFalse, Field(discriminator="type")]


class Rejected(_Frozen):
    question: Question
    problems: tuple[str, ...]


class QuestionSet(_Frozen):
    source_name: str
    document_sha256: str
    unit: Unit  # what source.page counts: pages, slides or sections
    model: str
    topics: TopicMap
    questions: tuple[Question, ...]  # passed every check
    rejected: tuple[Rejected, ...] = ()  # kept for review, and for regeneration later
    warnings: tuple[str, ...] = ()  # about the set as a whole, e.g. true/false balance
