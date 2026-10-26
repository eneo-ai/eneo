"""delete a service key's sessions together with the key

``sessions.api_key_id`` was ON DELETE SET NULL, but only service-key sessions
set it, and those have no ``user_id``. Every row the SET NULL reached
therefore violated ``ck_sessions_user_xor_api_key``, so deleting a key that
owned sessions failed. That happened both when the key was purged and when its
tenant was deleted: Postgres reaches the sessions through the key (two levels)
before it reaches them through their assistant, service or group chat (three).

With CASCADE the key's sessions and their questions go with the key, as
user-owned sessions already go with their user. No rows change.

Revision ID: 202610262130
Revises: 202610261210
Create Date: 2026-10-26 21:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202610262130"
down_revision: str | None = "202610261210"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "sessions_api_key_id_fkey"


def _recreate_api_key_fk(ondelete: str) -> None:
    op.drop_constraint(_CONSTRAINT, "sessions", type_="foreignkey")
    op.create_foreign_key(
        _CONSTRAINT,
        "sessions",
        "api_keys_v2",
        ["api_key_id"],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    _recreate_api_key_fk("CASCADE")


def downgrade() -> None:
    _recreate_api_key_fk("SET NULL")
