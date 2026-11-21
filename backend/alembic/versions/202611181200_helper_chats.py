"""Make the flow authoring chat binding a helper chat binding of any target

``flow_authoring_chats`` becomes ``helper_chats``: ``flow_id`` becomes
``target_id`` and ``target_type`` names what it points at (``flow`` for every
existing row). One person has one chat per target, so the owner constraint
covers ``target_type``. ``target_id`` names rows of different tables and has
no foreign key; deleting a flow removes its chats with their hidden
assistants (``FlowService.delete_flow``). Constraints and indexes take the
new table's names.

The downgrade removes the chats of other targets, with their hidden
assistants and their conversations, and the chats whose flow no longer
exists, before the flow foreign key is restored.

Revision ID: 202611181200
Revises: 202611111400
Create Date: 2026-11-18 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611181200"
down_revision: str | None = "202611111400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "flow_authoring_chats"
_NEW = "helper_chats"
# The foreign keys that stay, by column.
_FOREIGN_KEY_COLUMNS = (
    "session_id",
    "assistant_id",
    "tenant_id",
    "space_id",
    "user_id",
    "completion_model_id",
)


def _rename_names(old: str, new: str) -> None:
    """Name the constraints and index of the table now called ``new`` after
    it, in place of ``old``."""
    op.execute(f"ALTER TABLE {new} RENAME CONSTRAINT {old}_pkey TO {new}_pkey")
    op.execute(
        f"ALTER TABLE {new} RENAME CONSTRAINT {old}_assistant_id_key "
        f"TO {new}_assistant_id_key"
    )
    for column in _FOREIGN_KEY_COLUMNS:
        op.execute(
            f"ALTER TABLE {new} RENAME CONSTRAINT {old}_{column}_fkey "
            f"TO {new}_{column}_fkey"
        )
    op.execute(f"ALTER INDEX ix_{old}_tenant_id RENAME TO ix_{new}_tenant_id")


def upgrade() -> None:
    op.rename_table(_OLD, _NEW)
    _rename_names(_OLD, _NEW)
    op.drop_constraint(f"{_OLD}_flow_id_fkey", _NEW, type_="foreignkey")
    op.alter_column(_NEW, "flow_id", new_column_name="target_id")
    op.add_column(
        _NEW,
        sa.Column("target_type", sa.Text(), nullable=False, server_default="flow"),
    )
    op.alter_column(_NEW, "target_type", server_default=None)
    op.drop_constraint("uq_flow_authoring_chat_owner", _NEW, type_="unique")
    op.create_unique_constraint(
        "uq_helper_chat_owner",
        _NEW,
        ["tenant_id", "user_id", "target_type", "target_id"],
    )


def downgrade() -> None:
    # A chat whose target is no flow, or whose flow is gone, has no place in
    # the old table. Its hidden assistant goes with it, and the assistant's
    # deletion takes its conversations, their questions and the chat's row.
    op.execute(
        f"""
        DELETE FROM assistants
        WHERE id IN (
            SELECT chat.assistant_id
            FROM {_NEW} AS chat
            WHERE chat.target_type <> 'flow'
               OR NOT EXISTS (SELECT 1 FROM flows WHERE flows.id = chat.target_id)
        )
        """
    )
    op.execute(
        f"""
        DELETE FROM {_NEW} AS chat
        WHERE chat.target_type <> 'flow'
           OR NOT EXISTS (SELECT 1 FROM flows WHERE flows.id = chat.target_id)
        """
    )
    op.drop_constraint("uq_helper_chat_owner", _NEW, type_="unique")
    op.drop_column(_NEW, "target_type")
    op.alter_column(_NEW, "target_id", new_column_name="flow_id")
    op.create_unique_constraint(
        "uq_flow_authoring_chat_owner", _NEW, ["tenant_id", "user_id", "flow_id"]
    )
    op.create_foreign_key(
        f"{_OLD}_flow_id_fkey", _NEW, "flows", ["flow_id"], ["id"], ondelete="CASCADE"
    )
    op.rename_table(_NEW, _OLD)
    _rename_names(_NEW, _OLD)
