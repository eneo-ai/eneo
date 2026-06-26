from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import assert_never
from uuid import UUID, uuid4

from intric.assistants.assistant_update import AssistantUpdateCommand
from intric.flows.application.flow_draft_materialization import (
    FlowDraftAssistantToDelete,
    FlowDraftChangeSet,
    FlowDraftCompiledStep,
    FlowDraftMaterializationProgress,
    FlowDraftMaterializationResult,
    FlowDraftMaterializationStage,
    FlowDraftStepChangeKind,
)
from intric.flows.application.flow_service import FlowService
from intric.flows.domain.flow import FlowStep
from intric.flows.flow_authoring_name import normalize_flow_name
from intric.flows.flow_authoring_spec import AssistantSpec
from intric.flows.flow_capability_manifest import requires_completion_model
from intric.flows.flow_resource_bindings import (
    FlowResourceBindingResolutionError,
    FlowResourceBindingResolutionReason,
    FlowResourceBindingSource,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    assistant_update_field_for_knowledge_local_kind,
    index_local_resource_bindings,
    local_resource_kinds_for_slot_kind,
    resolve_local_resource_ref,
)
from intric.main.exceptions import BadRequestException
from intric.prompts.api.prompt_models import PromptCreate

_MODEL_LOCAL_KINDS = frozenset({LocalResourceKind.COMPLETION_MODEL})
_MCP_SERVER_LOCAL_KINDS = frozenset({LocalResourceKind.MCP_SERVER})
_MCP_TOOL_LOCAL_KINDS = frozenset({LocalResourceKind.MCP_TOOL})


