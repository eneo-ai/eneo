from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, assert_never
from uuid import UUID, uuid4

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.flows.application.flow_draft_materialization import (
    ALL_ASSISTANT_FIELDS,
    AssistantField,
    FlowDraftAssistantToUpdate,
    FlowDraftChangeSet,
    FlowDraftCompiledStep,
    FlowDraftMaterializationProgress,
    FlowDraftMaterializationResult,
    FlowDraftMaterializationStage,
    FlowDraftStepChangeKind,
)
from eneo.flows.application.flow_service import FlowService
from eneo.flows.application.flow_template_attachment_materialization import (
    materialize_template_attachment,
    materialize_template_imports,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_name import normalize_flow_name
from eneo.flows.flow_authoring_spec import AssistantSpec
from eneo.flows.flow_authoring_variable_rewriting import renumber_step_aliases
from eneo.flows.flow_capability_manifest import requires_completion_model
from eneo.flows.flow_resource_bindings import (
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
from eneo.flows.infrastructure.flow_repo import StoredAssistantPrompt
from eneo.main.exceptions import BadRequestException
from eneo.prompts.api.prompt_models import PromptCreate

if TYPE_CHECKING:
    from eneo.flows.application.flow_authoring_command import (
        TemplateAttachmentIntent,
        TemplateImportIntent,
    )
    from eneo.flows.flow_template_asset_service import FlowTemplateAssetService

_MODEL_LOCAL_KINDS = frozenset({LocalResourceKind.COMPLETION_MODEL})


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
        template_attachment_intent: "TemplateAttachmentIntent | None" = None,
        template_asset_service: "FlowTemplateAssetService | None" = None,
        template_imports: tuple[TemplateImportIntent, ...] = (),
        progress_callback: Callable[[FlowDraftMaterializationProgress], None]
        | None = None,
    ) -> FlowDraftMaterializationResult:
        is_create = flow_id is None
        progress = _MaterializationProgressAccumulator(callback=progress_callback)

        if (
            template_attachment_intent is not None or template_imports
        ) and template_asset_service is None:
            raise RuntimeError(
                "Template attachment materialization requires a template asset service."
            )

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

        if template_imports:
            assert template_asset_service is not None
            changeset, template_bindings = await materialize_template_imports(
                intents=template_imports,
                changeset=changeset,
                flow_id=flow_id,
                template_asset_service=template_asset_service,
            )
            resource_bindings = (*resource_bindings, *template_bindings)
            resource_bindings_by_slot_ref = (
                index_and_validate_changeset_resource_bindings(
                    changeset=changeset, resource_bindings=resource_bindings
                )
            )

        if template_attachment_intent is not None:
            assert template_asset_service is not None
            resolved_template = await materialize_template_attachment(
                intent=template_attachment_intent,
                changeset=changeset,
                flow_id=flow_id,
                template_asset_service=template_asset_service,
            )
            changeset = resolved_template.changeset
            resource_bindings = (*resource_bindings, resolved_template.binding)
            resource_bindings_by_slot_ref = (
                index_and_validate_changeset_resource_bindings(
                    changeset=changeset,
                    resource_bindings=resource_bindings,
                )
            )

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
                fields=ALL_ASSISTANT_FIELDS,
                new_assistant=True,
                prompt_alias_renumbering={},
                stored_prompt=None,
            )
            progress.assistants_configured += 1
            progress.emit(FlowDraftMaterializationStage.ASSISTANTS_CONFIGURED)

        stored_prompts = await _stored_prompts(
            flow_service=flow_service,
            flow_id=flow_id,
            assistants_to_update=changeset.assistants_to_update,
        )
        for assistant_to_update in changeset.assistants_to_update:
            if assistant_to_update.existing_assistant_id is None:
                raise BadRequestException(
                    "Existing assistant id missing while applying changeset."
                )
            written = await _configure_assistant(
                flow_service=flow_service,
                flow_id=flow_id,
                assistant_id=assistant_to_update.existing_assistant_id,
                assistant_spec=assistant_to_update.assistant_spec,
                requires_completion_model_for_step=_completion_required_for_assistant_id(
                    assistant_id=assistant_to_update.existing_assistant_id,
                    completion_required_by_assistant_id=completion_required_by_assistant_id,
                ),
                resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
                fields=assistant_to_update.fields,
                new_assistant=False,
                prompt_alias_renumbering=assistant_to_update.prompt_alias_renumbering,
                stored_prompt=stored_prompts.get(
                    assistant_to_update.existing_assistant_id
                ),
            )
            if not written:
                continue
            progress.assistants_updated += 1
            progress.emit(FlowDraftMaterializationStage.ASSISTANTS_UPDATED)

        final_steps = build_flow_steps(
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
                unchanged_step_ids=frozenset(
                    compiled.saved_step.id
                    for compiled in changeset.compiled_steps
                    if compiled.change_kind is FlowDraftStepChangeKind.UNCHANGED
                    and compiled.saved_step is not None
                    and compiled.saved_step.id is not None
                ),
            )
        progress.flow_updated = True
        progress.emit(FlowDraftMaterializationStage.FLOW_UPDATED)

        await flow_service.replace_resource_bindings(
            flow_id=flow_id,
            bindings=resource_bindings,
            source=binding_source,
        )

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
            steps_removed=len(changeset.removed_existing_step_refs),
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
            fields=ALL_ASSISTANT_FIELDS,
            new_assistant=True,
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
            fields=assistant_to_update.fields,
            new_assistant=False,
        )

    return resource_bindings_by_slot_ref


