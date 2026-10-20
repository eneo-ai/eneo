from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Optional, cast

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import selectinload
from typing_extensions import Unpack, override

from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.integration_table import (
    Integration as IntegrationDBModel,
)
from eneo.database.tables.integration_table import (
    IntegrationKnowledge as IntegrationKnowledgeDBModel,
)
from eneo.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDBModel,
)
from eneo.database.tables.integration_table import (
    UserIntegration as UserIntegrationDBModel,
)
from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from eneo.integration.domain.repositories.integration_knowledge_repo import (
    IntegrationKnowledgeLocation,
    IntegrationKnowledgeRepository,
    IntegrationKnowledgeSyncingError,
    SyncStateFields,
)
from eneo.integration.infrastructure.mappers.integration_knowledge_mapper import (
    IntegrationKnowledgeMapper,
)
from eneo.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl
from eneo.integration.infrastructure.repo_impl.document_counts import (
    active_document_counts,
)
from eneo.main.exceptions import NotFoundException

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.embedding_models.domain.embedding_model_repo import (
        EmbeddingModelRepository,
    )


# A sync holds its row until it commits; a rename or delete waits this long.
ROW_LOCK_TIMEOUT = "5s"
_LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"


def _lock_not_available(error: DBAPIError) -> bool:
    orig = error.orig
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return sqlstate == _LOCK_NOT_AVAILABLE_SQLSTATE


