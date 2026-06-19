"""constrain Flow result files to step attempts

Result files are attempt-owned evidence; input files stay as run-start snapshots
because they are persisted before step attempts exist.

Revision ID: 20260605_flow_result_file_fk
Revises: 20260605_builder_session_idx
Create Date: 2026-06-05 21:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260605_flow_result_file_fk"
down_revision = "20260605_builder_session_idx"
branch_labels = None
depends_on = None


_CONSTRAINT_NAME = "fk_flow_run_step_result_files_step_attempt"
_RESULT_FILES_TABLE = "flow_run_step_result_files"
_ATTEMPTS_TABLE = "flow_step_attempts"


def _orphan_result_file_count() -> int:
    bind = op.get_bind()
    return int(
        bind.scalar(
            sa.text(
                """
                SELECT count(*)
                FROM flow_run_step_result_files AS result_file
                LEFT JOIN flow_step_attempts AS attempt
                  ON attempt.flow_run_id = result_file.flow_run_id
                 AND attempt.step_id = result_file.step_id
                 AND attempt.attempt_no = result_file.attempt_no
                WHERE attempt.id IS NULL
                """
            )
        )
        or 0
    )


def _orphan_result_file_samples() -> list[str]:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT
                result_file.id::text,
                result_file.tenant_id::text,
                result_file.flow_id::text,
                result_file.flow_run_id::text,
                result_file.step_id::text,
                result_file.step_order,
                result_file.attempt_no,
                result_file.step_result_id::text,
                result_file.file_id::text,
                result_file.ordinal,
                result_file.source,
                result_file.created_at
            FROM flow_run_step_result_files AS result_file
            LEFT JOIN flow_step_attempts AS attempt
              ON attempt.flow_run_id = result_file.flow_run_id
             AND attempt.step_id = result_file.step_id
             AND attempt.attempt_no = result_file.attempt_no
            WHERE attempt.id IS NULL
            ORDER BY result_file.created_at, result_file.id
            LIMIT 5
            """
        )
    )
    return [
        (
            f"id={row[0]} tenant_id={row[1]} flow_id={row[2]} "
            f"flow_run_id={row[3]} step_id={row[4]} step_order={row[5]} "
            f"attempt_no={row[6]} step_result_id={row[7]} file_id={row[8]} "
            f"ordinal={row[9]} source={row[10]} created_at={row[11]}"
        )
        for row in rows
    ]


def upgrade() -> None:
    orphan_count = _orphan_result_file_count()
    if orphan_count > 0:
        samples = "; ".join(_orphan_result_file_samples())
        raise RuntimeError(
            f"Cannot add {_CONSTRAINT_NAME}: {orphan_count} "
            "flow_run_step_result_files rows do not reference flow_step_attempts. "
            f"Sample result files: {samples}. Delete or repair orphan result files, "
            "then rerun the upgrade."
        )

    op.create_foreign_key(
        _CONSTRAINT_NAME,
        _RESULT_FILES_TABLE,
        _ATTEMPTS_TABLE,
        ["flow_run_id", "step_id", "attempt_no"],
        ["flow_run_id", "step_id", "attempt_no"],
        ondelete="CASCADE",
        postgresql_not_valid=True,
    )
    op.execute(
        f"ALTER TABLE {_RESULT_FILES_TABLE} VALIDATE CONSTRAINT {_CONSTRAINT_NAME}"
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, _RESULT_FILES_TABLE, type_="foreignkey")
