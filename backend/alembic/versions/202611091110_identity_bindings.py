"""bind accounts to the provider identities that sign in to them

Revision ID: 202611091110
Revises: 202611091100
Create Date: 2026-11-09 11:10:00.000000

identity_bindings maps (tenant, issuer, audience, subject claim, subject) to
one account.
identity_migration_windows and users.identity_rebinding_until are the two
explicit ways an organisation admin lets an already bound account take a new
identity by its email. Existing accounts start unbound: their next sign-in
binds them by email, as sign-in matched them before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202611091110"
down_revision: str | None = "202611091100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.TIMESTAMP(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def _tenant_id() -> sa.Column:
    return sa.Column(
        "tenant_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "identity_bindings",
        _id(),
        _tenant_id(),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issuer", sa.String(), nullable=False),
        sa.Column("audience", sa.String(), nullable=False),
        sa.Column("subject_claim", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            # The insert's own time: a binding written after a window opened
            # is newer than the window, however long its transaction waited.
            server_default=sa.func.clock_timestamp(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "issuer",
            "subject_claim",
            "subject",
            "audience",
            name="identity_bindings_identity_key",
        ),
        sa.UniqueConstraint(
            "user_id", "issuer", "audience", name="identity_bindings_account_key"
        ),
    )
    op.create_table(
        "identity_migration_windows",
        _id(),
        _tenant_id(),
        sa.Column("from_issuer", sa.String(), nullable=False),
        sa.Column("from_audience", sa.String(), nullable=False),
        sa.Column("to_issuer", sa.String(), nullable=False),
        sa.Column("to_audience", sa.String(), nullable=False),
        sa.Column("closes_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _created_at(),
    )
    op.create_index(
        "ix_identity_migration_windows_target",
        "identity_migration_windows",
        ["tenant_id", "to_issuer", "to_audience"],
    )
    op.add_column(
        "users",
        sa.Column(
            "identity_rebinding_until", sa.TIMESTAMP(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "identity_rebinding_until")
    op.drop_table("identity_migration_windows")
    op.drop_table("identity_bindings")
