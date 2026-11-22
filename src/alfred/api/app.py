"""The HTTP API. A thin shell: it stores requests and queues jobs; the worker does the work.

There are no accounts yet, so run it on localhost only.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from pydantic import TypeAdapter
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload
from starlette.types import ASGIApp, Receive, Scope, Send

from alfred import jobs, uploads
from alfred.api.schemas import (
    AnswerOut,
    AttemptIn,
    AttemptOut,
    CourseDetail,
    CourseIn,
    CourseSummary,
    DocumentOut,
    DocumentPages,
    FlagIn,
    MultipleChoiceOut,
    PageOut,
    QuestionOut,
    Score,
    SetDetail,
    SetIn,
    SetSummary,
    SourceOut,
    TrueFalseOut,
)
from alfred.config import get_settings
from alfred.db.models import (
    Answer,
    Attempt,
    Course,
    DocumentRecord,
    DocumentStatus,
    JobKind,
    PracticeSet,
    QuestionRecord,
    SetStatus,
    now,
)
from alfred.db.session import Sessions, make_sessions
from alfred.ingest import Document, IngestError, Limits
from alfred.ingest.detect import detect_format
from alfred.questions import MultipleChoice, Question, TopicMap

MAX_UPLOAD_BYTES = Limits().max_bytes
_CHUNK = 1024 * 1024
_QUESTION: TypeAdapter[Question] = TypeAdapter(Question)

router = APIRouter(prefix="/api")


def _session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session


Db = Annotated[Session, Depends(_session)]


def create_app(sessions: Sessions | None = None, upload_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Alfred", version="0.1.0")
    app.state.sessions = sessions or make_sessions()
    app.state.upload_dir = upload_dir or get_settings().alfred_upload_dir
    app.include_router(router)
    app.add_middleware(_UploadLimit)
    return app


class _UploadLimit:
    """Refuse an oversized upload from its Content-Length, before reading any of it."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            declared = dict(scope["headers"]).get(b"content-length", b"0")
            # The form around the file adds a little to its size.
            if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES + _CHUNK:
                response = PlainTextResponse(_too_large(), status.HTTP_413_CONTENT_TOO_LARGE)
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


def _too_large() -> str:
    return f"The file is larger than the {MAX_UPLOAD_BYTES // _CHUNK} MB limit."


# --- Courses ---------------------------------------------------------------------------------


@router.get("/health")
def health(db: Db) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/courses")
def list_courses(db: Db) -> list[CourseSummary]:
    courses = db.scalars(
        select(Course)
        .options(selectinload(Course.documents), selectinload(Course.sets))
        .order_by(Course.created_at)
    )
    return [
        CourseSummary(
            id=c.id,
            name=c.name,
            documents=len(c.documents),
            sets=len(c.sets),
            created_at=c.created_at,
        )
        for c in courses
    ]


@router.post("/courses", status_code=status.HTTP_201_CREATED)
def create_course(body: CourseIn, db: Db) -> CourseSummary:
    course = Course(name=body.name)
    db.add(course)
    db.commit()
    return CourseSummary(
        id=course.id, name=course.name, documents=0, sets=0, created_at=course.created_at
    )


@router.get("/courses/{course_id}")
def get_course(course_id: uuid.UUID, db: Db) -> CourseDetail:
    course = _get(db, Course, course_id)
    counts = _question_counts(db, [s.id for s in course.sets])
    return CourseDetail(
        id=course.id,
        name=course.name,
        documents=[_document_out(d) for d in course.documents],
        sets=[SetSummary(**_set_summary(s, counts.get(s.id, 0))) for s in course.sets],
    )


@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(course_id: uuid.UUID, db: Db, request: Request) -> None:
    """Deletes the course with its documents, practice sets and attempts."""
    course = _get(db, Course, course_id)
    document_ids = [d.id for d in course.documents]
    db.delete(course)
    db.commit()
    for document_id in document_ids:  # uploads still waiting to be parsed
        uploads.discard(request.app.state.upload_dir, document_id)