class FlowDraftMaterializer:
    """Executes a compiled FlowDraftChangeSet against a draft Flow."""

    async def execute(
        self,
        *,
        changeset: FlowDraftChangeSet,
        flow_service: FlowService,
        space_id: UUID,
        flow_id: UUID | None,
        expected_revision: int | None = None,
        resource_bindings: tuple[LocalResourceBinding, ...] = tuple(),
        binding_source: FlowResourceBindingSource,
        progress_callback: Callable[[FlowDraftMaterializationProgress], None]
        | None = None,
    ) -> FlowDraftMaterializationResult:
        is_create = flow_id is None
        progress = _MaterializationProgressAccumulator(callback=progress_callback)

        resource_bindings_by_slot_ref = index_and_validate_changeset_resource_bindings(
            changeset=changeset,
            resource_bindings=resource_bindings,
        )

        ref_to_assistant_id: dict[str, UUID] = {}
        completion_required_by_plan_ref = _completion_required_by_plan_ref(
            changeset.compiled_steps
        )
        completion_required_by_assistant_id = _completion_required_by_assistant_id(
            changeset.compiled_steps
        )
        flow_name = changeset.flow_name

        if is_create:
            flow_name = await _deduplicate_flow_name(
                flow_service=flow_service,
                space_id=space_id,
                desired_name=changeset.flow_name,
            )
            temp_flow = await flow_service.create_flow(
                space_id=space_id,
                name=flow_name,
                description=changeset.flow_description,
                steps=[],
                metadata_json=changeset.metadata_json,
            )
            flow_id = temp_flow.id
            progress.flow_created = True
            progress.emit(FlowDraftMaterializationStage.FLOW_CREATED)

        if flow_id is None:
            raise BadRequestException("Flow id missing while executing changeset.")

        for assistant_to_create in changeset.assistants_to_create:
            assistant, _ = await flow_service.create_flow_assistant(
                flow_id=flow_id,
                name=assistant_to_create.plan_step_ref,
            )
            ref_to_assistant_id[assistant_to_create.plan_step_ref] = assistant.id
            progress.assistants_created += 1
            progress.emit(FlowDraftMaterializationStage.ASSISTANTS_CREATED)

            await _configure_assistant(
                flow_service=flow_service,
                flow_id=flow_id,
                assistant_id=assistant.id,
                assistant_spec=assistant_to_create.assistant_spec,
                requires_completion_model_for_step=_completion_required_for_plan_ref(
                    plan_step_ref=assistant_to_create.plan_step_ref,
                    completion_required_by_plan_ref=completion_required_by_plan_ref,
                ),
                resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
            )
            progress.assistants_configured += 1
            progress.emit(FlowDraftMaterializationStage.ASSISTANTS_CONFIGURED)

        for assistant_to_update in changeset.assistants_to_update:
            if assistant_to_update.existing_assistant_id is None:
                raise BadRequestException(
                    "Existing assistant id missing while applying changeset."
                )
            await _configure_assistant(
                flow_service=flow_service,
                flow_id=flow_id,
                assistant_id=assistant_to_update.existing_assistant_id,
                assistant_spec=assistant_to_update.assistant_spec,
                requires_completion_model_for_step=_completion_required_for_assistant_id(
                    assistant_id=assistant_to_update.existing_assistant_id,
                    completion_required_by_assistant_id=completion_required_by_assistant_id,
                ),
                resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
            )
            progress.assistants_updated += 1
            progress.emit(FlowDraftMaterializationStage.ASSISTANTS_UPDATED)

        final_steps = _build_flow_steps(
            compiled_steps=changeset.compiled_steps,
            ref_to_assistant_id=ref_to_assistant_id,
        )

        if is_create:
            materialized_flow = await flow_service.update_flow(
                flow_id=flow_id,
                steps=final_steps,
            )
        else:
            materialized_flow = await flow_service.update_flow(
                flow_id=flow_id,
                name=changeset.flow_name,
                description=changeset.flow_description,
                steps=final_steps,
                metadata_json=changeset.metadata_json,
                expected_revision=expected_revision,
            )
        progress.flow_updated = True
        progress.emit(FlowDraftMaterializationStage.FLOW_UPDATED)

        await flow_service.replace_resource_bindings(
            flow_id=flow_id,
            bindings=resource_bindings,
            source=binding_source,
        )

        for assistant_to_delete in changeset.assistants_to_delete:
            await _delete_removed_assistant(
                flow_service=flow_service,
                flow_id=flow_id,
                assistant_to_delete=assistant_to_delete,
            )
            progress.assistants_deleted += 1
            progress.emit(FlowDraftMaterializationStage.ASSISTANTS_DELETED)

        return FlowDraftMaterializationResult(
            flow_id=flow_id,
            flow_name=flow_name,
            draft_revision=materialized_flow.draft_revision,
            steps_created=sum(
                1
                for step in changeset.compiled_steps
                if step.change_kind == FlowDraftStepChangeKind.ADDED
            ),
            steps_updated=sum(
                1
                for step in changeset.compiled_steps
                if step.change_kind == FlowDraftStepChangeKind.MODIFIED
            ),
            steps_removed=len(changeset.assistants_to_delete),
        )


class _MaterializationProgressAccumulator:
    def __init__(
        self,
        *,
        callback: Callable[[FlowDraftMaterializationProgress], None] | None,
    ) -> None:
        self._callback = callback
        self.assistants_created = 0
        self.assistants_configured = 0
        self.assistants_updated = 0
        self.assistants_deleted = 0
        self.flow_created = False
        self.flow_updated = False

    def emit(self, stage: FlowDraftMaterializationStage) -> None:
        if self._callback is None:
            return
        self._callback(
            FlowDraftMaterializationProgress(
                stage=stage,
                assistants_created=self.assistants_created,
                assistants_configured=self.assistants_configured,
                assistants_updated=self.assistants_updated,
                assistants_deleted=self.assistants_deleted,
                flow_created=self.flow_created,
                flow_updated=self.flow_updated,
            )
        )


