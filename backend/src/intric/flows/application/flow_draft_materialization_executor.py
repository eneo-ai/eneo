from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from uuid import UUID, uuid4

from intric.flows.application.flow_assistant_update import FlowAssistantUpdateCommand
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
from intric.flows.flow_resource_bindings import (
    FlowResourceBindingResolutionError,
    FlowResourceBindingResolutionReason,
    FlowResourceBindingSource,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    index_local_resource_bindings,
    resolve_local_resource_ref,
)
from intric.main.exceptions import BadRequestException
from intric.prompts.api.prompt_models import PromptCreate

logger = logging.getLogger(__name__)

_MODEL_LOCAL_KINDS = frozenset({LocalResourceKind.COMPLETION_MODEL})
_KNOWLEDGE_LOCAL_KINDS = frozenset({LocalResourceKind.COLLECTION})
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
        created_flow_id: UUID | None = None
        progress = _MaterializationProgressAccumulator(callback=progress_callback)

        try:
            resource_bindings_by_slot_ref = index_local_resource_bindings(
                resource_bindings
            )
        except FlowResourceBindingResolutionError as exc:
            raise _slot_binding_bad_request(exc) from exc

        try:
            ref_to_assistant_id: dict[str, UUID] = {}
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
                created_flow_id = flow_id
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
                    resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
                )
                progress.assistants_updated += 1
                progress.emit(FlowDraftMaterializationStage.ASSISTANTS_UPDATED)

            final_steps = _build_flow_steps(
                compiled_steps=changeset.compiled_steps,
                ref_to_assistant_id=ref_to_assistant_id,
            )

            if is_create:
                await flow_service.update_flow(flow_id=flow_id, steps=final_steps)
            else:
                await flow_service.update_flow(
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
        except Exception:
            if is_create and created_flow_id is not None:
                try:
                    await flow_service.delete_flow(created_flow_id)
                except Exception as cleanup_error:
                    logger.warning(
                        "Failed to clean up temporary flow after materialization error",
                        exc_info=cleanup_error,
                        extra={"flow_id": str(created_flow_id), "space_id": str(space_id)},
                    )
            raise


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
    resource_bindings_by_slot_ref: Mapping[str, LocalResourceBinding],
) -> None:
    command_fields: dict[str, object] = {
        "prompt": PromptCreate(text=assistant_spec.instructions)
    }
    if assistant_spec.model_ref is not None:
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
        groups = [
            _resolve_materializer_resource_ref(
                ref,
                expected_slot_kind=ResourceSlotKind.KNOWLEDGE,
                allowed_local_kinds=_KNOWLEDGE_LOCAL_KINDS,
                resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
                invalid_code="invalid_kb_ref",
                invalid_message=f"Invalid knowledge base reference '{ref}'.",
                invalid_context={"knowledge_refs": assistant_spec.knowledge_refs},
            )
            for ref in assistant_spec.knowledge_refs
        ]
        mcp_server_ids = []
        mcp_tools = []
        websites = []
        integration_knowledge_ids = []
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

    await flow_service.update_flow_assistant(
        flow_id=flow_id,
        assistant_id=assistant_id,
        update=FlowAssistantUpdateCommand.model_validate(command_fields),
    )


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
    try:
        return resolve_local_resource_ref(
            resource_ref,
            expected_slot_kind=expected_slot_kind,
            bindings_by_slot_ref=resource_bindings_by_slot_ref,
            allowed_local_kinds=allowed_local_kinds,
        )
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
            context=invalid_context or error.context(),
        )
    return BadRequestException(
        str(error),
        code=error.reason.value,
        context=error.context(),
    )


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
