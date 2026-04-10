"""merge remaining alembic heads after develop sync

Revision ID: 20260410_merge_heads
Revises: 202603311430, svc_api_keys_001
Create Date: 2026-04-10 00:00:00.000000
"""


# revision identifiers, used by Alembic.
revision = "20260410_merge_heads"
down_revision = ("202603311430", "svc_api_keys_001")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
