"""Let an app run belong to a service principal.

An app run had to belong to a person. The column also said SET NULL on a
value that could not be NULL, so removing a person who had run an app failed.
A service key could run no app at all: the run would have carried the key's
id, which is no user.

``app_runs.user_id`` may now be empty, and ``service_principal_id`` is the
owner of a run a service key started. A run has at most one owner.

No row is rewritten and every existing run keeps its person. The keys and the
check are validated, which reads ``app_runs`` while it is locked.

Revision ID: 202611251200
Revises: 202611251100
Create Date: 2026-11-25 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202611251200"
down_revision: str = "202611251100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SINGLE_OWNER = "ck_app_runs_single_owner"
_OLD_USER_KEY = "app_runs_user_id_fkey"


def _user_key_names() -> list[str]:
    """The foreign keys from ``app_runs.user_id`` to ``users``, whatever they
    are called: the names differ between databases of different age."""
    rows = op.get_bind().execute(
        sa.text(
            """
            SELECT con.conname
            FROM pg_constraint AS con
            JOIN pg_attribute AS att
              ON att.attrelid = con.conrelid
             AND att.attnum = ANY (con.conkey)
            WHERE con.contype = 'f'
              AND con.conrelid = 'app_runs'::regclass
              AND con.confrelid = 'users'::regclass
              AND att.attname = 'user_id'
              AND cardinality(con.conkey) = 1
            """
        )
    )
    return [row[0] for row in rows]


def _add_validated_key(name: str, referred: str, column: str, ondelete: str) -> None:
    op.create_foreign_key(
        name,
        "app_runs",
        referred,
        [column],
        ["id"],
        ondelete=ondelete,
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE app_runs VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    op.alter_column(
        "app_runs",
        "user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    for name in _user_key_names():
        op.drop_constraint(name, "app_runs", type_="foreignkey")
    _add_validated_key("fk_app_runs_user_id", "users", "user_id", "SET NULL")
    op.add_column(
        "app_runs",
        sa.Column("service_principal_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _add_validated_key(
        "fk_app_runs_service_principal",
        "service_principals",
        "service_principal_id",
        "RESTRICT",
    )
    op.create_check_constraint(
        _SINGLE_OWNER,
        "app_runs",
        "user_id IS NULL OR service_principal_id IS NULL",
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE app_runs VALIDATE CONSTRAINT {_SINGLE_OWNER}")


def downgrade() -> None:
    # A run without a person cannot go back to a column that requires one.
    # It holds what the app produced: refuse instead of deleting it.
    without_person = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM app_runs WHERE user_id IS NULL"))
        .scalar_one()
    )
    if without_person:
        raise RuntimeError(
            f"Cannot require a person on app runs again: {without_person} runs "
            "belong to no person. Remove those runs first."
        )
    op.drop_constraint(_SINGLE_OWNER, "app_runs", type_="check")
    op.drop_constraint("fk_app_runs_service_principal", "app_runs", type_="foreignkey")
    op.drop_column("app_runs", "service_principal_id")
    op.drop_constraint("fk_app_runs_user_id", "app_runs", type_="foreignkey")
    op.alter_column(
        "app_runs",
        "user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    _add_validated_key(_OLD_USER_KEY, "users", "user_id", "SET NULL")
