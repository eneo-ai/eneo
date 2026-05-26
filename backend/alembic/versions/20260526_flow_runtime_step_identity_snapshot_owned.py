"""make flow runtime step identity snapshot-owned

Revision ID: 20260526_flow_step_identity
Revises: 20260522_builder_lock
Create Date: 2026-05-26 07:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

from alembic import op

revision = "20260526_flow_step_identity"
down_revision = "20260522_builder_lock"
branch_labels = None
depends_on = None


_RESULTS_TABLE = "flow_step_results"
_ATTEMPTS_TABLE = "flow_step_attempts"
_RESULTS_STEP_FK = "flow_step_results_step_id_fkey"
_ATTEMPTS_STEP_FK = "flow_step_attempts_step_id_fkey"
_UUID_PATTERN = (
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _recovered_step_ids_sql(table_name: str) -> str:
    return f"""
        SELECT
            runtime_row.id AS runtime_row_id,
            runtime_row.flow_run_id,
            runtime_row.step_order,
            (published_step.value ->> 'step_id')::uuid AS snapshot_step_id
        FROM {table_name} AS runtime_row
        JOIN flow_runs AS runtime_run
          ON runtime_run.id = runtime_row.flow_run_id
         AND runtime_run.flow_id = runtime_row.flow_id
         AND runtime_run.tenant_id = runtime_row.tenant_id
        JOIN flow_versions AS published_version
          ON published_version.flow_id = runtime_run.flow_id
         AND published_version.tenant_id = runtime_run.tenant_id
         AND published_version.version = runtime_run.flow_version
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN jsonb_typeof(published_version.definition_json -> 'steps') = 'array'
                THEN published_version.definition_json -> 'steps'
                ELSE '[]'::jsonb
            END
        ) AS published_step(value)
        WHERE runtime_row.step_id IS NULL
          AND published_step.value ? 'step_id'
          AND (published_step.value ->> 'step_id') ~ '{_UUID_PATTERN}'
          AND published_step.value ? 'step_order'
          AND (published_step.value ->> 'step_order') ~ '^[0-9]+$'
          AND (published_step.value ->> 'step_order')::integer = runtime_row.step_order
    """


def _preflight_recoverable_runtime_rows(
    bind: Connection,
    *,
    table_name: str,
    label: str,
) -> None:
    recovered_step_ids = _recovered_step_ids_sql(table_name)
    bind.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM {table_name} AS runtime_row
                    WHERE runtime_row.step_id IS NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM ({recovered_step_ids}) AS recovered
                          WHERE recovered.runtime_row_id = runtime_row.id
                      )
                ) THEN
                    RAISE EXCEPTION
                        'Cannot migrate flow % step identity: null step_id rows are not recoverable from published snapshot step_id',
                        '{label}';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM ({recovered_step_ids}) AS recovered
                    GROUP BY recovered.runtime_row_id
                    HAVING count(*) <> 1
                ) THEN
                    RAISE EXCEPTION
                        'Cannot migrate flow % step identity: published snapshot step_order maps to multiple step_id values',
                        '{label}';
                END IF;
            END $$;
            """
        )
    )


def _preflight_result_unique_keys(bind: Connection) -> None:
    recovered_step_ids = _recovered_step_ids_sql(_RESULTS_TABLE)
    bind.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    WITH recovered AS (
                        {recovered_step_ids}
                    ),
                    final_keys AS (
                        SELECT flow_run_id, step_id
                        FROM {_RESULTS_TABLE}
                        WHERE step_id IS NOT NULL
                        UNION ALL
                        SELECT flow_run_id, snapshot_step_id AS step_id
                        FROM recovered
                    )
                    SELECT 1
                    FROM final_keys
                    GROUP BY flow_run_id, step_id
                    HAVING count(*) > 1
                ) THEN
                    RAISE EXCEPTION
                        'Cannot migrate flow result step identity: recovered step_id values would violate uq_flow_step_results_run_step';
                END IF;
            END $$;
            """
        )
    )


def _preflight_attempt_unique_keys(bind: Connection) -> None:
    recovered_step_ids = _recovered_step_ids_sql(_ATTEMPTS_TABLE)
    bind.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    WITH recovered AS (
                        {recovered_step_ids}
                    ),
                    final_keys AS (
                        SELECT flow_run_id, step_id, attempt_no
                        FROM {_ATTEMPTS_TABLE}
                        WHERE step_id IS NOT NULL
                        UNION ALL
                        SELECT
                            runtime_row.flow_run_id,
                            recovered.snapshot_step_id AS step_id,
                            runtime_row.attempt_no
                        FROM {_ATTEMPTS_TABLE} AS runtime_row
                        JOIN recovered
                          ON recovered.runtime_row_id = runtime_row.id
                    )
                    SELECT 1
                    FROM final_keys
                    GROUP BY flow_run_id, step_id, attempt_no
                    HAVING count(*) > 1
                ) THEN
                    RAISE EXCEPTION
                        'Cannot migrate flow attempt step identity: recovered step_id values would violate uq_flow_step_attempts_run_step_attempt';
                END IF;
            END $$;
            """
        )
    )


def _backfill_step_ids(bind: Connection, *, table_name: str) -> None:
    recovered_step_ids = _recovered_step_ids_sql(table_name)
    bind.execute(
        sa.text(
            f"""
            WITH recovered AS (
                {recovered_step_ids}
            )
            UPDATE {table_name} AS runtime_row
            SET step_id = recovered.snapshot_step_id
            FROM recovered
            WHERE runtime_row.id = recovered.runtime_row_id
              AND runtime_row.step_id IS NULL
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    _preflight_recoverable_runtime_rows(
        bind,
        table_name=_RESULTS_TABLE,
        label="result",
    )
    _preflight_recoverable_runtime_rows(
        bind,
        table_name=_ATTEMPTS_TABLE,
        label="attempt",
    )
    _preflight_result_unique_keys(bind)
    _preflight_attempt_unique_keys(bind)

    # Published snapshot step ids may no longer exist in mutable draft flow_steps.
    op.drop_constraint(_RESULTS_STEP_FK, _RESULTS_TABLE, type_="foreignkey")
    op.drop_constraint(_ATTEMPTS_STEP_FK, _ATTEMPTS_TABLE, type_="foreignkey")

    _backfill_step_ids(bind, table_name=_RESULTS_TABLE)
    _backfill_step_ids(bind, table_name=_ATTEMPTS_TABLE)

    op.alter_column(
        _RESULTS_TABLE,
        "step_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        _ATTEMPTS_TABLE,
        "step_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        _ATTEMPTS_TABLE,
        "step_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.alter_column(
        _RESULTS_TABLE,
        "step_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"""
            UPDATE {_RESULTS_TABLE} AS runtime_row
            SET step_id = NULL
            WHERE runtime_row.step_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM flow_steps AS draft_step
                  WHERE draft_step.id = runtime_row.step_id
              )
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            UPDATE {_ATTEMPTS_TABLE} AS runtime_row
            SET step_id = NULL
            WHERE runtime_row.step_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM flow_steps AS draft_step
                  WHERE draft_step.id = runtime_row.step_id
              )
            """
        )
    )

    op.create_foreign_key(
        _RESULTS_STEP_FK,
        _RESULTS_TABLE,
        "flow_steps",
        ["step_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        _ATTEMPTS_STEP_FK,
        _ATTEMPTS_TABLE,
        "flow_steps",
        ["step_id"],
        ["id"],
        ondelete="SET NULL",
    )
