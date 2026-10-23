"""Merge the develop head and the flow authoring chat head.

Develop's 202610211200 (website path index) and 202610161000 (password
lifecycle) follow 202610191600, which the flow chain already contains, so a
flow database upgrades through them here and a develop database picks up the
flow chain. Re-pointing 202610151000 instead would mark both develop
migrations applied on flow databases without running them.

Revision ID: 202610231000
Revises: 202610161000, 202610221100
Create Date: 2026-10-23 10:00:00.000000
"""

revision: str = "202610231000"
down_revision: tuple[str, str] = ("202610161000", "202610221100")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