def build_flow_steps(
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
        # A retained step is its saved row with the authored columns laid over
        # it: its id and every column the spec has no field for stay, so the
        # repository patches the row instead of replacing it.
        saved = {} if compiled.saved_step is None else compiled.saved_step.model_dump()
        final_steps.append(
            FlowStep.model_validate(
                {
                    **saved,
                    "assistant_id": assistant_id,
                    "step_order": compiled.step_order,
                    "user_description": compiled.user_description,
                    "input_source": compiled.input_source,
                    "input_type": compiled.input_type,
                    "output_mode": compiled.output_mode,
                    "output_type": compiled.output_type,
                    "input_bindings": compiled.input_bindings,
                    "input_contract": compiled.input_contract,
                    "output_contract": compiled.output_contract,
                    "input_config": compiled.input_config,
                    "output_config": compiled.output_config,
                    "review_policy": compiled.review_policy,
                }
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


async def _configure_assistant(
    *,
    flow_service: FlowService,
    flow_id: UUID,
    assistant_id: UUID,
    assistant_spec: AssistantSpec,
    requires_completion_model_for_step: bool,
    resource_bindings_by_slot_ref: Mapping[str, LocalResourceBinding],
    fields: frozenset[AssistantField],
    new_assistant: bool,
    prompt_alias_renumbering: Mapping[int, int],
    stored_prompt: StoredAssistantPrompt | None,
) -> bool:
    """Write `fields` of the assistant and nothing else: a field the update
    does not name is not in the command, so the assistant keeps it. A new
    assistant is given every field and is configured in full. A prompt is
    written with the description of the one the assistant held when the apply
    began (`stored_prompt`). When the update does not write `instructions` but
    steps moved, that stored prompt is written with the aliases of moved steps
    renumbered, and only when that changes it. Returns whether the assistant
    was written."""

    command_fields: dict[str, object] = {}
    if "instructions" in fields:
        # A prompt is written whole: the stored description goes with it.
        command_fields["prompt"] = PromptCreate(
            text=assistant_spec.instructions,
            description=None if stored_prompt is None else stored_prompt.description,
        )
    elif prompt_alias_renumbering and stored_prompt is not None:
        renumbered = renumber_step_aliases(stored_prompt.text, prompt_alias_renumbering)
        if renumbered != stored_prompt.text:
            # A prompt is written whole: the description goes with it as stored.
            command_fields["prompt"] = PromptCreate(
                text=renumbered, description=stored_prompt.description
            )
    command_fields.update(
        _resolve_assistant_resource_update_fields(
            assistant_spec=assistant_spec,
            requires_completion_model_for_step=requires_completion_model_for_step,
            resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
            fields=fields,
            new_assistant=new_assistant,
        )
    )
    if not command_fields:
        return False

    # The steps are saved after the assistants, by update_flow in the same
    # transaction, which judges the classification of the flow as saved: a
    # prompt written for the new step positions is judged against them.
    await flow_service.update_flow_assistant(
        flow_id=flow_id,
        assistant_id=assistant_id,
        update=AssistantUpdateCommand.model_validate(command_fields),
        classification_judged_by_flow_update=True,
    )
    return True


async def _stored_prompts(
    *,
    flow_service: FlowService,
    flow_id: UUID,
    assistants_to_update: Sequence[FlowDraftAssistantToUpdate],
) -> dict[UUID, StoredAssistantPrompt]:
    """The prompts the assistants hold now, as stored and read once, for the
    updates that write a prompt: the plan's instructions keep the stored
    description, and a renumbered prompt is the stored one. Empty when no
    update writes a prompt."""

    if not any(
        "instructions" in update.fields or update.prompt_alias_renumbering
        for update in assistants_to_update
    ):
        return {}
    return await flow_service.get_flow_assistant_prompts(
        await flow_service.get_flow(flow_id)
    )


def _resolve_assistant_resource_update_fields(
    *,
    assistant_spec: AssistantSpec,
    requires_completion_model_for_step: bool,
    resource_bindings_by_slot_ref: Mapping[str, LocalResourceBinding],
    fields: frozenset[AssistantField],
    new_assistant: bool,
) -> dict[str, object]:
    command_fields: dict[str, object] = {}
    if new_assistant:
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
    elif "model_ref" in fields:
        # An edit never picks another model for a step; the one change to a
        # model is that a step turned into one that runs no completion model
        # has none. Anything else named here could not be carried out.
        if requires_completion_model_for_step:
            raise BadRequestException(
                "An edit does not choose the model of a step that runs one; "
                "change it in the step's model picker."
            )
        command_fields["completion_model_id"] = None

    if "knowledge_refs" in fields:
        groups, websites, integration_knowledge_ids = _resolve_knowledge_refs(
            knowledge_refs=assistant_spec.knowledge_refs,
            resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
        )
        command_fields["groups"] = groups
        # A new assistant is configured in full. An existing one is listed only
        # by collections in the spec: a website or integration knowledge it has
        # is not in it, and absence is not a request to clear, so they are
        # written only when the spec names some.
        if new_assistant or websites:
            command_fields["websites"] = websites
        if new_assistant or integration_knowledge_ids:
            command_fields["integration_knowledge_ids"] = integration_knowledge_ids

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
    existing_flows = await flow_service.list_flows(
        space_ids=[space_id], draft_space_ids=[space_id]
    )
    existing_names = {flow.name for flow in existing_flows}

    if desired_name not in existing_names:
        return desired_name

    base = re.sub(r"\s*\(\d+\)$", "", desired_name)
    for index in range(2, 100):
        candidate = f"{base} ({index})"
        if candidate not in existing_names:
            return candidate

    return f"{base} ({uuid4().hex[:8]})"
