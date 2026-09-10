"""Add tenant policy for API-key CORS origins.

Revision ID: 202609101000
Revises: 202609071000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609101000"
down_revision: str | None = "202609071000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_POLICY_DEFAULT_WITH_TENANT_ORIGIN = (
    "jsonb_build_object("
    "'max_delegation_depth', 3, "
    "'revocation_cascade_enabled', false, "
    "'require_tenant_allowed_origin', true, "
    "'require_expiration', false, "
    "'max_expiration_days', NULL, "
    "'auto_expire_unused_days', NULL, "
    "'max_rate_limit_override', NULL"
    ")"
)

_PREVIOUS_POLICY_DEFAULT = (
    "jsonb_build_object("
    "'max_delegation_depth', 3, "
    "'revocation_cascade_enabled', false, "
    "'require_expiration', false, "
    "'max_expiration_days', NULL, "
    "'auto_expire_unused_days', NULL, "
    "'max_rate_limit_override', NULL"
    ")"
)


def upgrade() -> None:
    op.execute(
        """
        UPDATE tenants
        SET api_key_policy = jsonb_set(
            api_key_policy,
            '{require_tenant_allowed_origin}',
            'true'::jsonb,
            true
        )
        WHERE NOT api_key_policy ? 'require_tenant_allowed_origin'
        """
    )
    op.alter_column(
        "tenants",
        "api_key_policy",
        server_default=sa.text(_POLICY_DEFAULT_WITH_TENANT_ORIGIN),
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE tenants
        SET api_key_policy = api_key_policy - 'require_tenant_allowed_origin'
        """
    )
    op.alter_column(
        "tenants",
        "api_key_policy",
        server_default=sa.text(_PREVIOUS_POLICY_DEFAULT),
    )
