"""constrain Flow review checkpoints to step attempts

Review checkpoints are human-review state for completed attempts; deletion stays
explicit because checkpoint and audit rows are governance state.

Revision ID: 20260605_review_ckpt_attempt_fk
Revises: 20260605_flow_result_file_fk
Create Date: 2026-06-05 22:12:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260605_review_ckpt_attempt_fk"
down_revision = "20260605_flow_result_file_fk"
branch_labels = None
depends_on = None


_CONSTRAINT_NAME = "fk_flow_run_review_checkpoints_step_attempt"
_CHECKPOINTS_TABLE = "flow_run_review_checkpoints"
_ATTEMPTS_TABLE = "flow_step_attempts"


def _orphan_checkpoint_count() -> int:
    bind = op.get_bind()
    return int(
        bind.scalar(
            sa.text(
                """
                SELECT count(*)
                FROM flow_run_review_checkpoints AS checkpoint
                LEFT JOIN flow_step_attempts AS attempt
                  ON attempt.flow_run_id = checkpoint.flow_run_id
                 AND attempt.step_id = checkpoint.step_id
                 AND attempt.attempt_no = checkpoint.attempt_no
                WHERE attempt.id IS NULL
                """
            )
        )
        or 0
    )


def _orphan_checkpoint_samples() -> list[str]:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT
                checkpoint.id::text,
                checkpoint.flow_run_id::text,
                checkpoint.step_id::text,
                checkpoint.attempt_no
            FROM flow_run_review_checkpoints AS checkpoint
            LEFT JOIN flow_step_attempts AS attempt
              ON attempt.flow_run_id = checkpoint.flow_run_id
             AND attempt.step_id = checkpoint.step_id
             AND attempt.attempt_no = checkpoint.attempt_no
            WHERE attempt.id IS NULL
            ORDER BY checkpoint.created_at, checkpoint.id
            LIMIT 5
            """
        )
    )
    return [
        (f"id={row[0]} flow_run_id={row[1]} step_id={row[2]} attempt_no={row[3]}")
        for row in rows
    ]


def upgrade() -> None:
    orphan_count = _orphan_checkpoint_count()
    if orphan_count > 0:
        samples = "; ".join(_orphan_checkpoint_samples())
        raise RuntimeError(
            f"Cannot add {_CONSTRAINT_NAME}: {orphan_count} "
            "flow_run_review_checkpoints rows do not reference "
            f"{_ATTEMPTS_TABLE}. Sample checkpoints: {samples}. "
            "Delete or repair orphan checkpoints, then rerun the upgrade."
        )

    op.create_foreign_key(
        _CONSTRAINT_NAME,
        _CHECKPOINTS_TABLE,
        _ATTEMPTS_TABLE,
        ["flow_run_id", "step_id", "attempt_no"],
        ["flow_run_id", "step_id", "attempt_no"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.execute(
        f"ALTER TABLE {_CHECKPOINTS_TABLE} VALIDATE CONSTRAINT {_CONSTRAINT_NAME}"
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, _CHECKPOINTS_TABLE, type_="foreignkey")
