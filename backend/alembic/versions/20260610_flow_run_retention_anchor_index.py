"""add Flow run-history retention-anchor index

Revision ID: 20260610_flow_retention_anchor
Revises: 20260610_flow_retention_range
Create Date: 2026-06-10 23:58:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "20260610_flow_retention_anchor"
down_revision = "20260610_flow_retention_range"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_flow_runs_terminal_retention_anchor"
_TABLE_NAME = "flow_runs"
_TERMINAL_FLOW_RUN_STATUS_VALUES = ("completed", "failed", "cancelled")


def _index_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


_INDEX_PREDICATE_SQL = f"status IN ({_index_values(_TERMINAL_FLOW_RUN_STATUS_VALUES)})"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME}
            ON {_TABLE_NAME} (
                coalesce(finished_at, created_at),
                id
            )
            INCLUDE (flow_id)
            WHERE {_INDEX_PREDICATE_SQL};
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME};")
