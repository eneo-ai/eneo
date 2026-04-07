from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.repositories.base import BaseRepository
from intric.database.tables.service_table import Services
from intric.database.tables.workflow_tables import Filters, Steps, Workflows
from intric.workflows.workflow import WorkflowBase, WorkflowInDB


class WorkflowRepository(BaseRepository):
    async def add(self, workflow: WorkflowBase, user_id: UUID):
        stmt = (
            sa.insert(Workflows)
            .values(name=workflow.name, user_id=user_id)
            .options(
                selectinload(Workflows.steps)
                .options(selectinload(Steps.filter))
                .options(selectinload(Steps.service).selectinload(Services.groups))
                .options(
                    selectinload(Steps.service).selectinload(Services.completion_model)
                )
            )
            .returning(Workflows)
        )

        workflow_in_db = await self.session.scalar(stmt)
        assert workflow_in_db is not None

        step_records = []
        for i, step in enumerate(workflow.steps):
            step_stmt = (
                sa.insert(Steps)
                .values(
                    order=i,
                    workflow_id=workflow_in_db.id,
                    service_id=step.service_id,
                )
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
                    sa.insert(Filters)
                    .values(**step.filter.model_dump())
                    .returning(Filters)
                )
                filter_in_db = await self.session.scalar(filter_stmt)
                assert filter_in_db is not None

                step_stmt = step_stmt.values(filter_id=filter_in_db.id)

            step_record = await self.session.scalar(step_stmt)
            step_records.append(step_record)

        workflow_in_db.steps = step_records

        return WorkflowInDB.model_validate(workflow_in_db)

    async def get(self, id: UUID):
        stmt = (
            sa.select(Workflows)
            .where(Workflows.id == id)
            .options(
                selectinload(Workflows.steps)
                .options(selectinload(Steps.filter))
                .options(selectinload(Steps.service).selectinload(Services.groups))
                .options(
                    selectinload(Steps.service).selectinload(Services.completion_model)
                )
                .options(selectinload(Steps.service).selectinload(Services.user))
            )
        )

        record = await self.session.scalar(stmt)

        if record is None:
            return

        return WorkflowInDB.model_validate(record)

    async def delete(self, id: UUID):
        stmt = (
            sa.delete(Workflows)
            .where(Workflows.id == id)
            .returning(Workflows)
            .options(
                selectinload(Workflows.steps)
                .options(selectinload(Steps.filter))
                .options(selectinload(Steps.service).selectinload(Services.groups))
                .options(
                    selectinload(Steps.service).selectinload(Services.completion_model)
                )
                .options(selectinload(Steps.service).selectinload(Services.user))
            )
        )

        record = await self.session.scalar(stmt)

        if record is None:
            return

        return WorkflowInDB.model_validate(record)
