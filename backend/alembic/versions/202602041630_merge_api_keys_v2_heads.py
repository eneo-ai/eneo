"""merge api_keys_v2 and remove_legacy_templates heads

Revision ID: 202602041630
Revises: remove_legacy_templates, 202602041600
Create Date: 2026-02-04 16:30:00.000000
"""

# revision identifiers, used by Alembic
revision = "202602041630"
down_revision = ("remove_legacy_templates", "202602041600")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
