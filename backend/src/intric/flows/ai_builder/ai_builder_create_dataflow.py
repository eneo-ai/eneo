from __future__ import annotations

from typing import Any, cast

from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_mechanical_refs import (
    clean_raw_previous_field_refs,
)
from intric.flows.ai_builder.ai_builder_models import InputSource, InputType, OutputType
from intric.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    PreviousFieldRef,
    PreviousOutputRef,
)
from intric.flows.ai_builder.ai_builder_source_material import (
    normalize_create_draft_source_material,
)
from intric.flows.ai_builder.ai_builder_structured_field_paths import (
    missing_draft_field_path,
)

_FILE_INPUT_TYPES = {InputType.AUDIO, InputType.DOCUMENT, InputType.FILE}
_DOCUMENT_OUTPUT_TYPES = {OutputType.DOCX, OutputType.PDF}


def strip_malformed_previous_field_refs(arguments: dict[str, Any]) -> dict[str, Any]:
    """Drop malformed field-level refs before strict Pydantic parsing.

    `uses_previous_fields` is a backend binding hint. LLMs frequently produce
    malformed variants when they try to author low-level wiring, so create-mode
    parsing treats malformed refs as absent instead of forcing a repair round.
    Strict semantic validation remains responsible for unsanitized callers.
    """

    steps = arguments.get("steps")
    if not isinstance(steps, list):
        return arguments

    updated_steps: list[Any] = []
    changed = False
    for raw_step in cast(list[Any], steps):
        if not isinstance(raw_step, dict):
            updated_steps.append(raw_step)
            continue

        raw_step_dict = cast(dict[str, Any], raw_step)
        refs = raw_step_dict.get("uses_previous_fields")
        if refs is None:
            updated_steps.append(raw_step_dict)
            continue

        cleaned_refs = clean_raw_previous_field_refs(refs)
        if cleaned_refs == refs:
            updated_steps.append(raw_step_dict)
            continue

        changed = True
        updated_step: dict[str, Any] = dict(raw_step_dict)
        if cleaned_refs:
            updated_step["uses_previous_fields"] = cleaned_refs
        else:
            updated_step.pop("uses_previous_fields", None)
        updated_steps.append(updated_step)

    if not changed:
        return arguments
    return {**arguments, "steps": updated_steps}


def normalize_create_draft_mechanics(draft: FlowCreateDraft) -> FlowCreateDraft:
    """Remove low-level references the backend cannot compile safely.

    The model may describe semantic flow intent, but exact structured field
    paths, form-variable joins, runtime-upload flags, and step-source invariants
    are canonical mechanics owned by the backend. Invalid mechanical details are
    normalized before proposal validation so the compiler can preserve semantic
    intent instead of rejecting an otherwise useful plan.
    """

    mechanically_normalized_steps: list[NewStepDraft] = []
    changed = False
    for step_index, step in enumerate(draft.steps):
        normalized_step = _normalize_step_mechanics(step, step_index=step_index)
        if normalized_step != step:
            changed = True
        mechanically_normalized_steps.append(normalized_step)

    updated_steps: list[NewStepDraft] = []
    known_form_fields = {field.variable_name for field in draft.form_fields}
    for step_index, step in enumerate(mechanically_normalized_steps):
        normalized_refs = _compile_safe_previous_field_refs(
            steps=mechanically_normalized_steps,
            step_index=step_index,
            refs=step.uses_previous_fields,
        )
        normalized_form_fields = [
            field_name
            for field_name in step.uses_form_fields
            if field_name in known_form_fields
        ]
        normalized_output_refs = _compile_safe_previous_output_refs(
            steps=mechanically_normalized_steps,
            step_index=step_index,
            refs=step.uses_previous_outputs,
        )
        if (
            normalized_refs == step.uses_previous_fields
            and normalized_output_refs == step.uses_previous_outputs
            and normalized_form_fields == step.uses_form_fields
        ):
            updated_steps.append(step)
            continue
        changed = True
        updated_steps.append(
            step.model_copy(
                update={
                    "uses_form_fields": normalized_form_fields,
                    "uses_previous_fields": normalized_refs,
                    "uses_previous_outputs": normalized_output_refs,
                }
            )
        )

    normalized_draft = (
        draft if not changed else draft.model_copy(update={"steps": updated_steps})
    )
    return normalize_create_draft_source_material(normalized_draft)


