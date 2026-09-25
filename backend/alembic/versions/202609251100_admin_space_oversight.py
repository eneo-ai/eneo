"""record oversight joins and widget activation requests

Two small additions for tenant-admin oversight:

- `spaces_users` records when a tenant administrator joined a space through
  oversight, and the reason they gave. Both are set together or not at all.
- `widgets` records a pending activation request (when and by whom) and the
  last time an administrator sent one back (when, by whom and why). A widget
  is never both requested and sent back, and only a draft or paused widget
  can have a pending request.

Every column is nullable without a default, so adding it only changes the
catalog. The CHECK constraints scan two small tables once.

Revision ID: 202609251100
Revises: 202609251000
Create Date: 2026-09-25 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609251100"
down_revision: str | None = "202609251000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SPACES_USERS_CHECKS = {
    "ck_spaces_users_oversight_join_pair": (
        "(oversight_joined_at IS NULL) = (oversight_join_reason IS NULL)"
    ),
    "ck_spaces_users_oversight_join_reason_length": (
        "oversight_join_reason IS NULL"
        " OR char_length(oversight_join_reason) BETWEEN 10 AND 500"
    ),
}

_WIDGETS_CHECKS = {
    "ck_widgets_activation_request_status": (
        "activation_requested_at IS NULL OR status IN ('draft', 'paused')"
    ),
    "ck_widgets_activation_decline_pair": (
        "(activation_declined_at IS NULL) = (activation_decline_reason IS NULL)"
    ),
    "ck_widgets_activation_request_xor_decline": (
        "activation_requested_at IS NULL OR activation_declined_at IS NULL"
    ),
    "ck_widgets_activation_decline_reason_length": (
        "activation_decline_reason IS NULL"
        " OR char_length(activation_decline_reason) BETWEEN 10 AND 500"
    ),
}


def upgrade() -> None:
    # Fail fast instead of queueing space and widget reads behind a long
    # transaction; rerunning the upgrade is safe because nothing committed.
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.add_column(
        "spaces_users",
        sa.Column("oversight_joined_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "spaces_users",
        sa.Column("oversight_join_reason", sa.Text(), nullable=True),
    )
    for name, condition in _SPACES_USERS_CHECKS.items():
        op.create_check_constraint(name, "spaces_users", condition)

    op.add_column(
        "widgets",
        sa.Column(
            "activation_requested_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "widgets",
        sa.Column(
            "activation_requested_by_user_id",
            sa.UUID(),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_widgets_activation_requested_by_user_id",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "widgets",
        sa.Column("activation_declined_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "widgets",
        sa.Column(
            "activation_declined_by_user_id",
            sa.UUID(),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_widgets_activation_declined_by_user_id",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "widgets",
        sa.Column("activation_decline_reason", sa.Text(), nullable=True),
    )
    for name, condition in _WIDGETS_CHECKS.items():
        op.create_check_constraint(name, "widgets", condition)

    # Later revisions in the same run must not inherit the short timeout.
    op.execute("SET LOCAL lock_timeout = DEFAULT")


def downgrade() -> None:
    for name in _WIDGETS_CHECKS:
        op.drop_constraint(name, "widgets", type_="check")
    # Dropping a column drops its foreign key with it.
    op.drop_column("widgets", "activation_decline_reason")
    op.drop_column("widgets", "activation_declined_by_user_id")
    op.drop_column("widgets", "activation_declined_at")
    op.drop_column("widgets", "activation_requested_by_user_id")
    op.drop_column("widgets", "activation_requested_at")

    for name in _SPACES_USERS_CHECKS:
        op.drop_constraint(name, "spaces_users", type_="check")
    op.drop_column("spaces_users", "oversight_join_reason")
    op.drop_column("spaces_users", "oversight_joined_at")
