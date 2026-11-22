import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from alfred.api import create_app
from alfred.db.models import Base
from alfred.db.session import Sessions, make_sessions
from alfred.ingest import Engine as IngestEngine
from alfred.questions.generate import Generator
from alfred.worker import Worker
from tests.conftest import MakePdf
from tests.fake_claude import FakeClaude
from tests.questions.test_generate import QUESTIONS, SLIDE_2, SLIDE_3, TOPICS


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """An empty database: a SQLite file, or Postgres when ALFRED_TEST_DATABASE_URL is set.

    SQLite keeps the tests free of services. Postgres is what production runs, so CI sets
    the variable and runs them there too.
    """
    url = os.environ.get("ALFRED_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(url)
    _drop_everything(engine)
    yield engine
    _drop_everything(engine)
    engine.dispose()


def _drop_everything(engine: Engine) -> None:
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture
def sessions(engine: Engine) -> Sessions:
    Base.metadata.create_all(engine)
    return make_sessions(engine)


@pytest.fixture
def upload_dir(tmp_path: Path) -> Path:
    return tmp_path / "uploads"


@pytest.fixture
def claude() -> FakeClaude:
    """Answers the first call with a topic map and every later one with questions."""
    return FakeClaude(json.dumps(TOPICS), json.dumps(QUESTIONS))


@pytest.fixture
def worker(sessions: Sessions, upload_dir: Path, claude: FakeClaude) -> Worker:
    return Worker(
        sessions,
        upload_dir,
        engine=IngestEngine.BASELINE,
        make_generator=lambda: Generator(claude.client),
    )


@pytest.fixture
def client(sessions: Sessions, upload_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(sessions, upload_dir)) as test_client:
        yield test_client


@pytest.fixture
def lecture(make_pdf: MakePdf) -> Path:
    """A three-page PDF whose pages 2 and 3 carry the text the fake questions quote."""
    return make_pdf(["Cloud networking", SLIDE_2, SLIDE_3])
