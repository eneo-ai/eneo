from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from intric.assistants.assistant_update import AssistantUpdateCommand
from intric.flows.application.flow_authoring_command import (
    AIBuilderFlowAuthoringOrigin,
    CreateFlowAuthoringCommand,
    FlowAuthoringCommandService,
)
from intric.flows.application.flow_draft_materialization import (
    FlowDraftCompiledStep,
    FlowDraftStepChangeKind,
)
from intric.flows.domain.flow import Flow, FlowPersistedJsonObject, FlowStep
from intric.flows.flow_authoring_spec import FlowDraftSpecCore
from intric.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
)


async def assert_create_spec_prepares_through_authoring_command_async(
    spec: FlowDraftSpecCore,
) -> None:
    prepared = await FlowAuthoringCommandService().prepare(
        command=_create_command(spec=spec, space_id=uuid4()),
        flow_service=MagicMock(),
    )

    assert prepared.preview.steps_created == len(prepared.spec.steps)
    assert prepared.preview.steps_updated == 0
    assert prepared.preview.steps_removed == 0
    assert {step.change_kind for step in prepared.preview.step_changes} == {
        FlowDraftStepChangeKind.ADDED
    }
    assert prepared.preview.spec_hash == prepared.spec.spec_hash()


def assert_create_spec_prepares_through_authoring_command(
    spec: FlowDraftSpecCore,
) -> None:
    # Sync tests use this wrapper; async tests call the coroutine to avoid nesting event loops.
    asyncio.run(assert_create_spec_prepares_through_authoring_command_async(spec))


async def assert_create_spec_materializes_through_authoring_command_async(
    spec: FlowDraftSpecCore,
) -> None:
    space_id = uuid4()
    command = _create_command(spec=spec, space_id=space_id)
    service = FlowAuthoringCommandService()
    prepared = await service.prepare(command=command, flow_service=MagicMock())

    flow_service = _CreateFlowMaterializationService(space_id=space_id)
    result = await service.apply_prepared(
        prepared=prepared,
        flow_service=flow_service,
    )

    assert result.flow_id == flow_service.flow_id
    assert result.flow_name == prepared.changeset.flow_name
    assert result.steps_created == len(prepared.changeset.compiled_steps)
    assert result.steps_updated == 0
    assert result.steps_removed == 0
    assert flow_service.created_metadata_json == prepared.changeset.metadata_json
    assert flow_service.replaced_bindings == command.resource_bindings
    assert flow_service.replaced_binding_source is FlowResourceBindingSource.AI_BUILDER
    _assert_materialized_steps_match_compiled(
        materialized_steps=flow_service.materialized_steps,
        compiled_steps=prepared.changeset.compiled_steps,
        assistant_ids_by_plan_ref=flow_service.assistant_ids_by_plan_ref,
    )


def _create_command(
    *,
    spec: FlowDraftSpecCore,
    space_id: UUID,
) -> CreateFlowAuthoringCommand:
    return CreateFlowAuthoringCommand(
        space_id=space_id,
        spec=spec,
        origin=AIBuilderFlowAuthoringOrigin(
            session_id=uuid4(),
            plan_id=uuid4(),
            spec_hash=spec.spec_hash(),
            applied_at=datetime.now(UTC),
        ),
    )


def _assert_materialized_steps_match_compiled(
    *,
    materialized_steps: tuple[FlowStep, ...],
    compiled_steps: list[FlowDraftCompiledStep],
    assistant_ids_by_plan_ref: dict[str, UUID],
) -> None:
    assert len(materialized_steps) == len(compiled_steps)
    for materialized, compiled in zip(materialized_steps, compiled_steps, strict=True):
        assert (
            materialized.assistant_id
            == assistant_ids_by_plan_ref[compiled.plan_step_ref]
        )
        assert materialized.step_order == compiled.step_order
        assert materialized.user_description == compiled.user_description
        assert materialized.input_source == compiled.input_source
        assert materialized.input_type == compiled.input_type
        assert materialized.output_mode == compiled.output_mode
        assert materialized.output_type == compiled.output_type
        assert materialized.mcp_policy == compiled.mcp_policy
        assert materialized.input_bindings == compiled.input_bindings
        assert materialized.input_contract == compiled.input_contract
        assert materialized.output_contract == compiled.output_contract
        assert materialized.input_config == compiled.input_config
        assert materialized.output_config == compiled.output_config
        assert materialized.review_policy == compiled.review_policy


