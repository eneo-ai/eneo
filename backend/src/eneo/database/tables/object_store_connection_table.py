from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseWithTableName, TimestampMixin

#: The one destination-slot contract shared by connections and bindings:
#: slot 1 is permanently the active destination; slot 2 exists only while a
#: destination migration holds a candidate or retiring destination.
ACTIVE_DESTINATION_SLOT = 1
TEMPORARY_DESTINATION_SLOT = 2


class ObjectStoreConnections(TimestampMixin, BaseWithTableName):
    """Administrator-managed object-store connections for this deployment.

    Slot 1 is permanently the active destination every reader consults.
    Slot 2 exists only while a destination migration holds a candidate or,
    after cutover, the retiring source. The cutover transaction swaps
    destination payloads between the slots; rows never change identity.

    Revision semantics: slot 1 advances monotonically with every mutation
    (rotation, generation fence, cutover). While slot 2 holds a candidate,
    its revision is a slot-local ownership token that moves on every claim
    change. At cutover the archive adopts the retired active generation's
    revision, so no archive ever re-exposes a value an earlier archive
    carried — administrators name that revision when switching back to or
    forgetting the archive, and a stale token is refused.
    """

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
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
        CheckConstraint("id IN (1, 2)", name="ck_object_store_connections_slots"),
        CheckConstraint(
            "(id = 1 AND role = 'active') OR "
            "(id = 2 AND role IN ('candidate', 'retiring'))",
            name="ck_object_store_connections_role",
        ),
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
