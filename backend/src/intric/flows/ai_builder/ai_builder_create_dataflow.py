from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_critic_invariants import (
    TARGETED_UNDERLAG_SOFT_CAP,
)
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

if TYPE_CHECKING:
    from intric.flows.ai_builder.planning_state import AggregationIntent

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


def auto_bind_targeted_underlag_for_text_composer(
    steps: list[NewStepDraft],
    *,
    aggregation_intent: "AggregationIntent",
) -> list[NewStepDraft]:
    """Rewrite the last compositional text step so it reads JSON predecessors
    via explicit field refs instead of `all_previous_steps` or a single
    daisy-chained predecessor.

    Two source patterns qualify for the rewrite:

    - `all_previous_steps`: the skeleton's default for document-body
      composer steps in linear flows with three or more semantic phases.
      When earlier steps emit structured JSON output_contracts, the
      `prefer_targeted_underlag_over_all_previous_steps` semantic critic
      fires and the LLM is asked to switch to `previous_step` plus
      `uses_previous_fields` references. Those mechanics are backend-owned
      — stripped from outline_flow before the model ever sees them — so
      the repair loop spins on the same complaint until it bails.
    - `previous_step` with two or more prior content steps emitting JSON
      contracts: the composer would otherwise see only the immediate
      predecessor and silently lose the earlier extractions. The rewrite
      keeps `previous_step` and populates `uses_previous_fields` across
      every JSON prior. Single-extraction → composer pipelines remain
      untouched (the floor is two JSON priors).

    Authoring the refs from the JSON predecessors' contracts at draft
    time makes the spec satisfy the targeted-underlag policy without
    depending on the planner.

    Suppression matches the critic invariant: `aggregate`/`compare`
    intents need fan-in for cross-document compositions, prior content
    counts above the soft cap make targeted underlag unwieldy, and a
    composer that already targets fields is left alone.
    """
    if aggregation_intent in {"aggregate", "compare"}:
        return steps
    composer_index = _last_compositional_step_index(steps)
    if composer_index is None or composer_index == 0:
        return steps
    composer = steps[composer_index]
    if composer.input_source not in (
        InputSource.ALL_PREVIOUS_STEPS,
        InputSource.PREVIOUS_STEP,
    ):
        return steps
    if composer.output_type != OutputType.TEXT:
        return steps
    if (
        composer.input_source == InputSource.ALL_PREVIOUS_STEPS
        and composer.input_type != InputType.TEXT
    ):
        return steps
    if composer.uses_previous_fields:
        return steps

    priors = [
        (index, step)
        for index, step in enumerate(steps[:composer_index])
        if not _is_renderer_draft(step)
    ]
    if not priors or len(priors) > TARGETED_UNDERLAG_SOFT_CAP:
        return steps

    json_priors = [
        (index, step)
        for index, step in priors
        if step.output_type == OutputType.JSON and step.output_fields
    ]
    if not json_priors:
        return steps
    if composer.input_source == InputSource.PREVIOUS_STEP and len(json_priors) < 2:
        return steps

    new_field_refs: list[PreviousFieldRef] = []
    seen_field_keys: set[tuple[int, str]] = set()
    for predecessor_index, predecessor in json_priors:
        for field in predecessor.output_fields or []:
            key = (predecessor_index + 1, field.name)
            if key in seen_field_keys:
                continue
            seen_field_keys.add(key)
            new_field_refs.append(
                PreviousFieldRef(
                    from_step=predecessor_index + 1,
                    field_path=field.name,
                    label=(field.description or field.name).strip() or field.name,
                )
            )

    new_output_refs: list[PreviousOutputRef] = list(composer.uses_previous_outputs)
    seen_output_steps = {ref.from_step for ref in new_output_refs}
    for predecessor_index, predecessor in priors:
        if predecessor.output_type != OutputType.TEXT:
            continue
        if predecessor_index + 1 in seen_output_steps:
            continue
        seen_output_steps.add(predecessor_index + 1)
        new_output_refs.append(
            PreviousOutputRef(
                from_step=predecessor_index + 1,
                label=predecessor.name or f"Steg {predecessor_index + 1}",
            )
        )

    immediate_predecessor = steps[composer_index - 1]
    new_input_type = (
        InputType.JSON
        if immediate_predecessor.output_type == OutputType.JSON
        else InputType.TEXT
    )

    rewritten = composer.model_copy(
        update={
            "input_source": InputSource.PREVIOUS_STEP,
            "input_type": new_input_type,
            "uses_previous_fields": new_field_refs,
            "uses_previous_outputs": new_output_refs,
        }
    )
    new_steps = list(steps)
    new_steps[composer_index] = rewritten
    return new_steps


def _last_compositional_step_index(steps: list[NewStepDraft]) -> int | None:
    for index in range(len(steps) - 1, -1, -1):
        if not _is_renderer_draft(steps[index]):
            return index
    return None


def _is_renderer_draft(step: NewStepDraft) -> bool:
    return (
        step.document_delivery_mode == "template_fill"
        or step.output_type in _DOCUMENT_OUTPUT_TYPES
    )


__all__ = [
    "auto_bind_targeted_underlag_for_text_composer",
    "normalize_create_draft_mechanics",
    "strip_malformed_previous_field_refs",
]
