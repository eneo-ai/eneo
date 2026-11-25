"""Let a service principal, not its key, own a conversation.

A conversation started with a service key was owned by ``sessions.api_key_id``.
A rotated key has a new id, so the service lost its conversations on every
rotation, and a key that owned conversations could not be removed.

The owner is now ``sessions.service_principal_id``. ``api_key_id`` stays as a
trace of the key that started the conversation and may become empty.

Existing conversations get the principal of their key. Only rows started with
a service key are written, but the two checks and the key read the whole
table while it is locked. Upgrade with the application stopped.

Revision ID: 202611241200
Revises: 202611241100
Create Date: 2026-11-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202611241200"
down_revision: str = "202611241100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SINGLE_PRINCIPAL = "ck_sessions_single_principal"
_KEY_REQUIRES_PRINCIPAL = "ck_sessions_api_key_requires_service_principal"


def _add_validated_check(name: str, condition: str) -> None:
    op.create_check_constraint(
        name,
        "sessions",
        condition,
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE sessions VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "service_principal_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE sessions AS session
            SET service_principal_id = api_key.service_principal_id
            FROM api_keys_v2 AS api_key
            WHERE session.api_key_id = api_key.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                sessions_without_principal integer;
            BEGIN
                SELECT count(*)
                INTO sessions_without_principal
                FROM sessions
                WHERE api_key_id IS NOT NULL
                  AND service_principal_id IS NULL;

                IF sessions_without_principal > 0 THEN
                    RAISE EXCEPTION
                        'Cannot move conversations to service principals: % conversations name an API key that has no service principal.',
                        sessions_without_principal;
                END IF;
            END $$;
            """
        )
    )
    op.drop_constraint(_SINGLE_PRINCIPAL, "sessions", type_="check")
    _add_validated_check(
        _SINGLE_PRINCIPAL,
        "(user_id IS NOT NULL)::int + (service_principal_id IS NOT NULL)::int"
        " + (widget_id IS NOT NULL)::int = 1",
    )
    _add_validated_check(
        _KEY_REQUIRES_PRINCIPAL,
        "api_key_id IS NULL OR service_principal_id IS NOT NULL",
    )
    op.create_foreign_key(
        "fk_sessions_service_principal",
        "sessions",
        "service_principals",
        ["service_principal_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.execute("ALTER TABLE sessions VALIDATE CONSTRAINT fk_sessions_service_principal")
    op.create_index(
        "ix_sessions_service_principal_id",
        "sessions",
        ["service_principal_id"],
        postgresql_where=sa.text("service_principal_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Before this revision the key was the owner. A conversation whose key is
    # gone has no owner to go back to. Refuse instead of deleting it.
    ownerless_count = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM sessions"
                " WHERE service_principal_id IS NOT NULL AND api_key_id IS NULL"
            )
        )
        .scalar_one()
    )
    if ownerless_count:
        raise RuntimeError(
            "Cannot move conversations back to API keys while "
            f"{ownerless_count} conversations belong to a service principal "
            "whose key has been removed. Delete those conversations first."
        )
    op.drop_index("ix_sessions_service_principal_id", table_name="sessions")
    op.drop_constraint("fk_sessions_service_principal", "sessions", type_="foreignkey")
    op.drop_constraint(_KEY_REQUIRES_PRINCIPAL, "sessions", type_="check")
    op.drop_constraint(_SINGLE_PRINCIPAL, "sessions", type_="check")
    op.drop_column("sessions", "service_principal_id")
    _add_validated_check(
        _SINGLE_PRINCIPAL,
        "(user_id IS NOT NULL)::int + (api_key_id IS NOT NULL)::int"
        " + (widget_id IS NOT NULL)::int = 1",
    )
