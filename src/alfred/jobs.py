"""The job queue: a Postgres table, not a separate queue service.

A worker claims the oldest waiting job with `FOR UPDATE SKIP LOCKED`, so several workers
never take the same one. A claim is a lease, not a lock held for the whole job: if a worker
dies, its job becomes claimable again when the lease runs out.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from alfred.db.models import Job, JobKind, JobStatus, now

# Long enough for the slowest job: a 300-page file read by the vision model.
LEASE = timedelta(minutes=30)
# A job whose lease ran out is retried, but not forever: a job that kills its worker would
# otherwise do so on every retry.
MAX_ATTEMPTS = 3


def enqueue(session: Session, kind: JobKind, target_id: uuid.UUID) -> Job:
    job = Job(kind=kind, target_id=target_id)
    session.add(job)
    return job


def claim(session: Session, *, at: datetime | None = None) -> Job | None:
    """Take the oldest job that is waiting, or whose worker seems to have died."""
    at = at or now()
    waiting = or_(
        Job.status == JobStatus.QUEUED,
        and_(Job.status == JobStatus.RUNNING, Job.locked_until < at),
    )
    job = session.scalars(
        select(Job)
        .where(waiting)
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.locked_until = at + LEASE
    return job


def finish(session: Session, job_id: uuid.UUID, *, error: str | None = None) -> None:
    job = session.get_one(Job, job_id)
    job.status = JobStatus.FAILED if error else JobStatus.DONE
    job.error = error
    job.locked_until = None
    job.finished_at = now()


def release(session: Session, job_id: uuid.UUID) -> None:
    """Put a claimed job back, untouched, e.g. when its worker is shutting down."""
    job = session.get_one(Job, job_id)
    job.status = JobStatus.QUEUED
    job.attempts -= 1
    job.locked_until = None
