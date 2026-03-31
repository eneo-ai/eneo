"""Edit IR compiler for the AI Builder.

Compiles FlowEditDraft operations into a CompiledEditResult: a concrete
flow preview + diff that the user approves. The key principle is that
the LLM describes the change, and the backend preserves everything else.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_description_semantics import (
    FlowSemanticSignature,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    CompiledEditResult,
    EditAdvisory,
    EditConfidence,
    FlowEditDiff,
    FlowEditDraft,
    FormFieldChange,
    MetadataChange,
    StepChange,
    StepEditOperation,
    StepPatch,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.domain.flow import FlowStep

_RUNTIME_STEP_ALIAS_PATTERN = re.compile(r"\{\{\s*step_(\d+)(\.[^{}]+?)\s*\}\}")


def compile_edit_draft(
    edit_draft: FlowEditDraft,
    current_steps: list[FlowStep],
    base_flow_revision: int,
    *,
    flow_name: str | None = None,
    flow_description: str | None = None,
    current_metadata_json: dict[str, Any] | None = None,
    assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
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
    # Build ref mapping: existing_step_{order} → FlowStep
    steps_by_ref: dict[str, FlowStep] = {}
    for step in current_steps:
        ref = f"existing_step_{step.step_order}"
        steps_by_ref[ref] = step

    # Work on a mutable ordered list of (ref_or_None, FlowStep_or_AddPayload)
    working: list[tuple[str | None, FlowStep | AddStepPayload]] = [
        (f"existing_step_{s.step_order}", s) for s in current_steps
    ]

    step_changes: list[StepChange] = []
    form_changes = []
    removed_refs: set[str] = set()
    modified_refs: dict[str, StepPatch] = {}
    warnings: list[str] = []

    # Process operations in order
    for op in edit_draft.operations:
        if op.op == "remove":
            _apply_remove(op, working, step_changes, removed_refs)
        elif op.op == "modify":
            _apply_modify(op, step_changes, modified_refs)
        elif op.op == "add":
            _apply_add(op, working, step_changes, steps_by_ref)

    # Mark unchanged steps
    touched_refs = removed_refs | set(modified_refs.keys())
    for ref, item in working:
        if ref is not None and ref not in touched_refs and isinstance(item, FlowStep):
            step_changes.append(StepChange(
                kind="unchanged",
                step_name=item.user_description or f"Step {item.step_order}",
                step_ref=ref,
            ))

    # Build compiled StepSpec list from working order
    compiled_steps: list[StepSpec] = []
    for i, (ref, item) in enumerate(working):
        plan_ref = f"step_{chr(ord('a') + i)}" if i < 26 else f"step_{i + 1}"

        if isinstance(item, AddStepPayload):
            compiled_steps.append(_payload_to_step_spec(item, plan_ref))
        elif isinstance(item, FlowStep):
            patch = modified_refs.get(ref)  # type: ignore[arg-type]
            compiled_steps.append(
                _flow_step_to_spec(
                    item,
                    plan_ref,
                    patch,
                    assistant_snapshots=assistant_snapshots,
                )
            )

    compiled_steps = _canonicalize_existing_runtime_aliases(compiled_steps)

    compiled_form_fields, form_changes = _compile_form_fields(
        edit_draft,
        current_metadata_json=current_metadata_json,
    )

    # Resolve flow name/description — no regex mutation, just pass-through
    final_name = edit_draft.flow_name or flow_name or "Unnamed Flow"
    final_description = _resolve_flow_description(
        edit_draft=edit_draft,
        current_description=flow_description,
    )

    compiled_spec = FlowDraftSpecCore(
        flow_name=final_name,
        flow_description=final_description,
        steps=compiled_steps,
        form_fields=compiled_form_fields,
    )

    # Build advisories from semantic signature comparison
    advisories: list[EditAdvisory] = _build_description_advisories(
        edit_draft=edit_draft,
        current_steps=current_steps,
        compiled_steps=compiled_steps,
        current_description=flow_description,
    )

    # Build diff
    metadata_changes: list[MetadataChange] = []
    flow_property_changes: dict[str, tuple[Any, Any]] = {}
    if edit_draft.flow_name and edit_draft.flow_name != flow_name:
        flow_property_changes["flow_name"] = (flow_name, edit_draft.flow_name)
    previous_description = flow_description or ""
    if final_description != previous_description:
        flow_property_changes["flow_description"] = (flow_description, final_description)

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

    # Compute confidence
    risk_flags: list[str] = []
    if any(op.op == "remove" for op in edit_draft.operations):
        risk_flags.append("step_removal")
    confidence = _compute_confidence(step_changes, warnings, edit_draft)

    return CompiledEditResult(
        compiled_spec=compiled_spec,
        diff=diff,
        original_draft=edit_draft,
        base_flow_revision=base_flow_revision,
        warnings=warnings,
        advisories=advisories,
        risk_flags=risk_flags,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Operation helpers
# ---------------------------------------------------------------------------


def _apply_remove(
    op: StepEditOperation,
    working: list[tuple[str | None, FlowStep | AddStepPayload]],
    step_changes: list[StepChange],
    removed_refs: set[str],
) -> None:
    if op.target_ref is None:
        return
    for i, (ref, item) in enumerate(working):
        if ref == op.target_ref and isinstance(item, FlowStep):
            step_changes.append(StepChange(
                kind="removed",
                step_name=item.user_description or f"Step {item.step_order}",
                step_ref=op.target_ref,
            ))
            removed_refs.add(op.target_ref)
            working.pop(i)
            return


def _apply_modify(
    op: StepEditOperation,
    step_changes: list[StepChange],
    modified_refs: dict[str, StepPatch],
) -> None:
    if op.target_ref is None or op.patch is None:
        return
    modified_refs[op.target_ref] = op.patch
    details_parts: list[str] = []
    if op.patch.name is not None:
        details_parts.append(f"name → '{op.patch.name}'")
    if op.patch.input_source is not None:
        details_parts.append(f"input_source → {op.patch.input_source.value}")
    if op.patch.assistant_spec is not None:
        details_parts.append("instructions updated")
    step_changes.append(StepChange(
        kind="modified",
        step_name=op.patch.name or op.target_ref,
        step_ref=op.target_ref,
        details=", ".join(details_parts) if details_parts else None,
    ))


def _apply_add(
    op: StepEditOperation,
    working: list[tuple[str | None, FlowStep | AddStepPayload]],
    step_changes: list[StepChange],
    steps_by_ref: dict[str, FlowStep],
) -> None:
    if op.add_payload is None:
        return

    step_changes.append(StepChange(
        kind="added",
        step_name=op.add_payload.name,
        step_ref=None,
    ))

    new_entry: tuple[str | None, AddStepPayload] = (None, op.add_payload)

    if op.placement is None or op.placement.position == "append":
        working.append(new_entry)
        return

    if op.placement.anchor_ref is not None:
        for i, (ref, _) in enumerate(working):
            if ref == op.placement.anchor_ref:
                if op.placement.position == "before":
                    working.insert(i, new_entry)
                else:  # after
                    working.insert(i + 1, new_entry)
                return

    # Fallback: append
    working.append(new_entry)


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _payload_to_step_spec(payload: AddStepPayload, plan_ref: str) -> StepSpec:
    return StepSpec(
        plan_step_ref=plan_ref,
        name=payload.name,
        assistant_spec=payload.assistant_spec,
        input_source=payload.input_source,
        input_type=payload.input_type,
        output_mode=payload.output_mode,
        output_type=payload.output_type,
        mcp_policy=payload.mcp_policy,
        input_bindings=payload.input_bindings,
        input_contract=payload.input_contract,
        output_contract=payload.output_contract,
        input_config=payload.input_config,
    )


def _flow_step_to_spec(
    step: FlowStep,
    plan_ref: str,
    patch: StepPatch | None = None,
    *,
    assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
) -> StepSpec:
    """Convert an existing FlowStep to a StepSpec, applying patch if present."""
    name = step.user_description or f"Step {step.step_order}"
    input_source = InputSource(step.input_source)
    base_assistant_spec = _resolve_existing_assistant_spec(
        step=step,
        assistant_snapshots=assistant_snapshots,
    )

    spec = StepSpec(
        plan_step_ref=plan_ref,
        existing_step_ref=f"existing_step_{step.step_order}",
        name=name,
        assistant_spec=base_assistant_spec,
        input_source=input_source,
        input_type=InputType(step.input_type),
        output_mode=OutputMode(step.output_mode),
        output_type=OutputType(step.output_type),
        mcp_policy=MCPPolicy(step.mcp_policy),
        input_bindings=step.input_bindings,
        input_contract=step.input_contract,
        output_contract=step.output_contract,
        input_config=step.input_config,
    )

    if patch is not None:
        updates: dict[str, Any] = {}
        if patch.name is not None:
            updates["name"] = patch.name
        if patch.input_source is not None:
            updates["input_source"] = patch.input_source
        if patch.input_type is not None:
            updates["input_type"] = patch.input_type
        if patch.output_mode is not None:
            updates["output_mode"] = patch.output_mode
        if patch.output_type is not None:
            updates["output_type"] = patch.output_type
        if patch.mcp_policy is not None:
            updates["mcp_policy"] = patch.mcp_policy
        if patch.assistant_spec is not None:
            updates["assistant_spec"] = _merge_assistant_specs(
                base_assistant_spec,
                patch.assistant_spec,
            )
        if patch.input_bindings is not None:
            updates["input_bindings"] = patch.input_bindings
        if patch.input_contract is not None:
            updates["input_contract"] = patch.input_contract
        if patch.output_contract is not None:
            updates["output_contract"] = patch.output_contract
        if patch.input_config is not None:
            updates["input_config"] = patch.input_config
        if updates:
            spec = spec.model_copy(update=updates)

    return spec


def _resolve_existing_assistant_spec(
    *,
    step: FlowStep,
    assistant_snapshots: dict[UUID, dict[str, Any]] | None,
) -> AssistantSpec:
    if step.assistant_id is None or not assistant_snapshots:
        return AssistantSpec(instructions="")

    snapshot = assistant_snapshots.get(step.assistant_id)
    if not isinstance(snapshot, dict):
        return AssistantSpec(instructions="")

    instructions_raw = snapshot.get("instructions")
    model_ref_raw = snapshot.get("model_ref")
    knowledge_refs_raw = snapshot.get("knowledge_refs")
    return AssistantSpec(
        instructions=instructions_raw.strip() if isinstance(instructions_raw, str) else "",
        model_ref=model_ref_raw if isinstance(model_ref_raw, str) and model_ref_raw.strip() else None,
        knowledge_refs=(
            [str(ref).strip() for ref in knowledge_refs_raw if str(ref).strip()]
            if isinstance(knowledge_refs_raw, list)
            else []
        ),
    )


def _merge_assistant_specs(
    existing: AssistantSpec,
    patch: AssistantSpec,
) -> AssistantSpec:
    instructions = patch.instructions.strip() or existing.instructions
    model_ref = patch.model_ref if patch.model_ref is not None else existing.model_ref
    knowledge_refs = patch.knowledge_refs or existing.knowledge_refs
    return AssistantSpec(
        instructions=instructions,
        model_ref=model_ref,
        knowledge_refs=knowledge_refs,
    )


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
    """Resolve description: use draft's if provided, otherwise preserve current."""
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

    old_sig = FlowSemanticSignature.from_steps(_flow_steps_to_step_specs(current_steps))
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


