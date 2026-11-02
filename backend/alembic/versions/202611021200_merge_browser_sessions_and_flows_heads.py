"""Merge the Vite lane's browser sessions head and the Flows candidate's head.

The Vite lane's 202611021100 adds browser_sessions on top of the skill
revision dependencies (202610291900). The Flows candidate's 202611011000
already includes 202610291900 through 202610301500. The two heads share
that revision and touch different tables, so this merge adds nothing of its own.

Revision ID: 202611021200
Revises: 202611011000, 202611021100
Create Date: 2026-11-02 12:00:00.000000
"""

revision: str = "202611021200"
down_revision: tuple[str, str] = ("202611011000", "202611021100")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
