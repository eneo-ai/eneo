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
    checksum: Mapped[str] = mapped_column(index=True)
    size: Mapped[int] = mapped_column()
    mimetype: Mapped[Optional[str]] = mapped_column()
    file_type: Mapped[str] = mapped_column(server_default=FileType.TEXT)
    transcription: Mapped[Optional[str]] = mapped_column()
    # URL returned by the external file-storage service (today
    # eneo-knowledge's temporary file-upload feature) when raw bytes
    # were pushed there at upload time. The URL is just a generic
    # hosting URL — the MCP later ingests it like any other URL.
    # NULL when storage is unconfigured or the upload failed.
    storage_url: Mapped[Optional[str]] = mapped_column(Text)

    # Foreign keys
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
