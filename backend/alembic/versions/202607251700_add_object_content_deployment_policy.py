"""add object-content deployment policy and platform-admin authority

Revision ID: 202607251700
Revises: 202607241100
"""

import os
from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from dotenv import dotenv_values

from alembic import op

revision: str = "202607251700"
down_revision: str | None = "202607241100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Historical schema snapshot: migrations must remain isolated from runtime modules.
_MAXIMUM_UPLOAD_POLICY_BYTES = 9_007_199_254_740_991
_SEEDS = {
    "session_file_limit_bytes": ("UPLOAD_FILE_TO_SESSION_MAX_SIZE", 10 * 1024**2),
    "session_image_limit_bytes": ("UPLOAD_IMAGE_TO_SESSION_MAX_SIZE", 10 * 1024**2),
    "knowledge_file_limit_bytes": ("UPLOAD_MAX_FILE_SIZE", 10 * 1024**2),
    "transcription_audio_limit_bytes": (
        "TRANSCRIPTION_MAX_FILE_SIZE",
        200 * 1024**2,
    ),
}


def resolve_seed_limits(environment: Mapping[str, str]) -> dict[str, int]:
    values: dict[str, int] = {}
    for field, (variable, default) in _SEEDS.items():
        if variable not in environment:
            values[field] = default
            continue
        raw = environment[variable]
        try:
            value = int(raw)
        except ValueError as error:
            raise ValueError(
                f"{variable} must be a positive integer byte count"
            ) from error
        if value < 1 or value > _MAXIMUM_UPLOAD_POLICY_BYTES:
            raise ValueError(
                f"{variable} must be an integer byte count between "
                f"1 and {_MAXIMUM_UPLOAD_POLICY_BYTES}"
            )
        values[field] = value
    return values


def _seed_environment() -> dict[str, str]:
    # Match legacy Settings precedence: a CWD-relative .env, then process values.
    values = {
        key: value for key, value in dotenv_values(".env").items() if value is not None
    }
    values.update(os.environ)
    return values


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "object_content_deployment_policy",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("new_write_storage_target", sa.String(), nullable=False),
        sa.Column("session_file_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("session_image_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("knowledge_file_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("transcription_audio_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("updated_by_actor", sa.String(), nullable=False),
        sa.Column("updated_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_object_content_policy_singleton"),
        sa.CheckConstraint("revision >= 1", name="ck_object_content_policy_revision"),
        sa.CheckConstraint(
            "new_write_storage_target IN ('postgres_inline', 'object_store')",
            name="ck_object_content_policy_target",
        ),
        sa.CheckConstraint(
            "updated_by_actor IN ('migration', 'platform_admin')",
            name="ck_object_content_policy_actor",
        ),
        sa.CheckConstraint(
            "session_file_limit_bytes > 0 "
            "AND session_file_limit_bytes <= 9007199254740991 "
            "AND session_image_limit_bytes > 0 "
            "AND session_image_limit_bytes <= 9007199254740991 "
            "AND knowledge_file_limit_bytes > 0 "
            "AND knowledge_file_limit_bytes <= 9007199254740991 "
            "AND transcription_audio_limit_bytes > 0 "
            "AND transcription_audio_limit_bytes <= 9007199254740991",
            name="ck_object_content_policy_limit_range",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    limits = resolve_seed_limits(_seed_environment())
    op.execute(
        sa.text(
            "INSERT INTO object_content_deployment_policy "
            "(id, revision, new_write_storage_target, updated_by_actor, "
            "session_file_limit_bytes, session_image_limit_bytes, "
            "knowledge_file_limit_bytes, transcription_audio_limit_bytes) "
            "VALUES (1, 1, 'postgres_inline', 'migration', :session_file, "
            ":session_image, :knowledge_file, :transcription_audio)"
        ).bindparams(
            session_file=limits["session_file_limit_bytes"],
            session_image=limits["session_image_limit_bytes"],
            knowledge_file=limits["knowledge_file_limit_bytes"],
            transcription_audio=limits["transcription_audio_limit_bytes"],
        )
    )


def downgrade() -> None:
    op.drop_table("object_content_deployment_policy")
    op.drop_column("users", "is_platform_admin")
