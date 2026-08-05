from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseWithTableName, TimestampMixin


class ObjectStoreConnections(TimestampMixin, BaseWithTableName):
    """The one administrator-managed object-store connection for this deployment."""

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    region: Mapped[str] = mapped_column(String(128), nullable=False)
    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    access_key_id_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    secret_access_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    deployment_id: Mapped[UUID] = mapped_column(nullable=False)
    addressing_style: Mapped[str] = mapped_column(String(7), nullable=False)
    updated_by_actor: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_object_store_connections_singleton"),
        CheckConstraint("revision >= 1", name="ck_object_store_connections_revision"),
        CheckConstraint(
            "addressing_style IN ('path', 'virtual')",
            name="ck_object_store_connections_addressing_style",
        ),
        CheckConstraint(
            "updated_by_actor IN ('migration', 'platform_admin')",
            name="ck_object_store_connections_actor",
        ),
    )
