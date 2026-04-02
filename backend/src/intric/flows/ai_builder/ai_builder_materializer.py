"""Materializer for the AI Flow Builder.

Split into two layers:
1. Pure Compiler (compile_changeset) — no side effects, fully testable
2. Executor (execute_changeset) — creates/updates/deletes assistants + calls FlowService

The compiler diffs a FlowDraftSpecCore against the current flow state and produces
a FlowChangeSet. The executor consumes the changeset and performs all mutations
in a single logical transaction.
"""

from __future__ import annotations

from datetime import datetime
import logging
import re
from typing import Any
from uuid import UUID, uuid4

from intric.flows.ai_builder.ai_builder_description_semantics import (
    DescriptionProvenance,
    FlowSemanticSignature,
    _description_hash,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    FlowInputSource,
    FlowInputType,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    FlowOutputMode,
)
from intric.flows.ai_builder.ai_builder_models import (
    ApplyResultResponse,
    AssistantSpec,
    AssistantToCreate,
    AssistantToDelete,
    AssistantToUpdate,
    CompiledStep,
    FlowChangeSet,
    FlowDraftSpecCore,
    StepChangeKind,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_flow_name import normalize_flow_name
from intric.flows.ai_builder.ai_builder_runtime_input_defaults import (
    resolve_runtime_input_config,
)
from intric.flows.ai_builder.ai_builder_reference_rewriter import (
    build_ref_to_order,
    rewrite_step_spec_variables,
)
from intric.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
)
from intric.flows.ai_builder.ai_builder_transcription_defaults import (
    apply_audio_transcription_defaults,
)
from intric.flows.domain.flow import Flow, FlowStep
from intric.main.exceptions import BadRequestException
from intric.prompts.api.prompt_models import PromptCreate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure Compiler
# ---------------------------------------------------------------------------


def compile_changeset(
    spec: FlowDraftSpecCore,
    current_flow: Flow | None,
    *,
    default_transcription_model_id: UUID | None = None,
    description_override_manual: bool = False,
    ai_builder_origin: dict[str, Any] | None = None,
) -> FlowChangeSet:
    """Compile a FlowDraftSpecCore into a FlowChangeSet.

    Pure function — no side effects, no DB calls.

    Args:
        spec: The AI-generated flow specification.
        current_flow: The existing flow (None for create mode).

    Returns:
        A FlowChangeSet describing all mutations needed.
    """
    spec, _ = normalize_ai_builder_spec(spec)

    # Build mapping: existing_step_ref → existing FlowStep
    existing_by_ref: dict[str, FlowStep] = {}
    if current_flow:
        for step in current_flow.steps:
            ref = f"existing_step_{step.step_order}"
            existing_by_ref[ref] = step

    # Build plan_step_ref → step_order mapping (1-based, derived from spec order)
    ref_to_order = build_ref_to_order(spec.steps)

    # Track which existing steps are referenced by the spec
    referenced_existing_refs: set[str] = set()

    assistants_to_create: list[AssistantToCreate] = []
    assistants_to_update: list[AssistantToUpdate] = []
    compiled_steps: list[CompiledStep] = []

    for idx, step_spec in enumerate(spec.steps):
        step_order = idx + 1
        existing_step = _resolve_existing_step(step_spec, existing_by_ref)

        if existing_step is not None:
            # Existing step found → MODIFIED
            referenced_existing_refs.add(step_spec.existing_step_ref)  # type: ignore[arg-type]
            rewritten_spec = rewrite_step_spec_variables(step_spec, ref_to_order)

            assistants_to_update.append(
                AssistantToUpdate(
                    existing_step_id=existing_step.id,  # type: ignore[arg-type]
                    existing_assistant_id=existing_step.assistant_id,
                    assistant_spec=rewritten_spec.assistant_spec,
                )
            )
            compiled_steps.append(
                _compile_modified_step(
                    step_spec=rewritten_spec,
                    existing_step=existing_step,
                    step_order=step_order,
                )
            )
        else:
            # New step → ADDED
            rewritten_spec = rewrite_step_spec_variables(step_spec, ref_to_order)

            assistants_to_create.append(
                AssistantToCreate(
                    plan_step_ref=step_spec.plan_step_ref,
                    assistant_spec=rewritten_spec.assistant_spec,
                )
            )
            compiled_steps.append(
                _compile_new_step(
                    step_spec=rewritten_spec,
                    step_order=step_order,
                )
            )

    # Find removed steps (in existing flow but not referenced in spec)
    assistants_to_delete: list[AssistantToDelete] = []
    if current_flow:
        for ref, existing_step in existing_by_ref.items():
            if ref not in referenced_existing_refs:
                assistants_to_delete.append(
                    AssistantToDelete(
                        step_id=existing_step.id,  # type: ignore[arg-type]
                        assistant_id=existing_step.assistant_id,
                    )
                )

    resolved_description = _resolve_changeset_flow_description(
        spec=spec,
        current_flow=current_flow,
        description_override_manual=description_override_manual,
    )
    effective_spec = (
        spec
        if resolved_description == spec.flow_description
        else spec.model_copy(update={"flow_description": resolved_description})
    )

    # Build metadata_json
    metadata_json = _build_metadata_json(
        effective_spec,
        current_flow,
        default_transcription_model_id=default_transcription_model_id,
        description_override_manual=description_override_manual,
        ai_builder_origin=ai_builder_origin,
    )

    return FlowChangeSet(
        flow_name=effective_spec.flow_name,
        flow_description=effective_spec.flow_description,
        description_override_manual=description_override_manual,
        assistants_to_create=assistants_to_create,
        assistants_to_update=assistants_to_update,
        assistants_to_delete=assistants_to_delete,
        compiled_steps=compiled_steps,
        metadata_json=metadata_json,
    )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


