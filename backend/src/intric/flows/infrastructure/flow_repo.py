from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.assistant_table import (
    AssistantMCPServers,
    AssistantMCPServerTools,
    Assistants,
    AssistantsGroups,
)
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.flow_tables import (
    FlowRuns,
    FlowRunStepResultFiles,
    Flows,
    FlowStepResults,
    FlowSteps,
)
from intric.database.tables.mcp_server_table import MCPServers, MCPServerTools
from intric.database.tables.prompts_table import Prompts, PromptsAssistants
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.users_table import Users
from intric.flows.domain.flow import Flow, FlowSparse, FlowStep, FlowStepResult
from intric.flows.enums import FlowStepResultStatus
from intric.flows.flow_factory import FlowFactory
from intric.flows.flow_review_policy import FlowStepReviewPolicy
from intric.flows.flow_run_step_result_file import FlowStepResultFileReference
from intric.main.exceptions import BadRequestException, NotFoundException


@dataclass(frozen=True)
class AssistantScopeRow:
    id: UUID
    origin: str | None
    managing_flow_id: UUID | None


def _review_policy_to_json(
    review_policy: FlowStepReviewPolicy | None,
) -> dict[str, Any] | None:
    if review_policy is None:
        return None
    return review_policy.model_dump(mode="json")


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
            "review_policy": _review_policy_to_json(step.review_policy),
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
        flow_id = flow_in_db.id

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
        published_only: bool = False,
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
        if published_only:
            stmt = stmt.where(Flows.published_version.is_not(None))
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        flow_rows = (await self.session.execute(stmt)).scalars().all()
        if not flow_rows:
            return []

        flow_ids = [row.id for row in flow_rows]
        steps_rows = (
            (
                await self.session.execute(
                    sa.select(FlowSteps)
                    .where(FlowSteps.flow_id.in_(flow_ids))
                    .where(FlowSteps.tenant_id == tenant_id)
                    .order_by(FlowSteps.flow_id.asc(), FlowSteps.step_order.asc())
                )
            )
            .scalars()
            .all()
        )
        steps_by_flow: dict[UUID, list[FlowSteps]] = defaultdict(list)
        for row in steps_rows:
            steps_by_flow[row.flow_id].append(row)

        return [
            self.factory.from_flow_db(
                flow_row,
                steps_by_flow.get(flow_row.id, []),
            )
            for flow_row in flow_rows
        ]

    async def get_sparse_by_space(
        self,
        space_id: UUID,
        tenant_id: UUID,
        *,
        published_only: bool = False,
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
        if published_only:
            stmt = stmt.where(Flows.published_version.is_not(None))
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        flow_rows = (await self.session.execute(stmt)).scalars().all()
        return [self.factory.from_flow_sparse_db(row) for row in flow_rows]

    async def get_assistant_snapshots(
        self,
        *,
        assistant_ids: list[UUID],
        tenant_id: UUID,
    ) -> dict[UUID, dict[str, Any]]:
        if not assistant_ids:
            return {}

        assistant_rows = (
            await self.session.execute(
                sa.select(
                    Assistants.id,
                    Assistants.completion_model_id,
                    CompletionModels.name.label("model_name"),
                    Prompts.text.label("instructions"),
                )
                .join(Users, Users.id == Assistants.user_id)
                .outerjoin(
                    CompletionModels,
                    CompletionModels.id == Assistants.completion_model_id,
                )
                .outerjoin(
                    PromptsAssistants,
                    sa.and_(
                        PromptsAssistants.assistant_id == Assistants.id,
                        PromptsAssistants.is_selected.is_(True),
                    ),
                )
                .outerjoin(Prompts, Prompts.id == PromptsAssistants.prompt_id)
                .where(Assistants.id.in_(assistant_ids))
                .where(Users.tenant_id == tenant_id)
            )
        ).all()

        snapshots: dict[UUID, dict[str, Any]] = {
            row.id: {
                "instructions": getattr(row, "instructions", None),
                "model_ref": str(row.completion_model_id)
                if row.completion_model_id
                else None,
                "model_label": getattr(row, "model_name", None),
                "knowledge_refs": [],
                "knowledge_labels": [],
                "mcp_server_refs": [],
                "mcp_server_labels": [],
                "mcp_tool_refs": [],
                "mcp_tool_labels": [],
            }
            for row in assistant_rows
        }

        collection_rows = (
            await self.session.execute(
                sa.select(
                    AssistantsGroups.assistant_id,
                    CollectionsTable.id,
                    CollectionsTable.name,
                )
                .join(
                    CollectionsTable,
                    CollectionsTable.id == AssistantsGroups.group_id,
                )
                .where(AssistantsGroups.assistant_id.in_(assistant_ids))
                .where(CollectionsTable.tenant_id == tenant_id)
                .order_by(
                    AssistantsGroups.assistant_id.asc(),
                    CollectionsTable.created_at.asc(),
                )
            )
        ).all()
        for row in collection_rows:
            if row.assistant_id not in snapshots:
                continue
            snapshots[row.assistant_id]["knowledge_refs"].append(str(row.id))
            snapshots[row.assistant_id]["knowledge_labels"].append(row.name)

        mcp_server_rows = (
            await self.session.execute(
                sa.select(
                    AssistantMCPServers.assistant_id,
                    MCPServers.id,
                    MCPServers.name,
                )
                .join(MCPServers, MCPServers.id == AssistantMCPServers.mcp_server_id)
                .where(AssistantMCPServers.assistant_id.in_(assistant_ids))
                .where(MCPServers.tenant_id == tenant_id)
                .order_by(
                    AssistantMCPServers.assistant_id.asc(),
                    MCPServers.created_at.asc(),
                )
            )
        ).all()
        for row in mcp_server_rows:
            if row.assistant_id not in snapshots:
                continue
            snapshots[row.assistant_id].setdefault("mcp_server_refs", []).append(
                str(row.id)
            )
            snapshots[row.assistant_id].setdefault("mcp_server_labels", []).append(
                row.name
            )

        mcp_tool_rows = (
            await self.session.execute(
                sa.select(
                    AssistantMCPServerTools.assistant_id,
                    MCPServerTools.id,
                    MCPServerTools.name,
                )
                .join(
                    MCPServerTools,
                    MCPServerTools.id == AssistantMCPServerTools.mcp_server_tool_id,
                )
                .join(MCPServers, MCPServers.id == MCPServerTools.mcp_server_id)
                .where(AssistantMCPServerTools.assistant_id.in_(assistant_ids))
                .where(AssistantMCPServerTools.is_enabled.is_(True))
                .where(MCPServers.tenant_id == tenant_id)
                .order_by(
                    AssistantMCPServerTools.assistant_id.asc(),
                    MCPServerTools.name.asc(),
                )
            )
        ).all()
        for row in mcp_tool_rows:
            if row.assistant_id not in snapshots:
                continue
            snapshots[row.assistant_id].setdefault("mcp_tool_refs", []).append(
                str(row.id)
            )
            snapshots[row.assistant_id].setdefault("mcp_tool_labels", []).append(
                row.name
            )

        return {
            assistant_id: snapshots[assistant_id]
            for assistant_id in assistant_ids
            if assistant_id in snapshots
        }

    async def get_assistant_scope_rows(
        self,
        *,
        assistant_ids: set[UUID],
        space_id: UUID,
        tenant_id: UUID,
    ) -> list[AssistantScopeRow]:
        if not assistant_ids:
            return []

        rows = (
            await self.session.execute(
                sa.select(
                    Assistants.id,
                    getattr(Assistants, "origin"),
                    getattr(Assistants, "managing_flow_id"),
                )
                .join(Spaces, Spaces.id == Assistants.space_id)
                .where(Assistants.id.in_(assistant_ids))
                .where(Assistants.space_id == space_id)
                .where(Spaces.tenant_id == tenant_id)
            )
        ).all()
        return [
            AssistantScopeRow(
                id=row.id,
                origin=row.origin,
                managing_flow_id=row.managing_flow_id,
            )
            for row in rows
        ]

    async def is_active(self, *, flow_id: UUID, tenant_id: UUID) -> bool:
        flow_id_in_db = await self.session.scalar(
            sa.select(Flows.id)
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
        )
        return flow_id_in_db is not None

    async def update(
        self,
        flow: Flow,
        tenant_id: UUID,
        *,
        expected_revision: int | None = None,
    ) -> Flow:
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
                draft_revision=Flows.draft_revision + 1,
            )
            .returning(Flows)
        )
        if expected_revision is not None:
            stmt = stmt.where(Flows.draft_revision == expected_revision)
        flow_in_db = await self.session.scalar(stmt)
        if flow_in_db is None:
            if expected_revision is not None:
                exists_stmt = (
                    sa.select(Flows.id)
                    .where(Flows.id == flow.id)
                    .where(Flows.tenant_id == tenant_id)
                    .where(Flows.deleted_at.is_(None))
                )
                existing_id = await self.session.scalar(exists_stmt)
                if existing_id is not None:
                    raise BadRequestException(
                        "Flödet ändrades av en annan användare. "
                        "Dina ändringar beräknas mot den nya versionen.",
                        code="stale_revision",
                    )
            raise NotFoundException("Flow not found.")

        await self._sync_flow_steps(
            flow_id=flow.id, tenant_id=tenant_id, steps=flow.steps
        )

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

        has_runs = bool(
            await self.session.scalar(
                sa.select(sa.literal(True))
                .select_from(FlowRuns)
                .where(FlowRuns.flow_id == flow_id)
                .where(FlowRuns.tenant_id == tenant_id)
                .limit(1)
            )
        )
        if has_runs:
            return

        await self.session.execute(
            sa.delete(FlowSteps)
            .where(FlowSteps.flow_id == flow_id)
            .where(FlowSteps.tenant_id == tenant_id)
        )
        await self.session.execute(
            sa.delete(Assistants)
            .where(getattr(Assistants, "origin") == "flow_managed")
            .where(getattr(Assistants, "managing_flow_id") == flow_id)
            .where(self._managed_assistant_belongs_to_tenant(tenant_id=tenant_id))
            .where(self._managed_assistant_has_no_step_references(tenant_id=tenant_id))
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
        attempt_no: int = 1,
        result_file_references: Sequence[FlowStepResultFileReference] | None = None,
    ) -> None:
        """Persist a step result and optionally replace this attempt's file rows.

        `None` leaves file rows untouched for non-success updates; an empty sequence
        intentionally clears them.
        """
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

        if result.status in (
            FlowStepResultStatus.COMPLETED,
            FlowStepResultStatus.FAILED,
            FlowStepResultStatus.CANCELLED,
        ):
            payload["finished_at"] = datetime.now(timezone.utc)
        if result.status == FlowStepResultStatus.COMPLETED:
            payload["current_attempt_no"] = attempt_no

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
            .returning(FlowStepResults)
        )
        saved = await db_session.scalar(stmt)
        if saved is None:
            return
        await self._replace_step_result_file_rows(
            db_session=db_session,
            result_row=saved,
            result_file_references=result_file_references,
            attempt_no=attempt_no,
        )

    async def _replace_step_result_file_rows(
        self,
        *,
        db_session: AsyncSession,
        result_row: FlowStepResults,
        result_file_references: Sequence[FlowStepResultFileReference] | None,
        attempt_no: int,
    ) -> None:
        if result_file_references is None:
            return
        await db_session.execute(
            sa.delete(FlowRunStepResultFiles)
            .where(FlowRunStepResultFiles.step_result_id == result_row.id)
            .where(FlowRunStepResultFiles.tenant_id == result_row.tenant_id)
            .where(FlowRunStepResultFiles.attempt_no == attempt_no)
        )
        if result_row.step_id is None or not result_file_references:
            return

        rows = [
            {
                "flow_run_id": result_row.flow_run_id,
                "flow_id": result_row.flow_id,
                "tenant_id": result_row.tenant_id,
                "step_result_id": result_row.id,
                "step_id": result_row.step_id,
                "step_order": result_row.step_order,
                "attempt_no": attempt_no,
                "file_id": reference.file_id,
                "ordinal": ordinal,
                "source": reference.source,
            }
            for ordinal, reference in enumerate(result_file_references)
        ]
        await db_session.execute(sa.insert(FlowRunStepResultFiles).values(rows))

    async def _sync_flow_steps(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
        steps: list[FlowStep],
    ) -> None:
        existing_rows = (
            (
                await self.session.execute(
                    sa.select(FlowSteps)
                    .where(FlowSteps.flow_id == flow_id)
                    .where(FlowSteps.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
        existing_by_order = {int(row.step_order): row for row in existing_rows}

        incoming_orders = {int(step.step_order) for step in steps}
        cleanup_candidates: set[UUID] = set()
        for step in steps:
            payload = self._step_to_db_row(
                flow_id=flow_id, tenant_id=tenant_id, step=step
            )
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

        stale_orders = [
            order for order in existing_by_order if order not in incoming_orders
        ]
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
            .where(getattr(Assistants, "origin") == "flow_managed")
            .where(getattr(Assistants, "managing_flow_id") == flow_id)
            .where(self._managed_assistant_belongs_to_tenant(tenant_id=tenant_id))
            .where(self._managed_assistant_has_no_step_references(tenant_id=tenant_id))
        )

    @staticmethod
    def _managed_assistant_belongs_to_tenant(
        *, tenant_id: UUID
    ) -> sa.ColumnElement[bool]:
        return sa.exists(
            sa.select(1)
            .select_from(Flows)
            .where(Flows.id == getattr(Assistants, "managing_flow_id"))
            .where(Flows.tenant_id == tenant_id)
        )

    @staticmethod
    def _managed_assistant_has_no_step_references(
        *, tenant_id: UUID
    ) -> sa.ColumnElement[bool]:
        return ~sa.exists(
            sa.select(1)
            .select_from(FlowSteps)
            .where(FlowSteps.assistant_id == Assistants.id)
            .where(FlowSteps.tenant_id == tenant_id)
        )
