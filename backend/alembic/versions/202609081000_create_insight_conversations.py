"""create insight_conversations

Link table marking a ``sessions`` row as an insights analysis conversation:
a persisted, multi-turn chat an operator has with the model about how a
target assistant or group chat is used. The session itself is a regular
``sessions`` row (operator as ``user_id``, analysed target as partner) so
streaming, history replay and retention all work unchanged; this row is what
hides it from every normal session / conversation / analytics listing, the
same way ``help_assistant_runs`` hides helper conversations.

``tenant_id`` is explicit so listing and retention paths need no join.
Exactly one of ``assistant_id`` / ``group_chat_id`` is set (CHECK), and both
cascade with their target. ``actor_user_id`` and ``completion_model_id`` are
``SET NULL`` so the row survives user removal and model retirement.

Indexes:
- ``ix_insight_conversations_tenant_id`` — tenant-scoped reads.
- ``ix_insight_conversations_target_actor_created_at`` on
  ``(tenant_id, assistant_id, group_chat_id, actor_user_id, created_at DESC)``
  — the operator's "previous analyses" list for one target.

The UNIQUE constraint on ``session_id`` is backed by a unique index, which
also serves the NOT EXISTS lookup in the hidden-session filter.

Revision ID: 202609081000
Revises: 202609071000
Create Date: 2026-09-08
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "202609081000"
down_revision = "202609071000"
branch_labels = None
depends_on = None


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