def _normalize_step_mechanics(
    step: NewStepDraft,
    *,
    step_index: int,
) -> NewStepDraft:
    updates: dict[str, Any] = {}
    input_source = step.input_source
    input_type = step.input_type
    output_type = step.output_type

    if step_index == 0 and input_source != InputSource.FLOW_INPUT:
        input_source = InputSource.FLOW_INPUT
        updates["input_source"] = input_source
    elif step_index > 0 and input_source == InputSource.FLOW_INPUT:
        input_source = InputSource.PREVIOUS_STEP
        updates["input_source"] = input_source

    if input_source == InputSource.ALL_PREVIOUS_STEPS and input_type == InputType.JSON:
        input_type = InputType.TEXT
        updates["input_type"] = input_type

    if input_source != InputSource.FLOW_INPUT and input_type in _FILE_INPUT_TYPES:
        input_type = InputType.TEXT
        updates["input_type"] = input_type

    if input_source == InputSource.FLOW_INPUT and input_type in _FILE_INPUT_TYPES:
        if not step.runtime_upload:
            updates["runtime_upload"] = True
    elif step.runtime_upload:
        updates["runtime_upload"] = False
        updates["runtime_required"] = False
        updates["runtime_max_files"] = None
    elif step.runtime_required or step.runtime_max_files is not None:
        updates["runtime_required"] = False
        updates["runtime_max_files"] = None

    if (
        step.document_delivery_mode != "not_applicable"
        and output_type not in _DOCUMENT_OUTPUT_TYPES
    ):
        updates["document_delivery_mode"] = "not_applicable"

    if step.citations_requested and (
        output_type != OutputType.TEXT or input_type == InputType.AUDIO
    ):
        updates["citations_requested"] = False

    return step.model_copy(update=updates) if updates else step


def _compile_safe_previous_field_refs(
    *,
    steps: list[NewStepDraft],
    step_index: int,
    refs: list[PreviousFieldRef],
) -> list[PreviousFieldRef]:
    safe_refs: list[PreviousFieldRef] = []
    seen: set[tuple[int, str]] = set()
    for field_ref in refs:
        target_index = field_ref.from_step - 1
        if target_index < 0 or target_index >= step_index:
            continue

        target_step = steps[target_index]
        if target_step.output_type != OutputType.JSON:
            continue
        if target_step.output_fields is None:
            continue
        if missing_draft_field_path(target_step.output_fields, field_ref.field_path):
            continue

        key = (field_ref.from_step, field_ref.field_path)
        if key in seen:
            continue
        seen.add(key)
        safe_refs.append(field_ref)
    return safe_refs


def _compile_safe_previous_output_refs(
    *,
    steps: list[NewStepDraft],
    step_index: int,
    refs: list[PreviousOutputRef],
) -> list[PreviousOutputRef]:
    safe_refs: list[PreviousOutputRef] = []
    seen: set[int] = set()
    for output_ref in refs:
        target_index = output_ref.from_step - 1
        if target_index < 0 or target_index >= step_index:
            continue
        target_step = steps[target_index]
        if target_step.output_type != OutputType.TEXT:
            continue
        if output_ref.from_step in seen:
            continue
        seen.add(output_ref.from_step)
        safe_refs.append(output_ref)
    return safe_refs


__all__ = [
    "normalize_create_draft_mechanics",
    "strip_malformed_previous_field_refs",
]
