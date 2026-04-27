"""constrain builder latest_plan_id to the same session

Revision ID: 20260426_latest_plan_fk
Revises: 20260424_builder_attachment_obs
Create Date: 2026-04-26 00:00:00.000000

`builder_sessions.latest_plan_id` points at the plan shown as the latest
AI Builder proposal. A plain FK to `builder_plans.id` proves the plan
exists, but not that it belongs to the same session. This migration
promotes that pointer into a session-scoped invariant before production
data can accumulate inconsistent approval state.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260426_latest_plan_fk"
down_revision = "20260424_builder_attachment_obs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    orphan_latest_plan = conn.execute(
        sa.text(
            "SELECT 1 "
            "FROM builder_sessions bs "
            "LEFT JOIN builder_plans bp ON bs.latest_plan_id = bp.id "
            "WHERE bs.latest_plan_id IS NOT NULL AND bp.id IS NULL "
            "LIMIT 1"
        )
    ).scalar()
    if orphan_latest_plan is not None:
        raise RuntimeError(
            "Cannot apply builder latest-plan migration: "
            "builder_sessions.latest_plan_id references a missing plan."
        )

    invalid_latest_plan = conn.execute(
        sa.text(
            "SELECT 1 "
            "FROM builder_sessions bs "
            "JOIN builder_plans bp ON bs.latest_plan_id = bp.id "
            "WHERE bs.latest_plan_id IS NOT NULL AND bp.session_id <> bs.id "
            "LIMIT 1"
        )
    ).scalar()
    if invalid_latest_plan is not None:
        raise RuntimeError(
            "Cannot apply builder latest-plan migration: "
            "builder_sessions.latest_plan_id references a plan from another session."
        )

    op.drop_constraint(
        "fk_builder_sessions_latest_plan",
        "builder_sessions",
        type_="foreignkey",
    )
    op.create_unique_constraint(
        "uq_builder_plans_id_session_id",
        "builder_plans",
        ["id", "session_id"],
    )
    op.create_foreign_key(
        "fk_builder_sessions_latest_plan_session",
        "builder_sessions",
        "builder_plans",
        ["latest_plan_id", "id"],
        ["id", "session_id"],
        # Plans are session-owned records and should be deleted through the
        # session cascade. A composite FK cannot safely SET NULL here because
        # the second referencing column is builder_sessions.id.
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_builder_sessions_latest_plan_session",
        "builder_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_builder_plans_id_session_id",
        "builder_plans",
        type_="unique",
    )
    op.create_foreign_key(
        "fk_builder_sessions_latest_plan",
        "builder_sessions",
        "builder_plans",
        ["latest_plan_id"],
        ["id"],
        ondelete="SET NULL",
    )
