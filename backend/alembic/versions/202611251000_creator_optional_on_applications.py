"""Make the creator a trace on assistants, services, apps and prompts.

``user_id`` on these tables said who made the row, and the row could not
exist without that person. Access never came from it: it comes from the
space. A service key has no person behind it, so it could make none of these.

On ``assistants``, ``services``, ``apps``, ``input_fields`` and ``prompts``:

- ``user_id`` may be empty, and removing the person empties it instead of
  removing the row (``apps`` and ``input_fields`` already said SET NULL on a
  column that could not be NULL, so removing such a person failed);
- ``created_by_service_id`` names the service principal that made the row.

No row is rewritten and every existing row keeps its creator. Each new key is
validated, which reads its table while it is locked.

Revision ID: 202611251000
Revises: 202611241200
Create Date: 2026-11-25 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202611251000"
down_revision: str = "202611241200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table -> (name and ON DELETE rule of the users key before this revision)
_TABLES: dict[str, tuple[str, str]] = {
    "assistants": ("assistants_users_fkey", "CASCADE"),
    "services": ("services_users_fkey", "CASCADE"),
    "apps": ("build_a_services_user_id_fkey", "SET NULL"),
    "input_fields": ("input_fields_user_id_fkey", "SET NULL"),
    "prompts": ("prompts_user_id_fkey", "CASCADE"),
}


def _user_key_names(table: str) -> list[str]:
    """The foreign keys from ``table.user_id`` to ``users``, whatever they are
    called: the names differ between databases of different age."""
    rows = op.get_bind().execute(
        sa.text(
            """
            SELECT con.conname
            FROM pg_constraint AS con
            JOIN pg_attribute AS att
              ON att.attrelid = con.conrelid
             AND att.attnum = ANY (con.conkey)
            WHERE con.contype = 'f'
              AND con.conrelid = to_regclass(:table)
              AND con.confrelid = 'users'::regclass
              AND att.attname = 'user_id'
              AND cardinality(con.conkey) = 1
            """
        ),
        {"table": table},
    )
    return [row[0] for row in rows]


def _drop_user_keys(table: str) -> None:
    for name in _user_key_names(table):
        op.drop_constraint(name, table, type_="foreignkey")


def _add_validated_key(
    name: str, table: str, referred: str, column: str, ondelete: str
) -> None:
    op.create_foreign_key(
        name,
        table,
        referred,
        [column],
        ["id"],
        ondelete=ondelete,
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "user_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=True,
        )
        _drop_user_keys(table)
        _add_validated_key(f"fk_{table}_user_id", table, "users", "user_id", "SET NULL")
        op.add_column(
            table,
            sa.Column(
                "created_by_service_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        _add_validated_key(
            f"fk_{table}_created_by_service",
            table,
            "service_principals",
            "created_by_service_id",
            "SET NULL",
        )


def downgrade() -> None:
    # A row without a person as creator cannot go back to a column that
    # requires one. Refuse instead of inventing a creator or deleting the row.
    bind = op.get_bind()
    for table in _TABLES:
        without_person = bind.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE user_id IS NULL")
        ).scalar_one()
        if without_person:
            raise RuntimeError(
                f"Cannot make the creator required again: {without_person} rows "
                f"of {table} have no person as creator. Remove those rows first."
            )
    for table, (key_name, ondelete) in _TABLES.items():
        op.drop_constraint(f"fk_{table}_created_by_service", table, type_="foreignkey")
        op.drop_column(table, "created_by_service_id")
        op.drop_constraint(f"fk_{table}_user_id", table, type_="foreignkey")
        op.alter_column(
            table,
            "user_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )
        _add_validated_key(key_name, table, "users", "user_id", ondelete)
