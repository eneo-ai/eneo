"""MCP OAuth client signing keys

Eneo authenticates as a confidential OAuth client with ``private_key_jwt``
(RFC 7523) at authorization servers that support it. The deployment's
signing keys live here: the private key as a Fernet envelope, the public
key as the JWK the backend publishes in its JWKS document. A retired key
stays published for a grace period so assertions in flight still verify.

Revision ID: 202610191200
Revises: 202610191100
Create Date: 2026-10-19

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "202610191200"
down_revision = "202610191100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_signing_keys",
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
        sa.Column("kid", sa.Text(), nullable=False),
        sa.Column("algorithm", sa.String(), nullable=False),
        sa.Column("private_key_ciphertext", sa.Text(), nullable=False),
        sa.Column(
            "public_jwk", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("retired_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("kid", name="uq_mcp_oauth_signing_keys_kid"),
    )


def downgrade() -> None:
    op.drop_table("mcp_oauth_signing_keys")