def _flow_steps_to_step_specs(steps: list[FlowStep]) -> list[StepSpec]:
    """Convert FlowSteps to minimal StepSpecs for signature extraction."""
    return [
        StepSpec(
            plan_step_ref=f"existing_step_{s.step_order}",
            name=s.user_description or f"Step {s.step_order}",
            assistant_spec=AssistantSpec(instructions=""),
            input_source=InputSource(s.input_source),
            input_type=InputType(s.input_type),
            output_mode=OutputMode(s.output_mode),
            output_type=OutputType(s.output_type),
        )
        for s in steps
    ]


def _compile_form_fields(
    edit_draft: FlowEditDraft,
    *,
    current_metadata_json: dict[str, Any] | None,
) -> tuple[list[FormFieldSpec] | None, list]:
    current_fields = _extract_form_fields_from_metadata(current_metadata_json)
    if not edit_draft.form_operations:
        return (deepcopy(current_fields) if current_fields is not None else None, [])

    working_fields = deepcopy(current_fields) if current_fields is not None else []
    field_index = {field.name: index for index, field in enumerate(working_fields)}
    form_changes = []

    for op in edit_draft.form_operations:
        existing_index = field_index.get(op.field_name)
        existing_field = (
            working_fields[existing_index]
            if existing_index is not None
            else None
        )

        if op.op == "remove":
            if existing_index is None:
                continue
            working_fields.pop(existing_index)
            field_index = {field.name: index for index, field in enumerate(working_fields)}
            form_changes.append(FormFieldChange(kind="removed", field_name=op.field_name))
            continue

        payload = op.field_payload
        merged_field = FormFieldSpec(
            name=op.field_name,
            type=(
                payload.field_type
                if payload is not None and payload.field_type is not None
                else existing_field.type if existing_field is not None else "text"
            ),
            label=(
                payload.label
                if payload is not None and payload.label is not None
                else existing_field.label if existing_field is not None else op.field_name
            ),
            required=(
                payload.required
                if payload is not None and payload.required is not None
                else existing_field.required if existing_field is not None else False
            ),
            options=(
                deepcopy(payload.options)
                if payload is not None and payload.options is not None
                else deepcopy(existing_field.options) if existing_field is not None else None
            ),
        )

        if existing_index is None:
            working_fields.append(merged_field)
            field_index[merged_field.name] = len(working_fields) - 1
            form_changes.append(FormFieldChange(kind="added", field_name=op.field_name))
            continue

        working_fields[existing_index] = merged_field
        form_changes.append(FormFieldChange(kind="modified", field_name=op.field_name))

    return (working_fields or None, form_changes)


