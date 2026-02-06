"""merge api_keys_v2 and crawl failure_summary heads

Revision ID: 202602051000
Revises: 202602041630, add_failure_summary
Create Date: 2026-02-05 10:00:00.000000
"""

# revision identifiers, used by Alembic
revision = "202602051000"
down_revision = ("202602041630", "add_failure_summary")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
