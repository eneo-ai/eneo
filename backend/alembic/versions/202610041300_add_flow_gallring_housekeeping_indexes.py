"""add the keyset indexes of the nightly flows housekeeping

Revision ID: 202610041300
Revises: 202610041200
Create Date: 2026-10-04 13:00:00.000000

Partial indexes the flows.housekeeping selections range over, built
CONCURRENTLY so writes continue. A build that fails (for example a lock timeout
behind an old snapshot) leaves an INVALID index and no version stamp; the next
upgrade drops the invalid leftover and builds it again. Offline it emits the
static DDL.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610041300"
down_revision: str = "202610041200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    (
        "ix_flow_live_transcripts_unbound_created",
        "flow_live_transcripts",
        ["created_at", "id"],
        "bound_file_id IS NULL",
    ),
    (
        "ix_flow_run_audit_outbox_delivered",
        "flow_run_audit_outbox",
        ["delivered_at", "id"],
        "delivery_status = 'delivered'",
    ),
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
    offline = op.get_context().as_sql
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, table, columns, predicate in _INDEXES:
                if not offline and _index_is_invalid(name):
                    op.drop_index(name, table_name=table, postgresql_concurrently=True)
                op.create_index(
                    name,
                    table,
                    columns,
                    postgresql_where=sa.text(predicate),
                    postgresql_concurrently=True,
                    if_not_exists=True,
                )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, table, _columns, _predicate in reversed(_INDEXES):
                op.drop_index(
                    name,
                    table_name=table,
                    postgresql_concurrently=True,
                    if_exists=True,
                )
        finally:
            op.execute("RESET lock_timeout")
