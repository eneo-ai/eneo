from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

from eneo.assistants.assistant import AssistantOrigin
from eneo.assistants.assistant_service import AssistantService
from eneo.assistants.assistant_update import (
    AssistantUpdateCaller,
    AssistantUpdateCommand,
)
from eneo.files.file_repo import FileRepository
from eneo.flows.application.flow_authoring_command import (
    AIBuilderFlowAuthoringOrigin,
    CreateFlowAuthoringCommand,
    EditFlowAuthoringCommand,
    FlowAuthoringCommandService,
)
from eneo.flows.application.flow_draft_materialization import (
    FlowDraftCompiledStep,
    FlowDraftStepChangeKind,
)
from eneo.flows.application.flow_service import FlowService
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore, StepSpec
from eneo.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
)
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.users.user import UserInDB


async def assert_create_spec_prepares_through_authoring_command_async(
    spec: FlowDraftSpecCore,
) -> None:
    harness = _RealFlowServiceHarness()
    prepared = await FlowAuthoringCommandService().prepare(
        command=_create_command(spec=spec, space_id=harness.space_id),
        flow_service=harness.flow_service,
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
    asyncio.run(assert_create_spec_prepares_through_authoring_command_async(spec))


async def assert_create_spec_materializes_through_authoring_command_async(
    spec: FlowDraftSpecCore,
) -> None:
    harness = _RealFlowServiceHarness()
    command = _create_command(spec=spec, space_id=harness.space_id)
    service = FlowAuthoringCommandService()
    prepared = await service.prepare(
        command=command,
        flow_service=harness.flow_service,
    )

    result = await service.apply_prepared(
        prepared=prepared,
        flow_service=harness.flow_service,
    )
    materialized = await harness.flow_service.get_flow(result.flow_id)

    assert result.flow_name == prepared.changeset.flow_name
    assert result.steps_created == len(prepared.changeset.compiled_steps)
    assert result.steps_updated == 0
    assert result.steps_removed == 0
    assert materialized.metadata_json == prepared.changeset.metadata_json
    assert harness.flow_repo.resource_bindings[result.flow_id] == (
        command.resource_bindings,
        FlowResourceBindingSource.AI_BUILDER,
    )
    _assert_materialized_steps_match_compiled(
        declared_steps_by_plan_ref={
            step.plan_step_ref: step for step in command.spec.steps
        },
        materialized_steps=tuple(materialized.steps),
        compiled_steps=prepared.changeset.compiled_steps,
        assistant_ids_by_plan_ref=harness.assistant_service.ids_by_name,
    )


async def assert_edit_spec_materializes_through_authoring_command_async(
    spec: FlowDraftSpecCore,
) -> None:
    harness = _RealFlowServiceHarness()
    authoring_service = FlowAuthoringCommandService()
    create_command = _create_command(spec=spec, space_id=harness.space_id)
    create_result = await authoring_service.apply(
        command=create_command,
        flow_service=harness.flow_service,
    )
    current_flow = await harness.flow_service.get_flow(create_result.flow_id)
    current_assistant_ids = [step.assistant_id for step in current_flow.steps]
    edit_spec = spec.model_copy(
        deep=True,
        update={
            "steps": [
                step.model_copy(update={"existing_step_ref": f"existing_step_{index}"})
                for index, step in enumerate(spec.steps, start=1)
            ]
        },
    )
    command = EditFlowAuthoringCommand(
        space_id=harness.space_id,
        flow_id=create_result.flow_id,
        expected_revision=current_flow.draft_revision,
        spec=edit_spec,
        removed_existing_step_refs=frozenset(),
        origin=_authoring_origin(edit_spec),
    )

    prepared = await authoring_service.prepare(
        command=command,
        flow_service=harness.flow_service,
    )
    assert prepared.current_flow == current_flow
    assert prepared.preview.kind == "edit"
    assert prepared.preview.steps_created == 0
    assert prepared.preview.steps_updated == len(edit_spec.steps)
    assert prepared.preview.steps_removed == 0
    assert {step.change_kind for step in prepared.preview.step_changes} == {
        FlowDraftStepChangeKind.MODIFIED
    }

    result = await authoring_service.apply_prepared(
        prepared=prepared,
        flow_service=harness.flow_service,
    )
    materialized = await harness.flow_service.get_flow(result.flow_id)

    assert result.flow_id == current_flow.id
    assert result.draft_revision == current_flow.draft_revision + 1
    assert result.steps_created == 0
    assert result.steps_updated == len(edit_spec.steps)
    assert result.steps_removed == 0
    assert [step.assistant_id for step in materialized.steps] == current_assistant_ids
    _assert_materialized_steps_match_compiled(
        declared_steps_by_plan_ref={
            step.plan_step_ref: step for step in edit_spec.steps
        },
        materialized_steps=tuple(materialized.steps),
        compiled_steps=prepared.changeset.compiled_steps,
        assistant_ids_by_plan_ref={
            step.plan_step_ref: assistant_id
            for step, assistant_id in zip(
                edit_spec.steps,
                current_assistant_ids,
                strict=True,
            )
        },
    )


def _create_command(
    *,
    spec: FlowDraftSpecCore,
    space_id: UUID,
) -> CreateFlowAuthoringCommand:
    return CreateFlowAuthoringCommand(
        space_id=space_id,
        spec=spec,
        origin=_authoring_origin(spec),
        default_transcription_model_id=uuid4(),
    )


def _authoring_origin(spec: FlowDraftSpecCore) -> AIBuilderFlowAuthoringOrigin:
    return AIBuilderFlowAuthoringOrigin(
        session_id=uuid4(),
        plan_id=uuid4(),
        spec_hash=spec.spec_hash(),
        applied_at=datetime.now(UTC),
    )


def _assert_materialized_steps_match_compiled(
    *,
    declared_steps_by_plan_ref: dict[str, StepSpec],
    materialized_steps: tuple[FlowStep, ...],
    compiled_steps: list[FlowDraftCompiledStep],
    assistant_ids_by_plan_ref: dict[str, UUID],
) -> None:
    assert len(materialized_steps) == len(compiled_steps)
    for materialized, compiled in zip(materialized_steps, compiled_steps, strict=True):
        declared = declared_steps_by_plan_ref[compiled.plan_step_ref]
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
        assert materialized.input_bindings == compiled.input_bindings
        assert materialized.input_contract == compiled.input_contract
        assert materialized.output_contract == compiled.output_contract
        assert materialized.input_config == compiled.input_config
        assert materialized.output_config == compiled.output_config
        assert materialized.review_policy == compiled.review_policy
        # Anchor to the declared spec; this catches compiler contract drops.
        assert compiled.output_contract == declared.output_contract


class _ActiveTransactionSession:
    def in_transaction(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class _TestUser:
    id: UUID
    tenant_id: UUID


@dataclass(slots=True)
class _FlowManagedAssistant:
    id: UUID
    space_id: UUID
    name: str
    origin: AssistantOrigin
    managing_flow_id: UUID
    prompt: object | None = None


class _AssistantServiceDouble:
    def __init__(self) -> None:
        self.assistants: dict[UUID, _FlowManagedAssistant] = {}
        self.ids_by_name: dict[str, UUID] = {}

    async def create_assistant(
        self,
        *,
        name: str,
        space_id: UUID,
        hidden: bool,
        origin: AssistantOrigin,
        managing_flow_id: UUID,
    ) -> tuple[_FlowManagedAssistant, list[object]]:
        assert hidden is True
        assert origin is AssistantOrigin.FLOW_MANAGED
        assistant = _FlowManagedAssistant(
            id=uuid4(),
            space_id=space_id,
            name=name,
            origin=origin,
            managing_flow_id=managing_flow_id,
        )
        self.assistants[assistant.id] = assistant
        self.ids_by_name[name] = assistant.id
        return assistant, []

    async def get_assistant(
        self,
        assistant_id: UUID,
    ) -> tuple[_FlowManagedAssistant, list[object]]:
        return self.assistants[assistant_id], []

    async def update_assistant(
        self,
        *,
        assistant_id: UUID,
        update: AssistantUpdateCommand,
        caller: AssistantUpdateCaller,
        include_hidden: bool,
    ) -> tuple[_FlowManagedAssistant, list[object]]:
        assert caller is AssistantUpdateCaller.FLOW_MANAGED
        assert include_hidden is True
        assistant = self.assistants[assistant_id]
        if update.prompt is not None:
            assistant.prompt = update.prompt
        return assistant, []

    async def delete_assistant(self, assistant_id: UUID) -> None:
        assistant = self.assistants.pop(assistant_id)
        self.ids_by_name.pop(assistant.name)


class _FlowRepositoryDouble:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        assistant_service: _AssistantServiceDouble,
    ) -> None:
        self.session = _ActiveTransactionSession()
        self.tenant_id = tenant_id
        self.assistant_service = assistant_service
        self.flows: dict[UUID, Flow] = {}
        self.resource_bindings: dict[
            UUID,
            tuple[tuple[LocalResourceBinding, ...], FlowResourceBindingSource],
        ] = {}

    async def create(self, *, flow: Flow, tenant_id: UUID) -> Flow:
        self._assert_tenant(tenant_id)
        flow_id = uuid4()
        persisted = flow.model_copy(
            deep=True,
            update={"id": flow_id, "steps": self._persist_steps(flow_id, flow.steps)},
        )
        self.flows[flow_id] = persisted
        return persisted.model_copy(deep=True)

    async def get(self, *, flow_id: UUID, tenant_id: UUID) -> Flow:
        self._assert_tenant(tenant_id)
        return self.flows[flow_id].model_copy(deep=True)

    async def get_sparse_by_space(
        self,
        *,
        space_id: UUID,
        tenant_id: UUID,
        published_only: bool,
        limit: int | None,
        offset: int | None,
    ) -> list[Flow]:
        self._assert_tenant(tenant_id)
        assert published_only is False
        assert limit is None
        assert offset is None
        return [
            flow.model_copy(deep=True)
            for flow in self.flows.values()
            if flow.space_id == space_id
        ]

    async def update(
        self,
        *,
        flow: Flow,
        tenant_id: UUID,
        expected_revision: int | None,
    ) -> Flow:
        self._assert_tenant(tenant_id)
        flow_id = flow.require_persisted_id()
        current = self.flows[flow_id]
        if expected_revision is not None:
            assert current.draft_revision == expected_revision
        persisted = flow.model_copy(
            deep=True,
            update={
                "draft_revision": current.draft_revision + 1,
                "steps": self._persist_steps(flow_id, flow.steps),
            },
        )
        self.flows[flow_id] = persisted
        return persisted.model_copy(deep=True)

    async def replace_resource_bindings(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
        bindings: tuple[LocalResourceBinding, ...],
        source: FlowResourceBindingSource,
    ) -> None:
        self._assert_tenant(tenant_id)
        self.resource_bindings[flow_id] = (bindings, source)

    async def get_assistant_scope_rows(
        self,
        *,
        assistant_ids: set[UUID],
        space_id: UUID,
        tenant_id: UUID,
    ) -> list[SimpleNamespace]:
        self._assert_tenant(tenant_id)
        return [
            SimpleNamespace(
                id=assistant.id,
                origin=assistant.origin,
                managing_flow_id=assistant.managing_flow_id,
            )
            for assistant_id in assistant_ids
            if (assistant := self.assistant_service.assistants[assistant_id]).space_id
            == space_id
        ]

    def _persist_steps(self, flow_id: UUID, steps: list[FlowStep]) -> list[FlowStep]:
        return [
            step.model_copy(
                deep=True,
                update={
                    "id": step.id or uuid4(),
                    "flow_id": flow_id,
                    "tenant_id": self.tenant_id,
                },
            )
            for step in steps
        ]

    def _assert_tenant(self, tenant_id: UUID) -> None:
        assert tenant_id == self.tenant_id


class _UnusedDependency:
    pass


class _RealFlowServiceHarness:
    def __init__(self) -> None:
        self.space_id = uuid4()
        user = _TestUser(id=uuid4(), tenant_id=uuid4())
        self.assistant_service = _AssistantServiceDouble()
        self.flow_repo = _FlowRepositoryDouble(
            tenant_id=user.tenant_id,
            assistant_service=self.assistant_service,
        )
        unused = _UnusedDependency()
        self.flow_service = FlowService(
            user=cast(UserInDB, user),
            flow_repo=cast(FlowRepository, self.flow_repo),
            flow_version_repo=cast(FlowVersionRepository, unused),
            assistant_service=cast(AssistantService, self.assistant_service),
            file_repo=cast(FileRepository, unused),
        )
