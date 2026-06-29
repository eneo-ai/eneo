from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic
from intric.database.tables.tenant_table import Tenants

if TYPE_CHECKING:
    pass


class TenantMetadataFields(BasePublic):
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name", name="uq_tenant_metadata_fields_tenant_name"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    field_type: Mapped[str] = mapped_column(String(32))
    visible_on_assistants: Mapped[bool] = mapped_column(Boolean, default=True)
    visible_on_spaces: Mapped[bool] = mapped_column(Boolean, default=True)

    tenant: Mapped[Tenants] = relationship()