def _extract_form_fields_from_metadata(
    metadata_json: dict[str, Any] | None,
) -> list[FormFieldSpec] | None:
    if not isinstance(metadata_json, dict):
        return None
    form_schema = metadata_json.get("form_schema")
    if not isinstance(form_schema, dict):
        return None
    raw_fields = form_schema.get("fields")
    if not isinstance(raw_fields, list):
        return None

    fields: list[FormFieldSpec] = []
    for raw_field in raw_fields:
        if not isinstance(raw_field, dict):
            continue
        name = str(raw_field.get("name", "")).strip()
        if not name:
            continue
        label = str(raw_field.get("label", name)).strip() or name
        field_type = str(raw_field.get("type", "text")).strip() or "text"
        options = raw_field.get("options")
        normalized_options = (
            [str(option) for option in options]
            if isinstance(options, list)
            else None
        )
        fields.append(
            FormFieldSpec(
                name=name,
                type=field_type,
                label=label,
                required=bool(raw_field.get("required", False)),
                options=normalized_options,
            )
        )
    return fields or None


def _canonicalize_existing_runtime_aliases(step_specs: list[StepSpec]) -> list[StepSpec]:
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
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [
            _rewrite_runtime_alias_value(item, existing_order_to_plan_ref)
            for item in value
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
