from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
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
from eneo.database.tables.flow_tables import (
    FlowResourceBindings,
    FlowRuns,
    Flows,
    FlowStepResults,
    FlowSteps,
)
from eneo.database.tables.prompts_table import Prompts, PromptsAssistants
from eneo.database.tables.security_classifications_table import (
    SecurityClassification,
)
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
    FlowSparse,
    FlowStep,
    FlowStepResult,
)
from eneo.flows.domain.flow_run_retention_policy import (
    flow_run_retention_policy_from_storage,
    resolve_flow_run_retention_policy,
)
from eneo.flows.enums import (
    FlowOutputMode,
    final_output_delivery,
    final_step_output_type,
)
from eneo.flows.flow_evidence_policy import (
    FlowEvidenceAccessContext,
    flow_metadata_marks_sensitive_or_unreadable,
)
from eneo.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.flows.flow_review_policy import dump_flow_step_review_policy
from eneo.flows.flow_run_step_inputs import primary_runtime_input_format
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


def _derived_step_projection(
    *,
    output_types: Sequence[str],
    output_modes: Sequence[str],
    input_configs: Sequence[dict[str, Any] | None],
) -> dict[str, Any]:
    """Sparse list projection of a flow's steps: count, primary input, terminal output.

    All sequences must already be ordered by `step_order` ascending (every
    caller queries `FlowSteps` with that order) and have matching length, one
    entry per step. Resolves through the flow's single output-type, delivery
    and input-format derivations (`final_step_output_type`,
    `final_output_delivery`, `primary_runtime_input_format`) so these fields
    can never diverge from what the run contract exposes for the same flow.

    The result populates `FlowSparse.step_count`/`input_type`/`output_type`/`delivery`,
    which are not auto-derived from `Flow.steps` — every repository method
    that returns a persisted `Flow`/`FlowSparse` must call this with that
    flow's current steps, or the projection silently goes stale.
    """
    output_type = final_step_output_type(list(output_types))
    return {
        "step_count": len(output_types),
        "input_type": primary_runtime_input_format(list(input_configs)),
        "output_type": output_type,
        "delivery": None
        if output_type is None
        else final_output_delivery(
            output_type=output_type, output_mode=FlowOutputMode(output_modes[-1])
        ),
    }


