"""Local password lifecycle.

``users.password_changed_at`` and ``users.password_change_required`` carry
when a local password was last written and whether someone other than the
account (an administrator, provisioning or the deployment seed) chose it.
Such a password is always one-time. ``tenants.password_policy`` holds the
tenant's rotation rule (eneo.users.password_lifecycle.PasswordLifecyclePolicy).

Existing local passwords are stamped with the upgrade time: their real age is
unknown, so a rotation limit counts from this deployment rather than forcing
every account to change at once.

Revision ID: 202610161000
Revises: 202610211200
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202610161000"
down_revision: str | None = "202610211200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PASSWORD_POLICY_DEFAULT = "jsonb_build_object('max_age_days', NULL)"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "password_change_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        "UPDATE users SET password_changed_at = now() WHERE password IS NOT NULL"
    )
    op.add_column(
        "tenants",
        sa.Column(
            "password_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(_PASSWORD_POLICY_DEFAULT),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "password_policy")
    op.drop_column("users", "password_change_required")
    op.drop_column("users", "password_changed_at")
