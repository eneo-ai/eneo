from typing import TYPE_CHECKING, Optional
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.orm import selectinload

from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.service_table import Services
from eneo.services.service import Service, ServiceUpdate

if TYPE_CHECKING:
    from eneo.completion_models.domain.completion_model_repo import (
        CompletionModelRepository,
    )


class ServiceRepository:
    def __init__(
        self,
        session: AsyncSession,
        completion_model_repo: "CompletionModelRepository",
    ) -> None:
        super().__init__()
        self._session = session
        self._delegate: BaseRepositoryDelegate[Service] = BaseRepositoryDelegate(
            session, Services, Service, with_options=self._get_options()
        )
        self.completion_model_repo = completion_model_repo

    @staticmethod
    def _get_options():
        return [
            selectinload(Services.user),
            selectinload(Services.groups),
            selectinload(Services.completion_model),
        ]

    # TODO: this is a hack to ensure domain completion model
    async def _set_domain_completion_model(
        self, service: Optional[Service]
    ) -> Optional[Service]:
        if service is None:
            return None

        if service.completion_model_id:
            service.completion_model = await self.completion_model_repo.one(
                service.completion_model_id
            )

        return service

    async def add(self, service: BaseModel) -> Service | None:
        s = await self._delegate.add(service)
        return await self._set_domain_completion_model(s)

    async def get_by_id(self, id: UUID) -> Service | None:
        s = await self._delegate.get(id)
        return await self._set_domain_completion_model(s)

    async def get_for_user(
        self, user_id: UUID, search_query: str | None = None
    ) -> list[Service | None]:
        stmt = (
            sa.select(Services)
            .where(Services.user_id == user_id)
            .order_by(Services.created_at)
        )

        if search_query is not None:
            stmt = stmt.filter(Services.name.like(f"%{search_query}%"))

        services = await self._delegate.get_models_from_query(stmt)

        return [
            await self._set_domain_completion_model(service) for service in services
        ]

    async def update(self, service: ServiceUpdate) -> Service | None:
        s = await self._delegate.update(service)
        return await self._set_domain_completion_model(s)

    async def delete(self, id: UUID):
        query = sa.delete(Services).where(Services.id == id)
        await self._session.execute(query)

    async def add_service_to_space(self, service_id: UUID, space_id: UUID):
        stmt = (
            sa.update(Services)
            .where(Services.id == service_id)
            .values(space_id=space_id)
            .returning(Services)
        )

        s = await self._delegate.get_model_from_query(stmt)
        return await self._set_domain_completion_model(s)
