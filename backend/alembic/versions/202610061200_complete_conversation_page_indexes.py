"""Complete conversation keysets without sorting all roots sharing a timestamp.

Revision ID: 202610061200
Revises: 202610051020

Build both replacements before removing their shorter prefixes. Concurrent builds
keep normal reads and writes available; failed builds leave invalid indexes that
the next online attempt replaces. Offline SQL assumes no invalid leftovers.
Downgrade restores the historical prefix indexes.
No conversation data changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610061200"
down_revision: str = "202610051020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = (
    (
        "ix_questions_retention_owner_created_id",
        "questions",
        ("assistant_id", "created_at", "id"),
    ),
    (
        "ix_app_runs_retention_owner_created_id",
        "app_runs",
        ("app_id", "created_at", "id"),
    ),
)
_OLD = (
    ("ix_questions_assistant_created", "questions", ("assistant_id", "created_at")),
    ("idx_questions_assistant_created", "questions", ("assistant_id", "created_at")),
    ("ix_app_runs_app_created", "app_runs", ("app_id", "created_at")),
)


def _replace(
    create: tuple[tuple[str, str, tuple[str, ...]], ...],
    drop: tuple[tuple[str, str, tuple[str, ...]], ...],
) -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, table, columns in create:
                if not op.get_context().as_sql:
                    valid = (
                        op.get_bind()
                        .execute(
                            sa.text(
                                "SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"
                            ),
                            {"name": name},
                        )
                        .scalar()
                    )
                    if valid is False:
                        op.drop_index(
                            name,
                            table_name=table,
                            postgresql_concurrently=True,
                            if_exists=True,
                        )
                op.create_index(
                    name,
                    table,
                    list(columns),
                    postgresql_concurrently=True,
                    if_not_exists=True,
                )
            for name, table, _columns in drop:
                op.drop_index(
                    name, table_name=table, postgresql_concurrently=True, if_exists=True
                )
        finally:
            op.execute("RESET lock_timeout")


def upgrade() -> None:
    _replace(_NEW, _OLD)


def downgrade() -> None:
    _replace(_OLD, _NEW)
