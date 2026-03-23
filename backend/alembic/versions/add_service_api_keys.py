"""add service api keys

Revision ID: a1b2c3d4e5f6
Revises: 847ef045f3c1
Create Date: 2026-03-17 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision = "svc_api_keys_001"
down_revision = "202602131000"
branch_labels = None
depends_on = None

# Name of the FK constraint to recreate (matches SQLAlchemy auto-generated name)
_FK_NAME = "api_keys_v2_owner_user_id_fkey"
_TABLE = "api_keys_v2"


def upgrade() -> None:
    # 1. Add ownership column with server default
    op.add_column(
        _TABLE,
        sa.Column("ownership", sa.String(), nullable=False, server_default="user"),
    )

    # 2. Make owner_user_id nullable
    op.alter_column(_TABLE, "owner_user_id", existing_type=sa.UUID(), nullable=True)

    # 3. Recreate FK with SET NULL instead of CASCADE
    op.drop_constraint(_FK_NAME, _TABLE, type_="foreignkey")
    op.create_foreign_key(
        _FK_NAME,
        _TABLE,
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # 1. Recreate FK with CASCADE
    op.drop_constraint(_FK_NAME, _TABLE, type_="foreignkey")
    op.create_foreign_key(
        _FK_NAME,
        _TABLE,
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 2. Make owner_user_id non-nullable (service keys will fail — acceptable for downgrade)
    op.alter_column(_TABLE, "owner_user_id", existing_type=sa.UUID(), nullable=False)

    # 3. Drop ownership column
    op.drop_column(_TABLE, "ownership")