class _ActiveTransactionSession:
    def in_transaction(self) -> bool:
        return True


class _FlowRepoTransactionOwner:
    def __init__(self) -> None:
        self.session = _ActiveTransactionSession()


@dataclass(frozen=True, slots=True)
class _CreatedAssistant:
    id: UUID


class _CreateFlowMaterializationService:
    def __init__(self, *, space_id: UUID) -> None:
        self.flow_repo = _FlowRepoTransactionOwner()
        self.flow_id = uuid4()
        self.tenant_id = uuid4()
        self.space_id = space_id
        self.created_metadata_json: FlowPersistedJsonObject | None = None
        self.materialized_steps: tuple[FlowStep, ...] = ()
        self.assistant_ids_by_plan_ref: dict[str, UUID] = {}
        self.replaced_bindings: tuple[LocalResourceBinding, ...] = ()
        self.replaced_binding_source: FlowResourceBindingSource | None = None

    async def list_flows(
        self,
        *,
        space_id: UUID,
        sparse: bool = True,
    ) -> list[Flow]:
        assert space_id == self.space_id
        assert sparse is True
        return []

    async def create_flow(
        self,
        *,
        space_id: UUID,
        name: str,
        steps: list[FlowStep],
        description: str | None = None,
        metadata_json: FlowPersistedJsonObject | None = None,
    ) -> Flow:
        assert space_id == self.space_id
        assert steps == []
        self.created_metadata_json = metadata_json
        return Flow(
            id=self.flow_id,
            tenant_id=self.tenant_id,
            space_id=space_id,
            name=name,
            description=description,
            metadata_json=metadata_json,
            steps=[],
        )

    async def create_flow_assistant(
        self,
        *,
        flow_id: UUID,
        name: str,
    ) -> tuple[_CreatedAssistant, list[object]]:
        assert flow_id == self.flow_id
        assistant = _CreatedAssistant(id=uuid4())
        self.assistant_ids_by_plan_ref[name] = assistant.id
        return assistant, []

    async def update_flow_assistant(
        self,
        *,
        flow_id: UUID,
        assistant_id: UUID,
        update: AssistantUpdateCommand,
    ) -> None:
        assert flow_id == self.flow_id
        assert assistant_id in self.assistant_ids_by_plan_ref.values()
        assert update.prompt is not None

    async def update_flow(
        self,
        *,
        flow_id: UUID,
        steps: list[FlowStep] | None = None,
        name: object | None = None,
        description: object | None = None,
        metadata_json: object | None = None,
        expected_revision: int | None = None,
    ) -> Flow:
        assert flow_id == self.flow_id
        assert name is None
        assert description is None
        assert metadata_json is None
        assert expected_revision is None
        assert steps is not None
        self.materialized_steps = tuple(steps)
        return Flow(
            id=self.flow_id,
            tenant_id=self.tenant_id,
            space_id=self.space_id,
            name="Materialized flow",
            description=None,
            metadata_json=self.created_metadata_json,
            draft_revision=1,
            steps=list(steps),
        )

    async def replace_resource_bindings(
        self,
        *,
        flow_id: UUID,
        bindings: tuple[LocalResourceBinding, ...],
        source: FlowResourceBindingSource,
    ) -> None:
        assert flow_id == self.flow_id
        self.replaced_bindings = bindings
        self.replaced_binding_source = source
