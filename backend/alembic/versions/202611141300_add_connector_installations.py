"""Add connector_installations.

Revision ID: 202611141300
Revises: 202611141200
The installations of other systems a tenant lets call Eneo over the connector
protocol: a name, the address the installation publishes its signing keys at,
and the SHA-256 of the shared key (the key itself is never stored). Empty
after upgrade, so the surface stays off until an administrator adds one.
Downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202611141300"
down_revision: str = "202611141200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connector_installations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("base_url", sa.String(length=2000), nullable=False),
        sa.Column("key_digest", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_digest", name="uq_connector_installations_key_digest"),
        sa.UniqueConstraint(
            "tenant_id", "base_url", name="uq_connector_installations_tenant_base_url"
        ),
    )
    op.create_index(
        "ix_connector_installations_tenant_id",
        "connector_installations",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_connector_installations_tenant_id", table_name="connector_installations"
    )
    op.drop_table("connector_installations")
