"""merge seed_allowed_origins and personal_chat heads
Revision ID: 92cfef80384c
Revises: 202606041200, 20260608_add_personal_chat
Create Date: 2026-06-08 12:55:16.345176
"""

# revision identifiers, used by Alembic
revision = "92cfef80384c"
down_revision = ("202606041200", "20260608_add_personal_chat")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
