"""Complete session and client-error keysets without sorting all roots sharing a timestamp.

Revision ID: 202610061600
Revises: 202610061200

Build both replacements before removing their shorter prefixes. Concurrent builds
keep normal reads and writes available; failed builds leave invalid indexes that
the next online attempt replaces. Offline SQL assumes no invalid leftovers.
Downgrade restores the historical prefix indexes.
No row data changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610061600"
down_revision: str = "202610061200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = (
    ("ix_sessions_created_id", "sessions", ("created_at", "id")),
    (
        "ix_builder_client_errors_created_id",
        "builder_client_errors",
        ("created_at", "id"),
    ),
)
_OLD = (
    ("created_at_idx", "sessions", ("created_at",)),
    ("idx_sessions_created_at", "sessions", ("created_at",)),
    ("ix_builder_client_errors_created_at", "builder_client_errors", ("created_at",)),
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
