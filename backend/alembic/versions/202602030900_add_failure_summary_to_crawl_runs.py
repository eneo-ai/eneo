"""add_failure_summary_to_crawl_runs

Revision ID: add_failure_summary
Revises: remove_legacy_templates
Create Date: 2026-02-03 09:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic
revision = "add_failure_summary"
down_revision = "remove_legacy_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add JSONB column for storing categorized failure reasons
    # Format: {"EMPTY_CONTENT": 3, "EMBEDDING_TIMEOUT": 12, "DB_ERROR": 1}
    op.add_column(
        "crawl_runs",
        sa.Column(
            "failure_summary",
            JSONB,
            nullable=True,
            comment="JSONB dict mapping failure reason codes to counts",
        ),
    )


def downgrade() -> None:
    op.drop_column("crawl_runs", "failure_summary")
