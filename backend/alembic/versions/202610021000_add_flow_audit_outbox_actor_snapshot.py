"""add the actor snapshot to the flow run audit outbox and index its actor keys

Revision ID: 202610021000
Revises: 202609291100
Create Date: 2026-10-02 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202610021000"
down_revision: str = "202609291100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "flow_run_audit_outbox"
# Deleting a user or API key sets these FK columns NULL; without an index each
# deletion scans the outbox.
_INDEXES = (
    ("ix_flow_run_audit_outbox_actor_id", "actor_id"),
    ("ix_flow_run_audit_outbox_actor_api_key_id", "actor_api_key_id"),
)


def _index_is_invalid(name: str) -> bool:
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
    return valid is False


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        _TABLE,
        sa.Column("actor_snapshot", postgresql.JSONB(), nullable=True),
        if_not_exists=True,
    )
    # Offline (`alembic upgrade --sql`) there is no database to inspect, so only
    # the static DDL is emitted.
    offline = op.get_context().as_sql
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, column in _INDEXES:
                if not offline and _index_is_invalid(name):
                    op.drop_index(name, table_name=_TABLE, postgresql_concurrently=True)
                op.create_index(
                    name,
                    _TABLE,
                    [column],
                    postgresql_where=sa.text(f"{column} IS NOT NULL"),
                    postgresql_concurrently=True,
                    if_not_exists=True,
                )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, _column in reversed(_INDEXES):
                op.drop_index(
                    name,
                    table_name=_TABLE,
                    postgresql_concurrently=True,
                    if_exists=True,
                )
        finally:
            op.execute("RESET lock_timeout")
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column(_TABLE, "actor_snapshot")
