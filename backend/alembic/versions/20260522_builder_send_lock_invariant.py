"""enforce builder session send lock invariant

Revision ID: 20260522_builder_lock
Revises: 20260521_plan_edit_json
Create Date: 2026-05-22 01:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260522_builder_lock"
down_revision = "20260521_plan_edit_json"
branch_labels = None
depends_on = None


_CONSTRAINT_NAME = "ck_builder_sessions_send_lock_all_or_none"
_ALL_OR_NONE_SQL = (
    "("
    "active_request_id IS NULL "
    "AND lock_token IS NULL "
    "AND locked_at IS NULL "
    "AND lock_expires_at IS NULL"
    ") OR ("
    "active_request_id IS NOT NULL "
    "AND lock_token IS NOT NULL "
    "AND locked_at IS NOT NULL "
    "AND lock_expires_at IS NOT NULL"
    ")"
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE builder_sessions "
            "SET active_request_id = NULL, "
            "lock_token = NULL, "
            "locked_at = NULL, "
            "lock_expires_at = NULL "
            f"WHERE NOT ({_ALL_OR_NONE_SQL})"
        )
    )
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "builder_sessions",
        _ALL_OR_NONE_SQL,
    )


def downgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT_NAME,
        "builder_sessions",
        type_="check",
    )
