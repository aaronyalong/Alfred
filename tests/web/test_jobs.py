import uuid
from datetime import timedelta

import pytest

from alfred import jobs
from alfred.db.models import Job, JobKind, JobStatus, now
from alfred.db.session import Sessions


def enqueue(sessions: Sessions, count: int = 1) -> list[uuid.UUID]:
    with sessions.begin() as session:
        queued = [
            jobs.enqueue(session, JobKind.INGEST_DOCUMENT, uuid.uuid4()) for _ in range(count)
        ]
        # Spread out, so "oldest first" doesn't depend on the clock's resolution.
        for n, job in enumerate(queued):
            job.created_at = now() + timedelta(seconds=n)
        session.flush()
        return [job.id for job in queued]


def test_jobs_are_claimed_oldest_first_and_only_once(sessions: Sessions) -> None:
    first, second = enqueue(sessions, 2)

    with sessions.begin() as session:
        claimed = [jobs.claim(session), jobs.claim(session), jobs.claim(session)]

    assert [job.id if job else None for job in claimed] == [first, second, None]
    assert claimed[0] is not None
    assert claimed[0].status is JobStatus.RUNNING
    assert claimed[0].attempts == 1


def test_a_job_whose_worker_died_is_claimed_again_after_its_lease(sessions: Sessions) -> None:
    (job_id,) = enqueue(sessions)
    with sessions.begin() as session:
        assert jobs.claim(session) is not None

    with sessions.begin() as session:
        assert jobs.claim(session) is None  # still leased
        again = jobs.claim(session, at=now() + jobs.LEASE + timedelta(seconds=1))

    assert again is not None
    assert again.id == job_id
    assert again.attempts == 2


def test_finished_and_released_jobs(sessions: Sessions) -> None:
    done, failed, released = enqueue(sessions, 3)
    with sessions.begin() as session:
        for _ in range(3):
            jobs.claim(session)
        jobs.finish(session, done)
        jobs.finish(session, failed, error="no text")
        jobs.release(session, released)

    with sessions.begin() as session:
        assert session.get_one(Job, done).status is JobStatus.DONE
        assert session.get_one(Job, failed).status is JobStatus.FAILED
        assert session.get_one(Job, failed).error == "no text"
        assert session.get_one(Job, done).finished_at is not None
        back = session.get_one(Job, released)
        assert (back.status, back.attempts, back.locked_until) == (JobStatus.QUEUED, 0, None)
        assert jobs.claim(session) is back


def test_two_workers_never_claim_the_same_job(sessions: Sessions) -> None:
    with sessions() as session:
        if session.get_bind().dialect.name != "postgresql":
            pytest.skip("needs row locks, which SQLite doesn't have")
    first, second = enqueue(sessions, 2)

    # Both transactions are open at once, as with two worker processes.
    with sessions.begin() as one, sessions.begin() as other:
        claimed = [jobs.claim(one), jobs.claim(other), jobs.claim(other)]

        assert [job.id if job else None for job in claimed] == [first, second, None]
