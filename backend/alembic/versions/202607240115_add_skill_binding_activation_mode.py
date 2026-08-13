"""add Assistant and Governance Policy Skill binding activation mode

Revision ID: 202607240115
Revises: 202607231730
Create Date: 2026-07-24 01:15:00.000000
"""

from collections.abc import Sequence
from time import monotonic, sleep

from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "202607240115"
down_revision: str | None = "202607231730"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODE_TABLES = ("assistant_skill_bindings", "governance_policy_skill_bindings")
_LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"
_METADATA_LOCK_RETRY_SECONDS = 5.0
_METADATA_LOCK_RETRY_INTERVAL_SECONDS = 0.025


def _constraint_name(table: str) -> str:
    return f"ck_{table}_activation_mode"


def _execute_with_immediate_table_lock(
    *,
    table: str,
    statements: tuple[str, ...],
) -> None:
    """Run one short metadata phase without joining PostgreSQL's lock queue."""
    bind = op.get_bind()
    deadline = monotonic() + _METADATA_LOCK_RETRY_SECONDS

    while True:
        bind.exec_driver_sql("BEGIN")
        try:
            bind.exec_driver_sql(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE NOWAIT")
            for statement in statements:
                bind.exec_driver_sql(statement)
            bind.exec_driver_sql("COMMIT")
            return
        except DBAPIError as error:
            bind.exec_driver_sql("ROLLBACK")
            sqlstate = getattr(error.orig, "sqlstate", None) or getattr(
                error.orig, "pgcode", None
            )
            if sqlstate != _LOCK_NOT_AVAILABLE_SQLSTATE or monotonic() >= deadline:
                raise
            sleep(_METADATA_LOCK_RETRY_INTERVAL_SECONDS)
        except Exception:
            bind.exec_driver_sql("ROLLBACK")
            raise


def upgrade() -> None:
    # Each phase commits independently so a bounded lock retry never holds one
    # table's exclusive lock while touching the other, and the populated-table
    # CHECK scan happens under the weaker validation lock, not the metadata one.
    with op.get_context().autocommit_block():
        for table in _MODE_TABLES:
            _execute_with_immediate_table_lock(
                table=table,
                statements=(
                    f"""
                    ALTER TABLE {table}
                        ADD COLUMN IF NOT EXISTS activation_mode TEXT
                            NOT NULL DEFAULT 'always'
                    """,
                    f"""
                    ALTER TABLE {table}
                        DROP CONSTRAINT IF EXISTS {_constraint_name(table)}
                    """,
                    f"""
                    ALTER TABLE {table}
                        ADD CONSTRAINT {_constraint_name(table)}
                        CHECK (activation_mode IN ('always', 'on_demand'))
                        NOT VALID
                    """,
                ),
            )
        for table in _MODE_TABLES:
            op.execute(
                f"ALTER TABLE {table} VALIDATE CONSTRAINT {_constraint_name(table)}"
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for table in _MODE_TABLES:
            _execute_with_immediate_table_lock(
                table=table,
                statements=(
                    f"""
                    ALTER TABLE {table}
                        DROP CONSTRAINT IF EXISTS {_constraint_name(table)}
                    """,
                    f"""
                    ALTER TABLE {table}
                        DROP COLUMN IF EXISTS activation_mode
                    """,
                ),
            )
