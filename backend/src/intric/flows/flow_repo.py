from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.flow_tables import (
    FlowStepResults,
    FlowSteps,
    Flows,
)
from intric.flows.flow import Flow, FlowSparse, FlowStep, FlowStepResult
from intric.flows.flow_factory import FlowFactory
from intric.main.exceptions import BadRequestException, NotFoundException


class FlowRepository:
    """Tenant-scoped repository for flow aggregate operations."""

    def __init__(self, session: AsyncSession, factory: FlowFactory):
        self.session = session
        self.factory = factory

    async def _get_flow_steps(self, flow_id: UUID, tenant_id: UUID) -> list[FlowSteps]:
        stmt = (
            sa.select(FlowSteps)
            .where(FlowSteps.flow_id == flow_id)
            .where(FlowSteps.tenant_id == tenant_id)
            .order_by(FlowSteps.step_order.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    def _step_to_db_row(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
        step: FlowStep,
    ) -> dict[str, Any]:
        return {
            "flow_id": flow_id,
            "tenant_id": tenant_id,
            "assistant_id": step.assistant_id,
            "step_order": step.step_order,
            "user_description": step.user_description,
            "input_source": step.input_source,
            "input_type": step.input_type,
            "input_contract": step.input_contract,
            "output_mode": step.output_mode,
            "output_type": step.output_type,
            "output_contract": step.output_contract,
            "input_bindings": step.input_bindings,
            "output_classification_override": step.output_classification_override,
            "mcp_policy": step.mcp_policy,
            "input_config": step.input_config,
            "output_config": step.output_config,
        }

    async def create(self, flow: Flow, tenant_id: UUID) -> Flow:
        insert_stmt = (
            sa.insert(Flows)
            .values(
                name=flow.name,
                description=flow.description,
                tenant_id=tenant_id,
                space_id=flow.space_id,
                created_by_user_id=flow.created_by_user_id,
                owner_user_id=flow.owner_user_id,
                published_version=flow.published_version,
                metadata_json=flow.metadata_json,
                data_retention_days=flow.data_retention_days,
            )
            .returning(Flows)
        )
        flow_in_db = await self.session.scalar(insert_stmt)
        if flow_in_db is None:
            raise NotFoundException("Could not create flow.")
        flow_id = cast(UUID, flow_in_db.id)

        if flow.steps:
            rows = [
                self._step_to_db_row(
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    step=step,
                )
                for step in flow.steps
            ]
            await self.session.execute(sa.insert(FlowSteps).values(rows))

        return await self.get(flow_id, tenant_id)

    async def get(self, flow_id: UUID, tenant_id: UUID) -> Flow:
        stmt = (
            sa.select(Flows)
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
        )
        flow_in_db = await self.session.scalar(stmt)
        if flow_in_db is None:
            raise NotFoundException("Flow not found.")
        steps = await self._get_flow_steps(flow_id=flow_id, tenant_id=tenant_id)
        return self.factory.from_flow_db(flow_in_db=flow_in_db, steps=steps)

    async def get_by_space(
        self,
        space_id: UUID,
        tenant_id: UUID,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Flow]:
        stmt = (
            sa.select(Flows)
            .where(Flows.space_id == space_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
            .order_by(Flows.created_at.asc())
        )
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        flow_rows = (await self.session.execute(stmt)).scalars().all()
        if not flow_rows:
            return []

        flow_ids = [cast(UUID, row.id) for row in flow_rows]
        steps_rows = (
            await self.session.execute(
                sa.select(FlowSteps)
                .where(FlowSteps.flow_id.in_(flow_ids))
                .where(FlowSteps.tenant_id == tenant_id)
                .order_by(FlowSteps.flow_id.asc(), FlowSteps.step_order.asc())
            )
        ).scalars().all()
        steps_by_flow: dict[UUID, list[FlowSteps]] = defaultdict(list)
        for row in steps_rows:
            steps_by_flow[row.flow_id].append(row)

        return [
            self.factory.from_flow_db(
                flow_row,
                steps_by_flow.get(cast(UUID, flow_row.id), []),
            )
            for flow_row in flow_rows
        ]

    async def get_sparse_by_space(
        self,
        space_id: UUID,
        tenant_id: UUID,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowSparse]:
        stmt = (
            sa.select(Flows)
            .where(Flows.space_id == space_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
            .order_by(Flows.created_at.asc())
        )
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        flow_rows = (await self.session.execute(stmt)).scalars().all()
        return [self.factory.from_flow_sparse_db(row) for row in flow_rows]

    async def update(self, flow: Flow, tenant_id: UUID) -> Flow:
        if flow.id is None:
            raise BadRequestException("Flow id is required for update.")

        stmt = (
            sa.update(Flows)
            .where(Flows.id == flow.id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
            .values(
                name=flow.name,
                description=flow.description,
                owner_user_id=flow.owner_user_id,
                published_version=flow.published_version,
                metadata_json=flow.metadata_json,
                data_retention_days=flow.data_retention_days,
            )
            .returning(Flows)
        )
        flow_in_db = await self.session.scalar(stmt)
        if flow_in_db is None:
            raise NotFoundException("Flow not found.")

        await self._sync_flow_steps(flow_id=flow.id, tenant_id=tenant_id, steps=flow.steps)

        return await self.get(flow.id, tenant_id)

    async def delete(self, flow_id: UUID, tenant_id: UUID) -> None:
        stmt = (
            sa.update(Flows)
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
            .values(deleted_at=datetime.now(timezone.utc))
        )
        result = await self.session.execute(stmt)
        if getattr(result, "rowcount", 0) == 0:
            raise NotFoundException("Flow not found.")

        await self.session.execute(
            sa.delete(FlowSteps)
            .where(FlowSteps.flow_id == flow_id)
            .where(FlowSteps.tenant_id == tenant_id)
        )
        await self.session.execute(
            sa.delete(Assistants)
            .where(Assistants.origin == "flow_managed")
            .where(Assistants.managing_flow_id == flow_id)
        )

    async def get_step_result(
        self,
        flow_run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
    ) -> FlowStepResult | None:
        stmt = (
            sa.select(FlowStepResults)
            .where(FlowStepResults.flow_run_id == flow_run_id)
            .where(FlowStepResults.step_id == step_id)
            .where(FlowStepResults.tenant_id == tenant_id)
        )
        result = await self.session.scalar(stmt)
        if result is None:
            return None
        return self.factory.from_flow_step_result_db(result)

    async def get_step_result_by_order(
        self,
        flow_run_id: UUID,
        step_order: int,
        tenant_id: UUID,
    ) -> FlowStepResult | None:
        """Legacy ARQ-only method. New flow runtime should use step_id lookups."""
        stmt = (
            sa.select(FlowStepResults)
            .where(FlowStepResults.flow_run_id == flow_run_id)
            .where(FlowStepResults.step_order == step_order)
            .where(FlowStepResults.tenant_id == tenant_id)
        )
        result = await self.session.scalar(stmt)
        if result is None:
            return None
        return self.factory.from_flow_step_result_db(result)

    async def save_step_result(
        self,
        flow_run_id: UUID,
        result: FlowStepResult,
        tenant_id: UUID,
        session: AsyncSession | None = None,
    ) -> None:
        db_session = session or self.session

        payload: dict[str, Any] = {
            "flow_run_id": flow_run_id,
            "flow_id": result.flow_id,
            "tenant_id": tenant_id,
            "step_id": result.step_id,
            "step_order": result.step_order,
            "assistant_id": result.assistant_id,
            "input_payload_json": result.input_payload_json,
            "effective_prompt": result.effective_prompt,
            "output_payload_json": result.output_payload_json,
            "model_parameters_json": result.model_parameters_json,
            "num_tokens_input": result.num_tokens_input,
            "num_tokens_output": result.num_tokens_output,
            "status": result.status.value,
            "error_message": result.error_message,
            "flow_step_execution_hash": result.flow_step_execution_hash,
            "tool_calls_metadata": result.tool_calls_metadata,
        }

        if result.step_id is None:
            if result.id is None:
                await db_session.execute(sa.insert(FlowStepResults).values(payload))
                return
            update_result = await db_session.execute(
                sa.update(FlowStepResults)
                .where(FlowStepResults.id == result.id)
                .where(FlowStepResults.tenant_id == tenant_id)
                .values(**payload)
            )
            if getattr(update_result, "rowcount", 0) == 0:
                raise NotFoundException("Flow step result not found for legacy update.")
            return

        stmt = (
            pg_insert(FlowStepResults)
            .values(payload)
            .on_conflict_do_update(
                constraint="uq_flow_step_results_run_step",
                set_=payload,
            )
        )
        await db_session.execute(stmt)

    async def _sync_flow_steps(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
        steps: list[FlowStep],
    ) -> None:
        existing_rows = (
            await self.session.execute(
                sa.select(FlowSteps)
                .where(FlowSteps.flow_id == flow_id)
                .where(FlowSteps.tenant_id == tenant_id)
            )
        ).scalars().all()
        existing_by_order = {int(row.step_order): row for row in existing_rows}

        incoming_orders = {int(step.step_order) for step in steps}
        cleanup_candidates: set[UUID] = set()
        for step in steps:
            payload = self._step_to_db_row(flow_id=flow_id, tenant_id=tenant_id, step=step)
            existing = existing_by_order.get(int(step.step_order))
            if existing is None:
                await self.session.execute(sa.insert(FlowSteps).values(payload))
                continue
            if existing.assistant_id != step.assistant_id:
                cleanup_candidates.add(existing.assistant_id)
            await self.session.execute(
                sa.update(FlowSteps)
                .where(FlowSteps.id == existing.id)
                .where(FlowSteps.tenant_id == tenant_id)
                .values(**payload)
            )

        stale_orders = [order for order in existing_by_order if order not in incoming_orders]
        if stale_orders:
            cleanup_candidates.update(
                existing_by_order[order].assistant_id for order in stale_orders
            )
            await self.session.execute(
                sa.delete(FlowSteps)
                .where(FlowSteps.flow_id == flow_id)
                .where(FlowSteps.tenant_id == tenant_id)
                .where(FlowSteps.step_order.in_(stale_orders))
            )
        await self._delete_orphan_flow_managed_assistants(
            flow_id=flow_id,
            tenant_id=tenant_id,
            assistant_ids=cleanup_candidates,
        )

    async def _delete_orphan_flow_managed_assistants(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
        assistant_ids: set[UUID],
    ) -> None:
        if not assistant_ids:
            return

        await self.session.execute(
            sa.delete(Assistants)
            .where(Assistants.id.in_(assistant_ids))
            .where(Assistants.origin == "flow_managed")
            .where(Assistants.managing_flow_id == flow_id)
            .where(
                ~sa.exists(
                    sa.select(1)
                    .select_from(FlowSteps)
                    .where(FlowSteps.assistant_id == Assistants.id)
                    .where(FlowSteps.tenant_id == tenant_id)
                )
            )
        )
