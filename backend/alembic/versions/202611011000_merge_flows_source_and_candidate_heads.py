"""Merge the Flows source's develop head and the Flows candidate's Vite head.

The source's 202610301000 joins develop's personal skills permission
(202610291800) with the flow run date (202610281000). The candidate's
202610301500 joins the same flow run date with the skill revision
dependencies (202610291900), which follow 202610291800. Both heads carry
only those revisions, so this merge adds none of its own.

Revision ID: 202611011000
Revises: 202610301000, 202610301500
Create Date: 2026-11-01 10:00:00.000000
"""

revision: str = "202611011000"
down_revision: tuple[str, str] = ("202610301000", "202610301500")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
