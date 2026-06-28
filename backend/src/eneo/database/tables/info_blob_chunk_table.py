from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.tenant_table import Tenants


class InfoBlobChunks(BasePublic):
    text: Mapped[str] = mapped_column()
    chunk_no: Mapped[int] = mapped_column()
    size: Mapped[int] = mapped_column()
    embedding: Mapped[list[float]] = mapped_column(Vector())

    # Foreign keys
    info_blob_id: Mapped[UUID] = mapped_column(
        ForeignKey(InfoBlobs.id, ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), index=True
    )
