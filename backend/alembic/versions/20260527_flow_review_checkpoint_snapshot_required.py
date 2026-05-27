"""require Flow review checkpoint step snapshots

Revision ID: 20260527_review_ckpt_snapshot
Revises: 20260526_flow_user_mirror_drop
Create Date: 2026-05-27 01:25:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260527_review_ckpt_snapshot"
down_revision = "20260526_flow_user_mirror_drop"
branch_labels = None
depends_on = None


_TABLE = "flow_run_review_checkpoints"
_REVIEW_MODE_CHECK = "ck_flow_run_review_checkpoints_review_mode"
_OUTPUT_TYPE_CHECK = "ck_flow_run_review_checkpoints_output_type"
_REVIEW_MODE_VALUES = "'edit', 'view'"
_OUTPUT_TYPE_VALUES = "'text', 'json', 'pdf', 'docx'"


def _assert_review_checkpoint_snapshots_present() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM flow_run_review_checkpoints
                    WHERE review_mode IS NULL
                       OR output_type IS NULL
                ) THEN
                    RAISE EXCEPTION 'Cannot require review checkpoint snapshots: rows exist without review_mode or output_type.';
                END IF;
            END $$;
            """
        )
    )


def upgrade() -> None:
    _assert_review_checkpoint_snapshots_present()

    op.drop_constraint(_REVIEW_MODE_CHECK, _TABLE, type_="check")
    op.drop_constraint(_OUTPUT_TYPE_CHECK, _TABLE, type_="check")
    op.alter_column(
        _TABLE,
        "review_mode",
        existing_type=sa.String(length=16),
        nullable=False,
    )
    op.alter_column(
        _TABLE,
        "output_type",
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.create_check_constraint(
        _REVIEW_MODE_CHECK,
        _TABLE,
        f"review_mode IN ({_REVIEW_MODE_VALUES})",
    )
    op.create_check_constraint(
        _OUTPUT_TYPE_CHECK,
        _TABLE,
        f"output_type IN ({_OUTPUT_TYPE_VALUES})",
    )


def downgrade() -> None:
    op.drop_constraint(_REVIEW_MODE_CHECK, _TABLE, type_="check")
    op.drop_constraint(_OUTPUT_TYPE_CHECK, _TABLE, type_="check")
    op.alter_column(
        _TABLE,
        "output_type",
        existing_type=sa.String(length=32),
        nullable=True,
    )
    op.alter_column(
        _TABLE,
        "review_mode",
        existing_type=sa.String(length=16),
        nullable=True,
    )
    op.create_check_constraint(
        _REVIEW_MODE_CHECK,
        _TABLE,
        f"review_mode IS NULL OR review_mode IN ({_REVIEW_MODE_VALUES})",
    )
    op.create_check_constraint(
        _OUTPUT_TYPE_CHECK,
        _TABLE,
        f"output_type IS NULL OR output_type IN ({_OUTPUT_TYPE_VALUES})",
    )
