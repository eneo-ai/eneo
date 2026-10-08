from typing import Any, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.files.file_models import FileType, FileUsageKind

FILE_USAGE_INFO_KEY = "file_usage"


def file_usage(kind: FileUsageKind | None) -> dict[str, Any]:
    """Column ``info`` for a foreign key to ``files.id``.

    Every such column declares, where it is defined, whether it keeps the File
    in use (a ``FileUsageKind``) or not (``None``: a derived File belongs to its
    root's family, stored content is released with the File). The usage
    columns fence user deletion and the unused-file cleanup; a column without
    this declaration fails ``eneo.files.file_usage`` on import.
    """
    return {FILE_USAGE_INFO_KEY: kind}


class Files(BasePublic):
    name: Mapped[str] = mapped_column()
    mimetype: Mapped[Optional[str]] = mapped_column()
    file_type: Mapped[str] = mapped_column(server_default=FileType.TEXT)

    # Foreign keys
    owner_type: Mapped[str] = mapped_column(nullable=False, server_default="user")
    owner_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="RESTRICT"),
        nullable=True,
    )
    owner_service_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("service_principals.id", ondelete="RESTRICT"),
        nullable=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))

    # Set for files derived from another upload (for example extracted images).
    parent_file_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"),
        index=True,
        info=file_usage(None),
    )

    # Temporary Release A read source. Normal metadata queries must never
    # detoast these payloads; the File repository loads them explicitly only
    # when an object-content reference is still missing.
    legacy_text: Mapped[Optional[str]] = mapped_column(
        "text",
        Text,
        deferred=True,
        deferred_raiseload=True,
    )
    legacy_blob: Mapped[Optional[bytes]] = mapped_column(
        "blob",
        BYTEA,
        deferred=True,
        deferred_raiseload=True,
    )
    legacy_checksum: Mapped[Optional[str]] = mapped_column(
        "checksum",
        String,
        deferred=True,
        deferred_raiseload=True,
    )
    legacy_size: Mapped[Optional[int]] = mapped_column(
        "size",
        Integer,
        deferred=True,
        deferred_raiseload=True,
    )
    legacy_transcription: Mapped[Optional[str]] = mapped_column(
        "transcription",
        Text,
        deferred=True,
        deferred_raiseload=True,
    )

    __table_args__ = (
        CheckConstraint(
            "owner_type IN ('user','service_key')",
            name="ck_files_owner_type",
        ),
        CheckConstraint(
            "("
            "owner_type = 'user' "
            "AND owner_user_id IS NOT NULL "
            "AND owner_service_id IS NULL"
            ") OR ("
            "owner_type = 'service_key' "
            "AND owner_user_id IS NULL "
            "AND owner_service_id IS NOT NULL"
            ")",
            name="ck_files_owner_identity",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_files_id_tenant_id"),
        Index(
            "ix_files_service_owner_created_at",
            "tenant_id",
            "owner_service_id",
            "created_at",
            postgresql_where=sa.text("owner_type = 'service_key'"),
        ),
    )
