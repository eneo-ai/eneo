from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, insert, literal
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from eneo.database.tables.feature_flag_table import (
    GlobalFeatureFlag,
    TenantFeatureFlag,
)
from eneo.feature_flag.feature_flag import FeatureFlag
from eneo.feature_flag.feature_flag_factory import FeatureFlagFactory
from eneo.main.exceptions import NotFoundException


class FeatureFlagRepository:
    def __init__(self, db_session: AsyncSession) -> None:
        super().__init__()
        self.db_session = db_session

    async def add(self, obj: FeatureFlag) -> FeatureFlag:
        stmt = (
            insert(GlobalFeatureFlag)
            .values(name=obj.name, description=obj.description)
            .returning(GlobalFeatureFlag)
        )
        feature = await self.db_session.execute(stmt)
        return feature.scalar_one()  # type: ignore[return-value]

    async def set_tenant(
        self, feature_id: UUID, tenant_id: UUID, enabled: bool
    ) -> None:
        """Set one tenant's preference for a feature flag.

        One upsert of that tenant's own row, so other tenants' rows are neither
        read nor written: tenants switching the same flag at once cannot
        overwrite, remove or wait on each other's choice.
        """
        stmt = (
            pg_insert(TenantFeatureFlag)
            .from_select(
                ["feature_id", "tenant_id", "enabled", "name"],
                select(
                    GlobalFeatureFlag.id,
                    literal(tenant_id),
                    literal(enabled),
                    GlobalFeatureFlag.name,
                ).where(GlobalFeatureFlag.id == feature_id),
            )
            .on_conflict_do_update(
                index_elements=["feature_id", "tenant_id"],
                set_={"enabled": enabled, "updated_at": datetime.now(timezone.utc)},
            )
            .returning(TenantFeatureFlag.tenant_id)
        )
        if (await self.db_session.execute(stmt)).scalar_one_or_none() is None:
            raise NotFoundException("FeatureFlag not found")

    async def delete(self, id: UUID) -> None:
        pass

    async def one_or_none(
        self, id: UUID | None = None, **filters: object
    ) -> FeatureFlag | None:
        if not filters:
            if id is None:
                raise ValueError("No filter is specfied")
            filters = {"id": id}

        query = select(GlobalFeatureFlag).filter_by(**filters)
        global_feature_flag = await self.db_session.scalar(query)

        if not global_feature_flag:
            return

        tenant_feature_flags = await self._query_tenants(
            feature_id=global_feature_flag.id
        )

        feature_flag = FeatureFlagFactory.create_domain_feature_flag(
            global_feature_flag=global_feature_flag,
            tenant_feature_flags=tenant_feature_flags,
        )

        return feature_flag

    async def is_enabled_for_tenant(
        self, name: str, tenant_id: UUID | None
    ) -> bool | None:
        """Whether the named flag is on for ``tenant_id``; None if no such flag.

        One statement reads the global row and that tenant's preference, so a
        check costs the same however many tenants have preferences. It returns
        the effective value, not a partial aggregate.
        """
        query = (
            select(GlobalFeatureFlag, TenantFeatureFlag)
            .outerjoin(
                TenantFeatureFlag,
                and_(
                    TenantFeatureFlag.feature_id == GlobalFeatureFlag.id,
                    TenantFeatureFlag.tenant_id == tenant_id,
                ),
            )
            .where(GlobalFeatureFlag.name == name)
        )
        row = (await self.db_session.execute(query)).one_or_none()
        if row is None:
            return None
        global_feature_flag, tenant_feature_flag = row
        return FeatureFlagFactory.create_domain_feature_flag(
            global_feature_flag=global_feature_flag,
            tenant_feature_flags=[tenant_feature_flag] if tenant_feature_flag else [],
        ).is_enabled(tenant_id=tenant_id)

    async def one(self, id: UUID | None = None, **filters: object) -> FeatureFlag:
        feature_flag = await self.one_or_none(id=id, **filters)
        if not feature_flag:
            raise NotFoundException("FeatureFlag not found")
        return feature_flag

    async def _query_tenants(self, **filters: object) -> list[TenantFeatureFlag]:
        if not filters:
            return []

        query = select(TenantFeatureFlag).filter_by(**filters)
        result = await self.db_session.scalars(query)
        return result.all()  # type: ignore[return-value]