def index_and_validate_changeset_resource_bindings(
    *,
    changeset: FlowDraftChangeSet,
    resource_bindings: tuple[LocalResourceBinding, ...],
) -> dict[str, LocalResourceBinding]:
    try:
        resource_bindings_by_slot_ref = index_local_resource_bindings(resource_bindings)
    except FlowResourceBindingResolutionError as exc:
        raise _slot_binding_bad_request(exc) from exc

    completion_required_by_plan_ref = _completion_required_by_plan_ref(
        changeset.compiled_steps
    )
    completion_required_by_assistant_id = _completion_required_by_assistant_id(
        changeset.compiled_steps
    )

    for assistant_to_create in changeset.assistants_to_create:
        _resolve_assistant_resource_update_fields(
            assistant_spec=assistant_to_create.assistant_spec,
            requires_completion_model_for_step=_completion_required_for_plan_ref(
                plan_step_ref=assistant_to_create.plan_step_ref,
                completion_required_by_plan_ref=completion_required_by_plan_ref,
            ),
            resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
        )

    for assistant_to_update in changeset.assistants_to_update:
        if assistant_to_update.existing_assistant_id is None:
            continue
        _resolve_assistant_resource_update_fields(
            assistant_spec=assistant_to_update.assistant_spec,
            requires_completion_model_for_step=_completion_required_for_assistant_id(
                assistant_id=assistant_to_update.existing_assistant_id,
                completion_required_by_assistant_id=completion_required_by_assistant_id,
            ),
            resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
        )

    return resource_bindings_by_slot_ref


def _build_flow_steps(
    *,
    compiled_steps: list[FlowDraftCompiledStep],
    ref_to_assistant_id: Mapping[str, UUID],
) -> list[FlowStep]:
    final_steps: list[FlowStep] = []
    for compiled in compiled_steps:
        assistant_id = compiled.assistant_id or ref_to_assistant_id.get(
            compiled.plan_step_ref
        )
        if assistant_id is None:
            raise BadRequestException(
                "Assistant id missing while building materialized flow steps.",
                code="missing_materialized_assistant_id",
                context={"plan_step_ref": compiled.plan_step_ref},
            )
        final_steps.append(
            FlowStep(
                assistant_id=assistant_id,
                step_order=compiled.step_order,
                user_description=compiled.user_description,
                input_source=compiled.input_source,
                input_type=compiled.input_type,
                output_mode=compiled.output_mode,
                output_type=compiled.output_type,
                mcp_policy=compiled.mcp_policy,
                input_bindings=compiled.input_bindings,
                input_contract=compiled.input_contract,
                output_contract=compiled.output_contract,
                input_config=compiled.input_config,
                output_config=compiled.output_config,
                review_policy=compiled.review_policy,
            )
        )
    return final_steps


def _completion_required_by_plan_ref(
    compiled_steps: list[FlowDraftCompiledStep],
) -> dict[str, bool]:
    return {
        step.plan_step_ref: requires_completion_model(step.output_mode)
        for step in compiled_steps
    }


def _completion_required_by_assistant_id(
    compiled_steps: list[FlowDraftCompiledStep],
) -> dict[UUID, bool]:
    return {
        step.assistant_id: requires_completion_model(step.output_mode)
        for step in compiled_steps
        if step.assistant_id is not None
    }


def _completion_required_for_plan_ref(
    *,
    plan_step_ref: str,
    completion_required_by_plan_ref: Mapping[str, bool],
) -> bool:
    try:
        return completion_required_by_plan_ref[plan_step_ref]
    except KeyError as exc:
        raise RuntimeError(
            f"Compiled step missing for assistant create operation: {plan_step_ref}"
        ) from exc


def _completion_required_for_assistant_id(
    *,
    assistant_id: UUID,
    completion_required_by_assistant_id: Mapping[UUID, bool],
) -> bool:
    try:
        return completion_required_by_assistant_id[assistant_id]
    except KeyError as exc:
        raise RuntimeError(
            f"Compiled step missing for assistant update operation: {assistant_id}"
        ) from exc


async def _delete_removed_assistant(
    *,
    flow_service: FlowService,
    flow_id: UUID,
    assistant_to_delete: FlowDraftAssistantToDelete,
) -> None:
    if assistant_to_delete.assistant_id is None:
        raise BadRequestException(
            "Assistant id missing while deleting removed flow step assistant.",
            code="missing_removed_assistant_id",
            context={
                "step_id": (
                    str(assistant_to_delete.step_id)
                    if assistant_to_delete.step_id is not None
                    else None
                )
            },
        )
    await flow_service.delete_flow_assistant(
        flow_id=flow_id,
        assistant_id=assistant_to_delete.assistant_id,
    )


