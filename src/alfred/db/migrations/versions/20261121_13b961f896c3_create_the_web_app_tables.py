"""Create the web app tables

Revision ID: 13b961f896c3
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "13b961f896c3"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id(name: str = "id") -> sa.Column:
    return sa.Column(name, sa.Uuid(), nullable=False)


def _time(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _status(name: str) -> sa.Column:
    return sa.Column(name, sa.String(length=20), nullable=False)


def _json(name: str, *, nullable: bool = True) -> sa.Column:
    kind = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    return sa.Column(name, kind, nullable=nullable)


def _owner(name: str, table: str) -> sa.ForeignKeyConstraint:
    """Rows are deleted together with the row that owns them."""
    return sa.ForeignKeyConstraint([name], [f"{table}.id"], ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "courses",
        _id(),
        sa.Column("name", sa.String(length=200), nullable=False),
        _time("created_at"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "jobs",
        _id(),
        _status("kind"),
        _id("target_id"),
        _status("status"),
        sa.Column("attempts", sa.Integer(), nullable=False),
        _time("locked_until", nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _time("created_at"),
        _time("finished_at", nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_table(
        "documents",
        _id(),
        _id("course_id"),
        sa.Column("name", sa.String(length=255), nullable=False),
        _status("status"),
        sa.Column("error", sa.Text(), nullable=True),
        _json("content"),
        _json("topics"),
        sa.Column("format", sa.String(length=10), nullable=True),
        sa.Column("unit", sa.String(length=10), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("flagged_pages", sa.Integer(), nullable=True),
        sa.Column("topic_count", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Double(), nullable=True),
        _time("created_at"),
        _owner("course_id", "courses"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_course_id", "documents", ["course_id"])
    op.create_table(
        "practice_sets",
        _id(),
        _id("course_id"),
        sa.Column("name", sa.String(length=200), nullable=False),
        _status("status"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False),
        _status("format"),
        sa.Column("cost_usd", sa.Double(), nullable=True),
        _time("created_at"),
        _owner("course_id", "courses"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_practice_sets_course_id", "practice_sets", ["course_id"])
    op.create_table(
        "practice_set_documents",
        _id("set_id"),
        _id("document_id"),
        _owner("set_id", "practice_sets"),
        _owner("document_id", "documents"),
        sa.PrimaryKeyConstraint("set_id", "document_id"),
    )
    op.create_table(
        "questions",
        _id(),
        _id("set_id"),
        _id("document_id"),
        sa.Column("position", sa.Integer(), nullable=False),
        _json("data", nullable=False),
        _json("problems"),
        _time("flagged_at", nullable=True),
        _owner("set_id", "practice_sets"),
        _owner("document_id", "documents"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_questions_set_id", "questions", ["set_id"])
    op.create_table(
        "attempts",
        _id(),
        _id("set_id"),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        _time("created_at"),
        _owner("set_id", "practice_sets"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attempts_set_id", "attempts", ["set_id"])
    op.create_table(
        "answers",
        _id("attempt_id"),
        _id("question_id"),
        _json("given"),
        sa.Column("correct", sa.Boolean(), nullable=False),
        _owner("attempt_id", "attempts"),
        _owner("question_id", "questions"),
        sa.PrimaryKeyConstraint("attempt_id", "question_id"),
    )


def downgrade() -> None:
    for table in (
        "answers",
        "attempts",
        "questions",
        "practice_set_documents",
        "practice_sets",
        "documents",
        "jobs",
        "courses",
    ):
        op.drop_table(table)
