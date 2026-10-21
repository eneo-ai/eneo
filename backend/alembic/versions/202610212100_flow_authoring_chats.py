"""Bind ordinary assistant chats to a person, a space and a flow

A flow authoring chat is a session with a hidden assistant whose loopback
flows tools act on one flow only; the row also holds whether the chat is in
edit mode, which every write tool checks.

Revision ID: 202610212100
Revises: 202610211900
Create Date: 2026-10-21 21:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "202610212100"
down_revision = "202610211900"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "flow_authoring_chats",
        sa.Column(
            "session_id",
            sa.UUID(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "assistant_id",
            sa.UUID(),
            sa.ForeignKey("assistants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "space_id",
            sa.UUID(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "flow_id",
            sa.UUID(),
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("editing", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "flow_id", name="uq_flow_authoring_chat_owner"
        ),
    )
    op.create_index(
        "ix_flow_authoring_chats_tenant_id", "flow_authoring_chats", ["tenant_id"]
    )


def downgrade():
    table = sa.table("flow_authoring_chats", sa.column("session_id", sa.UUID()))
    if op.get_bind().scalar(sa.select(table.c.session_id).limit(1)) is not None:
        raise RuntimeError(
            "Authoring chats exist; explicitly remove test data before downgrading."
        )
    op.drop_table("flow_authoring_chats")
