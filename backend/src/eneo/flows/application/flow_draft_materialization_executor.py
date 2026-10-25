from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, assert_never
from uuid import UUID, uuid4

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.flows.application.flow_authoring_refusal import (
    FlowAuthoringRefusalCode,
    FlowAuthoringRefusalException,
)
from eneo.flows.application.flow_draft_materialization import (
    FlowDraftChangeSet,
    FlowDraftCompiledStep,
    FlowDraftMaterializationResult,
)
from eneo.flows.application.flow_service import FlowService
from eneo.flows.application.flow_template_import_materialization import (
    materialize_template_imports,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_name import flow_name_family, normalize_flow_name
from eneo.flows.flow_authoring_spec import AssistantSpec
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
from eneo.flows.infrastructure.flow_repo import DraftRevisionReservation
from eneo.main.exceptions import BadRequestException
from eneo.prompts.api.prompt_models import PromptCreate

if TYPE_CHECKING:
    from eneo.flows.application.flow_authoring_command import TemplateImportIntent
    from eneo.flows.flow_template_asset_service import FlowTemplateAssetService

_MODEL_LOCAL_KINDS = frozenset({LocalResourceKind.COMPLETION_MODEL})


class FlowDraftMaterializer:
    """Creates the draft flow a compiled FlowDraftChangeSet describes."""

    async def execute(
        self,
        *,
        changeset: FlowDraftChangeSet,
        flow_service: FlowService,
        space_id: UUID,
        resource_bindings: tuple[LocalResourceBinding, ...] = tuple(),
        binding_source: FlowResourceBindingSource,
        template_asset_service: "FlowTemplateAssetService | None" = None,
        template_imports: tuple[TemplateImportIntent, ...] = (),
    ) -> FlowDraftMaterializationResult:
        if template_imports and template_asset_service is None:
            raise RuntimeError(
                "Template import materialization requires a template asset service."
            )

        resource_bindings_by_slot_ref = index_and_validate_changeset_resource_bindings(
            changeset=changeset,
            resource_bindings=resource_bindings,
        )

        ref_to_assistant_id: dict[str, UUID] = {}
        completion_required_by_plan_ref = _completion_required_by_plan_ref(
            changeset.compiled_steps
        )
        flow_name = await _deduplicate_flow_name(
            flow_service=flow_service,
            space_id=space_id,
            desired_name=changeset.flow_name,
        )
        created_flow = await flow_service.create_flow(
            space_id=space_id,
            name=flow_name,
            description=changeset.flow_description,
            metadata_json=changeset.metadata_json,
        )
        flow_id = created_flow.require_persisted_id()

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

        # The flow row is locked ahead of its assistants, the order every
        # writer of both follows.
        reservation = await flow_service.reserve_draft_revision(
            flow_id=flow_id, expected_revision=None
        )

        for assistant_to_create in changeset.assistants_to_create:
            assistant, _ = await flow_service.create_flow_assistant(
                flow_id=flow_id,
                name=assistant_to_create.plan_step_ref,
            )
            ref_to_assistant_id[assistant_to_create.plan_step_ref] = assistant.id
            await _configure_assistant(
                flow_service=flow_service,
                reservation=reservation,
                assistant_id=assistant.id,
                assistant_spec=assistant_to_create.assistant_spec,
                requires_completion_model_for_step=_completion_required_for_plan_ref(
                    plan_step_ref=assistant_to_create.plan_step_ref,
                    completion_required_by_plan_ref=completion_required_by_plan_ref,
                ),
                resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
            )

        materialized_flow = await flow_service.update_flow(
            flow_id=flow_id,
            steps=build_flow_steps(
                compiled_steps=changeset.compiled_steps,
                ref_to_assistant_id=ref_to_assistant_id,
            ),
            expected_revision=reservation.revision,
        )
        await flow_service.replace_resource_bindings(
            flow_id=flow_id,
            bindings=resource_bindings,
            source=binding_source,
        )

        return FlowDraftMaterializationResult(
            flow_id=flow_id,
            flow_name=flow_name,
            draft_revision=materialized_flow.draft_revision,
            steps_created=len(changeset.compiled_steps),
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
    for assistant_to_create in changeset.assistants_to_create:
        _resolve_assistant_resource_update_fields(
            assistant_spec=assistant_to_create.assistant_spec,
            requires_completion_model_for_step=_completion_required_for_plan_ref(
                plan_step_ref=assistant_to_create.plan_step_ref,
                completion_required_by_plan_ref=completion_required_by_plan_ref,
            ),
            resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
        )
    return resource_bindings_by_slot_ref


def build_flow_steps(
    *,
    compiled_steps: list[FlowDraftCompiledStep],
    ref_to_assistant_id: Mapping[str, UUID],
) -> list[FlowStep]:
    final_steps: list[FlowStep] = []
    for compiled in compiled_steps:
        assistant_id = ref_to_assistant_id.get(compiled.plan_step_ref)
        if assistant_id is None:
            raise BadRequestException(
                "Assistant id missing while building materialized flow steps.",
                context={"plan_step_ref": compiled.plan_step_ref},
            )
        final_steps.append(
            FlowStep.model_validate(
                {
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


async def _configure_assistant(
    *,
    flow_service: FlowService,
    reservation: DraftRevisionReservation,
    assistant_id: UUID,
    assistant_spec: AssistantSpec,
    requires_completion_model_for_step: bool,
    resource_bindings_by_slot_ref: Mapping[str, LocalResourceBinding],
) -> None:
    """Configure a new step assistant in full: its prompt, model and
    knowledge."""

    command_fields: dict[str, object] = {
        "prompt": PromptCreate(text=assistant_spec.instructions, description=None),
        **_resolve_assistant_resource_update_fields(
            assistant_spec=assistant_spec,
            requires_completion_model_for_step=requires_completion_model_for_step,
            resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
        ),
    }
    # The steps are saved after the assistants, by update_flow in the same
    # transaction, which judges the classification of the flow as saved. That
    # save also advances the draft revision, once for the whole apply.
    await flow_service.update_reserved_flow_assistant(
        reservation=reservation,
        assistant_id=assistant_id,
        update=AssistantUpdateCommand.model_validate(command_fields),
        classification_judged_by_flow_update=True,
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
            invalid_code=FlowAuthoringRefusalCode.INVALID_MODEL_REF,
            invalid_message=f"Invalid model reference '{assistant_spec.model_ref}'.",
            invalid_context={"model_ref": assistant_spec.model_ref},
        )
    groups, websites, integration_knowledge_ids = _resolve_knowledge_refs(
        knowledge_refs=assistant_spec.knowledge_refs,
        resource_bindings_by_slot_ref=resource_bindings_by_slot_ref,
    )
    command_fields["groups"] = groups
    command_fields["websites"] = websites
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
            invalid_code=FlowAuthoringRefusalCode.INVALID_KB_REF,
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
    invalid_code: FlowAuthoringRefusalCode,
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
    invalid_code: FlowAuthoringRefusalCode,
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
        if exc.reason is FlowResourceBindingResolutionReason.INVALID_SLOT_REF:
            raise FlowAuthoringRefusalException(
                invalid_message, code=invalid_code, context=invalid_context
            ) from exc
        raise _slot_binding_bad_request(exc) from exc


def _slot_binding_bad_request(
    error: FlowResourceBindingResolutionError,
) -> BadRequestException:
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

    base = flow_name_family(desired_name)
    for index in range(2, 100):
        candidate = f"{base} ({index})"
        if candidate not in existing_names:
            return candidate

    return f"{base} ({uuid4().hex[:8]})"
