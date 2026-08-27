"""add user credential version for session invalidation

Revision ID: 202608271000
Revises: 202608251400
Create Date: 2026-08-27 10:00:00.000000

Existing Eneo JWTs have no credential-version claim and therefore represent
version zero. The non-null zero default keeps those sessions valid during a
rolling deployment. Password changes increment the value atomically with the
credential write, invalidating every earlier Eneo JWT on its next request.

Deploy in expand order: apply this migration, deploy backend enforcement, then
release the UI. Rolling application code back to a build that ignores this
column can resurrect still-unexpired pre-change JWTs even while the column
remains. A security-safe rollback must either retain version enforcement; or
freeze credential mutations and all JWT/module-token/module-ticket issuance
and exchange for the entire maximum lifetime before cutover; or rotate the JWT
secret at cutover and invalidate outstanding module tickets. Merely waiting
while credentials or sessions continue to change is not safe. Keep JWT_ISSUER
stable and distinct from provider issuers until the legacy version-zero token
window has drained: claim-less signed tokens are classified by that boundary.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608271000"
down_revision: str = "202608251400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "credential_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    # Removing the column re-enables every otherwise-valid pre-change token.
    # Downgrade only under one of the safe rollback procedures documented above.
    op.drop_column("users", "credential_version")
