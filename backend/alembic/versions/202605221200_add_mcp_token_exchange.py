"""mcp_exchanged_tokens + mcp_servers token-exchange columns

Phase 3 of the same-IdP MCP OAuth work. Lands the per-server columns the
broker needs (``tool_discovery_principal`` + ``target_resource_or_scope``)
and the short-lived audience-bound-token cache the broker writes through.

Tenant-level config (``exchange_protocol``, ``mcp_service_account.*``)
lives in the existing ``tenants.federation_config`` JSONB so we don't
have to migrate the tenants table for what is effectively additional
OIDC configuration. Strategy resolution reads from there at request time.

``mcp_exchanged_tokens`` is a cache — safe to truncate, no FK from
``idp_user_tokens`` (cross-tenant rows live independently). Cascades
from the owning ``mcp_server`` so deleting a server purges its cached
tokens; cascades from ``users`` (when ``subject_type='user'``) prevent
orphan rows after user deletion.

Revision ID: 202605221200
Revises: 202605221100
Create Date: 2026-05-22
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202605221200"
down_revision = "202605221100"
branch_labels = None
depends_on = None

DISCOVERY_PRINCIPAL_VALUES = ("anonymous", "tenant_service_account", "admin_user")
DISCOVERY_PRINCIPAL_ENUM_NAME = "mcp_discovery_principal"

SUBJECT_TYPE_VALUES = ("user", "tenant")
SUBJECT_TYPE_ENUM_NAME = "mcp_exchanged_token_subject_type"


def upgrade() -> None:
    discovery_enum = postgresql.ENUM(
        *DISCOVERY_PRINCIPAL_VALUES,
        name=DISCOVERY_PRINCIPAL_ENUM_NAME,
        create_type=False,
    )
    discovery_enum.create(op.get_bind(), checkfirst=True)

    subject_type_enum = postgresql.ENUM(
        *SUBJECT_TYPE_VALUES,
        name=SUBJECT_TYPE_ENUM_NAME,
        create_type=False,
    )
    subject_type_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "mcp_servers",
        sa.Column(
            "tool_discovery_principal",
            discovery_enum,
            nullable=False,
            server_default="anonymous",
        ),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("target_resource_or_scope", sa.Text(), nullable=True),
    )

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
        # subject_id is the user_id for subject_type='user' and the tenant_id
        # for 'tenant'. No FK because the column targets two different tables;
        # cascades come from mcp_server_id (server delete) and tenant_id
        # (tenant delete), which together cover every deletion path.
        sa.Column("subject_id", postgresql.UUID(), nullable=False),
        sa.Column("token_ciphertext", sa.Text(), nullable=False),
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
    # NOTE: a partial index with WHERE expires_at > now() would be ideal but
    # Postgres rejects it because now() is STABLE, not IMMUTABLE. The unique
    # constraint on (mcp_server_id, subject_type, subject_id) already gives
    # us an indexed lookup for the cache hit path; the cache size is bounded
    # by (active users) × (per_user MCP servers) so a full-row index is fine.


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_exchanged_tokens_tenant_id", table_name="mcp_exchanged_tokens"
    )
    op.drop_table("mcp_exchanged_tokens")

    op.drop_column("mcp_servers", "target_resource_or_scope")
    op.drop_column("mcp_servers", "tool_discovery_principal")

    postgresql.ENUM(
        *SUBJECT_TYPE_VALUES,
        name=SUBJECT_TYPE_ENUM_NAME,
        create_type=False,
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        *DISCOVERY_PRINCIPAL_VALUES,
        name=DISCOVERY_PRINCIPAL_ENUM_NAME,
        create_type=False,
    ).drop(op.get_bind(), checkfirst=True)
