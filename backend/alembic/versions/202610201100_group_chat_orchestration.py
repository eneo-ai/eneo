"""Explicit group-chat orchestrator and consultation history.

Existing groups retain their saved routing until an editor selects an
orchestrator. Historical questions have no consultation records.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202610201100"
down_revision = "202610191600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "group_chats",
        sa.Column(
            "orchestrator_assistant_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_group_chat_orchestrator",
        "group_chats",
        "assistants",
        ["orchestrator_assistant_id"],
        ["id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )
    op.add_column(
        "questions",
        sa.Column("consultations", postgresql.JSONB(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questions", "consultations")
    op.drop_constraint("fk_group_chat_orchestrator", "group_chats", type_="foreignkey")
    op.drop_column("group_chats", "orchestrator_assistant_id")
