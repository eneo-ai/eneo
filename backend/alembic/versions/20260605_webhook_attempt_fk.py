"""constrain Flow webhook deliveries to step attempts

Webhook delivery rows are side-effect state for persisted attempts; deletion
stays explicit instead of cascading from attempt cleanup.

Revision ID: 20260605_webhook_attempt_fk
Revises: 20260605_review_ckpt_attempt_fk
Create Date: 2026-06-05 22:45:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260605_webhook_attempt_fk"
down_revision = "20260605_review_ckpt_attempt_fk"
branch_labels = None
depends_on = None


_CONSTRAINT_NAME = "fk_flow_run_webhook_deliveries_step_attempt"
_DELIVERIES_TABLE = "flow_run_webhook_deliveries"
_ATTEMPTS_TABLE = "flow_step_attempts"


def _orphan_delivery_count() -> int:
    bind = op.get_bind()
    return int(
        bind.scalar(
            sa.text(
                """
                SELECT count(*)
                FROM flow_run_webhook_deliveries AS delivery
                LEFT JOIN flow_step_attempts AS attempt
                  ON attempt.flow_run_id = delivery.flow_run_id
                 AND attempt.step_id = delivery.step_id
                 AND attempt.attempt_no = delivery.attempt_no
                WHERE attempt.id IS NULL
                """
            )
        )
        or 0
    )


def _orphan_delivery_samples() -> list[str]:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT
                delivery.id::text,
                delivery.tenant_id::text,
                delivery.flow_id::text,
                delivery.flow_run_id::text,
                delivery.step_id::text,
                delivery.step_order,
                delivery.attempt_no,
                delivery.delivery_status,
                delivery.delivery_attempts,
                delivery.created_at
            FROM flow_run_webhook_deliveries AS delivery
            LEFT JOIN flow_step_attempts AS attempt
              ON attempt.flow_run_id = delivery.flow_run_id
             AND attempt.step_id = delivery.step_id
             AND attempt.attempt_no = delivery.attempt_no
            WHERE attempt.id IS NULL
            ORDER BY delivery.created_at, delivery.id
            LIMIT 5
            """
        )
    )
    return [
        (
            f"id={row[0]} tenant_id={row[1]} flow_id={row[2]} "
            f"flow_run_id={row[3]} step_id={row[4]} step_order={row[5]} "
            f"attempt_no={row[6]} delivery_status={row[7]} "
            f"delivery_attempts={row[8]} created_at={row[9]}"
        )
        for row in rows
    ]


def upgrade() -> None:
    orphan_count = _orphan_delivery_count()
    if orphan_count > 0:
        samples = "; ".join(_orphan_delivery_samples())
        raise RuntimeError(
            f"Cannot add {_CONSTRAINT_NAME}: {orphan_count} "
            "flow_run_webhook_deliveries rows do not reference "
            f"{_ATTEMPTS_TABLE}. Sample deliveries: {samples}. "
            "Delete or repair orphan webhook deliveries, then rerun the upgrade."
        )

    op.create_foreign_key(
        _CONSTRAINT_NAME,
        _DELIVERIES_TABLE,
        _ATTEMPTS_TABLE,
        ["flow_run_id", "step_id", "attempt_no"],
        ["flow_run_id", "step_id", "attempt_no"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.execute(
        f"ALTER TABLE {_DELIVERIES_TABLE} VALIDATE CONSTRAINT {_CONSTRAINT_NAME}"
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, _DELIVERIES_TABLE, type_="foreignkey")
