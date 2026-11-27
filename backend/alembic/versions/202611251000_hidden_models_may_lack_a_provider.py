"""Let a deleted or migrated tenant model have no provider.

Such a model is kept for the history that points at it, and must be able to
outlive its provider.

Revision ID: 202611251000
Revises: 202611201305
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202611251000"
down_revision: str | None = "202611201305"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "(tenant_id IS NULL AND provider_id IS NULL)"
    " OR (tenant_id IS NOT NULL AND provider_id IS NOT NULL)"
)
_DELETED = "deleted_at IS NOT NULL"
_DELETED_OR_MIGRATED = "(deleted_at IS NOT NULL OR migrated_to_model_id IS NOT NULL)"
_HIDDEN = {
    "completion_models": _DELETED_OR_MIGRATED,
    "transcription_models": _DELETED_OR_MIGRATED,
    "embedding_models": _DELETED,
    "image_models": _DELETED,
    "rerank_models": _DELETED,
}


def _replace(table: str, condition: str) -> None:
    name = f"ck_{table}_tenant_provider"
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, condition)


def upgrade() -> None:
    for table, hidden in _HIDDEN.items():
        _replace(
            table,
            f"{_BEFORE} OR (tenant_id IS NOT NULL AND provider_id IS NULL AND {hidden})",
        )


def downgrade() -> None:
    # NOT VALID: models already detached from a deleted provider stay as they are.
    for table in _HIDDEN:
        name = f"ck_{table}_tenant_provider"
        op.drop_constraint(name, table, type_="check")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({_BEFORE}) NOT VALID"
        )
