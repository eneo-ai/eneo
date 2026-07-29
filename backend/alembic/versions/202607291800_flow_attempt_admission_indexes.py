"""Bound Flow attempt evidence admission by runtime ordering indexes.

Concurrent index builds commit independently of Alembic's revision stamp. Each
named index is therefore verified before reuse so an interrupted upgrade can
resume after a successful build, while an invalid or unexpected index fails
closed for operator inspection.

Revision ID: 202607291800_attempt_admit_idx
Revises: 202607271700_call_input_indexes
Create Date: 2026-07-29 18:00:00.000000
"""

from __future__ import annotations

from typing import NamedTuple

import sqlalchemy as sa

from alembic import op

revision = "202607291800_attempt_admit_idx"
down_revision = "202607271700_call_input_indexes"
branch_labels = None
depends_on = None

_ATTEMPT_INDEX = "ix_flow_step_attempts_run_step_order_attempt"
_ATTEMPT_TABLE = "flow_step_attempts"
_ATTEMPT_COLUMNS = ("flow_run_id", "step_order", "attempt_no")
_RESULT_INDEX = "ix_flow_step_results_run_step_order"
_RESULT_TABLE = "flow_step_results"
_RESULT_COLUMNS = ("flow_run_id", "step_order")


class _IndexState(NamedTuple):
    table: str
    key_definitions: tuple[str, ...]
    key_options: tuple[int, ...]
    has_included_columns: bool
    access_method: str
    unique: bool
    valid: bool
    ready: bool
    live: bool
    partial: bool
    expression: bool


def _index_state(index: str) -> _IndexState | None:
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    table_row.relname,
                    array_agg(
                        pg_get_indexdef(
                            index_metadata.indexrelid,
                            key_position.position,
                            true
                        )
                        ORDER BY key_position.position
                    ),
                    index_metadata.indoption::smallint[],
                    index_metadata.indnatts != index_metadata.indnkeyatts,
                    access_method.amname,
                    index_metadata.indisunique,
                    index_metadata.indisvalid,
                    index_metadata.indisready,
                    index_metadata.indislive,
                    index_metadata.indpred IS NOT NULL,
                    index_metadata.indexprs IS NOT NULL
                FROM pg_class AS index_row
                JOIN pg_index AS index_metadata
                  ON index_metadata.indexrelid = index_row.oid
                JOIN pg_am AS access_method
                  ON access_method.oid = index_row.relam
                JOIN pg_class AS table_row
                  ON table_row.oid = index_metadata.indrelid
                JOIN LATERAL generate_series(
                    1,
                    index_metadata.indnkeyatts
                ) AS key_position(position)
                  ON true
                WHERE index_row.relnamespace = current_schema()::regnamespace
                  AND index_row.relname = :index_name
                GROUP BY
                    table_row.relname,
                    index_metadata.indoption,
                    index_metadata.indnatts,
                    index_metadata.indnkeyatts,
                    access_method.amname,
                    index_metadata.indisunique,
                    index_metadata.indisvalid,
                    index_metadata.indisready,
                    index_metadata.indislive,
                    (index_metadata.indpred IS NOT NULL),
                    (index_metadata.indexprs IS NOT NULL)
                """
            ),
            {"index_name": index},
        )
        .one_or_none()
    )
    if row is None:
        return None
    return _IndexState(
        table=str(row[0]),
        key_definitions=tuple(str(value) for value in row[1]),
        key_options=tuple(int(value) for value in row[2]),
        has_included_columns=bool(row[3]),
        access_method=str(row[4]),
        unique=bool(row[5]),
        valid=bool(row[6]),
        ready=bool(row[7]),
        live=bool(row[8]),
        partial=bool(row[9]),
        expression=bool(row[10]),
    )


def _create_or_verify_index(
    index: str,
    *,
    table: str,
    columns: tuple[str, ...],
) -> None:
    if _index_state(index) is None:
        op.execute(
            f"CREATE INDEX CONCURRENTLY {index} ON {table} ({', '.join(columns)})"
        )

    expected = _IndexState(
        table=table,
        key_definitions=columns,
        key_options=tuple(0 for _ in columns),
        has_included_columns=False,
        access_method="btree",
        unique=False,
        valid=True,
        ready=True,
        live=True,
        partial=False,
        expression=False,
    )
    actual = _index_state(index)
    if actual != expected:
        raise RuntimeError(
            f"Cannot continue Flow attempt admission migration: index {index} "
            f"has unexpected state {actual!r}; expected {expected!r}. Drop an "
            "invalid or mismatched index concurrently, then rerun the upgrade."
        )


def upgrade() -> None:
    with op.get_context().autocommit_block():
        _create_or_verify_index(
            _ATTEMPT_INDEX,
            table=_ATTEMPT_TABLE,
            columns=_ATTEMPT_COLUMNS,
        )
        _create_or_verify_index(
            _RESULT_INDEX,
            table=_RESULT_TABLE,
            columns=_RESULT_COLUMNS,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_RESULT_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_ATTEMPT_INDEX}")