async def _configure_assistant(
    *,
    flow_service: FlowService,
    flow_id: UUID,
    assistant_id: UUID,
    assistant_spec: AssistantSpec,
    requires_completion_model_for_step: bool,
    resource_bindings_by_slot_ref: Mapping[str, LocalResourceBinding],
) -> None:
    command_fields: dict[str, object] = {
        "prompt": PromptCreate(text=assistant_spec.instructions)
    }
    command_fields.update(
        _resolve_assistant_resource_update_fields(
            assistant_spec=assistant_spec,
            requires_completion_model_for_step=requires_completion_model_for_step,
            resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
        )
    )

    await flow_service.update_flow_assistant(
        flow_id=flow_id,
        assistant_id=assistant_id,
        update=AssistantUpdateCommand.model_validate(command_fields),
    )


def _resolve_assistant_resource_update_fields(
    *,
    assistant_spec: AssistantSpec,
    requires_completion_model_for_step: bool,
    resource_bindings_by_slot_ref: Mapping[str, LocalResourceBinding],
) -> dict[str, object]:
    command_fields: dict[str, object] = {}
    if not requires_completion_model_for_step:
        command_fields["completion_model_id"] = None
    elif assistant_spec.model_ref is not None:
        command_fields["completion_model_id"] = _resolve_materializer_resource_ref(
            assistant_spec.model_ref,
            expected_slot_kind=ResourceSlotKind.MODEL,
            allowed_local_kinds=_MODEL_LOCAL_KINDS,
            resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
            invalid_code="invalid_model_ref",
            invalid_message=f"Invalid model reference '{assistant_spec.model_ref}'.",
            invalid_context={"model_ref": assistant_spec.model_ref},
        )

    uses_knowledge = bool(assistant_spec.knowledge_refs)
    uses_mcp = bool(assistant_spec.mcp_server_refs or assistant_spec.mcp_tool_refs)

    if uses_mcp:
        mcp_invalid_context: dict[str, object] = {
            "mcp_server_refs": assistant_spec.mcp_server_refs,
            "mcp_tool_refs": assistant_spec.mcp_tool_refs,
        }
        mcp_server_ids = [
            _resolve_materializer_resource_ref(
                ref,
                expected_slot_kind=ResourceSlotKind.MCP_SERVER,
                allowed_local_kinds=_MCP_SERVER_LOCAL_KINDS,
                resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
                invalid_code="invalid_mcp_ref",
                invalid_message=f"Invalid MCP reference '{ref}'.",
                invalid_context=mcp_invalid_context,
            )
            for ref in assistant_spec.mcp_server_refs
        ]
        mcp_tools = [
            (
                _resolve_materializer_resource_ref(
                    ref,
                    expected_slot_kind=ResourceSlotKind.MCP_TOOL,
                    allowed_local_kinds=_MCP_TOOL_LOCAL_KINDS,
                    resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
                    invalid_code="invalid_mcp_ref",
                    invalid_message=f"Invalid MCP reference '{ref}'.",
                    invalid_context=mcp_invalid_context,
                ),
                True,
            )
            for ref in assistant_spec.mcp_tool_refs
        ]
        groups = []
        websites = []
        integration_knowledge_ids = []
    elif uses_knowledge:
        groups, websites, integration_knowledge_ids = _resolve_knowledge_refs(
            knowledge_refs=assistant_spec.knowledge_refs,
            resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
        )
        mcp_server_ids = []
        mcp_tools = []
    else:
        groups = []
        websites = []
        integration_knowledge_ids = []
        mcp_server_ids = []
        mcp_tools = []

    command_fields["groups"] = groups
    command_fields["websites"] = websites
    command_fields["integration_knowledge_ids"] = integration_knowledge_ids
    command_fields["mcp_server_ids"] = mcp_server_ids
    command_fields["mcp_tools"] = mcp_tools

    return command_fields


