"""drop legacy api_keys table

v1 API keys are retired. Keys previously used were lazily migrated into
api_keys_v2 (keeping their inp_/ina_ prefixes) and are unaffected; rows
only present in api_keys were never migrated and stop working here.

Revision ID: 202607071200
Revises: 202606281200
Create Date: 2026-07-07 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607071200"
down_revision: Union[str, None] = "202606281200"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("api_keys")


def downgrade() -> None:
    # Structural restore only — dropped key data is not recoverable.
    op.create_table(
        "api_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("truncated_key", sa.String(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "assistant_id", postgresql.UUID(as_uuid=True), nullable=True
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["assistant_id"],
            ["assistants.id"],
            name="api_keys_assistant_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        sa.UniqueConstraint(
            "assistant_id", name="api_keys_assistant_id_unique"
        ),
    )
    op.create_index(op.f("ix_api_keys_key"), "api_keys", ["key"], unique=False)
