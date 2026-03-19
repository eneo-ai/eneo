from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.repositories.base import BaseRepository
from intric.database.tables.service_table import Services
from intric.database.tables.workflow_tables import Filters, Steps
from intric.workflows.workflow import FilterInDB, Step, StepInDB


class StepRepository(BaseRepository):
    async def add(self, step: Step):
        step_stmt = (
            sa.insert(Steps)
            .values(service_id=step.service_id)
            .returning(Steps)
            .options(selectinload(Steps.filter))
            .options(selectinload(Steps.service).selectinload(Services.groups))
            .options(
                selectinload(Steps.service).selectinload(Services.completion_model)
            )
            .options(selectinload(Steps.service).selectinload(Services.user))
        )

        if step.filter is not None:
            filter_stmt = (
                sa.insert(Filters).values(**step.filter.model_dump()).returning(Filters)
            )
            filter_in_db = await self.session.scalar(filter_stmt)
            assert filter_in_db is not None

            step_stmt = step_stmt.values(filter_id=filter_in_db.id)

        step_record = await self.session.scalar(step_stmt)

        return StepInDB.model_validate(step_record)

    async def update_chain_breaker_message(
        self, filter_id: UUID, chain_breaker_message: str = None
    ):
        stmt = (
            sa.update(Filters)
            .values(chain_breaker_message=chain_breaker_message)
            .where(Filters.id == filter_id)
            .returning(Filters)
        )

        filter_in_db = await self.session.scalar(stmt)

        return FilterInDB.model_validate(filter_in_db)

    async def get(self, step_id: UUID):
        stmt = (
            sa.select(Steps)
            .where(Steps.id == step_id)
            .options(selectinload(Steps.filter))
            .options(selectinload(Steps.service).selectinload(Services.groups))
            .options(
                selectinload(Steps.service).selectinload(Services.completion_model)
            )
            .options(selectinload(Steps.service).selectinload(Services.user))
        )

        step_record = await self.session.scalar(stmt)

        return StepInDB.model_validate(step_record)
