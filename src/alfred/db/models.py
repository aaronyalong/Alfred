"""Database tables for the web app.

Parsed documents and questions are stored as JSON, in the same Pydantic formats the
command line uses (`ingest.Document`, `questions.TopicMap`, `questions.Question`), so the
library code works on them unchanged. Status columns hold plain strings, not database enum
types, which are painful to change later.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Table,
    Text,
    TypeDecorator,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    PARSING = "parsing"
    READY = "ready"
    FAILED = "failed"


class SetStatus(StrEnum):
    QUEUED = "queued"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class SetFormat(StrEnum):
    MIXED = "mixed"
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"


class JobKind(StrEnum):
    INGEST_DOCUMENT = "ingest_document"
    GENERATE_SET = "generate_set"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class UTCDateTime(TypeDecorator[datetime]):
    """Timestamps are always timezone-aware UTC, also on SQLite, which drops the zone."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def now() -> datetime:
    return datetime.now(UTC)


def _status(enum: type[StrEnum]) -> Enum:
    # Stored as the enum's value in a VARCHAR column.
    return Enum(enum, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e])


# none_as_null: Python's None is stored as SQL NULL, not as the JSON value `null`, so that
# "IS NULL" finds it.
_Json = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UTCDateTime, dict[str, Any]: _Json, list[str]: _Json}  # noqa: RUF012


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=now)

    documents: Mapped[list["DocumentRecord"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", order_by="DocumentRecord.created_at"
    )
    sets: Mapped[list["PracticeSet"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", order_by="PracticeSet.created_at"
    )


class DocumentRecord(Base):
    """An uploaded file. `content` and `topics` are filled in by the worker."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))  # the file name, as uploaded
    status: Mapped[DocumentStatus] = mapped_column(
        _status(DocumentStatus), default=DocumentStatus.QUEUED
    )
    error: Mapped[str | None] = mapped_column(Text)  # shown to the user when status is failed
    # Large, and not needed to list documents, so they are loaded only when read.
    content: Mapped[dict[str, Any] | None] = mapped_column(deferred=True)  # an ingest.Document
    topics: Mapped[dict[str, Any] | None] = mapped_column(deferred=True)  # a questions.TopicMap
    # A summary of `content` and `topics`, for listing documents without loading them.
    format: Mapped[str | None] = mapped_column(String(10))
    unit: Mapped[str | None] = mapped_column(String(10))
    pages: Mapped[int | None]
    flagged_pages: Mapped[int | None]  # pages with extraction warnings
    topic_count: Mapped[int | None]
    cost_usd: Mapped[float | None]  # what reading it cost in model calls
    created_at: Mapped[datetime] = mapped_column(default=now)

    course: Mapped[Course] = relationship(back_populates="documents")


set_documents = Table(
    "practice_set_documents",
    Base.metadata,
    Column("set_id", ForeignKey("practice_sets.id", ondelete="CASCADE"), primary_key=True),
    Column("document_id", ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
)


class PracticeSet(Base):
    """A request for questions from some of a course's documents, and its result."""

    __tablename__ = "practice_sets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[SetStatus] = mapped_column(_status(SetStatus), default=SetStatus.QUEUED)
    error: Mapped[str | None] = mapped_column(Text)
    count: Mapped[int]  # questions asked for; fewer may pass the checks
    format: Mapped[SetFormat] = mapped_column(_status(SetFormat))
    cost_usd: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(default=now)

    course: Mapped[Course] = relationship(back_populates="sets")
    documents: Mapped[list[DocumentRecord]] = relationship(
        secondary=set_documents, order_by="DocumentRecord.created_at"
    )
    questions: Mapped[list["QuestionRecord"]] = relationship(
        back_populates="set", cascade="all, delete-orphan", order_by="QuestionRecord.position"
    )
    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="set", cascade="all, delete-orphan", order_by="Attempt.created_at"
    )


class QuestionRecord(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_sets.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    position: Mapped[int]
    data: Mapped[dict[str, Any]]  # a questions.Question
    # Why the code checks rejected it. Rejected questions are kept for review, never shown.
    problems: Mapped[list[str] | None]
    flagged_at: Mapped[datetime | None]  # the student reported a problem with it

    set: Mapped[PracticeSet] = relationship(back_populates="questions")
    document: Mapped[DocumentRecord] = relationship()


class Attempt(Base):
    """One run through a practice set, graded by the server."""

    __tablename__ = "attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_sets.id", ondelete="CASCADE"), index=True
    )
    correct: Mapped[int]
    total: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=now)

    set: Mapped[PracticeSet] = relationship(back_populates="attempts")
    answers: Mapped[list["Answer"]] = relationship(cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answers"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attempts.id", ondelete="CASCADE"), primary_key=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    # An option index, true/false, or null when the question was skipped.
    given: Mapped[int | bool | None] = mapped_column(_Json)
    correct: Mapped[bool]


class Job(Base):
    """The work queue: one row per background task. See jobs.py for how rows are claimed."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[JobKind] = mapped_column(_status(JobKind))
    target_id: Mapped[uuid.UUID]  # the document or practice set to work on
    status: Mapped[JobStatus] = mapped_column(
        _status(JobStatus), default=JobStatus.QUEUED, index=True
    )
    attempts: Mapped[int] = mapped_column(default=0)
    # While running: when another worker may take over, in case this one died.
    locked_until: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None]
