"""mcp_exchanged_tokens: broker-minted token cache

Short-lived audience-restricted tokens minted by the MCP token broker.
The table is a cache, safe to truncate. One row per
(mcp_server_id, subject_type, subject_id).

``subject_id`` is the user_id for subject_type='user' and the tenant_id
for 'tenant'. No FK because the column targets two different tables;
cascades come from mcp_server_id (server delete) and tenant_id (tenant
delete), which together cover every deletion path.

``refresh_token_ciphertext`` holds the refresh token some authorization
servers return alongside the exchanged access token; the broker uses it
to renew the audience token without re-running the full exchange.

Tenant-level broker config (service-account credentials, default target)
lives in the existing ``tenants.federation_config`` JSONB; strategy
resolution reads it at request time, so no tenants-table migration.

Revision ID: 202608031200
Revises: 202608031100
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202608031200"
down_revision = "202608031100"
branch_labels = None
depends_on = None

SUBJECT_TYPE_VALUES = ("user", "tenant")
SUBJECT_TYPE_ENUM_NAME = "mcp_exchanged_token_subject_type"


def upgrade() -> None:
    subject_type_enum = postgresql.ENUM(
        *SUBJECT_TYPE_VALUES,
        name=SUBJECT_TYPE_ENUM_NAME,
        create_type=False,
    )
    subject_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "mcp_exchanged_tokens",
        sa.Column(
            "id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "mcp_server_id",
            postgresql.UUID(),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_type", subject_type_enum, nullable=False),
        sa.Column("subject_id", postgresql.UUID(), nullable=False),
        sa.Column("token_ciphertext", sa.Text(), nullable=False),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("idp_issuer", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "mcp_server_id",
            "subject_type",
            "subject_id",
            name="uq_mcp_exchanged_tokens_server_subject",
        ),
    )
    op.create_index(
        "ix_mcp_exchanged_tokens_tenant_id",
        "mcp_exchanged_tokens",
        ["tenant_id"],
    )
    # NOTE: a partial index with WHERE expires_at > now() is rejected by
    # Postgres because now() is STABLE, not IMMUTABLE. The unique constraint
    # already gives the cache-hit path an indexed lookup; the cache size is
    # bounded by (active users) x (per_user MCP servers).


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_exchanged_tokens_tenant_id", table_name="mcp_exchanged_tokens"
    )
    op.drop_table("mcp_exchanged_tokens")

    postgresql.ENUM(
        *SUBJECT_TYPE_VALUES,
        name=SUBJECT_TYPE_ENUM_NAME,
        create_type=False,
    ).drop(op.get_bind(), checkfirst=True)
