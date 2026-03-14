# flake8: noqa

"""add api_keys_v2 and tenant api_key_policy

Revision ID: 202602041600
Revises: e7354c72805b
Create Date: 2026-02-04 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision = "202602041600"
down_revision = "e7354c72805b"
branch_labels = None
depends_on = None


API_KEY_POLICY_DEFAULT = (
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
    op.create_table(
        "api_keys_v2",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.String(), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=True),
        sa.Column("permission", sa.String(), nullable=False),
        sa.Column("key_type", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False),
        sa.Column("hash_version", sa.String(), nullable=False),
        sa.Column("key_prefix", sa.String(), nullable=False),
        sa.Column("key_suffix", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rate_limit", sa.Integer(), nullable=True),
        sa.Column(
            "allowed_origins", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "allowed_ips", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "state",
            sa.String(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason_code", sa.String(), nullable=True),
        sa.Column("revoked_reason_text", sa.String(length=500), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_reason_code", sa.String(), nullable=True),
        sa.Column("suspended_reason_text", sa.String(length=500), nullable=True),
        sa.Column("rotation_grace_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_from_key_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_by_key_id", sa.UUID(), nullable=True),
        sa.Column(
            "delegation_depth",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rotated_from_key_id"],
            ["api_keys_v2.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_key_id"],
            ["api_keys_v2.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "key_hash",
            "hash_version",
            name="uq_api_keys_v2_key_hash_version",
        ),
    )

    op.create_index(
        "idx_api_keys_v2_tenant_scope",
        "api_keys_v2",
        ["tenant_id", "scope_type", "scope_id"],
    )
    op.create_index(
        "idx_api_keys_v2_key_hash",
        "api_keys_v2",
        ["key_hash"],
    )
    op.create_index(
        "idx_api_keys_v2_expires_at",
        "api_keys_v2",
        ["expires_at"],
    )
    op.create_index(
        "idx_api_keys_v2_created_by_key_id",
        "api_keys_v2",
        ["created_by_key_id"],
    )
    op.create_index(
        "idx_api_keys_v2_tenant_state",
        "api_keys_v2",
        ["tenant_id", "state"],
    )

    op.add_column(
        "tenants",
        sa.Column(
            "api_key_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(API_KEY_POLICY_DEFAULT),
        ),
    )

    op.drop_index("ix_allowed_origins_url", table_name="allowed_origins")
    op.create_unique_constraint(
        "uq_allowed_origins_tenant_url",
        "allowed_origins",
        ["tenant_id", "url"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_allowed_origins_tenant_url",
        "allowed_origins",
        type_="unique",
    )
    op.create_index(
        "ix_allowed_origins_url",
        "allowed_origins",
        ["url"],
        unique=True,
    )

    op.drop_column("tenants", "api_key_policy")

    op.drop_index("idx_api_keys_v2_tenant_state", table_name="api_keys_v2")
    op.drop_index("idx_api_keys_v2_created_by_key_id", table_name="api_keys_v2")
    op.drop_index("idx_api_keys_v2_expires_at", table_name="api_keys_v2")
    op.drop_index("idx_api_keys_v2_key_hash", table_name="api_keys_v2")
    op.drop_index("idx_api_keys_v2_tenant_scope", table_name="api_keys_v2")
    op.drop_table("api_keys_v2")
