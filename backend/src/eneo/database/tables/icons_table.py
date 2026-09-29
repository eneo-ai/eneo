from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic


class Icons(BasePublic):
    """Table for storing icon images used by assistants, apps, and spaces."""

    # Foreign key for multi-tenancy
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE")
    )

    # Temporary Release A fallback, loaded explicitly by IconRepository.
    legacy_blob: Mapped[bytes | None] = mapped_column(
        "blob",
        BYTEA,
        deferred=True,
        deferred_raiseload=True,
    )
    legacy_mimetype: Mapped[str | None] = mapped_column(
        "mimetype",
        String(100),
        deferred=True,
        deferred_raiseload=True,
    )
    legacy_size: Mapped[int | None] = mapped_column(
        "size",
        Integer,
        deferred=True,
        deferred_raiseload=True,
    )
