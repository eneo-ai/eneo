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
_RESULTS_RECOVERED_TABLE = "_flow_step_results_recovered_step_ids"
_ATTEMPTS_RECOVERED_TABLE = "_flow_step_attempts_recovered_step_ids"
_UUID_PATTERN = (
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _materialize_recovered_mapping(
    bind: Connection,
    *,
    source_table: str,
    temp_table_name: str,
) -> None:
    bind.execute(
        sa.text(
            f"""
            CREATE TEMP TABLE {temp_table_name} ON COMMIT DROP AS
            WITH nullable_runtime_rows AS (
                SELECT
                    runtime_row.id AS runtime_row_id,
                    runtime_row.flow_run_id,
                    runtime_row.flow_id,
                    runtime_row.tenant_id,
                    runtime_run.flow_version,
                    runtime_row.step_order
                FROM {source_table} AS runtime_row
                JOIN flow_runs AS runtime_run
                  ON runtime_run.id = runtime_row.flow_run_id
                 AND runtime_run.flow_id = runtime_row.flow_id
                 AND runtime_run.tenant_id = runtime_row.tenant_id
                WHERE runtime_row.step_id IS NULL
            ),
            referenced_versions AS (
                SELECT flow_id, tenant_id, flow_version
                FROM nullable_runtime_rows
                GROUP BY flow_id, tenant_id, flow_version
            ),
            published_steps AS (
                SELECT
                    referenced_version.flow_id,
                    referenced_version.tenant_id,
                    referenced_version.flow_version,
                    (published_step.value ->> 'step_order')::integer AS step_order,
                    (published_step.value ->> 'step_id')::uuid AS snapshot_step_id
                FROM referenced_versions AS referenced_version
                JOIN flow_versions AS published_version
                  ON published_version.flow_id = referenced_version.flow_id
                 AND published_version.tenant_id = referenced_version.tenant_id
                 AND published_version.version = referenced_version.flow_version
                CROSS JOIN LATERAL jsonb_array_elements(
                    CASE
                        WHEN jsonb_typeof(published_version.definition_json -> 'steps') = 'array'
                        THEN published_version.definition_json -> 'steps'
                        ELSE '[]'::jsonb
                    END
                ) AS published_step(value)
                WHERE published_step.value ? 'step_id'
                  AND (published_step.value ->> 'step_id') ~ '{_UUID_PATTERN}'
                  AND published_step.value ? 'step_order'
                  AND (published_step.value ->> 'step_order') ~ '^[0-9]+$'
            )
            -- Preserve duplicate matches so the ambiguity preflight can reject them.
            SELECT
                runtime_row.runtime_row_id,
                runtime_row.flow_run_id,
                runtime_row.step_order,
                published_step.snapshot_step_id
            FROM nullable_runtime_rows AS runtime_row
            JOIN published_steps AS published_step
              ON published_step.flow_id = runtime_row.flow_id
             AND published_step.tenant_id = runtime_row.tenant_id
             AND published_step.flow_version = runtime_row.flow_version
             AND published_step.step_order = runtime_row.step_order
            """
        )
    )


def _preflight_recoverable_runtime_rows(
    bind: Connection,
    *,
    table_name: str,
    temp_table_name: str,
    label: str,
) -> None:
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
                          FROM {temp_table_name} AS recovered
                          WHERE recovered.runtime_row_id = runtime_row.id
                      )
                ) THEN
                    RAISE EXCEPTION
                        'Cannot migrate flow % step identity: null step_id rows are not recoverable from published snapshot step_id',
                        '{label}';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM {temp_table_name} AS recovered
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
    bind.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    WITH final_keys AS (
                        SELECT flow_run_id, step_id
                        FROM {_RESULTS_TABLE}
                        WHERE step_id IS NOT NULL
                        UNION ALL
                        SELECT flow_run_id, snapshot_step_id AS step_id
                        FROM {_RESULTS_RECOVERED_TABLE}
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
    bind.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    WITH final_keys AS (
                        SELECT flow_run_id, step_id, attempt_no
                        FROM {_ATTEMPTS_TABLE}
                        WHERE step_id IS NOT NULL
                        UNION ALL
                        SELECT
                            runtime_row.flow_run_id,
                            recovered.snapshot_step_id AS step_id,
                            runtime_row.attempt_no
                        FROM {_ATTEMPTS_TABLE} AS runtime_row
                        JOIN {_ATTEMPTS_RECOVERED_TABLE} AS recovered
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


def _backfill_step_ids(
    bind: Connection,
    *,
    table_name: str,
    temp_table_name: str,
) -> None:
    bind.execute(
        sa.text(
            f"""
            UPDATE {table_name} AS runtime_row
            SET step_id = recovered.snapshot_step_id
            FROM {temp_table_name} AS recovered
            WHERE runtime_row.id = recovered.runtime_row_id
              AND runtime_row.step_id IS NULL
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    _materialize_recovered_mapping(
        bind,
        source_table=_RESULTS_TABLE,
        temp_table_name=_RESULTS_RECOVERED_TABLE,
    )
    _materialize_recovered_mapping(
        bind,
        source_table=_ATTEMPTS_TABLE,
        temp_table_name=_ATTEMPTS_RECOVERED_TABLE,
    )
    _preflight_recoverable_runtime_rows(
        bind,
        table_name=_RESULTS_TABLE,
        temp_table_name=_RESULTS_RECOVERED_TABLE,
        label="result",
    )
    _preflight_recoverable_runtime_rows(
        bind,
        table_name=_ATTEMPTS_TABLE,
        temp_table_name=_ATTEMPTS_RECOVERED_TABLE,
        label="attempt",
    )
    _preflight_result_unique_keys(bind)
    _preflight_attempt_unique_keys(bind)

    # Published snapshot step ids may no longer exist in mutable draft flow_steps.
    op.drop_constraint(_RESULTS_STEP_FK, _RESULTS_TABLE, type_="foreignkey")
    op.drop_constraint(_ATTEMPTS_STEP_FK, _ATTEMPTS_TABLE, type_="foreignkey")

    _backfill_step_ids(
        bind,
        table_name=_RESULTS_TABLE,
        temp_table_name=_RESULTS_RECOVERED_TABLE,
    )
    _backfill_step_ids(
        bind,
        table_name=_ATTEMPTS_TABLE,
        temp_table_name=_ATTEMPTS_RECOVERED_TABLE,
    )

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
