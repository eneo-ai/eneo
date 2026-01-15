from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.base_class import BasePublic


class Icons(BasePublic):
    """Table for storing icon images used by assistants, apps, and spaces."""

    blob: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    mimetype: Mapped[str] = mapped_column(nullable=False)
    size: Mapped[int] = mapped_column(nullable=False)

    # Foreign key for multi-tenancy
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE")
    )