async def execute_changeset(
    *,
    changeset: FlowChangeSet,
    flow_service: Any,
    space_id: UUID,
    flow_id: UUID | None,
    expected_revision: int | None = None,
) -> ApplyResultResponse:
    """Execute a FlowChangeSet — all mutations in one logical pass.

    1. Create new flow-managed assistants → get real IDs
    2. Configure all assistants (prompt, model, knowledge bases)
    3. Update existing assistants
    4. Remap placeholder IDs → real IDs in compiled steps
    5. Create or update the flow with final steps
    6. Delete removed assistants

    Args:
        changeset: The compiled changeset.
        flow_service: FlowService instance.
        space_id: Space to create flow/assistants in.
        flow_id: Existing flow ID (None for create mode).

    Returns:
        ApplyResultResponse with counts and flow_id.
    """
    is_create = flow_id is None
    created_flow_id: UUID | None = None

    try:
        # Step 1: Create new assistants and collect ref → real_id mapping
        ref_to_assistant_id: dict[str, UUID] = {}

        if is_create:
            # For create mode, we need a temporary flow to own the assistants.
            # Create the flow first with empty steps, then update with real steps.
            unique_name = await _deduplicate_flow_name(
                flow_service=flow_service,
                space_id=space_id,
                desired_name=changeset.flow_name,
            )
            temp_flow = await flow_service.create_flow(
                space_id=space_id,
                name=unique_name,
                description=changeset.flow_description,
                steps=[],
                metadata_json=changeset.metadata_json,
            )
            flow_id = temp_flow.id
            created_flow_id = flow_id
            # Update changeset flow_name so the returned result reflects the actual name
            changeset = FlowChangeSet(
                flow_name=unique_name,
                flow_description=changeset.flow_description,
                description_override_manual=changeset.description_override_manual,
                assistants_to_create=changeset.assistants_to_create,
                assistants_to_update=changeset.assistants_to_update,
                assistants_to_delete=changeset.assistants_to_delete,
                compiled_steps=changeset.compiled_steps,
                metadata_json=changeset.metadata_json,
            )
        if flow_id is None:
            raise BadRequestException("Flow id missing while executing AI builder changeset.")

        for assistant_to_create in changeset.assistants_to_create:
            assistant, _ = await flow_service.create_flow_assistant(
                flow_id=flow_id,
                name=assistant_to_create.plan_step_ref,
            )
            ref_to_assistant_id[assistant_to_create.plan_step_ref] = assistant.id

            # Configure the assistant with prompt, model, knowledge bases
            await _configure_assistant(
                flow_service=flow_service,
                flow_id=flow_id,
                assistant_id=assistant.id,
                assistant_spec=assistant_to_create.assistant_spec,
            )

        # Step 2: Update existing assistants
        for assistant_to_update in changeset.assistants_to_update:
            if assistant_to_update.existing_assistant_id is None:
                raise BadRequestException(
                    "Existing assistant id missing while applying AI builder changeset."
                )
            await _configure_assistant(
                flow_service=flow_service,
                flow_id=flow_id,
                assistant_id=assistant_to_update.existing_assistant_id,
                assistant_spec=assistant_to_update.assistant_spec,
            )

        # Step 3: Build final FlowStep list with real assistant IDs
        final_steps: list[FlowStep] = []
        for compiled in changeset.compiled_steps:
            assistant_id = compiled.assistant_id
            if assistant_id is None:
                # New step — look up the real ID from the creation mapping
                assistant_id = ref_to_assistant_id[compiled.plan_step_ref]

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
                )
            )

        # Step 4: Update the flow with final steps
        if is_create:
            # Update the temp flow with real steps
            await flow_service.update_flow(
                flow_id=flow_id,
                steps=final_steps,
            )
        else:
            await flow_service.update_flow(
                flow_id=flow_id,
                name=changeset.flow_name,
                description=changeset.flow_description,
                steps=final_steps,
                metadata_json=changeset.metadata_json,
                expected_revision=expected_revision,
            )

        # Step 5: Delete removed assistants (after flow update removed references)
        for assistant_to_delete in changeset.assistants_to_delete:
            await flow_service.delete_flow_assistant(
                flow_id=flow_id,
                assistant_id=assistant_to_delete.assistant_id,
            )

        # Count changes
        steps_created = sum(
            1 for s in changeset.compiled_steps if s.change_kind == StepChangeKind.ADDED
        )
        steps_updated = sum(
            1 for s in changeset.compiled_steps if s.change_kind == StepChangeKind.MODIFIED
        )
        steps_removed = len(changeset.assistants_to_delete)

        return ApplyResultResponse(
            flow_id=flow_id,  # type: ignore[arg-type]
            flow_name=changeset.flow_name,
            steps_created=steps_created,
            steps_updated=steps_updated,
            steps_removed=steps_removed,
        )
    except Exception:
        if is_create and created_flow_id is not None:
            try:
                await flow_service.delete_flow(created_flow_id)
            except Exception as cleanup_error:
                logger.warning(
                    "Failed to clean up temporary AI builder flow after apply error",
                    exc_info=cleanup_error,
                    extra={"flow_id": str(created_flow_id), "space_id": str(space_id)},
                )
        raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_existing_step(
    step_spec: StepSpec,
    existing_by_ref: dict[str, FlowStep],
) -> FlowStep | None:
    """Resolve a step spec's existing_step_ref to the actual FlowStep.

    Raises BadRequestException if existing_step_ref is set but doesn't match any
    existing step — this prevents the LLM from silently converting an
    intended modification into a new step creation.
    """
    if step_spec.existing_step_ref is None:
        return None
    resolved = existing_by_ref.get(step_spec.existing_step_ref)
    if resolved is None:
        valid_refs = sorted(existing_by_ref.keys())
        raise BadRequestException(
            (
                f"existing_step_ref '{step_spec.existing_step_ref}' does not match "
                f"any existing step. Valid refs: {valid_refs}"
            ),
            code="invalid_existing_step_ref",
            context={
                "existing_step_ref": step_spec.existing_step_ref,
                "valid_refs": valid_refs,
            },
        )
    return resolved


