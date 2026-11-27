"""Record MFA on the session and the requirement on the space.

A space that requires MFA needs a yes or no it can trust for the session
behind each call, and somewhere to say that it requires it.

``browser_sessions.mfa`` is whether the sign-in that started the session met
the organisation's MFA rule. It is no for every existing session: none of them
was judged under a rule. ``spaces.mfa_required`` is the requirement. It is off
for every space, and nothing switches it on yet.

Both columns get a constant default, so no row is rewritten and each table is
locked only for the catalogue change.

Revision ID: 202611271000
Revises: 202611201305
Create Date: 2026-11-27 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611271000"
down_revision: str = "202611201305"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "browser_sessions",
        sa.Column("mfa", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "spaces",
        sa.Column(
            "mfa_required", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )


def downgrade() -> None:
    # The earlier release checks no requirement, so it would open these spaces
    # to sessions without MFA. Refuse instead of dropping the requirement
    # silently.
    required = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM spaces WHERE mfa_required"))
        .scalar_one()
    )
    if required:
        raise RuntimeError(
            f"Cannot remove the MFA requirement: {required} spaces require MFA. "
            "Switch the requirement off for them first, or restore the backup "
            "taken before the upgrade."
        )
    op.drop_column("spaces", "mfa_required")
    op.drop_column("browser_sessions", "mfa")
