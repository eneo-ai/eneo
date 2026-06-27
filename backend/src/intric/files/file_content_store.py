"""Storage seam for file binary content (S3 readiness).

Today every file's bytes live inline in the ``files.blob`` BYTEA column. This
module introduces a thin abstraction so the binary payload (images, audio,
AI-generated images, PDF/Office-derived images) can later live in object
storage (S3/MinIO) WITHOUT changing the call sites. The extracted ``text``
column stays in the database unconditionally — it is small and queried.

The default backend is ``db`` (:class:`DbBlobContentStore`), which reads and
writes the existing BYTEA column, so behaviour is byte-for-byte identical until
an operator switches ``file_content_storage_backend``.

Dual-read contract (see :meth:`FileService.read_blob`): if a row's inline
``blob`` is present, use it; otherwise resolve via the named backend +
``storage_key``. Rows written before this seam have ``storage_backend = NULL``
and keep working.

S3 enablement (a later change) must, besides adding an ``S3ContentStore`` and a
backfill job, route the remaining blob consumers through the seam — they read
``file.blob`` directly today and would see ``None`` once bytes move out of the
DB:
  - completion_models/infrastructure/message_payload.py (build_image_block)
  - completion_models/infrastructure/context_builder.py (image token counting)
  - files/transcriber.py (audio bytes)
  - files/file_router.py (signed download)
Those are sync builders or independent services, so they need an async hydrate
pass at the assembly boundary before the bytes are read.
"""

from typing import Optional, Protocol
from uuid import UUID

import sqlalchemy as sa

from intric.database.database import AsyncSession
from intric.database.tables.files_table import Files

DB_BACKEND = "db"


class FileContentStore(Protocol):
    """Content-addressed blob store. Auth lives in FileService, never here."""

    backend_name: str

    def make_key(self, *, tenant_id: UUID, file_id: UUID) -> str: ...

    async def write(self, *, key: str, data: bytes) -> None: ...

    async def read(
        self, *, key: str, backend: Optional[str] = None
    ) -> Optional[bytes]: ...

    async def delete(self, *, key: str, backend: Optional[str] = None) -> None: ...


class DbBlobContentStore:
    """Default impl: bytes live in the ``files.blob`` BYTEA column.

    ``make_key`` returns the canonical tenant-scoped key; read/write operate on
    the row identified by the file_id embedded in the key. ``delete`` is a no-op
    because deleting the row already removes the bytes.
    """

    backend_name = DB_BACKEND

    def __init__(self, session: AsyncSession):
        self.session = session

    def make_key(self, *, tenant_id: UUID, file_id: UUID) -> str:
        return f"{tenant_id}/{file_id}"

    async def write(self, *, key: str, data: bytes) -> None:
        file_id = key.split("/")[-1]
        await self.session.execute(
            sa.update(Files).where(Files.id == file_id).values(blob=data)
        )

    async def read(self, *, key: str, backend: Optional[str] = None) -> Optional[bytes]:
        file_id = key.split("/")[-1]
        return await self.session.scalar(
            sa.select(Files.blob).where(Files.id == file_id)
        )

    async def delete(self, *, key: str, backend: Optional[str] = None) -> None:
        return None