def _compile_new_step(
    *,
    step_spec: StepSpec,
    step_order: int,
) -> CompiledStep:
    """Compile a new step spec into a CompiledStep."""
    return CompiledStep(
        plan_step_ref=step_spec.plan_step_ref,
        change_kind=StepChangeKind.ADDED,
        step_order=step_order,
        user_description=step_spec.name,
        assistant_id=None,
        input_source=FlowInputSource(step_spec.input_source.value),
        input_type=FlowInputType(step_spec.input_type.value),
        output_mode=FlowOutputMode(step_spec.output_mode.value),
        output_type=OutputType(step_spec.output_type.value),
        mcp_policy=MCPPolicy(step_spec.mcp_policy.value),
        input_bindings=step_spec.input_bindings,
        input_contract=step_spec.input_contract,
        output_contract=step_spec.output_contract,
        input_config=resolve_runtime_input_config(step_spec=step_spec),
        output_config=step_spec.output_config,
    )


def _compile_modified_step(
    *,
    step_spec: StepSpec,
    existing_step: FlowStep,
    step_order: int,
) -> CompiledStep:
    """Compile a modified step, preserving unspecified fields from the existing step."""
    return CompiledStep(
        plan_step_ref=step_spec.plan_step_ref,
        change_kind=StepChangeKind.MODIFIED,
        step_order=step_order,
        user_description=step_spec.name,
        assistant_id=existing_step.assistant_id,
        input_source=FlowInputSource(step_spec.input_source.value),
        input_type=FlowInputType(step_spec.input_type.value),
        output_mode=FlowOutputMode(step_spec.output_mode.value),
        output_type=OutputType(step_spec.output_type.value),
        mcp_policy=MCPPolicy(step_spec.mcp_policy.value),
        input_bindings=step_spec.input_bindings,
        input_contract=step_spec.input_contract,
        output_contract=step_spec.output_contract,
        input_config=resolve_runtime_input_config(
            step_spec=step_spec,
            existing_input_config=existing_step.input_config,
        ),
        output_config=_resolve_output_config(step_spec, existing_step),
    )


