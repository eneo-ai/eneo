"""Join group-chat retirement with the refreshed specialist migration chain.

Existing databases may already have retired their group chats. Preserve that
revision's parent so upgrading them applies develop's missing revisions without
repeating retirement or requiring a data-losing downgrade.

Revision ID: 202611161210
Revises: 202610221200, 202611161200
"""

revision: str = "202611161210"
down_revision: tuple[str, str] = ("202610221200", "202611161200")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
