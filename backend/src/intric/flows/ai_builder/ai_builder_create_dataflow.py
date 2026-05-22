from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_critic_invariants import (
    TARGETED_UNDERLAG_SOFT_CAP,
    targeted_underlag_all_previous_indexes_for_drafts,
)
from intric.flows.ai_builder.ai_builder_mechanical_refs import (
    clean_raw_previous_field_refs,
)
from intric.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    PreviousFieldRef,
    PreviousOutputRef,
    StructuredFieldDraft,
)
from intric.flows.ai_builder.ai_builder_source_material import (
    normalize_create_draft_source_material,
)
from intric.flows.ai_builder.ai_builder_structured_field_paths import (
    missing_draft_field_path,
)
from intric.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    OutputType,
)

if TYPE_CHECKING:
    from intric.flows.ai_builder.planning_state import AggregationIntent

_FILE_INPUT_TYPES = {InputType.AUDIO, InputType.DOCUMENT, InputType.FILE}
_DOCUMENT_OUTPUT_TYPES = {OutputType.DOCX, OutputType.PDF}
TARGETED_UNDERLAG_FIELDS_PER_JSON_PRIOR_CAP = 3
TARGETED_UNDERLAG_TOTAL_FIELD_CAP = 8


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


def normalize_create_draft_mechanics(
    draft: FlowCreateDraft,
    *,
    aggregation_intent: "AggregationIntent" = "linear",
) -> FlowCreateDraft:
    """Remove low-level references the backend cannot compile safely.

    The model may describe semantic flow intent, but exact structured field
    paths, form-variable joins, runtime-upload flags, and step-source invariants
    are canonical mechanics owned by the backend. Invalid mechanical details are
    normalized before proposal validation so the compiler can preserve semantic
    intent instead of rejecting an otherwise useful plan.
    """

    normalized_draft = _normalize_create_draft_refs(draft)
    source_normalized_draft = normalize_create_draft_source_material(normalized_draft)
    rebound_steps = auto_bind_targeted_underlag_for_text_composer(
        source_normalized_draft.steps,
        aggregation_intent=aggregation_intent,
    )
    rebound_draft = (
        source_normalized_draft
        if rebound_steps is source_normalized_draft.steps
        else source_normalized_draft.model_copy(update={"steps": rebound_steps})
    )
    return _normalize_create_draft_refs(rebound_draft)


def _normalize_create_draft_refs(draft: FlowCreateDraft) -> FlowCreateDraft:
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

    return draft if not changed else draft.model_copy(update={"steps": updated_steps})


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

    if (
        input_source != InputSource.FLOW_INPUT
        and output_type == OutputType.TEXT
        and input_type == InputType.JSON
        and (step.uses_previous_fields or step.uses_previous_outputs)
    ):
        # Explicit refs compile into input_bindings.question, which the runtime
        # treats as complete text input rather than augmenting structured JSON.
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
    """Rewrite compositional text steps so they read JSON predecessors
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
      untouched unless source-material normalization has already proved
      the step is composing structured fields with a separate text source.

    Outline mode strips backend-owned refs, so this pass must synthesize
    refs from declared contracts instead of asking the model to author them.

    Suppression matches the critic invariant: `aggregate`/`compare`
    intents need fan-in for cross-document compositions, prior content
    counts above the soft cap make targeted underlag unwieldy, and a
    composer that already targets fields is left alone.
    """
    if aggregation_intent in {"aggregate", "compare"}:
        return steps

    rewritten_steps = steps
    changed = False
    for composer_index in targeted_underlag_all_previous_indexes_for_drafts(
        rewritten_steps,
        aggregation_intent=aggregation_intent,
    ):
        updated_steps = _bind_targeted_underlag_for_composer(
            rewritten_steps,
            composer_index=composer_index,
            require_multiple_json_priors=False,
        )
        if updated_steps is not rewritten_steps:
            rewritten_steps = updated_steps
            changed = True

    composer_index = _last_compositional_step_index(rewritten_steps)
    if composer_index is not None:
        composer = rewritten_steps[composer_index]
        if (
            composer.input_source == InputSource.PREVIOUS_STEP
            and composer.input_type in {InputType.JSON, InputType.TEXT}
            and not composer.uses_previous_fields
        ):
            updated_steps = _bind_targeted_underlag_for_composer(
                rewritten_steps,
                composer_index=composer_index,
                require_multiple_json_priors=True,
            )
            if updated_steps is not rewritten_steps:
                rewritten_steps = updated_steps
                changed = True

    return rewritten_steps if changed else steps


