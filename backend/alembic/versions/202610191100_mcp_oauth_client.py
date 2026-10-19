"""MCP OAuth 2.1 client

Eneo becomes an OAuth 2.1 client toward MCP servers whose vendor protects
them with their own authorization server (``http_auth_type = "oauth"``).

``mcp_servers.auth_scope`` says whose identity the vendor sees: ``per_user``
(each user authorizes once) or ``shared`` (one machine or service-account
identity for the whole tenant). ``mcp_oauth_connections`` stores the
resulting tokens per user and server, with ``user_id IS NULL`` for the shared
row. ``mcp_oauth_client_registrations`` binds Eneo's client identity at an
authorization server to that server's issuer. ``idp_user_tokens`` keeps the
login ID token for tenants that enable the ID-JAG strategy.

Revision ID: 202610191100
Revises: 202610191000
Create Date: 2026-10-19

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "202610191100"
down_revision = "202610191000"
branch_labels = None
depends_on = None


def _id_and_timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("auth_scope", sa.String(), nullable=False, server_default="per_user"),
    )

    op.create_table(
        "mcp_oauth_connections",
        *_id_and_timestamps(),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mcp_server_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="connected"),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "connected_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "mcp_server_id", "user_id", name="uq_mcp_oauth_connections_server_user"
        ),
    )
    op.create_index(
        "uq_mcp_oauth_connections_shared",
        "mcp_oauth_connections",
        ["mcp_server_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "ix_mcp_oauth_connections_user_id", "mcp_oauth_connections", ["user_id"]
    )

    op.create_table(
        "mcp_oauth_client_registrations",
        *_id_and_timestamps(),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mcp_server_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("client_secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "registration_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "mcp_server_id",
            "issuer",
            name="uq_mcp_oauth_client_registrations_server_issuer",
        ),
    )

    op.create_table(
        "idp_user_tokens",
        *_id_and_timestamps(),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idp_issuer", sa.Text(), nullable=False),
        sa.Column("idp_subject", sa.Text(), nullable=True),
        sa.Column("id_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("id_token_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", name="uq_idp_user_tokens_user"),
    )


def downgrade() -> None:
    op.drop_table("idp_user_tokens")
    op.drop_table("mcp_oauth_client_registrations")
    op.drop_index(
        "ix_mcp_oauth_connections_user_id", table_name="mcp_oauth_connections"
    )
    op.drop_index("uq_mcp_oauth_connections_shared", table_name="mcp_oauth_connections")
    op.drop_table("mcp_oauth_connections")
    op.drop_column("mcp_servers", "auth_scope")
