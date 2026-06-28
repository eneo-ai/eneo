# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from eneo.database.database import AsyncSession
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.websites_table import Websites
from eneo.storage.domain.storage_factory import (
    StorageInfoFactory,
    StorageInfoQueryResult,
)
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.storage.domain.storage import StorageInfo


class StorageInfoRepository:
    def __init__(
        self, user: UserInDB, session: AsyncSession, factory: StorageInfoFactory
    ) -> None:
        super().__init__()
        self.user = user
        self.session = session
        self.factory = factory

    async def _get_spaces(self):
        tenant_id = self.user.tenant_id
        # Aliases for subqueries
        group_size_subquery = (
            sa.select(
                CollectionsTable.space_id,
                sa.func.sum(CollectionsTable.size).label("total_groups_size"),
            )
            .group_by(CollectionsTable.space_id)
            .alias("group_size_subquery")
        )

        website_size_subquery = (
            sa.select(
                Websites.space_id,
                sa.func.sum(Websites.size).label("total_website_size"),
            )
            .group_by(Websites.space_id)
            .alias("website_size_subquery")
        )

        integration_knowledge_size_subquery = (
            sa.select(
                IntegrationKnowledge.space_id,
                sa.func.sum(IntegrationKnowledge.size).label(
                    "total_integration_knowledge_size"
                ),
            )
            .group_by(IntegrationKnowledge.space_id)
            .alias("integration_knowledge_size_subquery")
        )

        # Main query
        query = (
            sa.select(
                Spaces,
                sa.func.coalesce(group_size_subquery.c.total_groups_size, 0).label(
                    "total_groups_size"
                ),
                sa.func.coalesce(website_size_subquery.c.total_website_size, 0).label(
                    "total_website_size"
                ),
                sa.func.coalesce(
                    integration_knowledge_size_subquery.c.total_integration_knowledge_size,
                    0,
                ).label("total_integration_knowledge_size"),
                Tenants.quota_limit,
            )
            .outerjoin(group_size_subquery, Spaces.id == group_size_subquery.c.space_id)
            .outerjoin(
                website_size_subquery, Spaces.id == website_size_subquery.c.space_id
            )
            .outerjoin(
                integration_knowledge_size_subquery,
                Spaces.id == integration_knowledge_size_subquery.c.space_id,
            )
            .join(Tenants, Spaces.tenant_id == Tenants.id)
            .where(Spaces.tenant_id == tenant_id)
            .options(selectinload(Spaces.members).selectinload(SpacesUsers.user))
        )

        return await self.session.execute(query)

    async def get_storage_info(self) -> "StorageInfo":
        results = await self._get_spaces()
        result = results.mappings().all()

        storage_info_list = [
            StorageInfoQueryResult(
                spaces=row["Spaces"],
                group_size=row["total_groups_size"],
                website_size=row["total_website_size"],
                integration_knowledge_size=row["total_integration_knowledge_size"],
                total_size=row["total_groups_size"]
                + row["total_website_size"]
                + row["total_integration_knowledge_size"],
                quota_limit=row["quota_limit"],
            )
            for row in result
        ]

        storage_info = self.factory.create_storage_info_from_db(
            query_result=storage_info_list
        )
        return storage_info
