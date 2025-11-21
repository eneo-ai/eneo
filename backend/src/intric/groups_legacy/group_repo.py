from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.assistant_table import AssistantsGroups
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.database.tables.service_table import ServicesGroups
from intric.database.tables.users_table import Users
from intric.groups_legacy.api.group_models import Group, GroupCreate, GroupUpdate
from intric.database.tables.groups_spaces_table import GroupsSpaces
from sqlalchemy.dialects.postgresql import insert as pg_insert

class GroupRepository:
    def __init__(self, session: AsyncSession):
        self.delegate = BaseRepositoryDelegate(
            session,
            CollectionsTable,
            Group,
            with_options=[
                selectinload(CollectionsTable.user).selectinload(Users.roles),
                selectinload(CollectionsTable.user).selectinload(Users.predefined_roles),
                selectinload(CollectionsTable.embedding_model),
            ],
        )
        self.session = session

    async def get_all_groups(self):
        return await self.delegate.get_all()

    async def get_groups_by_user(self, user_id: UUID) -> list[Group]:
        query = (
            sa.select(CollectionsTable)
            .where(CollectionsTable.user_id == user_id)
            .order_by(CollectionsTable.created_at)
        )

        return await self.delegate.get_models_from_query(query)

    async def get_group(self, id: UUID) -> Group:
        return await self.delegate.get(id)

    async def get_groups_by_ids(self, ids: list[UUID]) -> list[Group]:
        return await self.delegate.get_by_ids(ids)

    async def create_group(self, group: GroupCreate) -> Group:
        return await self.delegate.add(group)

    async def update_group(self, group: GroupUpdate) -> Group:
        return await self.delegate.update(group)

    async def update_group_size(self, group_id: UUID) -> Group:
        info_blobs_size_subquery = (
            sa.select(sa.func.coalesce(sa.func.sum(InfoBlobs.size), 0))
            .where(InfoBlobs.group_id == group_id)
            .scalar_subquery()
        )

        stmt = (
            sa.update(CollectionsTable)
            .where(CollectionsTable.id == group_id)
            .values(size=info_blobs_size_subquery)
            .returning(CollectionsTable)
        )

        return await self.session.scalar(stmt)

    async def delete_group_by_id(self, group_id: UUID) -> int:
        result = await self.session.execute(
            sa.delete(CollectionsTable).where(CollectionsTable.id == group_id)
        )
        return result.rowcount

    async def move_group_owner(self, group_id: UUID, new_owner_space_id: UUID) -> Group:
        query = (
            sa.update(CollectionsTable)
            .where(CollectionsTable.id == group_id)
            .values(space_id=new_owner_space_id)
            .returning(CollectionsTable)
        )
        return await self.delegate.get_model_from_query(query)

    async def remove_group_from_all_assistants(self, group_id: UUID, assistant_ids: list[UUID]):
        stmt = (
            sa.delete(AssistantsGroups)
            .where(AssistantsGroups.group_id == group_id)
            .where(
                AssistantsGroups.assistant_id.not_in(assistant_ids),
            )
        )

        await self.session.execute(stmt)

    async def remove_group_from_all_services(self, group_id: UUID, service_ids: list[UUID]):
        stmt = (
            sa.delete(ServicesGroups)
            .where(ServicesGroups.group_id == group_id)
            .where(
                ServicesGroups.service_id.not_in(service_ids),
            )
        )

        await self.session.execute(stmt)

    async def get_groups_by_space(self, space_id: UUID) -> list[Group]:
        query = (
            sa.select(CollectionsTable)
            .join(GroupsSpaces, GroupsSpaces.collection_id == CollectionsTable.id)
            .where(GroupsSpaces.space_id == space_id)
            .distinct(CollectionsTable.id)
            .order_by(CollectionsTable.created_at)
        )
        return await self.delegate.get_models_from_query(query)
    
    async def link_group_to_space(self, group_id: UUID, space_id: UUID) -> None:
        stmt = (
            pg_insert(GroupsSpaces)
            .values(collection_id=group_id, space_id=space_id)
            .on_conflict_do_nothing(
                index_elements=[GroupsSpaces.collection_id, GroupsSpaces.space_id]
            )
        )
        await self.session.execute(stmt)

    async def unlink_group_from_space(self, group_id: UUID, space_id: UUID) -> None:
        stmt = sa.delete(GroupsSpaces).where(
            GroupsSpaces.collection_id == group_id,
            GroupsSpaces.space_id == space_id,
        )
        await self.session.execute(stmt)

    async def get_spaces_for_group(self, group_id: UUID):
        query = sa.select(GroupsSpaces.space_id).where(GroupsSpaces.collection_id == group_id)
        result = await self.session.execute(query)
        return [row[0] for row in result.all()]
    
    async def unlink_group_from_all_spaces(self, group_id: UUID) -> None:
        stmt = sa.delete(GroupsSpaces).where(GroupsSpaces.collection_id == group_id)
        await self.session.execute(stmt)