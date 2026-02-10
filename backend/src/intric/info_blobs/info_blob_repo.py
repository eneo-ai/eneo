from typing import List
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import defer, selectinload

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.info_blob_chunk_table import InfoBlobChunks
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.database.tables.integration_table import IntegrationKnowledge
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import Websites
from intric.info_blobs.info_blob import (
    InfoBlobAdd,
    InfoBlobAddToDB,
    InfoBlobInDB,
    InfoBlobInDBNoText,
    InfoBlobUpdate,
)


class InfoBlobRepository:
    def __init__(self, session: AsyncSession):
        self.delegate = BaseRepositoryDelegate(
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

    async def add(self, info_blob: InfoBlobAdd):
        if info_blob.group_id is not None:
            group = await self._get_group(info_blob.group_id)
            embedding_model_id = group.embedding_model_id

        elif info_blob.website_id is not None:
            website = await self._get_website(info_blob.website_id)
            embedding_model_id = website.embedding_model_id

        elif info_blob.integration_knowledge_id is not None:
            integration_knowledge = await self._get_integration_knowledge(
                knowledge_id=info_blob.integration_knowledge_id
            )
            embedding_model_id = integration_knowledge.embedding_model_id

        else:
            # Skydd mot none
            raise ValueError("InfoBlob must reference a group, website, or integration_knowledge")
        
        info_blob_to_db = InfoBlobAddToDB(
            **info_blob.model_dump(),
            embedding_model_id=embedding_model_id,
        )

        return await self.delegate.add(info_blob_to_db)

    async def upsert_by_title_and_integration_knowledge(
        self, info_blob: InfoBlobAdd
    ) -> InfoBlobInDB:
        """Idempotent upsert for integration_knowledge blobs.

        If a blob with the same title already exists, update it.
        Otherwise, create a new one.

        This handles duplicate webhooks from Microsoft by ensuring
        we never create duplicates - just update existing ones.
        """
        if not info_blob.integration_knowledge_id or not info_blob.title:
            raise ValueError("title and integration_knowledge_id are required for upsert")

        # Check if blob already exists
        existing = await self.get_by_title_and_integration_knowledge(
            title=info_blob.title,
            integration_knowledge_id=info_blob.integration_knowledge_id,
        )

        if existing:
            # Update existing blob - update both text and metadata
            stmt = (
                sa.update(InfoBlobs)
                .where(InfoBlobs.id == existing.id)
                .values(
                    text=info_blob.text,
                    title=info_blob.title,
                    url=info_blob.url,
                    size=info_blob.size,  # Update size as well
                    updated_at=sa.func.now(),
                )
                .returning(InfoBlobs)
            )
            result = await self.session.execute(stmt)
            updated_blob = result.scalar_one()
            return InfoBlobInDB.model_validate(updated_blob)
        else:
            # Create new blob
            return await self.add(info_blob)

    async def upsert_by_sharepoint_item_and_integration_knowledge(
        self,
        info_blob: InfoBlobAdd,
    ) -> InfoBlobInDB:
        """Idempotent upsert keyed by sharepoint_item_id + integration_knowledge_id."""
        if not info_blob.integration_knowledge_id or not info_blob.sharepoint_item_id:
            raise ValueError(
                "sharepoint_item_id and integration_knowledge_id are required for SharePoint upsert"
            )

        stmt = sa.select(InfoBlobs).where(
            sa.and_(
                InfoBlobs.sharepoint_item_id == info_blob.sharepoint_item_id,
                InfoBlobs.integration_knowledge_id == info_blob.integration_knowledge_id,
            )
        )
        result = await self.session.execute(stmt)
        existing = result.scalars().all()

        if existing:
            primary = existing[0]

            # Cleanup any historical duplicates for the same SharePoint item.
            for duplicate in existing[1:]:
                await self.delegate.delete(duplicate.id)

            update_stmt = (
                sa.update(InfoBlobs)
                .where(InfoBlobs.id == primary.id)
                .values(
                    text=info_blob.text,
                    title=info_blob.title,
                    url=info_blob.url,
                    size=info_blob.size,
                    sharepoint_item_id=info_blob.sharepoint_item_id,
                    updated_at=sa.func.now(),
                )
                .returning(InfoBlobs)
            )
            update_result = await self.session.execute(update_stmt)
            updated_blob = update_result.scalar_one()
            return InfoBlobInDB.model_validate(updated_blob)

        return await self.add(info_blob)

    async def update(self, info_blob: InfoBlobUpdate) -> InfoBlobInDB:
        return await self.delegate.update(info_blob)

    async def update_size(self, info_blob_id: UUID) -> InfoBlobInDB:
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
            .where(InfoBlobs.user_id == user_id)
            .order_by(InfoBlobs.created_at)
            .options(selectinload(InfoBlobs.group))
            .options(selectinload(InfoBlobs.embedding_model))
            .options(defer(InfoBlobs.text))
        )
        items = await self.delegate.get_records_from_query(query)
        return [InfoBlobInDBNoText.model_validate(record) for record in items]

    async def get(self, id: UUID) -> InfoBlobInDB:
        return await self.delegate.get(id)

    async def get_by_title_and_group(self, title: str, group_id: UUID):
        return await self.delegate.get_by(
            conditions={InfoBlobs.title: title, InfoBlobs.group_id: group_id}
        )

    async def delete_by_title_and_group(
        self, title: str, group_id: UUID
    ) -> InfoBlobInDB:
        return await self.delegate.delete_by(
            conditions={InfoBlobs.title: title, InfoBlobs.group_id: group_id}
        )

    async def delete_by_title_and_website(
        self, title: str, website_id: UUID
    ) -> InfoBlobInDB:
        return await self.delegate.delete_by(
            conditions={InfoBlobs.title: title, InfoBlobs.website_id: website_id}
        )

    async def delete_by_title_and_integration_knowledge(
        self, title: str, integration_knowledge_id: UUID
    ) -> List[InfoBlobInDB]:
        """Delete ALL info_blobs with given title and integration_knowledge_id.

        Returns list of deleted blobs (can be multiple if duplicates exist).
        """
        # First, get all matching blobs
        stmt = sa.select(InfoBlobs).where(
            sa.and_(
                InfoBlobs.title == title,
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
            )
        )
        result = await self.session.execute(stmt)
        blobs_to_delete = result.scalars().all()

        # Delete each one
        deleted = []
        for blob in blobs_to_delete:
            deleted_blob = await self.delegate.delete(blob.id)
            deleted.append(deleted_blob)

        return deleted

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
        blobs_to_delete = result.scalars().all()

        deleted = []
        for blob in blobs_to_delete:
            deleted_blob = await self.delegate.delete(blob.id)
            deleted.append(deleted_blob)

        return deleted

    async def delete_by_website(self, website_id: UUID):
        await self.delegate.delete_by(conditions={InfoBlobs.website_id: website_id})

    async def delete_by_integration_knowledge(self, integration_knowledge_id: UUID):
        """Delete all info_blobs for a specific integration_knowledge."""
        await self.delegate.delete_by(
            conditions={InfoBlobs.integration_knowledge_id: integration_knowledge_id}
        )

    async def get_by_title_and_integration_knowledge(
        self, title: str, integration_knowledge_id: UUID
    ) -> InfoBlobInDB:
        """Get an info_blob by title and integration_knowledge_id."""
        return await self.delegate.get_by(
            conditions={
                InfoBlobs.title: title,
                InfoBlobs.integration_knowledge_id: integration_knowledge_id,
            }
        )

    async def get_by_sharepoint_item_and_integration_knowledge(
        self,
        sharepoint_item_id: str,
        integration_knowledge_id: UUID,
    ) -> InfoBlobInDB:
        """Get an info_blob by sharepoint_item_id and integration_knowledge_id."""
        return await self.delegate.get_by(
            conditions={
                InfoBlobs.sharepoint_item_id: sharepoint_item_id,
                InfoBlobs.integration_knowledge_id: integration_knowledge_id,
            }
        )

    async def get_by_group(self, group_id: UUID) -> list[InfoBlobInDB]:
        query = (
            sa.select(InfoBlobs)
            .where(InfoBlobs.group_id == group_id)
            .order_by(InfoBlobs.created_at)
            .options(selectinload(InfoBlobs.group))
            .options(selectinload(InfoBlobs.embedding_model))
        )
        return await self.delegate.get_models_from_query(query)

    async def get_by_website(self, website_id: UUID) -> list[InfoBlobInDB]:
        return await self.delegate.filter_by(
            conditions={InfoBlobs.website_id: website_id}
        )

    async def delete(self, id: int) -> InfoBlobInDB:
        return await self.delegate.delete(id)

    async def get_count_of_group(self, group_id: UUID):
        stmt = (
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(InfoBlobs.group_id == group_id)
        )

        return await self.session.scalar(stmt)

    async def get_count_by_integration_knowledge(self, integration_knowledge_id: UUID):
        """Get the count of info_blobs associated with a specific integration_knowledge."""
        stmt = (
            sa.select(sa.func.count()).select_from(InfoBlobs).where(InfoBlobs.integration_knowledge_id == integration_knowledge_id)
        )

        return await self.session.scalar(stmt)

    async def get_by_filter_integration_knowledge(self, integration_knowledge_id: UUID) -> list[InfoBlobInDB]:
        """Get all info_blobs for a specific integration_knowledge."""
        query = (
            sa.select(InfoBlobs)
            .where(InfoBlobs.integration_knowledge_id == integration_knowledge_id)
            .options(selectinload(InfoBlobs.embedding_model))
        )
        return await self.delegate.get_models_from_query(query)

    def _sum_stmt(self):
        return sa.select(sa.func.sum(InfoBlobs.size)).select_from(InfoBlobs)

    async def get_total_size_of_group(self, group_id: UUID):
        stmt = self._sum_stmt().where(InfoBlobs.group_id == group_id)

        size = await self.session.scalar(stmt)

        if size is None:
            return 0

        return size

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
        stmt = sa.select(InfoBlobs.id)

        ids = await self.session.scalars(stmt)

        return set(ids)

    async def get_titles_of_website(self, website_id: UUID) -> list[str]:
        stmt = sa.select(InfoBlobs.title).where(InfoBlobs.website_id == website_id)
        result = await self.session.scalars(stmt)
        return list(result)

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

        # Use SQLAlchemy's .in_() method for array-based deletion
        # This is more efficient than N individual DELETE queries
        stmt = sa.delete(InfoBlobs).where(
            InfoBlobs.website_id == website_id, InfoBlobs.title.in_(titles)
        )

        result = await self.session.execute(stmt)
        return result.rowcount

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
            InfoBlobs.website_id == website_id, InfoBlobs.title == title
        )
        result = await self.session.scalar(stmt)
        return result
