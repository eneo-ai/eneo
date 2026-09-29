from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.files.file_models import FileType


class Files(BasePublic):
    name: Mapped[str] = mapped_column()
    mimetype: Mapped[Optional[str]] = mapped_column()
    file_type: Mapped[str] = mapped_column(server_default=FileType.TEXT)

    # Foreign keys
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))

    # Set for files derived from another upload (e.g. images extracted from a
    # PDF attachment); derived files are deleted with their parent.
    parent_file_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), index=True
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
