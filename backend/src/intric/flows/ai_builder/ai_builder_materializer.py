"""AI Builder-specific adapter around shared Flow draft materialization."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable
from uuid import UUID

from intric.flows.ai_builder.ai_builder_description_semantics import (
    DescriptionProvenance,
    FlowSemanticSignature,
    description_hash,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from intric.flows.ai_builder.ai_builder_models import (
    ApplyResultResponse,
    AssistantSpec,
    FlowChangeSet,
    FlowDraftSpecCore,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    MaterializerProgressSnapshot,
)
from intric.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
)
from intric.flows.application.flow_draft_materialization import (
    FlowDraftMaterializationProgress,
    compile_flow_draft_changeset,
    preserve_modified_step_output_config,
)
from intric.flows.application.flow_draft_materialization_executor import (
    FlowDraftMaterializer,
)
from intric.flows.domain.flow import Flow, FlowStep
from intric.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
)

if TYPE_CHECKING:
    from intric.flows.application.flow_service import FlowService


def compile_changeset(
    spec: FlowDraftSpecCore,
    current_flow: Flow | None,
    *,
    default_transcription_model_id: UUID | None = None,
    description_override_manual: bool = False,
    ai_builder_origin: dict[str, Any] | None = None,
) -> FlowChangeSet:
    spec = _prepare_ai_builder_compile_spec(spec=spec, current_flow=current_flow)
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

    draft_changeset = compile_flow_draft_changeset(
        effective_spec,
        current_flow,
        default_transcription_model_id=default_transcription_model_id,
    )
    metadata_json = _stamp_description_provenance(
        metadata=draft_changeset.metadata_json,
        spec=effective_spec,
        description_override_manual=description_override_manual,
    )
    metadata_json = _stamp_ai_builder_origin(
        metadata=metadata_json,
        ai_builder_origin=ai_builder_origin,
    )

    return FlowChangeSet(
        flow_name=draft_changeset.flow_name,
        flow_description=draft_changeset.flow_description,
        description_override_manual=description_override_manual,
        assistants_to_create=draft_changeset.assistants_to_create,
        assistants_to_update=draft_changeset.assistants_to_update,
        assistants_to_delete=draft_changeset.assistants_to_delete,
        compiled_steps=draft_changeset.compiled_steps,
        metadata_json=metadata_json,
    )


async def execute_changeset(
    *,
    changeset: FlowChangeSet,
    flow_service: "FlowService",
    space_id: UUID,
    flow_id: UUID | None,
    expected_revision: int | None = None,
    resource_bindings: tuple[LocalResourceBinding, ...] = tuple(),
    progress_callback: Callable[[MaterializerProgressSnapshot], None] | None = None,
) -> ApplyResultResponse:
    def emit_progress(progress: FlowDraftMaterializationProgress) -> None:
        if progress_callback is None:
            return
        progress_callback(
            MaterializerProgressSnapshot(
                stage=progress.stage.value,
                assistants_created=progress.assistants_created,
                assistants_configured=progress.assistants_configured,
                assistants_updated=progress.assistants_updated,
                assistants_deleted=progress.assistants_deleted,
                flow_created=progress.flow_created,
                flow_updated=progress.flow_updated,
            )
        )

    result = await FlowDraftMaterializer().execute(
        changeset=changeset,
        flow_service=flow_service,
        space_id=space_id,
        flow_id=flow_id,
        expected_revision=expected_revision,
        resource_bindings=resource_bindings,
        binding_source=FlowResourceBindingSource.AI_BUILDER,
        progress_callback=emit_progress,
    )
    return ApplyResultResponse(
        flow_id=result.flow_id,
        flow_name=result.flow_name,
        steps_created=result.steps_created,
        steps_updated=result.steps_updated,
        steps_removed=result.steps_removed,
    )


def _prepare_ai_builder_compile_spec(
    *,
    spec: FlowDraftSpecCore,
    current_flow: Flow | None,
) -> FlowDraftSpecCore:
    normalized_spec, _ = normalize_ai_builder_spec(spec)
    if current_flow is None:
        return normalized_spec

    existing_by_ref = {
        f"existing_step_{step.step_order}": step for step in current_flow.steps
    }
    updated_steps: list[StepSpec] = []
    changed = False
    for step in normalized_spec.steps:
        existing_step = (
            existing_by_ref.get(step.existing_step_ref)
            if step.existing_step_ref is not None
            else None
        )
        updated_step = (
            preserve_modified_step_output_config(
                step_spec=step,
                existing_step=existing_step,
            )
            if existing_step is not None
            else step
        )
        changed = changed or updated_step is not step
        updated_steps.append(updated_step)

    if not changed:
        return normalized_spec
    output_config_spec = normalized_spec.model_copy(update={"steps": updated_steps})
    output_config_spec, _ = normalize_ai_builder_spec(output_config_spec)
    return output_config_spec


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
            last_generated_hash=description_hash(spec.flow_description),
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
        old_sig = FlowSemanticSignature.from_steps(
            _flow_steps_to_step_specs(current_flow.steps)
        )
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
