"""store the administrator-managed object-store connection

Revision ID: 202608031800
Revises: 202607311000
Create Date: 2026-08-03 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608031800"
down_revision: str | None = "202607311000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "object_store_connections"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("endpoint_url", sa.String(length=2048), nullable=False),
        sa.Column("region", sa.String(length=128), nullable=False),
        sa.Column("bucket", sa.String(length=63), nullable=False),
        sa.Column("access_key_id_encrypted", sa.Text(), nullable=False),
        sa.Column("secret_access_key_encrypted", sa.Text(), nullable=False),
        sa.Column("deployment_id", sa.UUID(), nullable=False),
        sa.Column("addressing_style", sa.String(length=7), nullable=False),
        sa.Column("updated_by_actor", sa.String(length=32), nullable=False),
        sa.Column("updated_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_object_store_connections_singleton"),
        sa.CheckConstraint(
            "revision >= 1", name="ck_object_store_connections_revision"
        ),
        sa.CheckConstraint(
            "addressing_style IN ('path', 'virtual')",
            name="ck_object_store_connections_addressing_style",
        ),
        sa.CheckConstraint(
            "updated_by_actor IN ('migration', 'platform_admin')",
            name="ck_object_store_connections_actor",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    connection_count = int(
        op.get_bind().execute(sa.text(f"SELECT count(*) FROM {_TABLE}")).scalar_one()
    )
    if connection_count:
        raise RuntimeError(
            "Cannot downgrade while an administrator-managed object-store "
            "connection exists; recover forward or restore the paired "
            "pre-upgrade database and object-store backup"
        )
    op.drop_table(_TABLE)