def _resolve_knowledge_refs(
    *,
    knowledge_refs: Sequence[str],
    resource_bindings_by_slot_ref: Mapping[str, LocalResourceBinding],
) -> tuple[list[UUID], list[UUID], list[UUID]]:
    groups: list[UUID] = []
    websites: list[UUID] = []
    integration_knowledge_ids: list[UUID] = []

    for ref in knowledge_refs:
        binding = _resolve_materializer_resource_binding(
            ref,
            expected_slot_kind=ResourceSlotKind.KNOWLEDGE,
            allowed_local_kinds=local_resource_kinds_for_slot_kind(
                ResourceSlotKind.KNOWLEDGE
            ),
            resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
            invalid_code="invalid_kb_ref",
            invalid_message=f"Invalid knowledge base reference '{ref}'.",
            invalid_context={"knowledge_refs": knowledge_refs},
        )
        target_field = assistant_update_field_for_knowledge_local_kind(
            binding.local_kind
        )
        match target_field:
            case "groups":
                groups.append(binding.local_id)
            case "websites":
                websites.append(binding.local_id)
            case "integration_knowledge_ids":
                integration_knowledge_ids.append(binding.local_id)
            case _:
                assert_never(target_field)

    return groups, websites, integration_knowledge_ids


def _resolve_materializer_resource_ref(
    resource_ref: str,
    *,
    expected_slot_kind: ResourceSlotKind,
    allowed_local_kinds: frozenset[LocalResourceKind],
    resource_bindings_by_slot_ref: Mapping[str, LocalResourceBinding],
    invalid_code: str,
    invalid_message: str,
    invalid_context: dict[str, object],
) -> UUID:
    return _resolve_materializer_resource_binding(
        resource_ref,
        expected_slot_kind=expected_slot_kind,
        allowed_local_kinds=allowed_local_kinds,
        resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
        invalid_code=invalid_code,
        invalid_message=invalid_message,
        invalid_context=invalid_context,
    ).local_id


def _resolve_materializer_resource_binding(
    resource_ref: str,
    *,
    expected_slot_kind: ResourceSlotKind,
    allowed_local_kinds: frozenset[LocalResourceKind],
    resource_bindings_by_slot_ref: Mapping[str, LocalResourceBinding],
    invalid_code: str,
    invalid_message: str,
    invalid_context: dict[str, object],
) -> LocalResourceBinding:
    try:
        resolve_local_resource_ref(
            resource_ref,
            expected_slot_kind=expected_slot_kind,
            bindings_by_slot_ref=resource_bindings_by_slot_ref,
            allowed_local_kinds=allowed_local_kinds,
        )
        return resource_bindings_by_slot_ref[resource_ref.strip()]
    except FlowResourceBindingResolutionError as exc:
        raise _slot_binding_bad_request(
            exc,
            invalid_code=invalid_code,
            invalid_message=invalid_message,
            invalid_context=invalid_context,
        ) from exc


def _slot_binding_bad_request(
    error: FlowResourceBindingResolutionError,
    *,
    invalid_code: str | None = None,
    invalid_message: str | None = None,
    invalid_context: dict[str, object] | None = None,
) -> BadRequestException:
    if error.reason is FlowResourceBindingResolutionReason.INVALID_SLOT_REF:
        return BadRequestException(
            invalid_message or str(error),
            code=invalid_code or error.reason.value,
            context=invalid_context or _bad_request_context(error),
        )
    return BadRequestException(
        str(error),
        code=error.reason.value,
        context=_bad_request_context(error),
    )


def _bad_request_context(
    error: FlowResourceBindingResolutionError,
) -> dict[str, object]:
    return dict(error.context())


async def _deduplicate_flow_name(
    *,
    flow_service: FlowService,
    space_id: UUID,
    desired_name: str,
) -> str:
    desired_name = normalize_flow_name(desired_name)
    existing_flows = await flow_service.list_flows(space_id=space_id, sparse=True)
    existing_names = {flow.name for flow in existing_flows}

    if desired_name not in existing_names:
        return desired_name

    base = re.sub(r"\s*\(\d+\)$", "", desired_name)
    for index in range(2, 100):
        candidate = f"{base} ({index})"
        if candidate not in existing_names:
            return candidate

    return f"{base} ({uuid4().hex[:8]})"
