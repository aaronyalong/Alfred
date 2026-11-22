"""Database connections. One engine per process, created on first use."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from alfred.config import get_settings

Sessions = sessionmaker[Session]


@lru_cache
def get_engine() -> Engine:
    # pool_pre_ping replaces connections the database closed while they sat idle.
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def make_sessions(engine: Engine | None = None) -> Sessions:
    # expire_on_commit=False: rows stay readable after their transaction has ended.
    return sessionmaker(engine or get_engine(), expire_on_commit=False)