# --- Documents -------------------------------------------------------------------------------


@router.post("/courses/{course_id}/documents", status_code=status.HTTP_202_ACCEPTED)
def upload_document(
    course_id: uuid.UUID, file: UploadFile, db: Db, request: Request
) -> DocumentOut:
    """Stores the file and queues it for parsing. Poll the course to follow its status."""
    course = _get(db, Course, course_id)
    record = DocumentRecord(course=course, name=uploads.safe_name(file.filename))
    db.add(record)
    db.flush()  # assigns the id that names the upload's folder

    upload_dir: Path = request.app.state.upload_dir
    path = uploads.upload_path(upload_dir, record.id, record.name)
    try:
        _save(file, path)
        detect_format(path)  # refuse other file types now, not minutes later in the worker
    except HTTPException:
        uploads.discard(upload_dir, record.id)
        raise
    except IngestError as e:
        uploads.discard(upload_dir, record.id)
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e

    jobs.enqueue(db, JobKind.INGEST_DOCUMENT, record.id)
    db.commit()
    return _document_out(record)


def _save(file: UploadFile, path: Path) -> None:
    path.parent.mkdir(parents=True)
    size = 0
    with path.open("wb") as out:
        while chunk := file.file.read(_CHUNK):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, _too_large())
            out.write(chunk)
    if size == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty.")


@router.get("/documents/{document_id}/pages")
def get_document_pages(document_id: uuid.UUID, db: Db) -> DocumentPages:
    record = _get(db, DocumentRecord, document_id)
    if record.status is not DocumentStatus.READY:
        raise HTTPException(status.HTTP_409_CONFLICT, "This document is not ready yet.")
    document = Document.model_validate(record.content)
    return DocumentPages(
        id=record.id,
        name=record.name,
        unit=document.unit,
        pages=[
            PageOut(number=p.number, text=p.text, issues=list(p.issues)) for p in document.pages
        ],
    )


# --- Practice sets ---------------------------------------------------------------------------


@router.post("/courses/{course_id}/sets", status_code=status.HTTP_202_ACCEPTED)
def create_set(course_id: uuid.UUID, body: SetIn, db: Db) -> SetSummary:
    """Queues question generation. Poll the set to follow its status."""
    course = _get(db, Course, course_id)
    chosen = set(body.document_ids)
    documents = [d for d in course.documents if d.id in chosen]
    if len(documents) != len(chosen):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "A chosen document is not in this course."
        )
    if waiting := [d.name for d in documents if d.status is not DocumentStatus.READY]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Not ready yet: {', '.join(waiting)}")

    record = PracticeSet(
        course=course,
        name=body.name or _default_name(documents),
        count=body.count,
        format=body.format,
        documents=documents,
    )
    db.add(record)
    db.flush()
    jobs.enqueue(db, JobKind.GENERATE_SET, record.id)
    db.commit()
    return SetSummary(**_set_summary(record, 0))


def _default_name(documents: list[DocumentRecord]) -> str:
    first = Path(documents[0].name).stem
    more = f" + {len(documents) - 1} more" if len(documents) > 1 else ""
    return f"{first[: 200 - len(more)]}{more}"


@router.get("/sets/{set_id}")
def get_set(set_id: uuid.UUID, db: Db) -> SetDetail:
    record = _get(db, PracticeSet, set_id)
    items = _question_outs(record)
    return SetDetail(
        **_set_summary(record, len(items)),
        course_id=record.course_id,
        course_name=record.course.name,
        items=items,
    )


