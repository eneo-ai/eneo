from dataclasses import dataclass
from typing import Any, List
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import defer, selectinload
from sqlalchemy.sql.elements import ColumnElement

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
from eneo.database.tables.object_content_table import (
    InfoBlobContentReferences,
    ObjectContents,
)
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_table import Websites
from eneo.info_blobs.info_blob import (
    InfoBlobAdd,
    InfoBlobAddToDB,
    InfoBlobInDB,
    InfoBlobInDBNoText,
    InfoBlobUpdate,
)
from eneo.main.exceptions import InfoBlobPublicationConflictError
from eneo.object_content.content import ContentState


@dataclass(frozen=True, slots=True)
class InfoBlobOriginal:
    sha256: bytes
    state: ContentState

    @property
    def usable(self) -> bool:
        return self.state is ContentState.AVAILABLE


@dataclass(frozen=True, slots=True)
class InfoBlobPublication:
    info_blob: InfoBlobInDB
    original: InfoBlobOriginal | None


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

    async def lock_publication_identity(
        self,
        info_blob: InfoBlobAdd,
        *,
        original_sha256: bytes | None = None,
    ) -> None:
        identities = {
            identity
            for identity in (
                self._publication_identity(info_blob),
                self._original_identity(info_blob, original_sha256),
            )
            if identity is not None
        }
        for identity in sorted(identities):
            await self.session.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                {"identity": identity},
            )

    @staticmethod
    def _publication_identity(info_blob: InfoBlobAdd) -> str | None:
        title = info_blob.title if info_blob.title and info_blob.title.strip() else None
        if info_blob.group_id is not None:
            return f"group:{info_blob.group_id}:title:{title}" if title else None
        if info_blob.website_id is not None:
            return f"website:{info_blob.website_id}:title:{title}" if title else None
        if info_blob.integration_knowledge_id is not None:
            item_id = (
                info_blob.sharepoint_item_id
                if info_blob.sharepoint_item_id and info_blob.sharepoint_item_id.strip()
                else None
            )
            source = item_id or title
            return (
                f"integration:{info_blob.integration_knowledge_id}:source:{source}"
                if source
                else None
            )
        raise ValueError("InfoBlob publication requires a source owner")

    @staticmethod
    def _original_identity(
        info_blob: InfoBlobAdd,
        original_sha256: bytes | None,
    ) -> str | None:
        if info_blob.group_id is None or original_sha256 is None:
            return None
        return f"group:{info_blob.group_id}:original:{original_sha256.hex()}"

    @staticmethod
    def _active_group_upload_identity(
        *,
        group_id: UUID,
        title: str | None,
        original_sha256: bytes | None,
    ) -> ColumnElement[bool]:
        title_identity = sa.and_(
            InfoBlobs.group_id == group_id,
            InfoBlobs.title == title,
        )
        if original_sha256 is None:
            return title_identity
        return sa.or_(
            title_identity,
            sa.and_(
                InfoBlobs.group_id == group_id,
                ObjectContents.sha256 == original_sha256,
            ),
        )

    async def get_active_for_publication(
        self,
        info_blob: InfoBlobAdd,
        *,
        original_sha256: bytes | None = None,
    ) -> InfoBlobPublication | None:
        if self._publication_identity(info_blob) is None:
            return None

        if info_blob.group_id is not None:
            candidate_identity = self._active_group_upload_identity(
                group_id=info_blob.group_id,
                title=info_blob.title,
                original_sha256=original_sha256,
            )
        else:
            source_conditions: list[ColumnElement[bool]] = []
            if info_blob.website_id is not None:
                source_conditions.extend(
                    [
                        InfoBlobs.website_id == info_blob.website_id,
                        InfoBlobs.title == info_blob.title,
                    ]
                )
            elif info_blob.integration_knowledge_id is not None:
                source_conditions.append(
                    InfoBlobs.integration_knowledge_id
                    == info_blob.integration_knowledge_id
                )
                if (
                    info_blob.sharepoint_item_id is not None
                    and info_blob.sharepoint_item_id.strip()
                ):
                    source_conditions.append(
                        InfoBlobs.sharepoint_item_id == info_blob.sharepoint_item_id
                    )
                else:
                    source_conditions.append(InfoBlobs.title == info_blob.title)
            else:
                raise ValueError("InfoBlob publication requires a source owner")
            candidate_identity = sa.and_(*source_conditions)
        query = sa.select(InfoBlobs)
        if info_blob.group_id is not None and original_sha256 is not None:
            query = query.outerjoin(
                InfoBlobContentReferences,
                InfoBlobContentReferences.info_blob_id == InfoBlobs.id,
            ).outerjoin(
                ObjectContents,
                ObjectContents.id == InfoBlobContentReferences.content_id,
            )

        records = list(
            await self.delegate.get_records_from_query(
                query.where(
                    active_info_blob_version(),
                    candidate_identity,
                )
                .order_by(InfoBlobs.id)
                .limit(2)
                .with_for_update(of=InfoBlobs)
            )
        )
        if len(records) > 1:
            raise InfoBlobPublicationConflictError(
                "Knowledge publication identity is ambiguous"
            )

        record = records[0] if records else None
        if record is None:
            return None
        published = InfoBlobInDB.model_validate(record)
        return InfoBlobPublication(
            info_blob=published,
            original=await self.get_original(published.id),
        )

    async def has_matching_active_upload_original(
        self,
        *,
        group_id: UUID,
        title: str,
        embedding_model_id: UUID,
        original_sha256: bytes,
    ) -> bool:
        rows = (
            await self.session.execute(
                sa.select(
                    InfoBlobs.embedding_model_id,
                    ObjectContents.sha256,
                )
                .select_from(InfoBlobs)
                .outerjoin(
                    InfoBlobContentReferences,
                    InfoBlobContentReferences.info_blob_id == InfoBlobs.id,
                )
                .outerjoin(
                    ObjectContents,
                    ObjectContents.id == InfoBlobContentReferences.content_id,
                )
                .where(
                    active_info_blob_version(),
                    self._active_group_upload_identity(
                        group_id=group_id,
                        title=title,
                        original_sha256=original_sha256,
                    ),
                )
                .order_by(InfoBlobs.id)
                .limit(2)
            )
        ).all()
        if len(rows) > 1:
            raise InfoBlobPublicationConflictError(
                "Knowledge publication identity is ambiguous"
            )
        if not rows:
            return False
        row = rows[0]
        return (
            row.embedding_model_id == embedding_model_id
            and row.sha256 == original_sha256
        )

    async def get_original(self, info_blob_id: UUID) -> InfoBlobOriginal | None:
        row = (
            await self.session.execute(
                sa.select(
                    ObjectContents.sha256,
                    ObjectContents.state,
                )
                .select_from(InfoBlobContentReferences)
                .join(
                    ObjectContents,
                    ObjectContents.id == InfoBlobContentReferences.content_id,
                )
                .where(InfoBlobContentReferences.info_blob_id == info_blob_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return InfoBlobOriginal(
            sha256=row.sha256,
            state=ContentState(row.state),
        )

    async def add_original_reference(
        self,
        *,
        info_blob_id: UUID,
        content_id: UUID,
        original_filename: str,
    ) -> None:
        await self.session.execute(
            sa.insert(InfoBlobContentReferences).values(
                info_blob_id=info_blob_id,
                content_id=content_id,
                original_filename=original_filename,
            )
        )

    async def replace_original_reference(
        self,
        *,
        info_blob_id: UUID,
        content_id: UUID,
        original_filename: str,
    ) -> None:
        deleted = await self.session.execute(
            sa.delete(InfoBlobContentReferences).where(
                InfoBlobContentReferences.info_blob_id == info_blob_id
            )
        )
        if affected_row_count(deleted) != 1:
            raise RuntimeError("Knowledge original reference changed during repair")
        await self.add_original_reference(
            info_blob_id=info_blob_id,
            content_id=content_id,
            original_filename=original_filename,
        )

    async def refresh_original_filename(
        self,
        *,
        info_blob_id: UUID,
        original_filename: str,
    ) -> None:
        updated = await self.session.execute(
            sa.update(InfoBlobContentReferences)
            .where(InfoBlobContentReferences.info_blob_id == info_blob_id)
            .values(original_filename=original_filename)
        )
        if affected_row_count(updated) != 1:
            raise RuntimeError("Knowledge original reference changed during refresh")

    async def refresh_publication_metadata(
        self,
        info_blob_id: UUID,
        info_blob: InfoBlobAdd,
    ) -> InfoBlobInDB:
        updated_id = await self.session.scalar(
            sa.update(InfoBlobs)
            .where(InfoBlobs.id == info_blob_id, active_info_blob_version())
            .values(title=info_blob.title, url=info_blob.url)
            .returning(InfoBlobs.id)
        )
        if updated_id is None:
            raise RuntimeError("The active knowledge version changed during publish")
        refreshed = await self.delegate.get(updated_id)
        if refreshed is None:
            raise RuntimeError("The refreshed knowledge version no longer exists")
        return refreshed

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

        text_size_subquery = (
            sa.select(sa.func.coalesce(sa.func.octet_length(InfoBlobs.text), 0))
            .where(InfoBlobs.id == info_blob_id)
            .scalar_subquery()
        )
        original_size_subquery = (
            sa.select(sa.func.coalesce(ObjectContents.size_bytes, 0))
            .select_from(InfoBlobContentReferences)
            .join(
                ObjectContents,
                ObjectContents.id == InfoBlobContentReferences.content_id,
            )
            .where(InfoBlobContentReferences.info_blob_id == info_blob_id)
            .scalar_subquery()
        )

        stmt = (
            sa.update(InfoBlobs)
            .values(
                size=sa.func.coalesce(
                    chunks_size_subquery
                    + text_size_subquery
                    + sa.func.coalesce(original_size_subquery, 0),
                    0,
                )
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
                active_info_blob_version(),
            )
        )
        result = await self.session.execute(stmt)
        active_blobs = [
            InfoBlobInDB.model_validate(blob) for blob in result.scalars().all()
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
        active = await self.delegate.get_record_from_query(
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

    def _retained_sum_stmt(self):
        return sa.select(sa.func.sum(InfoBlobs.size)).select_from(InfoBlobs)

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

    async def get_retained_size_of_user(self, user_id: UUID) -> int:
        size = await self.session.scalar(
            self._retained_sum_stmt().where(InfoBlobs.user_id == user_id)
        )
        return size or 0

    async def get_total_size_of_tenant(self, tenant_id: UUID):
        stmt = self._sum_stmt().join(Users).where(Users.tenant_id == tenant_id)

        size = await self.session.scalar(stmt)

        if size is None:
            return 0

        return size

    async def get_retained_size_of_tenant(self, tenant_id: UUID) -> int:
        size = await self.session.scalar(
            self._retained_sum_stmt().join(Users).where(Users.tenant_id == tenant_id)
        )
        return size or 0

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
