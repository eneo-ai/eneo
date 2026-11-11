"""Mark a conversation as an insights analysis of other conversations.

An operator's analysis chat about how an assistant or group chat is used is a
regular ``sessions`` row (the operator as ``user_id``, the analysed target as
its partner), so streaming, history replay and retention work unchanged. The
``insight_conversations`` row is what hides it from every normal session,
conversation, analytics and export read, the way ``help_assistant_runs``
hides helper conversations.

``tenant_id`` is explicit so the listing needs no join. Exactly one of
``assistant_id`` / ``group_chat_id`` is set (CHECK), and both cascade with
their target. ``actor_user_id`` and ``completion_model_id`` are ``SET NULL``
so the row survives user removal and model retirement. The UNIQUE constraint
on ``session_id`` is backed by an index that also serves the hidden-session
``NOT EXISTS`` lookup; the composite index serves an operator's list of
analyses of one target, newest first.

Revision ID: 202611111400
Revises: 202611101200
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611111400"
down_revision: str | None = "202611101200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "insight_conversations",
        sa.Column(
            "id",
            sa.UUID(),
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("assistant_id", sa.UUID(), nullable=True),
        sa.Column("group_chat_id", sa.UUID(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("completion_model_id", sa.UUID(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["assistant_id"], ["assistants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["group_chat_id"], ["group_chats.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["completion_model_id"], ["completion_models.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_insight_conversations_session_id"),
        sa.CheckConstraint(
            "(assistant_id IS NOT NULL) <> (group_chat_id IS NOT NULL)",
            name="ck_insight_conversations_target_xor",
        ),
    )
    op.create_index(
        op.f("ix_insight_conversations_tenant_id"),
        "insight_conversations",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_insight_conversations_target_actor_created_at",
        "insight_conversations",
        [
            "tenant_id",
            "assistant_id",
            "group_chat_id",
            "actor_user_id",
            sa.text("created_at DESC"),
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_insight_conversations_target_actor_created_at",
        table_name="insight_conversations",
    )
    op.drop_index(
        op.f("ix_insight_conversations_tenant_id"),
        table_name="insight_conversations",
    )
    op.drop_table("insight_conversations")