def _attach_run_history_retention(
    flow: _FlowReadModel,
    *,
    organization_mode: str | None,
    organization_days: int | None,
    space_mode: str | None,
    space_days: int | None,
    flow_mode: str | None,
    flow_days: int | None,
) -> _FlowReadModel:
    retention = resolve_flow_run_retention_policy(
        organization_policy=flow_run_retention_policy_from_storage(
            mode=organization_mode,
            days=organization_days,
        ),
        space_policy=flow_run_retention_policy_from_storage(
            mode=space_mode,
            days=space_days,
        ),
        flow_policy=flow_run_retention_policy_from_storage(
            mode=flow_mode,
            days=flow_days,
        ),
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


def _stale_revision_error(
    *, flow_id: UUID, expected_revision: int
) -> BadRequestException:
    return BadRequestException(
        "Flödet har ändrats sedan det lästes in, till exempel i en "
        "annan flik eller av en kollega. Ladda om sidan och gör om "
        "din senaste ändring.",
        code="stale_revision",
        context={"flow_id": str(flow_id), "expected_revision": expected_revision},
    )


class FlowRepository:
    """Tenant-scoped repository for flow aggregate operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _select_flows_with_run_history_retention() -> sa.Select[
        tuple[
            Flows,
            str | None,
            int | None,
            str | None,
            int | None,
            str | None,
            int | None,
            str,
        ]
    ]:
        return (
            sa.select(
                Flows,
                Tenants.flow_run_history_retention_mode.label(
                    "retention_organization_mode"
                ),
                Tenants.flow_run_history_retention_days.label(
                    "retention_organization_days"
                ),
                Spaces.flow_run_history_retention_mode.label("retention_space_mode"),
                Spaces.flow_run_history_retention_days.label("retention_space_days"),
                Flows.flow_run_history_retention_mode.label("retention_flow_mode"),
                Flows.flow_run_history_retention_days.label("retention_flow_days"),
                Spaces.name.label("space_name"),
            )
            .join(
                Spaces,
                sa.and_(
                    Flows.space_id == Spaces.id,
                    Flows.tenant_id == Spaces.tenant_id,
                ),
            )
            .join(Tenants, Flows.tenant_id == Tenants.id)
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

    async def get_evidence_access_context(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
    ) -> FlowEvidenceAccessContext:
        """Read only what decides whether evidence content may be disclosed.

        `get` loads the whole Flow aggregate including every step, and reading
        the space through the space service enforces membership that a tenant
        admin is not subject to. This one row answers the question directly.
        """
        stmt = (
            sa.select(
                Flows.id,
                Flows.space_id,
                Flows.metadata_json,
                SecurityClassification.security_level,
            )
            .select_from(Flows)
            .join(Spaces, Spaces.id == Flows.space_id)
            .outerjoin(
                SecurityClassification,
                SecurityClassification.id == Spaces.security_classification_id,
            )
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
        )
        row = (await self.session.execute(stmt)).one_or_none()
        if row is None:
            raise NotFoundException("Flow not found.")
        resolved_flow_id, space_id, metadata_json, security_level = row
        return FlowEvidenceAccessContext(
            flow_id=resolved_flow_id,
            space_id=space_id,
            sensitive=flow_metadata_marks_sensitive_or_unreadable(metadata_json),
            classification_level=(
                security_level if isinstance(security_level, int) else 0
            ),
        )

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
            organization_mode,
            organization_days,
            space_mode,
            space_days,
            flow_mode,
            flow_days,
            space_name,
        ) = row
        steps = await self._get_flow_steps(flow_id=flow_id, tenant_id=tenant_id)
        sparse_fields = {
            **FlowSparse.model_validate(flow_in_db).model_dump(),
            **_derived_step_projection(
                output_types=[step.output_type for step in steps],
                output_modes=[step.output_mode for step in steps],
                input_configs=[step.input_config for step in steps],
            ),
            "space_name": space_name,
        }
        return _attach_run_history_retention(
            Flow(
                **sparse_fields,
                steps=[FlowStep.model_validate(step) for step in steps],
            ),
            organization_mode=organization_mode,
            organization_days=organization_days,
            space_mode=space_mode,
            space_days=space_days,
            flow_mode=flow_mode,
            flow_days=flow_days,
        )

    async def allocate_next_version(self, *, flow_id: UUID, tenant_id: UUID) -> int:
        """Allocate with the publication pointer lock held in this transaction.

        Numbers come from the high-water mark, never surviving snapshot rows,
        so deleting the highest snapshot cannot let its number identify another.
        """
        version = await self.session.scalar(
            sa.update(Flows)
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
            .values(
                snapshot_allocation_high_water_mark=Flows.snapshot_allocation_high_water_mark
                + 1
            )
            .returning(Flows.snapshot_allocation_high_water_mark)
        )
        if version is None:
            raise NotFoundException("Flow not found.")
        return version

    async def lock_publication_pointer(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
    ) -> int | None:
        """Lock the target Flow row and return its fresh publication pointer."""
        row = (
            await self.session.execute(
                sa.select(Flows.published_version)
                .where(Flows.id == flow_id)
                .where(Flows.tenant_id == tenant_id)
                .where(Flows.deleted_at.is_(None))
                .with_for_update(key_share=True)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException("Flow not found.")
        return row.published_version

    async def get_sparse_by_spaces(
        self,
        *,
        tenant_id: UUID,
        space_ids: Collection[UUID],
        draft_space_ids: Collection[UUID],
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowSparse]:
        """Published flows in `space_ids` and drafts in `draft_space_ids`.

        Visibility is part of the query, so offset and limit page over visible
        flows only, and the id breaks created_at ties so pages never overlap.
        """
        stmt = (
            self._select_flows_with_run_history_retention()
            .where(Flows.space_id.in_(space_ids))
            .where(
                sa.or_(
                    Flows.published_version.is_not(None),
                    Flows.space_id.in_(draft_space_ids),
                )
            )
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
            .order_by(Flows.created_at.asc(), Flows.id.asc())
        )
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        flow_rows = (await self.session.execute(stmt)).all()
        if not flow_rows:
            return []

        flow_ids = [row[0].id for row in flow_rows]
        # `input_config` can carry an authored HTTP step's auth secrets and
        # custom headers (see http_transport/authored_config.py), so the list
        # projection extracts only the `runtime_input` subfield it actually
        # needs instead of materializing the whole JSONB column.
        step_columns = (
            await self.session.execute(
                sa.select(
                    FlowSteps.flow_id,
                    FlowSteps.output_type,
                    FlowSteps.output_mode,
                    FlowSteps.input_config["runtime_input"],
                )
                .where(FlowSteps.flow_id.in_(flow_ids))
                .where(FlowSteps.tenant_id == tenant_id)
                .order_by(FlowSteps.flow_id.asc(), FlowSteps.step_order.asc())
            )
        ).all()
        step_columns_by_flow: dict[
            UUID, list[tuple[str, str, dict[str, Any] | None]]
        ] = defaultdict(list)
        for row in step_columns:
            # `primary_runtime_input_format` resolves through the same
            # step-level `build_runtime_input_config` parser used everywhere
            # else, which reads `input_config["runtime_input"]` itself — so
            # this rewraps the extracted subfield into that shape rather than
            # introducing a second, narrower parser.
            step_columns_by_flow[row[0]].append(
                (row[1], row[2], {"runtime_input": row[3]})
            )

        return [
            _attach_run_history_retention(
                FlowSparse.model_validate(row[0]).model_copy(
                    update={
                        **_derived_step_projection(
                            output_types=[
                                output_type
                                for output_type, _, _ in step_columns_by_flow.get(
                                    row[0].id, []
                                )
                            ],
                            output_modes=[
                                output_mode
                                for _, output_mode, _ in step_columns_by_flow.get(
                                    row[0].id, []
                                )
                            ],
                            input_configs=[
                                input_config
                                for _, _, input_config in step_columns_by_flow.get(
                                    row[0].id, []
                                )
                            ],
                        ),
                        "space_name": row.space_name,
                    }
                ),
                organization_mode=row[1],
                organization_days=row[2],
                space_mode=row[3],
                space_days=row[4],
                flow_mode=row[5],
                flow_days=row[6],
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

    async def next_step_config_repair_flow(
        self, *, tenant_id: UUID | None, after: UUID | None
    ) -> tuple[UUID, UUID] | None:
        stmt = sa.select(Flows.tenant_id, Flows.id).where(Flows.deleted_at.is_(None))
        if tenant_id is not None:
            stmt = stmt.where(Flows.tenant_id == tenant_id)
        if after is not None:
            stmt = stmt.where(Flows.id > after)
        row = (
            await self.session.execute(stmt.order_by(Flows.id).limit(1))
        ).one_or_none()
        return (row.tenant_id, row.id) if row is not None else None

    async def get_step_config_repair_flow(
        self, *, flow_id: UUID, tenant_id: UUID
    ) -> Flow:
        # One statement keeps configs and the revision in the same read snapshot.
        rows = (
            await self.session.execute(
                sa.select(Flows, FlowSteps)
                .outerjoin(
                    FlowSteps,
                    sa.and_(
                        FlowSteps.flow_id == Flows.id,
                        FlowSteps.tenant_id == Flows.tenant_id,
                    ),
                )
                .where(
                    Flows.id == flow_id,
                    Flows.tenant_id == tenant_id,
                    Flows.deleted_at.is_(None),
                )
                .order_by(FlowSteps.step_order)
                .execution_options(populate_existing=True)
            )
        ).all()
        if not rows:
            raise NotFoundException("Flow not found.")
        return Flow(
            **FlowSparse.model_validate(rows[0][0]).model_dump(),
            steps=[
                FlowStep.model_validate(row[1]) for row in rows if row[1] is not None
            ],
        )

    async def repair_step_configs(self, *, flow: Flow, steps: list[FlowStep]) -> None:
        flow_id = flow.require_persisted_id()
        stored_by_id = {step.id: step for step in flow.steps}
        changes: list[tuple[UUID, dict[str, Any]]] = []
        for step in steps:
            if step.id is None or step.id not in stored_by_id:
                raise ValueError("Repair requires existing step ids.")
            stored = stored_by_id[step.id]
            values = {
                field: getattr(step, field)
                for field in ("input_config", "output_config")
                if getattr(step, field) != getattr(stored, field)
            }
            if values:
                changes.append((step.id, values))
        if not changes:
            return
        updated_id = await self.session.scalar(
            sa.update(Flows)
            .where(
                Flows.id == flow_id,
                Flows.tenant_id == flow.tenant_id,
                Flows.deleted_at.is_(None),
                Flows.draft_revision == flow.draft_revision,
            )
            .values(
                draft_revision=Flows.draft_revision + 1, updated_at=Flows.updated_at
            )
            .returning(Flows.id)
        )
        if updated_id is None:
            raise _stale_revision_error(
                flow_id=flow_id, expected_revision=flow.draft_revision
            )
        for step_id, values in changes:
            await self.session.execute(
                sa.update(FlowSteps)
                .where(
                    FlowSteps.id == step_id,
                    FlowSteps.flow_id == flow_id,
                    FlowSteps.tenant_id == flow.tenant_id,
                )
                .values(**values, updated_at=FlowSteps.updated_at)
            )

    async def update(
        self,
        flow: Flow,
        tenant_id: UUID,
        *,
        expected_revision: int | None = None,
    ) -> Flow:
        flow_id = flow.require_persisted_id()

        # Every update is revision-fenced. This statement writes the whole row,
        # `published_version` included, so an unfenced write silently reverts a
        # publish that committed after the caller read the flow. A caller that
        # carries its own optimistic-concurrency token passes it; everyone else
        # is fenced on the revision their own `flow` was read at.
        fenced_revision = (
            flow.draft_revision if expected_revision is None else expected_revision
        )
        flow_in_db = await self.session.scalar(
            sa.update(Flows)
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
            .where(Flows.draft_revision == fenced_revision)
            .values(
                name=flow.name,
                description=flow.description,
                owner_user_id=flow.owner_user_id,
                published_version=flow.published_version,
                metadata_json=flow.metadata_json,
                draft_revision=Flows.draft_revision + 1,
            )
            .returning(Flows)
        )
        if flow_in_db is None:
            existing_id = await self.session.scalar(
                sa.select(Flows.id)
                .where(Flows.id == flow_id)
                .where(Flows.tenant_id == tenant_id)
                .where(Flows.deleted_at.is_(None))
            )
            if existing_id is not None:
                raise _stale_revision_error(
                    flow_id=flow_id, expected_revision=fenced_revision
                )
            raise NotFoundException("Flow not found.")

        await self._sync_flow_steps(
            flow_id=flow_id, tenant_id=tenant_id, steps=flow.steps
        )

        return await self.get(flow_id, tenant_id)

    async def delete(self, flow_id: UUID, tenant_id: UUID) -> frozenset[UUID]:
        """Soft-delete the flow; return the flow-managed assistants to delete.

        A flow with runs keeps its steps and assistants, so it returns none.
        """
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
            return frozenset()

        await self.session.execute(
            sa.delete(FlowSteps)
            .where(FlowSteps.flow_id == flow_id)
            .where(FlowSteps.tenant_id == tenant_id)
        )
        return await self.orphaned_flow_managed_assistant_ids(
            flow_id=flow_id, tenant_id=tenant_id
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
        return FlowStepResult.model_validate(result)

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

    async def orphaned_flow_managed_assistant_ids(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
        assistant_ids: Collection[UUID] | None = None,
    ) -> frozenset[UUID]:
        """Assistants ``flow_id`` manages that no step references.

        Only among ``assistant_ids`` when given, else every one the flow manages.
        """
        if assistant_ids is not None and not assistant_ids:
            return frozenset()

        query = sa.select(Assistants.id)
        if assistant_ids is not None:
            query = query.where(Assistants.id.in_(assistant_ids))
        orphaned_ids = await self.session.scalars(
            query.where(getattr(Assistants, "origin") == "flow_managed")
            .where(getattr(Assistants, "managing_flow_id") == flow_id)
            .where(self._managed_assistant_belongs_to_tenant(tenant_id=tenant_id))
            .where(self._managed_assistant_has_no_step_references(tenant_id=tenant_id))
        )
        return frozenset(orphaned_ids)

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
