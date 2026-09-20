"""Raise unchanged upload seeds for long recordings and large documents.

Revision ID: 202609202000
Revises: 202609201000
"""

import sqlalchemy as sa

from alembic import op

revision = "202609202000"
down_revision = "202609201000"
branch_labels = None
depends_on = None

_LIMITS = {
    "session_file_limit_bytes": (10485760, 268435456),
    "knowledge_file_limit_bytes": (10485760, 268435456),
    "transcription_audio_limit_bytes": (209715200, 402653184),
}


def upgrade() -> None:
    policy = sa.table(
        "object_content_deployment_policy",
        sa.column("id", sa.SmallInteger),
        sa.column("revision", sa.BigInteger),
        sa.column("updated_at", sa.DateTime),
        sa.column("updated_by_actor", sa.String),
        sa.column("updated_by_user_id", sa.Uuid),
        *(sa.column(name, sa.BigInteger) for name in _LIMITS),
    )
    op.execute(
        policy.update()
        .where(
            policy.c.id == 1,
            sa.or_(*(policy.c[name] == old for name, (old, _) in _LIMITS.items())),
        )
        .values(
            **{
                name: sa.case((policy.c[name] == old, new), else_=policy.c[name])
                for name, (old, new) in _LIMITS.items()
            },
            revision=policy.c.revision + 1,
            updated_at=sa.func.now(),
            updated_by_actor="migration",
            updated_by_user_id=None,
        )
    )


def downgrade() -> None:
    """Preserve policy values and metadata in this data-only migration.

    Values matching the new defaults may be administrator choices; there is no
    provenance that safely distinguishes them from seeds raised by upgrade.
    """
