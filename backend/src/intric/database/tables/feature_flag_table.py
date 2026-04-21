from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BaseCrossReference, BasePublic
from intric.database.tables.tenant_table import Tenants


class GlobalFeatureFlag(BasePublic):
    __tablename__ = "global_feature_flags"  # type: ignore[assignment]

    name: Mapped[str] = mapped_column(nullable=False, unique=True)
    description: Mapped[str] = mapped_column(nullable=True)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)


class TenantFeatureFlag(BaseCrossReference):
    __tablename__ = "tenant_feature_flags"  # type: ignore[assignment]

    name: Mapped[str] = mapped_column(nullable=False)
    feature_id: Mapped[UUID] = mapped_column(
        ForeignKey(GlobalFeatureFlag.id),
        nullable=False,
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id), nullable=False, primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)

    tenant: Mapped[Tenants] = relationship()
    feature: Mapped[GlobalFeatureFlag] = relationship()
