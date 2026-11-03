"""Merge develop's audit description statistics head and the Flows head.

Develop's 202611030830 (jobs poll index) and 202611031000 (statistics on
lower(audit_logs.description)) follow 202611021100, which the Flows head
202611021200 already contains. The two heads touch different tables, so this
merge adds nothing of its own.

Revision ID: 202611031100
Revises: 202611021200, 202611031000
Create Date: 2026-11-03 11:00:00.000000
"""

revision: str = "202611031100"
down_revision: tuple[str, str] = ("202611021200", "202611031000")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
