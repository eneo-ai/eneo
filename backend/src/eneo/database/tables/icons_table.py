from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic


class Icons(BasePublic):
    """Table for storing icon images used by assistants, apps, and spaces."""

    # Foreign key for multi-tenancy
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE")
    )
