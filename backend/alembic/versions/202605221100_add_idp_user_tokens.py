"""idp_user_tokens: persisted IdP refresh + access tokens, encrypted at rest

Phase 2 of the same-IdP MCP OAuth work. Captures the user's IdP tokens
at the federation callback so the broker (Phase 3) can do RFC 8693 token
exchange or OBO without sending the user through a second consent screen.

Storage shape (per RFC 6749 §10.4 — tokens MUST be kept confidential in
transit and storage):

- One row per (user_id, idp_issuer). Re-login UPSERTs.
- ``refresh_token_ciphertext`` is the long-lived secret, encrypted via
  the existing ``EncryptionService`` (Fernet, ``enc:fernet:v1:`` prefix).
- ``access_token_ciphertext`` is a short-lived convenience cache so the
  broker can skip a refresh round-trip when still valid.
- ``key_version`` enables lazy re-encryption when the operator rotates
  the underlying key in a later phase.
- ``revoked_at`` is the logout sentinel; the broker treats a non-null
  ``revoked_at`` as "force re-authentication" without deleting the audit
  trail row.

Cascades: ``user_id`` ON DELETE CASCADE means tenant or user deletion
removes the token rows; the Phase-3 ``mcp_exchanged_tokens`` cache will
likewise cascade from this row (when it lands).

Revision ID: 202605221100
Revises: 202605221000
Create Date: 2026-05-22
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202605221100"
down_revision = "202605221000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idp_user_tokens",
        sa.Column(
            "id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idp_issuer", sa.Text(), nullable=False),
        sa.Column("idp_subject", sa.Text(), nullable=True),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=True),
        sa.Column(
            "access_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "scopes_granted",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "key_version",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
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
        sa.Column(
            "last_refresh_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "user_id",
            "idp_issuer",
            name="uq_idp_user_tokens_user_issuer",
        ),
    )
    op.create_index(
        "ix_idp_user_tokens_tenant_id",
        "idp_user_tokens",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_idp_user_tokens_tenant_id", table_name="idp_user_tokens")
    op.drop_table("idp_user_tokens")
