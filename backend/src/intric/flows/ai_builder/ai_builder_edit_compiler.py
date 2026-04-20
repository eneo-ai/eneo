"""Edit IR compiler for the AI Builder.

Compiles FlowEditDraft operations into a CompiledEditResult: a concrete
flow preview + diff that the user approves. The key principle is that
the LLM describes the change, and the backend preserves everything else.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, cast
from uuid import UUID

from intric.flows.ai_builder.ai_builder_description_semantics import (
    FlowSemanticSignature,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
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
from intric.flows.ai_builder.ai_builder_flow_name import normalize_flow_name
from intric.flows.ai_builder.ai_builder_form_fields import (
    extract_form_fields_from_metadata,
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
from intric.flows.ai_builder.ai_builder_new_step_compiler import (
    compile_new_step_draft,
    default_previous_field_label,
)
from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from intric.flows.ai_builder.ai_builder_step_transition_policy import (
    StepNormalizationChange,
    normalize_ai_builder_spec,
    normalize_ai_builder_step,
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
    # Work on a mutable ordered list of (ref_or_None, FlowStep_or_AddPayload)
    working: list[tuple[str | None, FlowStep | NewStepDraft]] = [
        (f"existing_step_{s.step_order}", s) for s in current_steps
    ]

    form_changes = []
    removed_refs: set[str] = set()
    modified_refs: dict[str, StepPatch] = {}
    warnings: list[str] = []

    # Process operations in order
    for op in edit_draft.operations:
        if op.op == "remove":
            _apply_remove(op, working, removed_refs)
        elif op.op == "modify":
            _apply_modify(op, modified_refs)
        elif op.op == "add":
            _apply_add(op, working)

    # Build compiled StepSpec list from working order
    compiled_steps: list[StepSpec] = []
    for i, (ref, item) in enumerate(working):
        plan_ref = f"step_{chr(ord('a') + i)}" if i < 26 else f"step_{i + 1}"

        if isinstance(item, NewStepDraft):
            compiled_steps.append(
                compile_new_step_draft(
                    step_draft=item,
                    step_index=i,
                    prior_steps=compiled_steps,
                )
            )
        else:
            patch = modified_refs.get(ref)  # type: ignore[arg-type]
            compiled_steps.append(
                _flow_step_to_spec(
                    item,
                    plan_ref,
                    patch,
                    assistant_snapshots=assistant_snapshots,
                    current_steps=current_steps,
                )
            )

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

    compiled_form_fields, form_changes = _compile_form_fields(
        edit_draft,
        current_metadata_json=current_metadata_json,
    )

    # Resolve flow name/description — no regex mutation, just pass-through
    final_name = normalized_spec.flow_name
    final_description = normalized_spec.flow_description

    compiled_spec = FlowDraftSpecCore(
        flow_name=final_name,
        flow_description=final_description,
        steps=compiled_steps,
        form_fields=compiled_form_fields,
    )

    # Build advisories from semantic signature comparison
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

    step_changes = _build_step_changes(
        current_steps=current_steps,
        compiled_steps=compiled_steps,
        removed_refs=removed_refs,
        assistant_snapshots=assistant_snapshots,
    )

    # Build diff
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
    working: list[tuple[str | None, FlowStep | NewStepDraft]],
    removed_refs: set[str],
) -> None:
    if op.target_ref is None:
        return
    for i, (ref, item) in enumerate(working):
        if ref == op.target_ref and isinstance(item, FlowStep):
            removed_refs.add(op.target_ref)
            working.pop(i)
            return


def _apply_modify(
    op: StepEditOperation,
    modified_refs: dict[str, StepPatch],
) -> None:
    if op.target_ref is None or op.patch is None:
        return
    modified_refs[op.target_ref] = op.patch


def _apply_add(
    op: StepEditOperation,
    working: list[tuple[str | None, FlowStep | NewStepDraft]],
) -> None:
    if op.add_payload is None:
        return

    new_entry: tuple[str | None, NewStepDraft] = (None, op.add_payload)

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


def _flow_step_to_spec(
    step: FlowStep,
    plan_ref: str,
    patch: StepPatch | None = None,
    *,
    assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
    current_steps: list[FlowStep] | None = None,
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
        output_config=step.output_config,
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
        if (
            "uses_previous_fields" in patch.model_fields_set
            or "uses_form_fields" in patch.model_fields_set
        ):
            updates["input_bindings"] = _compile_patch_input_bindings(
                uses_previous_fields=patch.uses_previous_fields or [],
                uses_form_fields=patch.uses_form_fields or [],
                current_steps=current_steps or [],
            )
        if "input_bindings" in patch.model_fields_set:
            updates["input_bindings"] = patch.input_bindings
        if "input_contract" in patch.model_fields_set:
            updates["input_contract"] = patch.input_contract
        if "output_contract" in patch.model_fields_set:
            updates["output_contract"] = patch.output_contract
        if "input_config" in patch.model_fields_set:
            updates["input_config"] = patch.input_config
        if "output_config" in patch.model_fields_set:
            updates["output_config"] = patch.output_config
        if updates:
            spec = spec.model_copy(update=updates)

    return spec


def _resolve_existing_assistant_spec(
    *,
    step: FlowStep,
    assistant_snapshots: dict[UUID, dict[str, Any]] | None,
) -> AssistantSpec:
    if not assistant_snapshots:
        return AssistantSpec(instructions="")

    snapshot = assistant_snapshots.get(step.assistant_id)
    if not isinstance(snapshot, dict):
        return AssistantSpec(instructions="")

    instructions_raw = snapshot.get("instructions")
    model_ref_raw = snapshot.get("model_ref")
    knowledge_refs_raw = snapshot.get("knowledge_refs")
    knowledge_refs = (
        cast(list[object], knowledge_refs_raw)
        if isinstance(knowledge_refs_raw, list)
        else []
    )
    return AssistantSpec(
        instructions=instructions_raw.strip()
        if isinstance(instructions_raw, str)
        else "",
        model_ref=model_ref_raw
        if isinstance(model_ref_raw, str) and model_ref_raw.strip()
        else None,
        knowledge_refs=[str(ref).strip() for ref in knowledge_refs if str(ref).strip()],
    )


def _merge_assistant_specs(
    existing: AssistantSpec,
    patch: AssistantSpec,
) -> AssistantSpec:
    instructions = existing.instructions
    if "instructions" in patch.model_fields_set:
        instructions = patch.instructions.strip() or existing.instructions

    model_ref = existing.model_ref
    if "model_ref" in patch.model_fields_set:
        model_ref = patch.model_ref

    knowledge_refs = existing.knowledge_refs
    if "knowledge_refs" in patch.model_fields_set:
        knowledge_refs = patch.knowledge_refs

    return AssistantSpec(
        instructions=instructions,
        model_ref=model_ref,
        knowledge_refs=knowledge_refs,
    )


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
    removed_refs: set[str],
    assistant_snapshots: dict[UUID, dict[str, Any]] | None,
) -> list[StepChange]:
    existing_order_to_plan_ref = {
        existing_order: step.plan_step_ref
        for step in compiled_steps
        if (existing_order := _existing_step_order(step.existing_step_ref)) is not None
    }
    baseline_specs: dict[str, StepSpec] = {}
    removed_names: dict[str, str] = {}
    for step in current_steps:
        ref = f"existing_step_{step.step_order}"
        baseline_spec = _flow_step_to_spec(
            step,
            ref,
            assistant_snapshots=assistant_snapshots,
            current_steps=current_steps,
        )
        baseline_specs[ref] = _canonicalize_step_for_diff(
            baseline_spec,
            existing_order_to_plan_ref,
        )
        removed_names[ref] = step.user_description or f"Step {step.step_order}"

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
    canonical_step = _rewrite_runtime_aliases_for_existing_step(
        step,
        existing_order_to_plan_ref,
    )
    return normalize_ai_builder_step(canonical_step)[0]


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
) -> tuple[list[FormFieldSpec] | None, list[FormFieldChange]]:
    current_fields = extract_form_fields_from_metadata(current_metadata_json)
    if not edit_draft.form_operations:
        return (deepcopy(current_fields) if current_fields is not None else None, [])

    working_fields = deepcopy(current_fields) if current_fields is not None else []
    field_index = {field.name: index for index, field in enumerate(working_fields)}
    form_changes: list[FormFieldChange] = []

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
        merged_field = FormFieldSpec(
            name=op.field_name,
            type=(
                payload.field_type
                if payload is not None and payload.field_type is not None
                else existing_field.type
                if existing_field is not None
                else "text"
            ),
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

    return (working_fields or None, form_changes)


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


def _compile_patch_input_bindings(
    *,
    uses_previous_fields: list[Any],
    uses_form_fields: list[str],
    current_steps: list[FlowStep],
) -> dict[str, Any] | None:
    sections: list[str] = []
    for field_ref in uses_previous_fields:
        from_step = getattr(field_ref, "from_step", None)
        field_path = getattr(field_ref, "field_path", None)
        if (
            not isinstance(from_step, int)
            or from_step < 1
            or from_step > len(current_steps)
            or not isinstance(field_path, str)
        ):
            continue
        label = getattr(field_ref, "label", None) or default_previous_field_label(
            field_path
        )
        sections.append(
            f"{label}: {{{{ step_{from_step}.output.structured.{field_path} }}}}"
        )

    if uses_form_fields:
        sections.append(
            "\n".join(
                f"{field_name}: {{{{ {field_name} }}}}"
                for field_name in uses_form_fields
            )
        )

    if not sections:
        return None
    return {"question": "\n\n".join(sections)}


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
