"""Retire group chats: each group becomes an assistant with specialists.

A group chat routed every question to one member. Its replacement is an
assistant that consults its specialists. Every group chat row becomes an
assistant with the same id, in the same space, with the same owner, name,
icon, publication and insight setting; its members become the assistant's
specialists with their routing descriptions. Keeping the id means sessions,
insights, audit entries and links keep pointing at the right thing.

The migrated assistant gets the space's first enabled model that can call
tools, or no model when the space has none; editors then choose one. It gets
no instructions: the orchestration prompt is the editor's to write.

This revision first followed 202610201100 on a chain that left the main one
at 202610161000. A database migrated on that chain reports itself at head,
so `alembic upgrade head` would skip the revisions now before it, and two of
them (202610261220 and 202610261300) still expect the group_chats table
that this revision drops. To move such a database without losing data, run
with this code:

    alembic stamp --purge 202610161000
    psql -c "CREATE TABLE group_chats (id uuid, space_id uuid, icon_id uuid)"
    alembic upgrade 202611031206
    psql -c "DROP TABLE group_chats"
    alembic stamp head

The empty table only lets those two revisions run; this revision and the
two before it are already applied.

Revision ID: 202610221200
Revises: 202610201100
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202610221200"
down_revision = "202610201100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO assistants (
            id, created_at, updated_at, name, completion_model_kwargs,
            logging_enabled, guardrail_active, completion_model_id, user_id,
            space_id, is_default, published, type, insight_enabled,
            metadata_json, icon_id
        )
        SELECT
            g.id, g.created_at, now(), g.name, '{}'::jsonb,
            false, false,
            (
                SELECT cm.id
                FROM spaces_completion_models scm
                JOIN completion_models cm ON cm.id = scm.completion_model_id
                WHERE scm.space_id = g.space_id
                  AND cm.supports_tool_calling
                  AND NOT cm.is_deprecated
                ORDER BY cm.created_at
                LIMIT 1
            ),
            g.user_id, g.space_id, false, g.published, 'assistant',
            g.insight_enabled,
            CASE
                WHEN jsonb_typeof(g.metadata_json) = 'object' THEN g.metadata_json
                ELSE '{}'::jsonb
            END || '{"migrated_from_group_chat": true}'::jsonb,
            g.icon_id
        FROM group_chats g
        WHERE NOT EXISTS (SELECT 1 FROM assistants a WHERE a.id = g.id)
        """
    )
    op.execute(
        """
        INSERT INTO assistants_specialists (
            assistant_id, specialist_id, description, created_at, updated_at
        )
        SELECT m.group_chat_id, m.assistant_id, m.user_description, now(), now()
        FROM group_chats_assistants_mapping m
        JOIN assistants orchestrator ON orchestrator.id = m.group_chat_id
        JOIN assistants specialist ON specialist.id = m.assistant_id
        WHERE m.group_chat_id <> m.assistant_id
          AND specialist.space_id = orchestrator.space_id
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE sessions
        SET assistant_id = group_chat_id
        WHERE group_chat_id IS NOT NULL
        """
    )
    op.drop_constraint("sessions_group_chat_id_fkey", "sessions", type_="foreignkey")
    op.drop_column("sessions", "group_chat_id")
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(permissions, 'group_chats')
        WHERE 'group_chats' = ANY(permissions)
        """
    )
    op.drop_table("group_chats_assistants_mapping")
    op.drop_table("group_chats")


def downgrade() -> None:
    # Structure only: migrated assistants stay assistants and sessions keep
    # pointing at them. Restore from a backup to get the group rows back.
    op.create_table(
        "group_chats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("allow_mentions", sa.Boolean(), nullable=False),
        sa.Column("show_response_label", sa.Boolean(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("insight_enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "icon_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("icons.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # 202610261220 indexed the icon reference; its downgrade drops it.
    op.create_index(
        "ix_group_chats_icon_id",
        "group_chats",
        ["icon_id"],
        postgresql_where=sa.text("icon_id IS NOT NULL"),
    )
    op.create_table(
        "group_chats_assistants_mapping",
        sa.Column(
            "group_chat_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("group_chats.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "assistant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assistants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_description", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "group_chat_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "group_chats.id",
                ondelete="CASCADE",
                name="sessions_group_chat_id_fkey",
            ),
            nullable=True,
        ),
    )
    # 20260130_add_analytics_indexes indexed the column; its downgrade drops it.
    op.create_index(
        "idx_sessions_group_chat_created_at",
        "sessions",
        ["group_chat_id", "created_at"],
        unique=False,
    )
