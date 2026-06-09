"""backfill personal_chat permission onto existing roles

The personal chat (personal space default assistant) is decoupled from the
ASSISTANTS permission into its own PERSONAL_CHAT permission. Before this change
the personal chat required ASSISTANTS, so every role that currently grants
ASSISTANTS is exactly the set of roles that could use the personal chat.

To preserve behavior across the cutover we backfill `personal_chat` onto those
roles and only those — roles without `assistants` could not use the personal
chat before and must not silently gain it now. Idempotent: skips roles that
already carry the permission.

Revision ID: 20260608_add_personal_chat
Revises: 20260603_transcription_migrate
Create Date: 2026-06-08

"""
from alembic import op

# revision identifiers, used by Alembic
revision = "20260608_add_personal_chat"
down_revision = "20260603_transcription_migrate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_append(permissions, 'personal_chat')
        WHERE 'assistants' = ANY(permissions)
          AND NOT ('personal_chat' = ANY(permissions))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(permissions, 'personal_chat')
        WHERE 'personal_chat' = ANY(permissions)
        """
    )
