from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypeVar
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import (
    AssistantMCPServers,
    AssistantMCPServerTools,
    Assistants,
    AssistantsGroups,
)
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.flow_classification_retention_policy_table import (
    FlowClassificationRetentionPolicies,
)
from eneo.database.tables.flow_tables import (
    FlowResourceBindings,
    FlowRuns,
    Flows,
    FlowStepResults,
    FlowSteps,
)
from eneo.database.tables.prompts_table import Prompts, PromptsAssistants
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.flows.assistant_authoring_snapshot import (
    AssistantAuthoringResourceRef,
    AssistantAuthoringSnapshot,
    AssistantAuthoringSnapshots,
)
from eneo.flows.domain.flow import (
    Flow,
    FlowRunRetentionActivationSource,
    FlowRunRetentionBarrierSource,
    FlowRunRetentionContributors,
    FlowRunRetentionDays,
    FlowRunRetentionOff,
    FlowSparse,
    FlowStep,
    FlowStepResult,
)
from eneo.flows.flow_factory import FlowFactory
from eneo.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.flows.flow_review_policy import dump_flow_step_review_policy
from eneo.main.exceptions import BadRequestException, NotFoundException


@dataclass(frozen=True)
class AssistantScopeRow:
    id: UUID
    origin: str | None
    managing_flow_id: UUID | None


@dataclass
class _AssistantAuthoringSnapshotBuilder:
    instructions: str
    model: AssistantAuthoringResourceRef | None
    knowledge_refs: list[AssistantAuthoringResourceRef] = field(
        default_factory=lambda: list[AssistantAuthoringResourceRef]()
    )

    def snapshot(self) -> AssistantAuthoringSnapshot:
        return AssistantAuthoringSnapshot(
            instructions=self.instructions,
            model=self.model,
            knowledge_refs=tuple(self.knowledge_refs),
        )


_FlowReadModel = TypeVar("_FlowReadModel", Flow, FlowSparse)


def _attach_run_history_retention(
    flow: _FlowReadModel,
    *,
    organization_days: int | None,
    classification_days: int | None,
    space_days: int | None,
    flow_days: int | None,
    organization_minimum_days: int | None,
    classification_minimum_days: int | None,
    organization_no_purge: bool,
    classification_no_purge: bool,
    effective_days: int | None,
    effective_minimum_days: int | None,
    no_purge: bool,
    policy_conflict: bool,
) -> _FlowReadModel:
    contributors = FlowRunRetentionContributors(
        organization_days=organization_days,
        classification_days=classification_days,
        space_days=space_days,
        flow_days=flow_days,
        organization_minimum_days=organization_minimum_days,
        classification_minimum_days=classification_minimum_days,
        organization_no_purge=organization_no_purge,
        classification_no_purge=classification_no_purge,
    )
    activation_candidates: tuple[tuple[FlowRunRetentionActivationSource, bool], ...] = (
        ("organization", organization_days is not None),
        ("classification", classification_days is not None),
    )
    activation_sources: tuple[FlowRunRetentionActivationSource, ...] = tuple(
        source for source, configured in activation_candidates if configured
    )
    barrier_candidates: tuple[tuple[FlowRunRetentionBarrierSource, bool], ...] = (
        ("organization_minimum", organization_minimum_days is not None),
        ("classification_minimum", classification_minimum_days is not None),
        ("organization_no_purge", organization_no_purge),
        ("classification_no_purge", classification_no_purge),
    )
    barrier_sources: tuple[FlowRunRetentionBarrierSource, ...] = tuple(
        source for source, configured in barrier_candidates if configured
    )
    retention = (
        FlowRunRetentionOff(
            state="off",
            effective_days=None,
            effective_minimum_days=effective_minimum_days,
            no_purge=no_purge,
            policy_conflict=policy_conflict,
            activation_sources=activation_sources,
            barrier_sources=barrier_sources,
            contributors=contributors,
        )
        if effective_days is None
        else FlowRunRetentionDays(
            state="days",
            effective_days=effective_days,
            effective_minimum_days=effective_minimum_days,
            no_purge=no_purge,
            policy_conflict=policy_conflict,
            activation_sources=activation_sources,
            barrier_sources=barrier_sources,
            contributors=contributors,
        )
    )
    return flow.model_copy(update={"run_history_retention": retention})


