"""Alembic's entry point: connects migrations to the app's settings and tables."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from alfred.config import get_settings
from alfred.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# A test can pass its own URL; otherwise the app's database is migrated.
url = config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_offline() -> None:
    """Print the SQL instead of running it (`alembic upgrade head --sql`)."""
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
