"""Edit IR compiler for the AI Builder.

Compiles FlowEditDraft operations into a CompiledEditResult: a concrete
flow preview + diff that the user approves. The key principle is that
the LLM describes the change, and the backend preserves everything else.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from intric.flows.ai_builder.ai_builder_authoring_projection import (
    AddStep,
    AssistantSpecPatch,
    ModifyExistingStep,
    OrderedEditProposal,
    compile_ordered_edit_proposal,
    flow_step_to_authoring_spec,
    flow_steps_to_authoring_specs,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    CompiledEditResult,
    FlowEditDraft,
    StepEditOperation,
    StepPatch,
)
from intric.flows.ai_builder.ai_builder_edit_preview_models import (
    EditAdvisory,
    EditConfidence,
    FlowEditDiff,
    FormFieldChange,
    MetadataChange,
    StepChange,
)
from intric.flows.ai_builder.ai_builder_form_fields import (
    extract_form_fields_from_metadata,
)
from intric.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    PreviousFieldRef,
)
from intric.flows.ai_builder.ai_builder_primary_input_fields import (
    is_primary_runtime_input_shadow_field,
    split_primary_runtime_input_shadow_names,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import AIBuilderResourceCatalog
from intric.flows.ai_builder.ai_builder_step_transition_policy import (
    StepNormalizationChange,
    normalize_ai_builder_spec,
)
from intric.flows.application.flow_authoring_description_semantics import (
    FlowSemanticSignature,
)
from intric.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from intric.flows.domain.flow import FlowStep
from intric.flows.flow_authoring_name import normalize_flow_name
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputType,
    StepSpec,
)

_RUNTIME_STEP_ALIAS_PATTERN = re.compile(r"\{\{\s*step_(\d+)(\.[^{}]+?)\s*\}\}")


@dataclass(frozen=True, slots=True)
class _ExistingStepEntry:
    ref: str
    step: FlowStep


@dataclass(frozen=True, slots=True)
class _NewStepEntry:
    draft: NewStepDraft


_EditStepEntry = _ExistingStepEntry | _NewStepEntry


@dataclass(frozen=True, slots=True)
class _OrderedEditBuildResult:
    proposal: OrderedEditProposal
    warnings: list[str]
    shadowed_primary_input_fields: list[str]


def compile_edit_draft(
    edit_draft: FlowEditDraft,
    current_steps: list[FlowStep],
    base_flow_revision: int,
    *,
    flow_name: str | None = None,
    flow_description: str | None = None,
    current_metadata_json: dict[str, Any] | None = None,
    assistant_snapshots: AssistantAuthoringSnapshots | None = None,
    resource_catalog: AIBuilderResourceCatalog | None = None,
) -> CompiledEditResult:
    """Compile edit operations into a concrete flow preview + diff.

    The user approves this compiled result, not the raw draft.

    Args:
        edit_draft: The LLM's edit operations.
        current_steps: Existing flow steps (ordered by step_order).
        base_flow_revision: Current flow revision for stale-plan protection.
        flow_name: Current flow name (used if edit_draft doesn't change it).
        flow_description: Current flow description.
    """
    primary_runtime_input_type = _primary_runtime_input_type_from_steps(current_steps)
    ordered_edit = _build_ordered_edit_proposal(
        edit_draft=edit_draft,
        current_steps=current_steps,
        primary_runtime_input_type=primary_runtime_input_type,
    )
    base_spec = _current_flow_authoring_spec(
        current_steps=current_steps,
        flow_name=flow_name,
        flow_description=flow_description,
        assistant_snapshots=assistant_snapshots,
        resource_catalog=resource_catalog,
    )
    compiled_spec = compile_ordered_edit_proposal(
        base_spec=base_spec,
        proposal=ordered_edit.proposal,
        primary_runtime_input_type=primary_runtime_input_type,
    )
    compiled_steps = compiled_spec.steps

    compiled_steps = _canonicalize_existing_runtime_aliases(compiled_steps)
    normalized_spec, normalization_changes = normalize_ai_builder_spec(
        FlowDraftSpecCore(
            flow_name=normalize_flow_name(
                edit_draft.flow_name or flow_name or "Unnamed Flow"
            ),
            flow_description=_resolve_flow_description(
                edit_draft=edit_draft,
                current_description=flow_description,
            ),
            steps=compiled_steps,
            form_fields=None,
        )
    )
    compiled_steps = normalized_spec.steps

    compiled_form_fields, form_changes, dropped_form_field_names = _compile_form_fields(
        edit_draft,
        current_metadata_json=current_metadata_json,
        primary_runtime_input_type=primary_runtime_input_type,
    )
    shadowed_primary_input_fields = [
        *ordered_edit.shadowed_primary_input_fields,
        *dropped_form_field_names,
    ]

    final_name = normalized_spec.flow_name
    final_description = normalized_spec.flow_description

    compiled_spec = FlowDraftSpecCore(
        flow_name=final_name,
        flow_description=final_description,
        steps=compiled_steps,
        form_fields=compiled_form_fields,
    )

    advisories: list[EditAdvisory] = _build_normalization_advisories(
        normalization_changes
    )
    advisories.extend(
        _build_description_advisories(
            edit_draft=edit_draft,
            current_steps=current_steps,
            compiled_steps=compiled_steps,
            current_description=flow_description,
        )
    )
    advisories.extend(
        _build_primary_input_shadow_advisories(
            field_names=shadowed_primary_input_fields,
            primary_runtime_input_type=primary_runtime_input_type,
        )
    )

    step_changes = _build_step_changes(
        current_steps=current_steps,
        compiled_steps=compiled_steps,
        removed_refs=ordered_edit.proposal.removed_existing_step_refs,
        assistant_snapshots=assistant_snapshots,
        resource_catalog=resource_catalog,
    )

    metadata_changes: list[MetadataChange] = []
    flow_property_changes: dict[str, tuple[Any, Any]] = {}
    if edit_draft.flow_name and edit_draft.flow_name != flow_name:
        flow_property_changes["flow_name"] = (flow_name, edit_draft.flow_name)
    previous_description = flow_description or ""
    if final_description != previous_description:
        flow_property_changes["flow_description"] = (
            flow_description,
            final_description,
        )

    net_added = sum(1 for c in step_changes if c.kind == "added")
    net_removed = sum(1 for c in step_changes if c.kind == "removed")

    diff = FlowEditDiff(
        step_changes=step_changes,
        form_changes=form_changes,
        metadata_changes=metadata_changes,
        flow_property_changes=flow_property_changes,
        net_steps_added=net_added,
        net_steps_removed=net_removed,
    )

    risk_flags: list[str] = []
    if any(op.op == "remove" for op in edit_draft.operations):
        risk_flags.append("step_removal")
    confidence = _compute_confidence(step_changes, ordered_edit.warnings, edit_draft)

    return CompiledEditResult(
        compiled_spec=compiled_spec,
        diff=diff,
        original_draft=edit_draft,
        base_flow_revision=base_flow_revision,
        warnings=ordered_edit.warnings,
        advisories=advisories,
        risk_flags=risk_flags,
        confidence=confidence,
    )


def _build_ordered_edit_proposal(
    *,
    edit_draft: FlowEditDraft,
    current_steps: list[FlowStep],
    primary_runtime_input_type: InputType | None,
) -> _OrderedEditBuildResult:
    working: list[_EditStepEntry] = [
        _ExistingStepEntry(ref=f"existing_step_{s.step_order}", step=s)
        for s in current_steps
    ]
    removed_refs: set[str] = set()
    modified_refs: dict[str, StepPatch] = {}
    warnings: list[str] = []
    shadowed_primary_input_fields: list[str] = []

    for op in edit_draft.operations:
        if op.op == "remove":
            _apply_remove(op, working, removed_refs)
        elif op.op == "modify":
            _apply_modify(op, modified_refs)
        elif op.op == "add":
            _apply_add(op, working)

    _repair_leading_audio_document_extraction(
        working=working,
        modified_refs=modified_refs,
        warnings=warnings,
    )

    ordered_steps: list[AddStep | ModifyExistingStep] = []
    compiled_index_by_original_order: dict[int, int] = {}
    for entry in working:
        if isinstance(entry, _NewStepEntry):
            step_draft, dropped_field_names = _without_primary_runtime_shadow_fields(
                entry.draft,
                primary_runtime_input_type=primary_runtime_input_type,
            )
            shadowed_primary_input_fields.extend(dropped_field_names)
            ordered_steps.append(AddStep(step=step_draft))
            continue

        patch = modified_refs.get(entry.ref)
        if patch is None:
            ordered_steps.append(ModifyExistingStep(existing_step_ref=entry.ref))
        else:
            ordered_steps.append(
                _modify_step_from_patch(
                    existing_step_ref=entry.ref,
                    patch=patch,
                    compiled_index_by_original_order=compiled_index_by_original_order,
                )
            )
        original_order = _existing_step_order(entry.ref)
        if original_order is not None:
            compiled_index_by_original_order[original_order] = len(ordered_steps)

    payload: dict[str, object] = {
        "steps": ordered_steps,
        "removed_existing_step_refs": frozenset(removed_refs),
    }
    if edit_draft.flow_name is not None:
        payload["flow_name"] = edit_draft.flow_name
    if edit_draft.flow_description is not None:
        payload["flow_description"] = edit_draft.flow_description

    return _OrderedEditBuildResult(
        proposal=OrderedEditProposal.model_validate(payload),
        warnings=warnings,
        shadowed_primary_input_fields=shadowed_primary_input_fields,
    )


def _current_flow_authoring_spec(
    *,
    current_steps: list[FlowStep],
    flow_name: str | None,
    flow_description: str | None,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    resource_catalog: AIBuilderResourceCatalog | None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name=normalize_flow_name(flow_name or "Unnamed Flow"),
        flow_description=flow_description or "",
        steps=[
            flow_step_to_authoring_spec(
                step,
                plan_ref=f"existing_step_{step.step_order}",
                assistant_snapshots=assistant_snapshots,
                resource_catalog=resource_catalog,
            )
            for step in current_steps
        ],
        form_fields=None,
    )


# ---------------------------------------------------------------------------
# Operation helpers
# ---------------------------------------------------------------------------


def _apply_remove(
    op: StepEditOperation,
    working: list[_EditStepEntry],
    removed_refs: set[str],
) -> None:
    if op.target_ref is None:
        return
    for i, entry in enumerate(working):
        if isinstance(entry, _ExistingStepEntry) and entry.ref == op.target_ref:
            removed_refs.add(entry.ref)
            working.pop(i)
            return


def _apply_modify(
    op: StepEditOperation,
    modified_refs: dict[str, StepPatch],
) -> None:
    if op.target_ref is None or op.patch is None:
        return
    if op.target_ref in modified_refs:
        raise ValueError(
            f"Duplicate modify operation for {op.target_ref}; edit drafts must be "
            "canonicalized before compilation."
        )
    modified_refs[op.target_ref] = op.patch


def _apply_add(
    op: StepEditOperation,
    working: list[_EditStepEntry],
) -> None:
    if op.add_payload is None:
        return

    new_entry = _NewStepEntry(draft=op.add_payload)

    if op.placement is None or op.placement.position == "append":
        working.append(new_entry)
        return

    if op.placement.anchor_ref is not None:
        for i, entry in enumerate(working):
            if (
                isinstance(entry, _ExistingStepEntry)
                and entry.ref == op.placement.anchor_ref
            ):
                if op.placement.position == "before":
                    working.insert(i, new_entry)
                else:  # after
                    working.insert(i + 1, new_entry)
                return

    # Fallback: append
    working.append(new_entry)


def _repair_leading_audio_document_extraction(
    *,
    working: list[_EditStepEntry],
    modified_refs: dict[str, StepPatch],
    warnings: list[str],
) -> None:
    if len(working) < 2:
        return
    first_entry = working[0]
    if not isinstance(first_entry, _ExistingStepEntry):
        return
    if not _is_bad_leading_audio_document_extraction(first_entry.step, working):
        return

    working.insert(
        0,
        _NewStepEntry(
            draft=NewStepDraft(
                name="Transkribera ljud",
                instructions="Transkribera uppladdat ljud till text.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
                runtime_upload=True,
                runtime_required=_runtime_input_required(first_entry.step.input_config),
                runtime_max_files=_runtime_input_max_files(
                    first_entry.step.input_config
                ),
            ),
        ),
    )
    modified_refs[first_entry.ref] = _merge_step_patch(
        modified_refs.get(first_entry.ref),
        StepPatch(
            input_source=InputSource.PREVIOUS_STEP,
            input_type=InputType.TEXT,
            input_bindings=None,
            input_contract=None,
            input_config=None,
        ),
    )
    warnings.append(
        "Inserted a dedicated audio transcription step before the existing "
        "structured analysis step."
    )


def _is_bad_leading_audio_document_extraction(
    step: FlowStep,
    working: list[_EditStepEntry],
) -> bool:
    terminal = working[-1]
    terminal_output_type = (
        terminal.draft.output_type
        if isinstance(terminal, _NewStepEntry)
        else OutputType(terminal.step.output_type)
    )
    return (
        step.input_source == InputSource.FLOW_INPUT.value
        and step.input_type == InputType.AUDIO.value
        and step.output_type != OutputType.TEXT.value
        and terminal_output_type in {OutputType.DOCX, OutputType.PDF}
    )


def _merge_step_patch(existing: StepPatch | None, repair: StepPatch) -> StepPatch:
    if existing is None:
        return repair
    return existing.model_copy(update=repair.model_dump(exclude_unset=True))


def _runtime_input_required(input_config: dict[str, Any] | None) -> bool:
    runtime_input = _runtime_input_config(input_config)
    if isinstance(runtime_input.get("required"), bool):
        return cast(bool, runtime_input["required"])
    return True


def _runtime_input_max_files(input_config: dict[str, Any] | None) -> int | None:
    runtime_input = _runtime_input_config(input_config)
    max_files = runtime_input.get("max_files")
    return max_files if isinstance(max_files, int) else None


def _runtime_input_config(input_config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(input_config, dict):
        return {}
    runtime_input = input_config.get("runtime_input")
    return (
        cast(dict[str, Any], runtime_input) if isinstance(runtime_input, dict) else {}
    )


def _modify_step_from_patch(
    *,
    existing_step_ref: str,
    patch: StepPatch,
    compiled_index_by_original_order: dict[int, int],
) -> ModifyExistingStep:
    payload: dict[str, object | None] = {
        "existing_step_ref": existing_step_ref,
    }
    # Non-nullable StepSpec fields preserve old StepPatch omission semantics;
    # nullable fields below use model_fields_set so explicit clears survive.
    for field_name in (
        "name",
        "input_source",
        "input_type",
        "output_mode",
        "output_type",
        "mcp_policy",
    ):
        value = getattr(patch, field_name)
        if value is not None:
            payload[field_name] = value
    if patch.assistant_spec is not None:
        payload["assistant_spec"] = AssistantSpecPatch.model_validate(
            patch.assistant_spec.model_dump(mode="python", exclude_unset=True)
        )
    for field_name in (
        "uses_form_fields",
        "document_delivery_mode",
        "input_bindings",
        "input_contract",
        "output_contract",
        "input_config",
        "output_config",
        "review_mode",
    ):
        if field_name in patch.model_fields_set:
            payload[field_name] = getattr(patch, field_name)
    if "uses_previous_fields" in patch.model_fields_set:
        payload["uses_previous_fields"] = _translate_previous_field_refs(
            field_refs=patch.uses_previous_fields or [],
            compiled_index_by_original_order=compiled_index_by_original_order,
        )
    return ModifyExistingStep.model_validate(payload)


def _translate_previous_field_refs(
    *,
    field_refs: list[PreviousFieldRef],
    compiled_index_by_original_order: dict[int, int],
) -> list[PreviousFieldRef]:
    # Legacy StepPatch refs are authored as original step_order values; the
    # shared owner consumes indexes into the compiled prior-step list.
    translated: list[PreviousFieldRef] = []
    for field_ref in field_refs:
        compiled_index = compiled_index_by_original_order.get(field_ref.from_step)
        if compiled_index is None:
            continue
        translated.append(field_ref.model_copy(update={"from_step": compiled_index}))
    return translated


def _build_normalization_advisories(
    normalization_changes: list[tuple[StepSpec, StepNormalizationChange]],
) -> list[EditAdvisory]:
    advisories: list[EditAdvisory] = []
    for step, change in normalization_changes:
        step_ref = step.existing_step_ref or step.plan_step_ref
        advisories.append(
            EditAdvisory(
                code=change.code,
                message=change.message,
                severity=change.severity,
                field=f"{step_ref}.{change.field_suffix}",
            )
        )
    return advisories


def _build_step_changes(
    *,
    current_steps: list[FlowStep],
    compiled_steps: list[StepSpec],
    removed_refs: frozenset[str],
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    resource_catalog: AIBuilderResourceCatalog | None,
) -> list[StepChange]:
    existing_order_to_plan_ref = {
        existing_order: step.plan_step_ref
        for step in compiled_steps
        if (existing_order := _existing_step_order(step.existing_step_ref)) is not None
    }
    removed_names: dict[str, str] = {}
    baseline_steps: list[StepSpec] = []
    for step in current_steps:
        ref = f"existing_step_{step.step_order}"
        plan_ref = existing_order_to_plan_ref.get(step.step_order, ref)
        baseline_spec = flow_step_to_authoring_spec(
            step,
            plan_ref,
            assistant_snapshots=assistant_snapshots,
            resource_catalog=resource_catalog,
        )
        baseline_steps.append(
            _canonicalize_step_for_diff(baseline_spec, existing_order_to_plan_ref)
        )
        removed_names[ref] = step.user_description or f"Step {step.step_order}"
    baseline_specs = _normalize_baseline_specs_for_diff(baseline_steps)

    step_changes: list[StepChange] = []
    for step in compiled_steps:
        if step.existing_step_ref is None:
            step_changes.append(
                StepChange(
                    kind="added",
                    step_name=step.name,
                    step_ref=None,
                )
            )
            continue

        previous = baseline_specs.get(step.existing_step_ref)
        if previous is None or not _step_specs_equivalent(previous, step):
            step_changes.append(
                StepChange(
                    kind="modified",
                    step_name=step.name,
                    step_ref=step.existing_step_ref,
                    details=_describe_step_change(previous, step),
                )
            )
            continue

        step_changes.append(
            StepChange(
                kind="unchanged",
                step_name=step.name,
                step_ref=step.existing_step_ref,
            )
        )

    for step in current_steps:
        ref = f"existing_step_{step.step_order}"
        if ref not in removed_refs:
            continue
        step_changes.append(
            StepChange(
                kind="removed",
                step_name=removed_names[ref],
                step_ref=ref,
            )
        )
    return step_changes


def _step_specs_equivalent(previous: StepSpec, current: StepSpec) -> bool:
    return _comparable_step_payload(previous) == _comparable_step_payload(current)


def _canonicalize_step_for_diff(
    step: StepSpec,
    existing_order_to_plan_ref: dict[int, str],
) -> StepSpec:
    return _rewrite_runtime_aliases_for_existing_step(
        step,
        existing_order_to_plan_ref,
    )


def _normalize_baseline_specs_for_diff(steps: list[StepSpec]) -> dict[str, StepSpec]:
    normalized_spec, _ = normalize_ai_builder_spec(
        FlowDraftSpecCore(flow_name="Existing flow", steps=steps, form_fields=None)
    )
    return {
        step.existing_step_ref: step
        for step in normalized_spec.steps
        if step.existing_step_ref is not None
    }


def _comparable_step_payload(step: StepSpec) -> dict[str, Any]:
    payload = step.model_dump(mode="json")
    payload.pop("plan_step_ref", None)
    payload.pop("existing_step_ref", None)
    return payload


def _describe_step_change(previous: StepSpec | None, current: StepSpec) -> str | None:
    if previous is None:
        return None

    details: list[str] = []
    if previous.name != current.name:
        details.append(f"name → '{current.name}'")
    if previous.input_source != current.input_source:
        details.append(f"input_source → {current.input_source.value}")
    if previous.input_type != current.input_type:
        details.append(f"input_type → {current.input_type.value}")
    if previous.output_mode != current.output_mode:
        details.append(f"output_mode → {current.output_mode.value}")
    if previous.output_type != current.output_type:
        details.append(f"output_type → {current.output_type.value}")
    if previous.assistant_spec.instructions != current.assistant_spec.instructions:
        details.append("instructions updated")
    if previous.assistant_spec.model_ref != current.assistant_spec.model_ref:
        details.append("model updated")
    if previous.assistant_spec.knowledge_refs != current.assistant_spec.knowledge_refs:
        details.append("knowledge updated")
    if (
        previous.assistant_spec.mcp_server_refs
        != current.assistant_spec.mcp_server_refs
        or previous.assistant_spec.mcp_tool_refs != current.assistant_spec.mcp_tool_refs
    ):
        details.append("MCP tools updated")
    return ", ".join(details) if details else None


def _compute_confidence(
    step_changes: list[StepChange],
    warnings: list[str],
    draft: FlowEditDraft,
) -> EditConfidence:
    if warnings:
        return "needs_review"
    removed_count = sum(1 for c in step_changes if c.kind == "removed")
    if removed_count > 1:
        return "needs_review"
    if len(draft.operations) > 5:
        return "needs_review"
    return "ready"


def _resolve_flow_description(
    *,
    edit_draft: FlowEditDraft,
    current_description: str | None,
) -> str:
    if edit_draft.flow_description is not None:
        return edit_draft.flow_description
    return current_description or ""


def _build_description_advisories(
    *,
    edit_draft: FlowEditDraft,
    current_steps: list[FlowStep],
    compiled_steps: list[StepSpec],
    current_description: str | None,
) -> list[EditAdvisory]:
    """Emit advisory when semantic signature changed but description wasn't updated."""
    if edit_draft.flow_description is not None:
        return []
    if not current_steps or not compiled_steps or not current_description:
        return []

    old_sig = FlowSemanticSignature.from_steps(
        flow_steps_to_authoring_specs(current_steps)
    )
    new_sig = FlowSemanticSignature.from_steps(compiled_steps)

    if not old_sig.has_semantic_change(new_sig):
        return []

    return [
        EditAdvisory(
            code="flow_description_update_required",
            message=(
                "Flow inputs or outputs changed but the description was not updated. "
                "Consider updating the description to reflect the new behavior."
            ),
            severity="warning",
            field="flow_description",
        )
    ]


def _build_primary_input_shadow_advisories(
    *,
    field_names: list[str],
    primary_runtime_input_type: InputType | None,
) -> list[EditAdvisory]:
    unique_names = sorted(set(field_names))
    if not unique_names or primary_runtime_input_type is None:
        return []
    joined_names = ", ".join(f"'{name}'" for name in unique_names)
    return [
        EditAdvisory(
            code="form_field_shadows_primary_input",
            message=(
                f"Ignored form field reference(s) {joined_names} because "
                f"the flow's primary {primary_runtime_input_type.value} input is "
                "already provided through Flow input, not an inmatningsfält."
            ),
            severity="info",
            field="form_fields",
        )
    ]


def _compile_form_fields(
    edit_draft: FlowEditDraft,
    *,
    current_metadata_json: dict[str, Any] | None,
    primary_runtime_input_type: InputType | None,
) -> tuple[list[FormFieldSpec] | None, list[FormFieldChange], list[str]]:
    current_fields = extract_form_fields_from_metadata(current_metadata_json)
    if not edit_draft.form_operations:
        return (
            deepcopy(current_fields) if current_fields is not None else None,
            [],
            [],
        )

    working_fields = deepcopy(current_fields) if current_fields is not None else []
    field_index = {field.name: index for index, field in enumerate(working_fields)}
    form_changes: list[FormFieldChange] = []
    dropped_primary_input_field_names: list[str] = []

    for op in edit_draft.form_operations:
        existing_index = field_index.get(op.field_name)
        existing_field = (
            working_fields[existing_index] if existing_index is not None else None
        )

        if op.op == "remove":
            if existing_index is None:
                continue
            working_fields.pop(existing_index)
            field_index = {
                field.name: index for index, field in enumerate(working_fields)
            }
            form_changes.append(
                FormFieldChange(kind="removed", field_name=op.field_name)
            )
            continue

        payload = op.field_payload
        payload_field_type = (
            payload.field_type
            if payload is not None and payload.field_type is not None
            else existing_field.type
            if existing_field is not None
            else "text"
        )
        if is_primary_runtime_input_shadow_field(
            variable_name=op.field_name,
            field_type=payload_field_type,
            runtime_input_type=primary_runtime_input_type,
        ):
            dropped_primary_input_field_names.append(op.field_name)
            continue

        merged_field = FormFieldSpec(
            name=op.field_name,
            type=payload_field_type,
            label=(
                payload.label
                if payload is not None and payload.label is not None
                else existing_field.label
                if existing_field is not None
                else op.field_name
            ),
            required=(
                payload.required
                if payload is not None and payload.required is not None
                else existing_field.required
                if existing_field is not None
                else False
            ),
            options=(
                deepcopy(payload.options)
                if payload is not None and payload.options is not None
                else deepcopy(existing_field.options)
                if existing_field is not None
                else None
            ),
        )

        if existing_index is None:
            working_fields.append(merged_field)
            field_index[merged_field.name] = len(working_fields) - 1
            form_changes.append(FormFieldChange(kind="added", field_name=op.field_name))
            continue

        working_fields[existing_index] = merged_field
        form_changes.append(FormFieldChange(kind="modified", field_name=op.field_name))

    return (working_fields or None, form_changes, dropped_primary_input_field_names)


def _primary_runtime_input_type_from_steps(
    steps: list[FlowStep],
) -> InputType | None:
    for step in sorted(steps, key=lambda item: item.step_order):
        if step.input_source != InputSource.FLOW_INPUT.value:
            continue
        try:
            return InputType(step.input_type)
        except ValueError:
            return None
    return None


def _without_primary_runtime_shadow_fields(
    step: NewStepDraft,
    *,
    primary_runtime_input_type: InputType | None,
) -> tuple[NewStepDraft, list[str]]:
    filtered, dropped = split_primary_runtime_input_shadow_names(
        field_names=step.uses_form_fields,
        runtime_input_type=primary_runtime_input_type,
    )
    if filtered == step.uses_form_fields:
        return step, dropped
    return step.model_copy(update={"uses_form_fields": filtered}), dropped


def _canonicalize_existing_runtime_aliases(
    step_specs: list[StepSpec],
) -> list[StepSpec]:
    existing_order_to_plan_ref = {
        existing_order: step.plan_step_ref
        for step in step_specs
        if (existing_order := _existing_step_order(step.existing_step_ref)) is not None
    }
    if not existing_order_to_plan_ref:
        return step_specs

    return [
        _rewrite_runtime_aliases_for_existing_step(step, existing_order_to_plan_ref)
        for step in step_specs
    ]


def _existing_step_order(existing_step_ref: str | None) -> int | None:
    if existing_step_ref is None or not existing_step_ref.startswith("existing_step_"):
        return None
    raw_order = existing_step_ref.removeprefix("existing_step_")
    return int(raw_order) if raw_order.isdigit() else None


def _rewrite_runtime_aliases_for_existing_step(
    step: StepSpec,
    existing_order_to_plan_ref: dict[int, str],
) -> StepSpec:
    if step.existing_step_ref is None:
        return step

    updates: dict[str, Any] = {}
    rewritten_instructions = _rewrite_runtime_alias_string(
        step.assistant_spec.instructions,
        existing_order_to_plan_ref,
    )
    if rewritten_instructions != step.assistant_spec.instructions:
        updates["assistant_spec"] = step.assistant_spec.model_copy(
            update={"instructions": rewritten_instructions}
        )

    if step.input_bindings is not None:
        rewritten_bindings = _rewrite_runtime_alias_value(
            step.input_bindings,
            existing_order_to_plan_ref,
        )
        if rewritten_bindings != step.input_bindings:
            updates["input_bindings"] = rewritten_bindings

    if step.output_config is not None:
        rewritten_output_config = _rewrite_runtime_alias_value(
            step.output_config,
            existing_order_to_plan_ref,
        )
        if rewritten_output_config != step.output_config:
            updates["output_config"] = rewritten_output_config

    return step.model_copy(update=updates) if updates else step


def _rewrite_runtime_alias_value(
    value: Any,
    existing_order_to_plan_ref: dict[int, str],
) -> Any:
    if isinstance(value, str):
        return _rewrite_runtime_alias_string(value, existing_order_to_plan_ref)
    if isinstance(value, dict):
        return {
            key: _rewrite_runtime_alias_value(inner, existing_order_to_plan_ref)
            for key, inner in cast(dict[str, Any], value).items()
        }
    if isinstance(value, list):
        return [
            _rewrite_runtime_alias_value(item, existing_order_to_plan_ref)
            for item in cast(list[Any], value)
        ]
    return value


def _rewrite_runtime_alias_string(
    text: str,
    existing_order_to_plan_ref: dict[int, str],
) -> str:
    def _replace(match: re.Match[str]) -> str:
        old_order = int(match.group(1))
        plan_ref = existing_order_to_plan_ref.get(old_order)
        if plan_ref is None:
            return match.group(0)
        return "{{ " + plan_ref + match.group(2) + " }}"

    return _RUNTIME_STEP_ALIAS_PATTERN.sub(_replace, text)
