from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.base_class import BasePublic
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.files.file_models import FileType


class Files(BasePublic):
    name: Mapped[str] = mapped_column()
    text: Mapped[Optional[str]] = mapped_column(Text)
    blob: Mapped[Optional[bytes]] = mapped_column(BYTEA)
    # Storage seam (S3 readiness): when storage_backend is NULL the bytes live
    # inline in `blob` (current behaviour); otherwise they live in the named
    # backend under `storage_key`. See files/file_content_store.py.
    storage_backend: Mapped[Optional[str]] = mapped_column(nullable=True)
    storage_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checksum: Mapped[str] = mapped_column(index=True)
    size: Mapped[int] = mapped_column()
    mimetype: Mapped[Optional[str]] = mapped_column()
    file_type: Mapped[str] = mapped_column(server_default=FileType.TEXT)
    transcription: Mapped[Optional[str]] = mapped_column()

    # Foreign keys
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))

    # Set for files derived from another upload (e.g. images extracted from a
    # PDF attachment); derived files are deleted with their parent.
    parent_file_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
