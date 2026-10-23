"""Merge provider connection checks and compute migration heads.

Revision ID: 202610131800
Revises: 202609261300, 202610131300
Create Date: 2026-10-13

Both branches are additive and touch different tables. Keep their deployed
revision identities intact; this revision only joins their histories.
"""

revision = "202610131800"
down_revision = ("202609261300", "202610131300")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
