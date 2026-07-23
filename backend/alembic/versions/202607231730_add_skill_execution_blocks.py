"""add organisation Skill execution blocks

Revision ID: 202607231730
Revises: 202607231330
Create Date: 2026-07-23 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607231730"
down_revision: str | None = "202607231330"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_execution_blocks",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "skill_space_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "blocked_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "unblocked_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("unblock_reason", sa.Text(), nullable=True),
        sa.Column(
            "unblocked_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
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
        sa.CheckConstraint(
            "char_length(btrim(reason)) BETWEEN 1 AND 1000",
            name="ck_skill_execution_blocks_reason_length",
        ),
        sa.CheckConstraint(
            """
            (
                unblocked_at IS NULL
                AND unblocked_by_user_id IS NULL
                AND unblock_reason IS NULL
            )
            OR
            (
                unblocked_at IS NOT NULL
                AND unblocked_by_user_id IS NOT NULL
                AND char_length(btrim(unblock_reason)) BETWEEN 1 AND 1000
            )
            """,
            name="ck_skill_execution_blocks_unblock_state",
        ),
        sa.ForeignKeyConstraint(
            ["blocked_by_user_id"],
            ["users.id"],
            name="fk_skill_execution_blocks_blocked_by_user_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["unblocked_by_user_id"],
            ["users.id"],
            name="fk_skill_execution_blocks_unblocked_by_user_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "skill_space_id"],
            ["spaces.tenant_id", "spaces.id"],
            name="fk_skill_execution_blocks_tenant_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_space_id", "skill_id"],
            ["skills.space_id", "skills.id"],
            name="fk_skill_execution_blocks_skill",
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_skill_execution_blocks"),
    )
    op.create_index(
        "uq_skill_execution_blocks_active_tenant_skill",
        "skill_execution_blocks",
        ["tenant_id", "skill_id"],
        unique=True,
        postgresql_where=sa.text("unblocked_at IS NULL"),
    )
    op.create_index(
        "ix_skill_execution_blocks_tenant_skill_created",
        "skill_execution_blocks",
        ["tenant_id", "skill_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_skill_execution_blocks_tenant_skill_created",
        table_name="skill_execution_blocks",
    )
    op.drop_index(
        "uq_skill_execution_blocks_active_tenant_skill",
        table_name="skill_execution_blocks",
    )
    op.drop_table("skill_execution_blocks")
