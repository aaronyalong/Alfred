import json
import shutil
import uuid
from pathlib import Path

import pytest

from alfred import jobs, uploads
from alfred.db.models import (
    Course,
    DocumentRecord,
    DocumentStatus,
    Job,
    JobKind,
    JobStatus,
    PracticeSet,
    SetFormat,
    SetStatus,
)
from alfred.db.session import Sessions
from alfred.ingest import Engine
from alfred.questions.generate import Generator
from alfred.worker import Worker, allocate
from tests.conftest import MakePdf
from tests.fake_claude import FakeClaude
from tests.questions.test_generate import TOPICS


def queue_upload(sessions: Sessions, upload_dir: Path, source: Path) -> uuid.UUID:
    """What the API does on upload: a document row, the stored file and an ingest job."""
    with sessions.begin() as session:
        record = DocumentRecord(course=Course(name="Cloud"), name="lecture.pdf")
        session.add(record)
        session.flush()
        path = uploads.upload_path(upload_dir, record.id, record.name)
        path.parent.mkdir(parents=True)
        shutil.copy(source, path)
        jobs.enqueue(session, JobKind.INGEST_DOCUMENT, record.id)
        return record.id


def queue_set(sessions: Sessions, document_id: uuid.UUID, **fields: object) -> uuid.UUID:
    with sessions.begin() as session:
        document = session.get_one(DocumentRecord, document_id)
        values = {"count": 10, "format": SetFormat.MIXED, **fields}
        record = PracticeSet(course=document.course, name="Set", documents=[document], **values)
        session.add(record)
        session.flush()
        jobs.enqueue(session, JobKind.GENERATE_SET, record.id)
        return record.id


def test_ingest_job_parses_the_file_maps_topics_and_deletes_the_upload(
    sessions: Sessions, upload_dir: Path, worker: Worker, lecture: Path
) -> None:
    document_id = queue_upload(sessions, upload_dir, lecture)

    assert worker.run_next() is True
    assert worker.run_next() is False  # nothing left

    with sessions() as session:
        record = session.get_one(DocumentRecord, document_id)
        assert record.status is DocumentStatus.READY
        assert (record.format, record.unit, record.pages) == ("pdf", "page", 3)
        assert record.topic_count == 2
        assert record.content is not None
        assert record.content["source_name"] == "lecture.pdf"
        assert record.cost_usd is not None
        assert record.cost_usd > 0
    assert not (upload_dir / str(document_id)).exists()


def test_a_file_that_cannot_be_parsed_fails_with_a_message_for_the_user(
    sessions: Sessions, upload_dir: Path, worker: Worker, tmp_path: Path, make_pdf: MakePdf
) -> None:
    not_a_document = tmp_path / "notes.txt"
    not_a_document.write_text("plain text")
    unsupported = queue_upload(sessions, upload_dir, not_a_document)
    blank = queue_upload(sessions, upload_dir, make_pdf(["", ""]))

    assert worker.run_next()
    assert worker.run_next()

    with sessions() as session:
        first = session.get_one(DocumentRecord, unsupported)
        assert first.status is DocumentStatus.FAILED
        assert first.error == "lecture.pdf is not a PDF, PPTX or DOCX file"
        second = session.get_one(DocumentRecord, blank)
        assert second.error == "No text could be read from this file."
        assert {job.status for job in session.query(Job)} == {JobStatus.FAILED}
    assert not (upload_dir / str(unsupported)).exists()


def test_generate_job_stores_passed_and_rejected_questions(
    sessions: Sessions, upload_dir: Path, worker: Worker, lecture: Path, claude: FakeClaude
) -> None:
    document_id = queue_upload(sessions, upload_dir, lecture)
    worker.run_next()
    set_id = queue_set(sessions, document_id)

    assert worker.run_next()

    with sessions() as session:
        record = session.get_one(PracticeSet, set_id)
        assert record.status is SetStatus.READY
        assert [q.position for q in record.questions] == [0, 1, 2]
        assert [q.data["type"] for q in record.questions] == [
            "multiple_choice",
            "true_false",
            "multiple_choice",
        ]
        assert [q.problems for q in record.questions] == [
            None,
            None,
            ["answer is not one of the options"],
        ]
        assert {q.document_id for q in record.questions} == {document_id}
    # The topic map stored at ingest is reused: one call to map topics, one to write questions.
    assert len(claude.requests) == 2
    assert "Write 7 multiple-choice and 3 true/false questions." in str(claude.requests[1])


