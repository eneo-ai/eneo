from typing import Any, List
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import defer, selectinload

from eneo.database.affected_rows import affected_row_count
from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.info_blob_chunk_table import InfoBlobChunks
from eneo.database.tables.info_blobs_table import (
    InfoBlobs,
    InfoBlobVersionState,
    active_info_blob_version,
)
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_table import Websites
from eneo.info_blobs.info_blob import (
    InfoBlobAdd,
    InfoBlobAddToDB,
    InfoBlobInDB,
    InfoBlobInDBNoText,
    InfoBlobUpdate,
)


class InfoBlobRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.delegate: BaseRepositoryDelegate[InfoBlobInDB] = BaseRepositoryDelegate(
            session,
            InfoBlobs,
            InfoBlobInDB,
            with_options=[
                selectinload(InfoBlobs.group),
                selectinload(InfoBlobs.group).selectinload(
                    CollectionsTable.embedding_model
                ),
                selectinload(InfoBlobs.embedding_model),
                selectinload(InfoBlobs.website),
            ],
        )
        self.session = session

    async def _get_group(self, group_id: UUID):
        stmt = sa.select(CollectionsTable).where(CollectionsTable.id == group_id)
        group = await self.session.scalar(stmt)

        return group

    async def _get_website(self, website_id: UUID):
        stmt = sa.select(Websites).where(Websites.id == website_id)
        website = await self.session.scalar(stmt)

        return website

    async def _get_integration_knowledge(self, knowledge_id: UUID):
        stmt = sa.select(IntegrationKnowledge).where(
            IntegrationKnowledge.id == knowledge_id
        )
        knowledge = await self.session.scalar(stmt)

        return knowledge

    async def add(
        self,
        info_blob: InfoBlobAdd,
        *,
        source_id: UUID | None = None,
        version_state: InfoBlobVersionState = InfoBlobVersionState.ACTIVE,
    ) -> InfoBlobInDB:
        if info_blob.group_id is not None:
            group = await self._get_group(info_blob.group_id)
            assert group is not None
            assert group.embedding_model_id is not None
            embedding_model_id = group.embedding_model_id

        elif info_blob.website_id is not None:
            website = await self._get_website(info_blob.website_id)
            assert website is not None
            embedding_model_id = website.embedding_model_id

        elif info_blob.integration_knowledge_id is not None:
            integration_knowledge = await self._get_integration_knowledge(
                knowledge_id=info_blob.integration_knowledge_id
            )
            assert integration_knowledge is not None
            embedding_model_id = integration_knowledge.embedding_model_id

        else:
            # Skydd mot none
            raise ValueError(
                "InfoBlob must reference a group, website, or integration_knowledge"
            )

        if info_blob.content_hash is None:
            raise ValueError("Published InfoBlob content requires a SHA-256 digest")

        info_blob_to_db = InfoBlobAddToDB(
            **info_blob.model_dump(),
            embedding_model_id=embedding_model_id,
            source_id=source_id or uuid4(),
            version_state=version_state.value,
        )

        record = await self.delegate.add(info_blob_to_db)
        return InfoBlobInDB.model_validate(record)

    async def lock_publication_identity(self, info_blob: InfoBlobAdd) -> None:
        identity = self._publication_identity(info_blob)
        await self.session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": identity},
        )

    @staticmethod
    def _publication_identity(info_blob: InfoBlobAdd) -> str:
        if info_blob.group_id is not None:
            return f"group:{info_blob.group_id}:title:{info_blob.title}"
        if info_blob.website_id is not None:
            return f"website:{info_blob.website_id}:title:{info_blob.title}"
        if info_blob.integration_knowledge_id is not None:
            source = info_blob.sharepoint_item_id or info_blob.title
            return f"integration:{info_blob.integration_knowledge_id}:source:{source}"
        raise ValueError("InfoBlob publication requires a source owner")

    async def get_active_for_publication(
        self, info_blob: InfoBlobAdd
    ) -> InfoBlobInDB | None:
        conditions = [active_info_blob_version()]
        if info_blob.group_id is not None:
            conditions.extend(
                [
                    InfoBlobs.group_id == info_blob.group_id,
                    InfoBlobs.title == info_blob.title,
                ]
            )
        elif info_blob.website_id is not None:
            conditions.extend(
                [
                    InfoBlobs.website_id == info_blob.website_id,
                    InfoBlobs.title == info_blob.title,
                ]
            )
        elif info_blob.integration_knowledge_id is not None:
            conditions.append(
                InfoBlobs.integration_knowledge_id == info_blob.integration_knowledge_id
            )
            if info_blob.sharepoint_item_id is not None:
                conditions.append(
                    InfoBlobs.sharepoint_item_id == info_blob.sharepoint_item_id
                )
            else:
                conditions.append(InfoBlobs.title == info_blob.title)
        else:
            raise ValueError("InfoBlob publication requires a source owner")

        record = await self.session.scalar(
            sa.select(InfoBlobs).where(*conditions).with_for_update()
        )
        return InfoBlobInDB.model_validate(record) if record is not None else None

    async def supersede(self, info_blob_id: UUID) -> bool:
        result = await self.session.execute(
            sa.update(InfoBlobs)
            .where(
                InfoBlobs.id == info_blob_id,
                active_info_blob_version(),
            )
            .values(version_state=InfoBlobVersionState.SUPERSEDED.value)
        )
        return affected_row_count(result) == 1

    async def update(self, info_blob: InfoBlobUpdate) -> InfoBlobInDB:
        record = await self.delegate.update(info_blob)
        return InfoBlobInDB.model_validate(record)

    async def update_size(self, info_blob_id: UUID) -> InfoBlobInDB | None:
        chunks_size_subquery = (
            sa.select(sa.func.coalesce(sa.func.sum(InfoBlobChunks.size), 0))
            .where(InfoBlobChunks.info_blob_id == info_blob_id)
            .scalar_subquery()
        )

        current_size_subquery = (
            sa.select(sa.func.coalesce(InfoBlobs.size, 0))
            .where(InfoBlobs.id == info_blob_id)
            .scalar_subquery()
        )

        stmt = (
            sa.update(InfoBlobs)
            .values(
                size=sa.func.coalesce(chunks_size_subquery + current_size_subquery, 0)
            )
            .where(InfoBlobs.id == info_blob_id)
            .returning(InfoBlobs)
        )

        result = await self.delegate.get_model_from_query(stmt)
        info_blob_updated = InfoBlobInDB.model_validate(result)

        return info_blob_updated

    async def get_by_user(self, user_id: UUID):
        query = (
            sa.select(InfoBlobs)
            .where(InfoBlobs.user_id == user_id, active_info_blob_version())
            .order_by(InfoBlobs.created_at)
            .options(selectinload(InfoBlobs.group))
            .options(selectinload(InfoBlobs.embedding_model))
            .options(defer(InfoBlobs.text))
        )
        items = await self.delegate.get_records_from_query(query)
        return [InfoBlobInDBNoText.model_validate(record) for record in items]

    async def get_by_user_and_space(
        self, user_id: UUID, space_ids: list[UUID]
    ) -> list[InfoBlobInDBNoText]:
        """User-scoped info blobs filtered to specific spaces (SQL-level).

        Resolves space membership via group/website/integration_knowledge joins.
        """
        if not space_ids:
            return []

        # Collect parent IDs that belong to the given spaces
        group_ids = list(
            await self.session.scalars(
                sa.select(CollectionsTable.id).where(
                    CollectionsTable.space_id.in_(space_ids)
                )
            )
        )
        website_ids = list(
            await self.session.scalars(
                sa.select(Websites.id).where(Websites.space_id.in_(space_ids))
            )
        )
        integration_ids = list(
            await self.session.scalars(
                sa.select(IntegrationKnowledge.id).where(
                    IntegrationKnowledge.space_id.in_(space_ids)
                )
            )
        )

        space_conditions: list[Any] = []
        if group_ids:
            space_conditions.append(InfoBlobs.group_id.in_(group_ids))
        if website_ids:
            space_conditions.append(InfoBlobs.website_id.in_(website_ids))
        if integration_ids:
            space_conditions.append(
                InfoBlobs.integration_knowledge_id.in_(integration_ids)
            )

        if not space_conditions:
            return []

        query = (
            sa.select(InfoBlobs)
            .where(InfoBlobs.user_id == user_id, active_info_blob_version())
            .where(sa.or_(*space_conditions))
            .order_by(InfoBlobs.created_at)
            .options(selectinload(InfoBlobs.group))
            .options(selectinload(InfoBlobs.embedding_model))
            .options(defer(InfoBlobs.text))
        )
        items = await self.delegate.get_records_from_query(query)
        return [InfoBlobInDBNoText.model_validate(record) for record in items]

    async def get(self, id: UUID) -> InfoBlobInDB:
        record = await self.delegate.get(id)
        return InfoBlobInDB.model_validate(record)

    async def get_by_title_and_group(
        self, title: str, group_id: UUID
    ) -> InfoBlobInDB | None:
        record = await self.session.scalar(
            sa.select(InfoBlobs).where(
                InfoBlobs.title == title,
                InfoBlobs.group_id == group_id,
                active_info_blob_version(),
            )
        )
        return InfoBlobInDB.model_validate(record) if record is not None else None

    async def list_by_space_ids(
        self,
        *,
        space_ids: list[UUID],
        include_groups: bool,
        include_websites: bool,
        include_integrations: bool,
        limit: int | None = None,
        order_desc: bool = True,
    ) -> list[InfoBlobInDBNoText]:
        if not space_ids:
            return []

        conditions: list[Any] = []

        if include_groups:
            group_ids = await self.session.scalars(
                sa.select(CollectionsTable.id).where(
                    CollectionsTable.space_id.in_(space_ids)
                )
            )
            group_ids_list = list(group_ids)
            if group_ids_list:
                conditions.append(InfoBlobs.group_id.in_(group_ids_list))

        if include_websites:
            website_ids = await self.session.scalars(
                sa.select(Websites.id).where(Websites.space_id.in_(space_ids))
            )
            website_ids_list = list(website_ids)
            if website_ids_list:
                conditions.append(InfoBlobs.website_id.in_(website_ids_list))

        if include_integrations:
            integration_ids = await self.session.scalars(
                sa.select(IntegrationKnowledge.id).where(
                    IntegrationKnowledge.space_id.in_(space_ids)
                )
            )
            integration_ids_list = list(integration_ids)
            if integration_ids_list:
                conditions.append(
                    InfoBlobs.integration_knowledge_id.in_(integration_ids_list)
                )

        if not conditions:
            return []

        query = (
            sa.select(InfoBlobs)
            .where(sa.or_(*conditions), active_info_blob_version())
            .options(selectinload(InfoBlobs.group))
            .options(selectinload(InfoBlobs.embedding_model))
            .options(selectinload(InfoBlobs.website))
            .options(defer(InfoBlobs.text))
        )

        if order_desc:
            query = query.order_by(InfoBlobs.created_at.desc())
        else:
            query = query.order_by(InfoBlobs.created_at.asc())

        if limit is not None:
            query = query.limit(limit)

        records = await self.delegate.get_records_from_query(query)
        return [InfoBlobInDBNoText.model_validate(record) for record in records]

    async def delete_by_sharepoint_item_and_integration_knowledge(
        self,
        sharepoint_item_id: str,
        integration_knowledge_id: UUID,
    ) -> List[InfoBlobInDB]:
        """Delete all info_blobs for a SharePoint item in one integration."""
        stmt = sa.select(InfoBlobs).where(
            sa.and_(
                InfoBlobs.sharepoint_item_id == sharepoint_item_id,
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
            )
        )
        result = await self.session.execute(stmt)
        active_blobs = [
            InfoBlobInDB.model_validate(blob)
            for blob in result.scalars().all()
            if blob.version_state == InfoBlobVersionState.ACTIVE.value
        ]
        await self.session.execute(
            sa.delete(InfoBlobs).where(
                InfoBlobs.sharepoint_item_id == sharepoint_item_id,
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
            )
        )
        return active_blobs

    async def delete_by_website(self, website_id: UUID):
        await self.delegate.delete_by(conditions={InfoBlobs.website_id: website_id})

    async def delete_by_integration_knowledge(self, integration_knowledge_id: UUID):
        """Delete all info_blobs for a specific integration_knowledge."""
        await self.delegate.delete_by(
            conditions={InfoBlobs.integration_knowledge_id: integration_knowledge_id}
        )

    async def get_by_title_and_integration_knowledge(
        self, title: str, integration_knowledge_id: UUID
    ) -> InfoBlobInDB | None:
        """Get an info_blob by title and integration_knowledge_id."""
        record = await self.session.scalar(
            sa.select(InfoBlobs).where(
                InfoBlobs.title == title,
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
                active_info_blob_version(),
            )
        )
        return InfoBlobInDB.model_validate(record) if record is not None else None

    async def get_by_sharepoint_item_and_integration_knowledge(
        self,
        sharepoint_item_id: str,
        integration_knowledge_id: UUID,
    ) -> InfoBlobInDB | None:
        """Get an info_blob by sharepoint_item_id and integration_knowledge_id."""
        record = await self.session.scalar(
            sa.select(InfoBlobs).where(
                InfoBlobs.sharepoint_item_id == sharepoint_item_id,
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
                active_info_blob_version(),
            )
        )
        return InfoBlobInDB.model_validate(record) if record is not None else None

    async def get_by_group(self, group_id: UUID) -> list[InfoBlobInDB]:
        query = (
            sa.select(InfoBlobs)
            .where(InfoBlobs.group_id == group_id, active_info_blob_version())
            .order_by(InfoBlobs.created_at)
            .options(selectinload(InfoBlobs.group))
            .options(selectinload(InfoBlobs.embedding_model))
        )
        records = await self.delegate.get_models_from_query(query)
        return [InfoBlobInDB.model_validate(record) for record in records]

    async def get_by_website(self, website_id: UUID) -> list[InfoBlobInDB]:
        records = await self.session.scalars(
            sa.select(InfoBlobs).where(
                InfoBlobs.website_id == website_id,
                active_info_blob_version(),
            )
        )
        return [InfoBlobInDB.model_validate(record) for record in records]

    async def delete(self, id: UUID) -> InfoBlobInDB:
        source_id = await self.session.scalar(
            sa.select(InfoBlobs.source_id).where(InfoBlobs.id == id)
        )
        if source_id is None:
            raise ValueError(f"InfoBlob {id} does not exist")
        active = await self.session.scalar(
            sa.select(InfoBlobs).where(
                InfoBlobs.source_id == source_id,
                active_info_blob_version(),
            )
        )
        if active is None:
            raise ValueError(f"InfoBlob source {source_id} has no active version")
        deleted = InfoBlobInDB.model_validate(active)
        await self.session.execute(
            sa.delete(InfoBlobs).where(InfoBlobs.source_id == source_id)
        )
        return deleted

    async def get_count_of_group(self, group_id: UUID):
        stmt = (
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(InfoBlobs.group_id == group_id, active_info_blob_version())
        )

        return await self.session.scalar(stmt)

    async def get_count_by_integration_knowledge(self, integration_knowledge_id: UUID):
        """Get the count of info_blobs associated with a specific integration_knowledge."""
        stmt = (
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
                active_info_blob_version(),
            )
        )

        return await self.session.scalar(stmt)

    async def get_by_filter_integration_knowledge(
        self, integration_knowledge_id: UUID
    ) -> list[InfoBlobInDB]:
        """Get all info_blobs for a specific integration_knowledge."""
        query = (
            sa.select(InfoBlobs)
            .where(
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
                active_info_blob_version(),
            )
            .options(selectinload(InfoBlobs.embedding_model))
        )
        records = await self.delegate.get_models_from_query(query)
        return [InfoBlobInDB.model_validate(record) for record in records]

    async def get_sharepoint_item_ids_for_integration_knowledge(
        self, integration_knowledge_id: UUID
    ) -> list[tuple[UUID, str]]:
        """Return (blob_id, sharepoint_item_id) for SharePoint-backed blobs.

        Lightweight (two columns, no text) — used by full-sync reconciliation to
        diff the indexed set against what still exists in SharePoint.
        """
        stmt = sa.select(InfoBlobs.id, InfoBlobs.sharepoint_item_id).where(
            sa.and_(
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
                InfoBlobs.sharepoint_item_id.is_not(None),
                active_info_blob_version(),
            )
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    def _sum_stmt(self):
        return (
            sa.select(sa.func.sum(InfoBlobs.size))
            .select_from(InfoBlobs)
            .where(active_info_blob_version())
        )

    async def get_total_size_of_group(self, group_id: UUID):
        stmt = self._sum_stmt().where(InfoBlobs.group_id == group_id)

        size = await self.session.scalar(stmt)

        if size is None:
            return 0

        return size

    async def get_total_size_of_integration_knowledge(
        self, integration_knowledge_id: UUID
    ) -> int:
        size = await self.session.scalar(
            self._sum_stmt().where(
                InfoBlobs.integration_knowledge_id == integration_knowledge_id
            )
        )
        return size or 0

    async def get_total_size_of_user(self, user_id: UUID):
        stmt = self._sum_stmt().where(InfoBlobs.user_id == user_id)

        size = await self.session.scalar(stmt)

        if size is None:
            return 0

        return size

    async def get_total_size_of_tenant(self, tenant_id: UUID):
        stmt = self._sum_stmt().join(Users).where(Users.tenant_id == tenant_id)

        size = await self.session.scalar(stmt)

        if size is None:
            return 0

        return size

    async def get_ids(self):
        stmt = sa.select(InfoBlobs.id).where(active_info_blob_version())

        ids = await self.session.scalars(stmt)

        return set(ids)

    async def get_titles_of_website(self, website_id: UUID) -> list[str]:
        stmt = sa.select(InfoBlobs.title).where(
            InfoBlobs.website_id == website_id,
            active_info_blob_version(),
        )
        result = await self.session.scalars(stmt)
        return [title for title in result if title is not None]

    async def batch_delete_by_titles_and_website(
        self, titles: list[str], website_id: UUID
    ) -> int:
        """Delete multiple info blobs by titles in a single query.

        Why: Reduces N queries to 1 query for better performance during re-crawls.
        Uses SQLAlchemy's .in_() method for efficient batch deletion.

        Args:
            titles: List of blob titles to delete
            website_id: Website UUID for tenant isolation

        Returns:
            Number of blobs deleted
        """
        if not titles:
            return 0

        active_count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(
                InfoBlobs.website_id == website_id,
                InfoBlobs.title.in_(titles),
                active_info_blob_version(),
            )
        )
        stmt = sa.delete(InfoBlobs).where(
            InfoBlobs.website_id == website_id, InfoBlobs.title.in_(titles)
        )
        await self.session.execute(stmt)
        return active_count or 0

    async def get_content_hash(self, website_id: UUID, title: str) -> bytes | None:
        """Get content hash for a specific page.

        Why: Enables content-based change detection to skip re-processing unchanged pages.
        Uses composite index (website_id, title) for efficient lookup.

        Args:
            website_id: Website UUID
            title: Page title/URL

        Returns:
            32-byte SHA-256 hash or None if page doesn't exist or hash not computed
        """
        stmt = sa.select(InfoBlobs.content_hash).where(
            InfoBlobs.website_id == website_id,
            InfoBlobs.title == title,
            active_info_blob_version(),
        )
        result = await self.session.scalar(stmt)
        return result
