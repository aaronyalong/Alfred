"""What the API accepts and returns. The frontend's TypeScript types are generated from these."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints

from alfred.db.models import DocumentStatus, SetFormat, SetStatus
from alfred.ingest import SourceFormat, Unit
from alfred.questions import Bloom

MAX_QUESTIONS = 50

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CourseIn(_In):
    name: Name


class CourseSummary(BaseModel):
    id: uuid.UUID
    name: str
    documents: int
    sets: int
    created_at: datetime


class DocumentOut(BaseModel):
    id: uuid.UUID
    name: str
    status: DocumentStatus
    error: str | None
    # Known once the document is ready.
    format: SourceFormat | None
    unit: Unit | None
    pages: int | None
    flagged_pages: int | None
    topics: int | None
    created_at: datetime


class PageOut(BaseModel):
    number: int
    text: str
    issues: list[str]


class DocumentPages(BaseModel):
    """The text extracted from a document, to check before generating questions from it."""

    id: uuid.UUID
    name: str
    unit: Unit
    pages: list[PageOut]


class Score(BaseModel):
    correct: int
    total: int


class SetSummary(BaseModel):
    id: uuid.UUID
    name: str
    status: SetStatus
    error: str | None
    count: int  # questions asked for
    format: SetFormat
    questions: int  # questions that passed the checks
    last_score: Score | None
    created_at: datetime


class CourseDetail(BaseModel):
    id: uuid.UUID
    name: str
    documents: list[DocumentOut]
    sets: list[SetSummary]


class SetIn(_In):
    document_ids: list[uuid.UUID] = Field(min_length=1)
    count: int = Field(default=10, ge=1, le=MAX_QUESTIONS)
    format: SetFormat = SetFormat.MIXED
    name: Name | None = None


class SourceOut(BaseModel):
    document_id: uuid.UUID
    document_name: str
    unit: Unit
    page: int
    quote: str


class _QuestionOut(BaseModel):
    id: uuid.UUID
    question: str
    explanation: str
    bloom: Bloom
    topics: list[str]  # topic names
    source: SourceOut
    flagged: bool


class MultipleChoiceOut(_QuestionOut):
    type: Literal["multiple_choice"] = "multiple_choice"
    options: list[str]
    answer: int  # index into options


class TrueFalseOut(_QuestionOut):
    type: Literal["true_false"] = "true_false"
    answer: bool


QuestionOut = Annotated[MultipleChoiceOut | TrueFalseOut, Field(discriminator="type")]


class SetDetail(SetSummary):
    course_id: uuid.UUID
    course_name: str
    # Empty until the set is ready. Answers are included: this is practice, not an exam.
    items: list[QuestionOut]


class AnswerIn(_In):
    question_id: uuid.UUID
    # An option index, true/false, or null for a skipped question. Strict, so that 1 and true
    # are never confused.
    answer: StrictInt | StrictBool | None


class AttemptIn(_In):
    answers: list[AnswerIn]


class AnswerOut(BaseModel):
    question_id: uuid.UUID
    given: int | bool | None
    correct: bool


class AttemptOut(BaseModel):
    id: uuid.UUID
    correct: int
    total: int
    answers: list[AnswerOut]


class FlagIn(_In):
    flagged: bool
