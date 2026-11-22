"""The background worker: runs the jobs that the API queues.

Parsing a file and writing questions take too long for a web request (seconds to minutes,
most of it waiting on model calls), so the API only records what to do and this process
does it. No database transaction is held open while a model call runs.
"""

import logging
import signal
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from alfred import jobs, uploads
from alfred.db.models import (
    DocumentRecord,
    DocumentStatus,
    JobKind,
    PracticeSet,
    QuestionRecord,
    SetFormat,
    SetStatus,
)
from alfred.db.session import Sessions
from alfred.ingest import Document, Engine, IngestError, ingest
from alfred.ingest.vision import VisionReader
from alfred.llm import Usage, default_cache
from alfred.questions import QuestionSet, TopicMap
from alfred.questions.generate import TRUE_FALSE_SHARE, GenerationError, Generator

log = logging.getLogger(__name__)

_UNEXPECTED = "Something went wrong on our side. Please try again."
_GAVE_UP = "Processing kept failing, so it was stopped. Please try again."
_TRUE_FALSE_SHARES = {
    SetFormat.MIXED: TRUE_FALSE_SHARE,
    SetFormat.MULTIPLE_CHOICE: 0.0,
    SetFormat.TRUE_FALSE: 1.0,
}


class JobFailed(Exception):
    """The job can't succeed. The message is shown to the user as-is."""


def _vision_reader() -> VisionReader:
    return VisionReader(cache=default_cache("vision"))


@dataclass(frozen=True)
class Worker:
    sessions: Sessions
    upload_dir: Path
    engine: Engine = Engine.VISION
    make_vision: Callable[[], VisionReader] = _vision_reader
    make_generator: Callable[[], Generator] = Generator

    def run_forever(self, *, poll_seconds: float = 2.0) -> None:
        # On `docker stop`, exit like on Ctrl-C, so the job in progress is put back.
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        log.info("worker started")
        while True:
            if not self.run_next():
                time.sleep(poll_seconds)

    def run_next(self) -> bool:
        """Run one waiting job to the end. Returns False when there was none."""
        with self.sessions.begin() as session:
            job = jobs.claim(session)
            if job is None:
                return False
            job_id, kind, target_id, attempts = job.id, job.kind, job.target_id, job.attempts

        run, fail = {
            JobKind.INGEST_DOCUMENT: (self._ingest_document, self._fail_document),
            JobKind.GENERATE_SET: (self._generate_set, self._fail_set),
        }[kind]
        error = None
        try:
            if attempts > jobs.MAX_ATTEMPTS:
                raise JobFailed(_GAVE_UP)
            run(target_id)
        except JobFailed as e:
            error = str(e)
        except Exception:
            log.exception("%s job %s failed", kind, job_id)
            error = _UNEXPECTED
        except BaseException:  # shutting down: leave the job for the next worker
            with self.sessions.begin() as session:
                jobs.release(session, job_id)
            raise

        if error:
            fail(target_id, error)
        with self.sessions.begin() as session:
            jobs.finish(session, job_id, error=error)
        log.info("%s job %s %s", kind, job_id, "failed" if error else "done")
        return True

    # --- Reading an uploaded file -----------------------------------------------------------

    def _ingest_document(self, document_id: uuid.UUID) -> None:
        with self.sessions.begin() as session:
            record = session.get(DocumentRecord, document_id)
            if record is None:  # deleted while it waited
                return
            record.status = DocumentStatus.PARSING
            path = uploads.upload_path(self.upload_dir, record.id, record.name)

        vision = self.make_vision() if self.engine is Engine.VISION else None
        generator = self.make_generator()
        try:
            document = ingest(path, engine=self.engine, vision=vision)
            if not any(page.text for page in document.pages):
                raise JobFailed("No text could be read from this file.")
            topics = generator.topic_map(document)
        except (IngestError, GenerationError) as e:
            raise JobFailed(str(e)) from e

        with self.sessions.begin() as session:
            record = session.get(DocumentRecord, document_id)
            if record is None:
                return
            record.content = document.model_dump(mode="json")
            record.topics = topics.model_dump(mode="json")
            record.format, record.unit = document.format.value, document.unit.value
            record.pages = len(document.pages)
            record.flagged_pages = sum(bool(page.issues) for page in document.pages)
            record.topic_count = len(topics.topics)
            record.cost_usd = _cost(generator.usage, *([vision.usage] if vision else []))
            record.status = DocumentStatus.READY
        # Only the extracted text is kept; the original is not needed again.
        uploads.discard(self.upload_dir, document_id)

    def _fail_document(self, document_id: uuid.UUID, error: str) -> None:
        with self.sessions.begin() as session:
            if record := session.get(DocumentRecord, document_id):
                record.status, record.error = DocumentStatus.FAILED, error
        uploads.discard(self.upload_dir, document_id)

    # --- Writing a practice set -------------------------------------------------------------

    def _generate_set(self, set_id: uuid.UUID) -> None:
        with self.sessions.begin() as session:
            record = session.get(PracticeSet, set_id)
            if record is None:
                return
            record.status = SetStatus.GENERATING
            count, share = record.count, _TRUE_FALSE_SHARES[record.format]
            sources = [
                (d.id, Document.model_validate(d.content), TopicMap.model_validate(d.topics))
                for d in record.documents
                if d.status is DocumentStatus.READY
            ]
        if not sources:
            raise JobFailed("None of the chosen documents is ready.")

        generator = self.make_generator()
        shares = allocate(count, [sum(bool(p.text) for p in doc.pages) for _, doc, _ in sources])
        results: list[tuple[uuid.UUID, QuestionSet]] = []
        try:
            for (document_id, document, topics), n in zip(sources, shares, strict=True):
                if n:
                    questions = generator.generate(
                        document, count=n, true_false_share=share, topics=topics
                    )
                    results.append((document_id, questions))
        except GenerationError as e:
            raise JobFailed(str(e)) from e
        if not any(questions.questions for _, questions in results):
            raise JobFailed("None of the questions passed the quality checks. Please try again.")

        with self.sessions.begin() as session:
            record = session.get(PracticeSet, set_id)
            if record is None:
                return
            rows = [
                (document_id, question.model_dump(mode="json"), problems)
                for document_id, questions in results
                for question, problems in (
                    *((q, None) for q in questions.questions),
                    *((r.question, list(r.problems)) for r in questions.rejected),
                )
            ]
            record.questions = [
                QuestionRecord(document_id=document_id, position=n, data=data, problems=problems)
                for n, (document_id, data, problems) in enumerate(rows)
            ]
            record.cost_usd = _cost(generator.usage)
            record.status = SetStatus.READY

    def _fail_set(self, set_id: uuid.UUID, error: str) -> None:
        with self.sessions.begin() as session:
            if record := session.get(PracticeSet, set_id):
                record.status, record.error = SetStatus.FAILED, error


def allocate(count: int, weights: list[int]) -> list[int]:
    """Split `count` questions over documents in proportion to their size.

    Largest-remainder rounding: the parts always add up to `count`.
    """
    total = sum(weights)
    if total == 0:
        return [0] * len(weights)
    exact = [count * weight / total for weight in weights]
    parts = [int(share) for share in exact]
    by_remainder = sorted(range(len(weights)), key=lambda i: exact[i] - parts[i], reverse=True)
    for i in by_remainder[: count - sum(parts)]:
        parts[i] += 1
    return parts


def _cost(*usages: Usage) -> float | None:
    costs = [usage.cost_usd for usage in usages]
    return None if None in costs else sum(c for c in costs if c is not None)