def _resource_binding_from_row(row: FlowResourceBindings) -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind(row.slot_kind),
            slot=row.slot,
            label=row.slot_label,
        ),
        local_kind=LocalResourceKind(row.local_resource_kind),
        local_id=row.local_resource_id,
    )


class FlowRepository:
    """Tenant-scoped repository for flow aggregate operations."""

    def __init__(self, session: AsyncSession, factory: FlowFactory):
        self.session = session
        self.factory = factory

    @staticmethod
    def _select_flows_with_run_history_retention() -> sa.Select[
        tuple[
            Flows,
            int | None,
            int | None,
            int | None,
            int | None,
            int | None,
            int | None,
            bool,
            bool | None,
            int | None,
            int | None,
            bool,
            bool,
        ]
    ]:
        # Local import avoids the infrastructure package's eager exports forming a
        # module cycle while keeping the SQL policy owned by DataRetentionService.
        from eneo.data_retention.infrastructure.data_retention_service import (
            DataRetentionService,
        )

        envelope = DataRetentionService.flow_run_history_retention_sql_envelope(
            organization_days=(
                Tenants.flow_run_history_retention_days.__clause_element__()
            ),
            classification_days=(
                FlowClassificationRetentionPolicies.data_retention_days.__clause_element__()
            ),
            space_days=Spaces.data_retention_days.__clause_element__(),
            flow_days=Flows.data_retention_days.__clause_element__(),
            organization_minimum_days=(
                Tenants.flow_run_history_minimum_retention_days.__clause_element__()
            ),
            classification_minimum_days=(
                FlowClassificationRetentionPolicies.minimum_retention_days.__clause_element__()
            ),
            organization_no_purge=(
                Tenants.flow_run_history_no_purge.__clause_element__()
            ),
            classification_no_purge=(
                FlowClassificationRetentionPolicies.no_purge.__clause_element__()
            ),
        )
        return (
            sa.select(
                Flows,
                envelope.organization_days.label("retention_organization_days"),
                envelope.classification_days.label("retention_classification_days"),
                envelope.space_days.label("retention_space_days"),
                envelope.flow_days.label("retention_flow_days"),
                envelope.organization_minimum_days.label(
                    "retention_organization_minimum_days"
                ),
                envelope.classification_minimum_days.label(
                    "retention_classification_minimum_days"
                ),
                envelope.organization_no_purge.label("retention_organization_no_purge"),
                envelope.classification_no_purge.label(
                    "retention_classification_no_purge"
                ),
                envelope.effective_days.label("retention_effective_days"),
                envelope.effective_minimum_days.label(
                    "retention_effective_minimum_days"
                ),
                envelope.no_purge.label("retention_no_purge"),
                envelope.policy_conflict.label("retention_policy_conflict"),
            )
            .join(Spaces, Flows.space_id == Spaces.id)
            .join(Tenants, Flows.tenant_id == Tenants.id)
            .outerjoin(
                FlowClassificationRetentionPolicies,
                sa.and_(
                    FlowClassificationRetentionPolicies.security_classification_id
                    == Spaces.security_classification_id,
                    FlowClassificationRetentionPolicies.tenant_id == Spaces.tenant_id,
                ),
            )
        )

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
            "timeout_seconds": step.timeout_seconds,
            "user_description": step.user_description,
            "input_source": step.input_source,
            "input_type": step.input_type,
            "input_contract": step.input_contract,
            "output_mode": step.output_mode,
            "output_type": step.output_type,
            "output_contract": step.output_contract,
            "input_bindings": step.input_bindings,
            "output_classification_override": step.output_classification_override,
            "input_config": step.input_config,
            "output_config": step.output_config,
            "review_policy": dump_flow_step_review_policy(step.review_policy),
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
            self._select_flows_with_run_history_retention()
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
        )
        row = (await self.session.execute(stmt)).one_or_none()
        if row is None:
            raise NotFoundException("Flow not found.")
        (
            flow_in_db,
            organization_days,
            classification_days,
            space_days,
            flow_days,
            organization_minimum_days,
            classification_minimum_days,
            organization_no_purge,
            classification_no_purge,
            effective_days,
            effective_minimum_days,
            no_purge,
            policy_conflict,
        ) = row
        steps = await self._get_flow_steps(flow_id=flow_id, tenant_id=tenant_id)
        return _attach_run_history_retention(
            self.factory.from_flow_db(flow_in_db=flow_in_db, steps=steps),
            organization_days=organization_days,
            classification_days=classification_days,
            space_days=space_days,
            flow_days=flow_days,
            organization_minimum_days=organization_minimum_days,
            classification_minimum_days=classification_minimum_days,
            organization_no_purge=organization_no_purge,
            classification_no_purge=classification_no_purge or False,
            effective_days=effective_days,
            effective_minimum_days=effective_minimum_days,
            no_purge=no_purge,
            policy_conflict=policy_conflict,
        )

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
            self._select_flows_with_run_history_retention()
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
        flow_rows = (await self.session.execute(stmt)).all()
        if not flow_rows:
            return []

        flow_ids = [row[0].id for row in flow_rows]
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
            _attach_run_history_retention(
                self.factory.from_flow_db(
                    row[0],
                    steps_by_flow.get(row[0].id, []),
                ),
                organization_days=row[1],
                classification_days=row[2],
                space_days=row[3],
                flow_days=row[4],
                organization_minimum_days=row[5],
                classification_minimum_days=row[6],
                organization_no_purge=row[7],
                classification_no_purge=row[8] or False,
                effective_days=row[9],
                effective_minimum_days=row[10],
                no_purge=row[11],
                policy_conflict=row[12],
            )
            for row in flow_rows
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
            self._select_flows_with_run_history_retention()
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
        flow_rows = (await self.session.execute(stmt)).all()
        return [
            _attach_run_history_retention(
                self.factory.from_flow_sparse_db(row[0]),
                organization_days=row[1],
                classification_days=row[2],
                space_days=row[3],
                flow_days=row[4],
                organization_minimum_days=row[5],
                classification_minimum_days=row[6],
                organization_no_purge=row[7],
                classification_no_purge=row[8] or False,
                effective_days=row[9],
                effective_minimum_days=row[10],
                no_purge=row[11],
                policy_conflict=row[12],
            )
            for row in flow_rows
        ]

    async def replace_resource_bindings(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
        bindings: tuple[LocalResourceBinding, ...],
        source: FlowResourceBindingSource,
    ) -> None:
        flow_space_id = await self.session.scalar(
            sa.select(Flows.space_id)
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
        )
        if flow_space_id is None:
            raise NotFoundException("Flow not found.")

        await self.session.execute(
            sa.delete(FlowResourceBindings)
            .where(FlowResourceBindings.flow_id == flow_id)
            .where(FlowResourceBindings.tenant_id == tenant_id)
        )
        if not bindings:
            return

        rows = [
            {
                "flow_id": flow_id,
                "tenant_id": tenant_id,
                "space_id": flow_space_id,
                "slot_kind": binding.slot_ref.kind.value,
                "slot": binding.slot_ref.slot,
                "slot_label": binding.slot_ref.label,
                "local_resource_kind": binding.local_kind.value,
                "local_resource_id": binding.local_id,
                "source": source.value,
            }
            for binding in bindings
        ]
        await self.session.execute(sa.insert(FlowResourceBindings).values(rows))

    async def list_resource_bindings(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
    ) -> tuple[LocalResourceBinding, ...]:
        flow_exists = await self.session.scalar(
            sa.select(Flows.id)
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
        )
        if flow_exists is None:
            raise NotFoundException("Flow not found.")

        rows = (
            (
                await self.session.execute(
                    sa.select(FlowResourceBindings)
                    .where(FlowResourceBindings.flow_id == flow_id)
                    .where(FlowResourceBindings.tenant_id == tenant_id)
                    .order_by(
                        FlowResourceBindings.slot_kind.asc(),
                        FlowResourceBindings.slot.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return tuple(_resource_binding_from_row(row) for row in rows)

    async def get_assistant_snapshots(
        self,
        *,
        assistant_ids: list[UUID],
        tenant_id: UUID,
    ) -> AssistantAuthoringSnapshots:
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

        snapshots: dict[UUID, _AssistantAuthoringSnapshotBuilder] = {
            row.id: _AssistantAuthoringSnapshotBuilder(
                instructions=getattr(row, "instructions", None) or "",
                model=(
                    AssistantAuthoringResourceRef(
                        local_ref=str(row.completion_model_id),
                        label=getattr(row, "model_name", None),
                        local_kind=LocalResourceKind.COMPLETION_MODEL,
                    )
                    if row.completion_model_id
                    else None
                ),
            )
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
            snapshots[row.assistant_id].knowledge_refs.append(
                AssistantAuthoringResourceRef(
                    local_ref=str(row.id),
                    label=row.name,
                    local_kind=LocalResourceKind.COLLECTION,
                )
            )

        return {
            assistant_id: snapshots[assistant_id].snapshot()
            for assistant_id in assistant_ids
            if assistant_id in snapshots
        }

    async def count_flow_step_assistants_with_mcp_configuration(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
    ) -> int:
        server_membership = sa.exists().where(
            AssistantMCPServers.assistant_id == FlowSteps.assistant_id
        )
        tool_membership = sa.exists().where(
            AssistantMCPServerTools.assistant_id == FlowSteps.assistant_id
        )
        count = await self.session.scalar(
            sa.select(sa.func.count(sa.distinct(FlowSteps.assistant_id)))
            .where(FlowSteps.flow_id == flow_id)
            .where(FlowSteps.tenant_id == tenant_id)
            .where(sa.or_(server_membership, tool_membership))
        )
        return int(count or 0)

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
        flow_id = flow.require_persisted_id()

        stmt = (
            sa.update(Flows)
            .where(Flows.id == flow_id)
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
                    .where(Flows.id == flow_id)
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
            flow_id=flow_id, tenant_id=tenant_id, steps=flow.steps
        )

        return await self.get(flow_id, tenant_id)

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
                    .order_by(FlowSteps.id.asc())
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        existing_by_id = {row.id: row for row in existing_rows}
        incoming_ids = {step.id for step in steps if step.id is not None}

        cleanup_candidates: set[UUID] = set()
        retained_steps: list[tuple[FlowStep, FlowSteps]] = []
        new_steps: list[FlowStep] = []
        for step in steps:
            if step.id is None:
                new_steps.append(step)
                continue
            existing = existing_by_id.get(step.id)
            if existing is None:
                # FlowService owns update-id validation; this protects direct
                # repository callers from treating stale ids as new rows.
                raise BadRequestException(
                    "Flow update references an unknown draft step id.",
                    code="unknown_step_id",
                )
            if existing.assistant_id != step.assistant_id:
                cleanup_candidates.add(existing.assistant_id)
            retained_steps.append((step, existing))

        changed_order_rows = [
            existing
            for step, existing in retained_steps
            if int(existing.step_order) != int(step.step_order)
        ]
        if changed_order_rows:
            max_step_order = max(
                (
                    int(step_order)
                    for step_order in (
                        *(row.step_order for row in existing_rows),
                        *(step.step_order for step in steps),
                    )
                ),
                default=0,
            )
            for offset, existing in enumerate(changed_order_rows, start=1):
                await self.session.execute(
                    sa.update(FlowSteps)
                    .where(FlowSteps.id == existing.id)
                    .where(FlowSteps.tenant_id == tenant_id)
                    .values(step_order=max_step_order + offset)
                )
            # uq_flow_steps_flow_step_order is not deferrable, so final orders
            # need a flushed temporary positive band.
            await self.session.flush()

        stale_id_set = {row.id for row in existing_rows if row.id not in incoming_ids}
        if stale_id_set:
            cleanup_candidates.update(
                row.assistant_id for row in existing_rows if row.id in stale_id_set
            )
            await self.session.execute(
                sa.delete(FlowSteps)
                .where(FlowSteps.flow_id == flow_id)
                .where(FlowSteps.tenant_id == tenant_id)
                .where(FlowSteps.id.in_(stale_id_set))
            )

        for step, existing in retained_steps:
            payload = self._step_to_db_row(
                flow_id=flow_id, tenant_id=tenant_id, step=step
            )
            await self.session.execute(
                sa.update(FlowSteps)
                .where(FlowSteps.id == existing.id)
                .where(FlowSteps.tenant_id == tenant_id)
                .values(**payload)
            )

        for step in new_steps:
            await self.session.execute(
                sa.insert(FlowSteps).values(
                    self._step_to_db_row(
                        flow_id=flow_id, tenant_id=tenant_id, step=step
                    )
                )
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