def _bind_targeted_underlag_for_composer(
    steps: list[NewStepDraft],
    *,
    composer_index: int,
    require_multiple_json_priors: bool,
) -> list[NewStepDraft]:
    composer = steps[composer_index]

    priors = [
        (index, step)
        for index, step in enumerate(steps[:composer_index])
        if not _is_renderer_draft(step)
    ]
    if not priors:
        return steps

    text_priors_count = sum(
        1 for _, step in priors if step.output_type == OutputType.TEXT
    )
    if text_priors_count > TARGETED_UNDERLAG_SOFT_CAP:
        return steps

    json_priors = [
        (index, step)
        for index, step in priors
        if step.output_type == OutputType.JSON and step.output_fields
    ]
    if not json_priors:
        return steps
    if (
        require_multiple_json_priors
        and len(json_priors) < 2
        and not composer.uses_previous_outputs
    ):
        return steps

    new_field_refs = _select_targeted_underlag_field_refs(json_priors)
    if not new_field_refs:
        return steps

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

    rewritten = composer.model_copy(
        update={
            "input_source": InputSource.PREVIOUS_STEP,
            "uses_previous_fields": new_field_refs,
            "uses_previous_outputs": new_output_refs,
        }
    )
    new_steps = list(steps)
    new_steps[composer_index] = rewritten
    return new_steps


def _select_targeted_underlag_field_refs(
    json_priors: list[tuple[int, NewStepDraft]],
) -> list[PreviousFieldRef]:
    ordered_priors = [
        (
            predecessor_index,
            _ordered_targeted_underlag_fields(predecessor)[
                :TARGETED_UNDERLAG_FIELDS_PER_JSON_PRIOR_CAP
            ],
        )
        for predecessor_index, predecessor in json_priors
    ]
    ordered_priors = [(index, fields) for index, fields in ordered_priors if fields]
    if not ordered_priors:
        return []

    effective_total_cap = max(
        TARGETED_UNDERLAG_TOTAL_FIELD_CAP,
        len(ordered_priors),
    )
    selected: list[PreviousFieldRef] = []
    positions = [0 for _ in ordered_priors]

    for prior_position, (predecessor_index, fields) in enumerate(ordered_priors):
        selected.append(_field_ref_from_draft_field(predecessor_index, fields[0]))
        positions[prior_position] = 1
        if len(selected) >= effective_total_cap:
            return selected

    while len(selected) < effective_total_cap:
        advanced = False
        for prior_position, (predecessor_index, fields) in enumerate(ordered_priors):
            field_position = positions[prior_position]
            if field_position >= len(fields):
                continue
            selected.append(
                _field_ref_from_draft_field(
                    predecessor_index,
                    fields[field_position],
                )
            )
            positions[prior_position] += 1
            advanced = True
            if len(selected) >= effective_total_cap:
                break
        if not advanced:
            break

    return selected


def _ordered_targeted_underlag_fields(
    step: NewStepDraft,
) -> list[StructuredFieldDraft]:
    fields = list(step.output_fields or [])
    fields_by_priority = [
        *(field for field in fields if field.required),
        *(field for field in fields if not field.required),
    ]
    selected_fields: list[StructuredFieldDraft] = []
    seen_field_names: set[str] = set()
    for field in fields_by_priority:
        if field.name in seen_field_names:
            continue
        seen_field_names.add(field.name)
        selected_fields.append(field)
    return selected_fields


def _field_ref_from_draft_field(
    predecessor_index: int,
    field: StructuredFieldDraft,
) -> PreviousFieldRef:
    return PreviousFieldRef(
        from_step=predecessor_index + 1,
        field_path=field.name,
        label=(field.description or field.name).strip() or field.name,
    )


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
    "TARGETED_UNDERLAG_FIELDS_PER_JSON_PRIOR_CAP",
    "TARGETED_UNDERLAG_TOTAL_FIELD_CAP",
    "auto_bind_targeted_underlag_for_text_composer",
    "normalize_create_draft_mechanics",
    "strip_malformed_previous_field_refs",
]
