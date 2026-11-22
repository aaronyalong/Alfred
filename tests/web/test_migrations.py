from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect

from alfred.db.models import Base

ROOT = Path(__file__).parents[2]


def test_migrations_build_exactly_the_tables_the_models_describe(engine: Engine) -> None:
    config = Config(ROOT / "alembic.ini")
    config.set_main_option("script_location", str(ROOT / "src/alfred/db/migrations"))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))

    command.upgrade(config, "head")

    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert differences == []  # a model changed without a migration, or the other way round

    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
