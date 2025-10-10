from typing import Any, Optional

from sqlalchemy import BigInteger, Column, ForeignKey, String, Table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import Base, BasePublic
from intric.database.tables.module_table import Modules
from intric.tenants.tenant import TenantState


class Tenants(BasePublic):
    name: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[Optional[str]] = mapped_column()
    slug: Mapped[Optional[str]] = mapped_column(String(63), unique=True, index=True)
    quota_limit: Mapped[int] = mapped_column(BigInteger)
    privacy_policy: Mapped[Optional[str]] = mapped_column()
    domain: Mapped[Optional[str]] = mapped_column()
    zitadel_org_id: Mapped[Optional[str]] = mapped_column(index=True)
    provisioning: Mapped[bool] = mapped_column(default=False)
    security_enabled: Mapped[bool] = mapped_column(default=False)
    state: Mapped[str] = mapped_column(String, default=TenantState.ACTIVE.value)
    api_credentials: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    federation_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # relationships
    modules: Mapped[list[Modules]] = relationship(secondary="tenants_modules")


tenants_modules_table = Table(
    "tenants_modules",
    Base.metadata,
    Column("tenant_id", ForeignKey(Tenants.id, ondelete="CASCADE"), primary_key=True),
    Column("module_id", ForeignKey(Modules.id, ondelete="CASCADE"), primary_key=True),
)