class IntegrationKnowledgeRepoImpl(
    BaseRepoImpl[
        IntegrationKnowledge, IntegrationKnowledgeDBModel, IntegrationKnowledgeMapper
    ],
    IntegrationKnowledgeRepository,
):
    def __init__(
        self,
        session: "AsyncSession",
        mapper: IntegrationKnowledgeMapper,
        embedding_model_repo: "EmbeddingModelRepository",
    ):
        super().__init__(
            session=session, model=IntegrationKnowledgeDBModel, mapper=mapper
        )
        self.embedding_model_repo = embedding_model_repo
        self._options = [
            selectinload(self._db_model.user_integration)
            .selectinload(UserIntegrationDBModel.tenant_integration)
            .selectinload(TenantIntegrationDBModel.integration),
            selectinload(self._db_model.sharepoint_subscription),
        ]

    @override
    async def one_or_none(
        self, id: Optional["UUID"] = None, **filters: object
    ) -> IntegrationKnowledge | None:
        if id is not None:
            filters = {**filters, "id": id}
        if not filters:
            raise ValueError("No filter is specified")
        query = sa.select(self._db_model).filter_by(**filters).options(*self._options)
        record = await self.session.scalar(query)

        if not record:
            return None

        embedding_model = await self.embedding_model_repo.one(
            model_id=record.embedding_model_id
        )

        return self.mapper.to_entity(db_model=record, embedding_model=embedding_model)

    @override
    async def get_by_ids(self, ids: list["UUID"]) -> list[IntegrationKnowledge]:
        query = (
            sa.select(self._db_model)
            .where(self._db_model.id.in_(ids))
            .options(*self._options)
        )
        return await self._entities_for((await self.session.scalars(query)).all())

    @override
    async def get_location(self, id: "UUID") -> IntegrationKnowledgeLocation:
        knowledge = self._db_model
        row = (
            await self.session.execute(
                sa.select(
                    knowledge.id,
                    IntegrationDBModel.integration_type,
                    knowledge.url,
                    knowledge.folder_path,
                    knowledge.resource_type,
                )
                .join(
                    UserIntegrationDBModel,
                    UserIntegrationDBModel.id == knowledge.user_integration_id,
                )
                .join(
                    TenantIntegrationDBModel,
                    TenantIntegrationDBModel.id
                    == UserIntegrationDBModel.tenant_integration_id,
                )
                .join(
                    IntegrationDBModel,
                    IntegrationDBModel.id == TenantIntegrationDBModel.integration_id,
                )
                .where(knowledge.id == id)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException(f"{knowledge.__name__} not found")
        knowledge_id, integration_type, url, folder_path, resource_type = row
        return IntegrationKnowledgeLocation(
            id=knowledge_id,
            integration_type=integration_type,
            url=url,
            folder_path=folder_path,
            resource_type=resource_type,
        )

    async def _entities_for(
        self, records: Sequence[IntegrationKnowledgeDBModel]
    ) -> list[IntegrationKnowledge]:
        if not records:
            return []
        # Knowledge keeps its embedding model after the model is deprecated.
        embedding_models = await self.embedding_model_repo.all(with_deprecated=True)
        return self.mapper.to_entities(records, embedding_models=embedding_models)

    @override
    async def attach_document_counts(
        self, items: Sequence[IntegrationKnowledge]
    ) -> None:
        # document_count is a projection over info_blobs, not a column. Fetches
        # leave it at zero so sync and webhook paths never pay for it; callers
        # that serve an item to the UI attach it here.
        counts = await active_document_counts(self.session, [item.id for item in items])
        for item in items:
            item.document_count = counts.get(item.id, 0)

    @override
    async def remove(self, id: "UUID") -> None:
        async with self._bounded_wait_for_a_sync():
            await self.delete(id=id)

    @override
    async def rename(self, id: "UUID", name: str) -> None:
        async with self._bounded_wait_for_a_sync():
            await self._update_columns([id], name=name)

    @override
    async def rename_wrapper(self, ids: Sequence["UUID"], wrapper_name: str) -> None:
        async with self._bounded_wait_for_a_sync():
            await self._update_columns(ids, wrapper_name=wrapper_name)

    @asynccontextmanager
    async def _bounded_wait_for_a_sync(self) -> AsyncGenerator[None, None]:
        """Wait at most ``ROW_LOCK_TIMEOUT`` for a row a sync holds.

        On a timeout the transaction is aborted, so the setting is restored
        only after a write that went through.
        """
        previous = await self.session.scalar(sa.text("SHOW lock_timeout"))
        await self._set_lock_timeout(ROW_LOCK_TIMEOUT)
        try:
            yield
        except DBAPIError as exc:
            if _lock_not_available(exc):
                raise IntegrationKnowledgeSyncingError() from exc
            raise
        await self._set_lock_timeout(str(previous))

    async def _set_lock_timeout(self, value: str) -> None:
        await self.session.execute(
            sa.text("SELECT set_config('lock_timeout', :value, true)"),
            {"value": value},
        )

    @override
    async def link_subscription(self, id: "UUID", subscription_id: "UUID") -> bool:
        # A sync holds its row until it commits, which can be hours; a request
        # (an import's or resync's link) must not wait for it.
        free = (
            sa.select(self._db_model.id)
            .where(self._db_model.id == id)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(
            sa.update(self._db_model)
            .where(self._db_model.id.in_(free))
            .values(sharepoint_subscription_id=subscription_id)
        )
        return affected_row_count(result) > 0

    async def _update_columns(self, ids: Sequence["UUID"], **values: object) -> None:
        if not ids:
            return
        result = await self.session.execute(
            sa.update(self._db_model)
            .where(self._db_model.id.in_(list(ids)))
            .values(**values)
        )
        if affected_row_count(result) != len(set(ids)):
            raise NotFoundException(f"{self._db_model.__name__} not found")

    @override
    async def update_sync_state(
        self, id: "UUID", **fields: Unpack[SyncStateFields]
    ) -> None:
        if not fields:
            return
        stmt = (
            sa.update(self._db_model)
            .where(self._db_model.id == id)
            .values(**cast(dict[str, object], fields))
        )
        result = await self.session.execute(stmt)
        if affected_row_count(result) == 0:
            raise NotFoundException(f"{self._db_model.__name__} not found")

    @override
    async def get_sync_failed_items(self, id: "UUID") -> dict[str, Any] | None:
        return await self.session.scalar(
            sa.select(self._db_model.sync_failed_items).where(self._db_model.id == id)
        )

    @override
    async def adjust_size(self, id: "UUID", delta: int) -> int:
        stmt = (
            sa.update(self._db_model)
            .where(self._db_model.id == id)
            .values(
                size=sa.func.greatest(
                    0, sa.func.coalesce(self._db_model.size, 0) + delta
                )
            )
            .returning(self._db_model.size)
        )
        new_size = await self.session.scalar(stmt)
        if new_size is None:
            raise NotFoundException(f"{self._db_model.__name__} not found")
        return int(new_size)
