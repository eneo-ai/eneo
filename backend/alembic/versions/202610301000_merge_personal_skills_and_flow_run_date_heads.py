"""Merge develop's personal skills head and the flow run date head.

Develop's 202610261200 to 202610291800 (active user size index, icon
reference indexes and cleanup, personal skills permission) follow
202610191000 and 202610221000, which the flow chain already contains
through 202610231000 and 202610261100. The flow chain's 202610281000
(flow run date) follows 202610261100. A flow database runs develop's
revisions here; a develop database picks up the flow chain.

Revision ID: 202610301000
Revises: 202610281000, 202610291800
Create Date: 2026-10-30 10:00:00.000000
"""

revision: str = "202610301000"
down_revision: tuple[str, str] = ("202610281000", "202610291800")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