@pytest.mark.parametrize(
    ("format", "asked"),
    [
        (SetFormat.MULTIPLE_CHOICE, "Write 4 multiple-choice questions."),
        (SetFormat.TRUE_FALSE, "Write 4 true/false questions."),
    ],
)
def test_a_set_can_be_one_kind_of_question_only(
    sessions: Sessions,
    upload_dir: Path,
    worker: Worker,
    lecture: Path,
    claude: FakeClaude,
    format: SetFormat,
    asked: str,
) -> None:
    document_id = queue_upload(sessions, upload_dir, lecture)
    worker.run_next()
    queue_set(sessions, document_id, count=4, format=format)

    worker.run_next()

    assert asked in str(claude.requests[1])


def test_a_set_with_no_usable_question_fails(
    sessions: Sessions, upload_dir: Path, lecture: Path
) -> None:
    nothing = {"multiple_choice": [], "true_false": []}
    claude = FakeClaude(json.dumps(TOPICS), json.dumps(nothing))
    worker = _worker(sessions, upload_dir, claude)
    document_id = queue_upload(sessions, upload_dir, lecture)
    worker.run_next()
    set_id = queue_set(sessions, document_id)

    worker.run_next()

    with sessions() as session:
        record = session.get_one(PracticeSet, set_id)
        assert record.status is SetStatus.FAILED
        assert record.error is not None
        assert "quality checks" in record.error


def test_an_unexpected_error_fails_the_job_without_leaking_details(
    sessions: Sessions, upload_dir: Path, lecture: Path
) -> None:
    def broken() -> object:
        raise RuntimeError("secret internal detail")

    worker = Worker(sessions, upload_dir, Engine.BASELINE, make_generator=broken)  # type: ignore[arg-type]
    document_id = queue_upload(sessions, upload_dir, lecture)

    assert worker.run_next()

    with sessions() as session:
        record = session.get_one(DocumentRecord, document_id)
        assert record.status is DocumentStatus.FAILED
        assert record.error == "Something went wrong on our side. Please try again."


def test_a_job_that_keeps_dying_is_given_up(
    sessions: Sessions, upload_dir: Path, worker: Worker, lecture: Path
) -> None:
    document_id = queue_upload(sessions, upload_dir, lecture)
    with sessions.begin() as session:
        session.query(Job).one().attempts = jobs.MAX_ATTEMPTS

    worker.run_next()

    with sessions() as session:
        record = session.get_one(DocumentRecord, document_id)
        assert record.status is DocumentStatus.FAILED
        assert record.error is not None
        assert "kept failing" in record.error


def test_a_job_interrupted_by_shutdown_goes_back_to_the_queue(
    sessions: Sessions, upload_dir: Path, lecture: Path
) -> None:
    def shutting_down() -> object:
        raise KeyboardInterrupt

    worker = Worker(sessions, upload_dir, Engine.BASELINE, make_generator=shutting_down)  # type: ignore[arg-type]
    document_id = queue_upload(sessions, upload_dir, lecture)

    with pytest.raises(KeyboardInterrupt):
        worker.run_next()

    with sessions() as session:
        job = session.query(Job).one()
        assert (job.status, job.attempts) == (JobStatus.QUEUED, 0)
    assert (upload_dir / str(document_id)).exists()  # the upload is kept for the retry


def test_questions_are_split_over_documents_by_size() -> None:
    assert allocate(10, [30, 10]) == [8, 2]  # 7.5 and 2.5: the tie goes to the first
    assert allocate(10, [1, 1, 1]) == [4, 3, 3]
    assert allocate(1, [5, 5]) == [1, 0]
    assert allocate(5, [0, 0]) == [0, 0]
    assert sum(allocate(17, [3, 11, 7, 2])) == 17


def _worker(sessions: Sessions, upload_dir: Path, claude: FakeClaude) -> Worker:
    return Worker(
        sessions,
        upload_dir,
        engine=Engine.BASELINE,
        make_generator=lambda: Generator(claude.client),
    )