def _resolve_output_config(
    step_spec: StepSpec,
    existing_step: FlowStep,
) -> dict[str, Any] | None:
    """Resolve output_config for a modified step.

    If the spec provides output_config, use it. Otherwise, preserve the existing
    config only if output_mode hasn't changed — a mode change invalidates the old config.
    """
    preserved_output_config = step_spec.output_config
    if preserved_output_config is None and step_spec.output_mode.value == existing_step.output_mode:
        preserved_output_config = existing_step.output_config

    effective_step, _ = normalize_ai_builder_spec(
        FlowDraftSpecCore(
            flow_name="normalized-output-config",
            steps=[step_spec.model_copy(update={"output_config": preserved_output_config})],
        )
    )
    return effective_step.steps[0].output_config


def _build_metadata_json(
    spec: FlowDraftSpecCore,
    current_flow: Flow | None,
    *,
    default_transcription_model_id: UUID | None = None,
    description_override_manual: bool = False,
    ai_builder_origin: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build metadata_json from spec form_fields, preserving existing metadata."""
    # Start with existing metadata or empty dict
    metadata: dict[str, Any] = {}
    if current_flow and current_flow.metadata_json:
        metadata = dict(current_flow.metadata_json)

    # If spec has form_fields, build form_schema
    if spec.form_fields is not None:
        fields = []
        for field in spec.form_fields:
            field_dict: dict[str, Any] = {
                "name": field.name,
                "type": field.type,
                "label": field.label,
                "required": field.required,
            }
            if field.options is not None:
                field_dict["options"] = field.options
            fields.append(field_dict)
        metadata["form_schema"] = {"fields": fields}

    metadata = apply_audio_transcription_defaults(
        metadata=metadata if metadata else None,
        spec=spec,
        default_transcription_model_id=default_transcription_model_id,
    ) or {}

    # Stamp description provenance
    metadata = _stamp_description_provenance(
        metadata=metadata,
        spec=spec,
        description_override_manual=description_override_manual,
    )
    metadata = _stamp_ai_builder_origin(
        metadata=metadata,
        ai_builder_origin=ai_builder_origin,
    )

    return metadata if metadata else None


def _stamp_description_provenance(
    *,
    metadata: dict[str, Any] | None,
    spec: FlowDraftSpecCore,
    description_override_manual: bool,
) -> dict[str, Any]:
    """Stamp ai_builder.description provenance into metadata."""
    result = dict(metadata or {})
    ai_builder = dict(result.get("ai_builder", {}))

    if description_override_manual:
        provenance = DescriptionProvenance(mode="manual")
    else:
        sig = FlowSemanticSignature.from_steps(spec.steps)
        provenance = DescriptionProvenance(
            mode="builder_managed",
            semantic_signature=sig,
            last_generated_hash=_description_hash(spec.flow_description),
        )

    ai_builder["description"] = provenance.model_dump(mode="json")
    result["ai_builder"] = ai_builder
    return result


def _stamp_ai_builder_origin(
    *,
    metadata: dict[str, Any] | None,
    ai_builder_origin: dict[str, Any] | None,
) -> dict[str, Any]:
    result = dict(metadata or {})
    if not ai_builder_origin:
        return result

    normalized_origin = {
        str(key): _normalize_ai_builder_origin_value(value)
        for key, value in ai_builder_origin.items()
        if value is not None
    }
    if not normalized_origin:
        return result

    ai_builder = dict(result.get("ai_builder", {}))
    ai_builder["origin"] = normalized_origin
    result["ai_builder"] = ai_builder
    return result


def _normalize_ai_builder_origin_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    value_attr = getattr(value, "value", None)
    if value_attr is not None and not callable(value_attr):
        return value_attr
    return value


def _resolve_changeset_flow_description(
    *,
    spec: FlowDraftSpecCore,
    current_flow: Flow | None,
    description_override_manual: bool,
) -> str:
    if current_flow is None or description_override_manual:
        return spec.flow_description

    current_description = current_flow.description or ""
    if spec.flow_description != current_description:
        return spec.flow_description

    try:
        old_sig = FlowSemanticSignature.from_steps(_flow_steps_to_step_specs(current_flow.steps))
    except ValueError:
        # Existing flows may contain supported runtime enums outside the AI Builder
        # subset. Keep the current description rather than failing apply-time
        # description rewriting for those legacy/manual flows.
        return spec.flow_description
    new_sig = FlowSemanticSignature.from_steps(spec.steps)
    if old_sig == new_sig:
        return spec.flow_description

    return _rewrite_terminal_output_phrase(
        description=current_description,
        old_output_type=old_sig.terminal_output_type,
        new_output_type=new_sig.terminal_output_type,
    )


def _flow_steps_to_step_specs(steps: list[FlowStep]) -> list[StepSpec]:
    return [
        StepSpec(
            plan_step_ref=f"existing_step_{step.step_order}",
            name=step.user_description or f"Step {step.step_order}",
            assistant_spec=AssistantSpec(instructions=""),
            input_source=InputSource(step.input_source.value),
            input_type=InputType(step.input_type.value),
            output_mode=OutputMode(step.output_mode.value),
            output_type=OutputType(step.output_type.value),
            input_bindings=step.input_bindings,
            input_contract=step.input_contract,
            output_contract=step.output_contract,
            input_config=step.input_config,
            output_config=step.output_config,
            mcp_policy=step.mcp_policy,
        )
        for step in steps
    ]


def _rewrite_terminal_output_phrase(
    *,
    description: str,
    old_output_type: str | None,
    new_output_type: str | None,
) -> str:
    output_labels = {
        "text": "text",
        "docx": "DOCX",
        "pdf": "PDF",
        "json": "JSON",
    }
    old_label = output_labels.get(old_output_type or "")
    new_label = output_labels.get(new_output_type or "")
    if old_label is None or new_label is None or old_label == new_label:
        return description

    format_pattern = re.compile(
        rf"\bi\s+{re.escape(old_label)}-?format\b",
        flags=re.IGNORECASE,
    )
    if format_pattern.search(description):
        return format_pattern.sub(f"i {new_label}-format", description)
    return description


async def _configure_assistant(
    *,
    flow_service: Any,
    flow_id: UUID,
    assistant_id: UUID,
    assistant_spec: AssistantSpec,
) -> None:
    """Configure a flow-managed assistant with prompt, model, and knowledge bases."""
    kwargs: dict[str, Any] = {
        "flow_id": flow_id,
        "assistant_id": assistant_id,
        "prompt": PromptCreate(text=assistant_spec.instructions),
    }

    if assistant_spec.model_ref is not None:
        try:
            kwargs["completion_model_id"] = UUID(assistant_spec.model_ref)
        except (ValueError, AttributeError) as exc:
            raise BadRequestException(
                f"Invalid model reference '{assistant_spec.model_ref}'.",
                code="invalid_model_ref",
                context={"model_ref": assistant_spec.model_ref},
            ) from exc

    if assistant_spec.knowledge_refs:
        try:
            kwargs["groups"] = [UUID(ref) for ref in assistant_spec.knowledge_refs]
        except (ValueError, AttributeError) as exc:
            invalid_ref = next(
                (
                    ref
                    for ref in assistant_spec.knowledge_refs
                    if not _looks_like_uuid(ref)
                ),
                assistant_spec.knowledge_refs[0],
            )
            raise BadRequestException(
                f"Invalid knowledge base reference '{invalid_ref}'.",
                code="invalid_kb_ref",
                context={"knowledge_refs": assistant_spec.knowledge_refs},
            ) from exc

    await flow_service.update_flow_assistant(**kwargs)


def _looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


async def _deduplicate_flow_name(
    *,
    flow_service: Any,
    space_id: UUID,
    desired_name: str,
) -> str:
    """Return a unique flow name for the space.

    If ``desired_name`` already exists, appends " (2)", " (3)", etc.
    """
    desired_name = normalize_flow_name(desired_name)
    existing_flows = await flow_service.list_flows(space_id=space_id, sparse=True)
    existing_names: set[str] = {f.name for f in existing_flows}

    if desired_name not in existing_names:
        return desired_name

    # Strip any existing " (N)" suffix from desired_name before generating candidates
    base = re.sub(r"\s*\(\d+\)$", "", desired_name)
    for i in range(2, 100):
        candidate = f"{base} ({i})"
        if candidate not in existing_names:
            return candidate

    # Extremely unlikely fallback
    return f"{base} ({uuid4().hex[:8]})"