@router.post("/sets/{set_id}/attempts", status_code=status.HTTP_201_CREATED)
def submit_attempt(set_id: uuid.UUID, body: AttemptIn, db: Db) -> AttemptOut:
    """Grades one run through the set. Questions left out count as skipped."""
    record = _get(db, PracticeSet, set_id)
    if record.status is not SetStatus.READY:
        raise HTTPException(status.HTTP_409_CONFLICT, "This practice set is not ready yet.")
    questions = {q.id: _question(q) for q in record.questions if q.problems is None}
    given = {a.question_id: a.answer for a in body.answers}
    if set(given) - set(questions):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "An answer is for a question not in this set."
        )

    answers = [
        Answer(question_id=qid, given=given.get(qid), correct=_is_correct(q, given.get(qid)))
        for qid, q in questions.items()
    ]
    attempt = Attempt(
        set=record, correct=sum(a.correct for a in answers), total=len(answers), answers=answers
    )
    db.add(attempt)
    db.commit()
    return AttemptOut(
        id=attempt.id,
        correct=attempt.correct,
        total=attempt.total,
        answers=[
            AnswerOut(question_id=a.question_id, given=a.given, correct=a.correct) for a in answers
        ],
    )


def _is_correct(question: Question, given: int | bool | None) -> bool:
    # bool is a kind of int in Python, so the types are compared too: true is not option 1.
    return type(given) is type(question.answer) and given == question.answer


@router.put("/questions/{question_id}/flag", status_code=status.HTTP_204_NO_CONTENT)
def flag_question(question_id: uuid.UUID, body: FlagIn, db: Db) -> None:
    """Reports a problem with a question, or takes the report back."""
    record = _get(db, QuestionRecord, question_id)
    record.flagged_at = (record.flagged_at or now()) if body.flagged else None
    db.commit()


# --- Helpers ---------------------------------------------------------------------------------


def _get[T](db: Session, model: type[T], record_id: uuid.UUID) -> T:
    record = db.get(model, record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return record


def _document_out(record: DocumentRecord) -> DocumentOut:
    return DocumentOut.model_validate(
        {
            "id": record.id,
            "name": record.name,
            "status": record.status,
            "error": record.error,
            "format": record.format,
            "unit": record.unit,
            "pages": record.pages,
            "flagged_pages": record.flagged_pages,
            "topics": record.topic_count,
            "created_at": record.created_at,
        }
    )


def _question_counts(db: Session, set_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """How many questions passed the checks, per practice set."""
    rows = db.execute(
        select(QuestionRecord.set_id, func.count())
        .where(QuestionRecord.set_id.in_(set_ids), QuestionRecord.problems.is_(None))
        .group_by(QuestionRecord.set_id)
    )
    return {set_id: count for set_id, count in rows}


def _set_summary(record: PracticeSet, questions: int) -> dict[str, Any]:
    last = record.attempts[-1] if record.attempts else None
    return {
        "id": record.id,
        "name": record.name,
        "status": record.status,
        "error": record.error,
        "count": record.count,
        "format": record.format,
        "questions": questions,
        "last_score": Score(correct=last.correct, total=last.total) if last else None,
        "created_at": record.created_at,
    }


def _question(record: QuestionRecord) -> Question:
    return _QUESTION.validate_python(record.data)


def _question_outs(record: PracticeSet) -> list[QuestionOut]:
    documents = {d.id: d for d in record.documents}
    topic_names = {
        d.id: {t.id: t.name for t in TopicMap.model_validate(d.topics).topics}
        for d in record.documents
    }
    items: list[QuestionOut] = []
    for row in record.questions:
        if row.problems is not None:
            continue
        question, document = _question(row), documents[row.document_id]
        names = topic_names[row.document_id]
        common: dict[str, Any] = {
            "id": row.id,
            "question": question.question,
            "explanation": question.explanation,
            "bloom": question.bloom,
            "topics": [names.get(topic_id, topic_id) for topic_id in question.topic_ids],
            "source": SourceOut.model_validate(
                {
                    "document_id": document.id,
                    "document_name": document.name,
                    "unit": document.unit,
                    "page": question.source.page,
                    "quote": question.source.quote,
                }
            ),
            "flagged": row.flagged_at is not None,
        }
        if isinstance(question, MultipleChoice):
            items.append(
                MultipleChoiceOut(**common, options=list(question.options), answer=question.answer)
            )
        else:
            items.append(TrueFalseOut(**common, answer=question.answer))
    return items
