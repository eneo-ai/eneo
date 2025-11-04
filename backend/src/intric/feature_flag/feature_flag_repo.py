from uuid import UUID

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from intric.database.tables.feature_flag_table import (
    GlobalFeatureFlag,
    TenantFeatureFlag,
)
from intric.feature_flag.feature_flag_factory import FeatureFlagFactory
from intric.feature_flag.feature_flag import FeatureFlag
from intric.main.exceptions import NotFoundException


class FeatureFlagRepository:
    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def _delete_tenant(self, tenant_id: UUID) -> None:
        stmt = delete(TenantFeatureFlag).where(TenantFeatureFlag.tenant_id == tenant_id)
        await self.db_session.execute(stmt)

    async def _insert_tenant(self, obj: FeatureFlag, tenant_id: UUID) -> None:
        stmt = insert(TenantFeatureFlag).values(
            feature_id=obj.feature_id,
            tenant_id=tenant_id,
            enabled=True,
            name=obj.name,
        )
        await self.db_session.execute(stmt)

    async def add(self, obj: FeatureFlag) -> FeatureFlag:
        stmt = (
            insert(GlobalFeatureFlag)
            .values(name=obj.name, description=obj.description)
            .returning(GlobalFeatureFlag)
        )
        feature = await self.db_session.execute(stmt)
        return feature.scalar_one()

    async def update(self, obj: FeatureFlag) -> FeatureFlag:
        # Enable or disable tenant
        feature_flag = await self.one(id=obj.feature_id)

        existing_tenants = feature_flag.tenant_ids
        incoming_tenants = obj.tenant_ids

        disabled_tenants = existing_tenants - incoming_tenants
        for tenant_id in disabled_tenants:
            await self._delete_tenant(tenant_id=tenant_id)

        enabled_tenants = incoming_tenants - existing_tenants
        for tenant_id in enabled_tenants:
            await self._insert_tenant(obj=obj, tenant_id=tenant_id)

        return obj

    async def delete(self, id: UUID) -> None:
        pass

    async def one_or_none(
        self, id: UUID | None = None, **filters
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

    async def one(self, id: UUID | None = None, **filters) -> FeatureFlag:
        feature_flag = await self.one_or_none(id=id, **filters)
        if not feature_flag:
            raise NotFoundException("FeatureFlag not found")
        return feature_flag

    async def _query_tenants(self, **filters) -> list[TenantFeatureFlag]:
        if not filters:
            return []

        query = select(TenantFeatureFlag).filter_by(**filters)
        result = await self.db_session.scalars(query)
        return result.all()
