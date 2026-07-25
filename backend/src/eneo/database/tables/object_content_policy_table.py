from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseWithTableName, TimestampMixin
from eneo.object_content.content import MAXIMUM_UPLOAD_POLICY_BYTES


class ObjectContentDeploymentPolicy(TimestampMixin, BaseWithTableName):
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_write_storage_target: Mapped[str] = mapped_column(String, nullable=False)
    session_file_limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    session_image_limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    knowledge_file_limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    transcription_audio_limit_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    updated_by_actor: Mapped[str] = mapped_column(String, nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_object_content_policy_singleton"),
        CheckConstraint("revision >= 1", name="ck_object_content_policy_revision"),
        CheckConstraint(
            "new_write_storage_target IN ('postgres_inline', 'object_store')",
            name="ck_object_content_policy_target",
        ),
        CheckConstraint(
            "updated_by_actor IN ('migration', 'platform_admin')",
            name="ck_object_content_policy_actor",
        ),
        CheckConstraint(
            f"session_file_limit_bytes > 0 "
            f"AND session_file_limit_bytes <= {MAXIMUM_UPLOAD_POLICY_BYTES} "
            f"AND session_image_limit_bytes > 0 "
            f"AND session_image_limit_bytes <= {MAXIMUM_UPLOAD_POLICY_BYTES} "
            f"AND knowledge_file_limit_bytes > 0 "
            f"AND knowledge_file_limit_bytes <= {MAXIMUM_UPLOAD_POLICY_BYTES} "
            f"AND transcription_audio_limit_bytes > 0 "
            f"AND transcription_audio_limit_bytes <= {MAXIMUM_UPLOAD_POLICY_BYTES}",
            name="ck_object_content_policy_limit_range",
        ),
    )
