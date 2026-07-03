from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    normalize_discovery_text,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    derive_position_input_source,
    normalize_new_step_input_shape,
    require_resolved_input_source,
    resolve_omitted_input_source,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    PreviousFieldRef,
    PreviousOutputRef,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_source_material import (
    create_steps_return_material_report,
    primary_source_material_ref_for_steps,
)
from eneo.flows.ai_builder.ai_builder_structured_field_paths import (
    missing_draft_field_path,
)
from eneo.flows.ai_builder.ai_builder_underlag_policy import (
    TARGETED_UNDERLAG_SOFT_CAP,
    TargetedUnderlagStepSignal,
    final_assembler_rewrite_indexes,
    is_document_renderer,
    is_source_surfacing_text,
    targeted_underlag_rewrite_indexes,
    terminal_renderer_rewrite_indexes,
)
from eneo.flows.flow_authoring_spec import (
    FormFieldSpec,
    InputSource,
    InputType,
    OutputType,
)

if TYPE_CHECKING:
    from eneo.flows.ai_builder.planning_state import AggregationIntent

_DOCUMENT_OUTPUT_TYPES = {OutputType.DOCX, OutputType.PDF}
TARGETED_UNDERLAG_FIELDS_PER_JSON_PRIOR_CAP = 3
TARGETED_UNDERLAG_TOTAL_FIELD_CAP = 8
TARGETED_UNDERLAG_BROAD_FIELD_CAP = 16
_TargetedUnderlagBindingMode = Literal["skip", "with_text_priors", "fields_only"]
_PreviousRefKind = Literal["uses_previous_fields", "uses_previous_outputs"]
_PreviousRefFailureReason = Literal[
    "previous_field_step_not_prior",
    "previous_field_source_not_json",
    "previous_field_source_missing_output_fields",
    "unknown_previous_field_path",
    "previous_output_step_not_prior",
    "previous_output_source_not_text",
]
_UNDERLAG_ALWAYS_BROAD_COMPOSER_MARKERS = (
    "bygg docx",
    "docx innehall",
    "docx innehåll",
    "dokumentets fullstandiga",
    "dokumentets fullständiga",
    "fardigt dokument",
    "färdigt dokument",
    "fardigt word",
    "färdigt word",
    "forbered docx",
    "förbered docx",
    "fullstandiga text",
    "fullständiga text",
    "sammanstall dokument",
    "sammanställ dokument",
    "sammanstall slutligt",
    "sammanställ slutligt",
    "sammanstall word",
    "sammanställ word",
    "skapa docx",
    "skapa word",
    "slutlig dokument",
    "slutligt dokument",
    "slutlig word",
    "slutligt word",
    "forbered word",
    "förbered word",
)
_UNDERLAG_BROAD_COMPOSER_MARKERS = (
    "alla avsnitt",
    "alla rubriker",
    "flera avsnitt",
    "verksamhetsavsnitt",
    *_UNDERLAG_ALWAYS_BROAD_COMPOSER_MARKERS,
)
_UNDERLAG_MATCH_STOPWORDS = frozenset(
    {
        "ai",
        "alla",
        "ange",
        "att",
        "av",
        "beskriv",
        "det",
        "dokument",
        "dokumentet",
        "en",
        "ett",
        "for",
        "fran",
        "from",
        "gora",
        "gör",
        "hela",
        "i",
        "med",
        "nedan",
        "och",
        "om",
        "pa",
        "plan",
        "rubrik",
        "ska",
        "skall",
        "skapa",
        "skriv",
        "som",
        "steg",
        "text",
        "the",
        "till",
        "under",
        "underlag",
        "ursprungliga",
        "ur",
    }
)
_UNDERLAG_SOURCE_SUMMARY_TOKENS = frozenset(
    {
        "helhet",
        "kallmaterial",
        "material",
        "sammanfattning",
        "sammanhang",
        "underlag",
    }
)
_UNDERLAG_MIN_TOKEN_PREFIX = 4
_UNDERLAG_SWEDISH_SUFFIXES = (
    "heternas",
    "heterna",
    "arnas",
    "ernas",
    "orna",
    "arna",
    "erna",
    "ande",
    "het",
    "ens",
    "ets",
    "nas",
    "en",
    "et",
    "na",
    "ar",
    "er",
    "or",
)


def normalize_create_step_mechanics(
    *,
    steps: list[NewStepDraft],
    form_fields: list[FormFieldSpec],
    flow_name: str,
    flow_description: str | None,
    aggregation_intent: "AggregationIntent" = "linear",
) -> list[NewStepDraft]:
    """Normalize server-owned create mechanics before compiling a flow.

    The model may describe semantic flow intent, but exact structured field
    paths, form-variable joins, runtime-upload flags, and step-source invariants
    are canonical mechanics owned by the backend. Previous-step underlag refs
    are backend-generated in create mode; invalid refs indicate an architecture
    bug and must fail before runtime.
    """

    normalized_steps = _normalize_create_step_refs(
        steps,
        form_fields=form_fields,
    )
    rebound_steps = auto_bind_targeted_underlag_for_text_composer(
        normalized_steps,
        flow_name=flow_name,
        flow_description=flow_description,
        aggregation_intent=aggregation_intent,
    )
    return _normalize_create_step_refs(
        rebound_steps,
        form_fields=form_fields,
    )


def _normalize_create_step_refs(
    steps: list[NewStepDraft],
    *,
    form_fields: list[FormFieldSpec],
) -> list[NewStepDraft]:
    mechanically_normalized_steps: list[NewStepDraft] = []
    changed = False
    for step_index, step in enumerate(steps):
        normalized_step = _normalize_step_mechanics(step, step_index=step_index)
        if normalized_step != step:
            changed = True
        mechanically_normalized_steps.append(normalized_step)

    updated_steps: list[NewStepDraft] = []
    known_form_fields = {field.name for field in form_fields}
    for step_index, step in enumerate(mechanically_normalized_steps):
        # Previous-step refs are backend-generated after create-intent stripping.
        # Form fields stay tolerant because runtime hints can complete their names.
        normalized_refs = _require_valid_previous_field_refs(
            steps=mechanically_normalized_steps,
            step_index=step_index,
            refs=step.uses_previous_fields,
        )
        normalized_form_fields = [
            field_name
            for field_name in step.uses_form_fields
            if field_name in known_form_fields
        ]
        normalized_output_refs = _require_valid_previous_output_refs(
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

    return updated_steps if changed else steps


def _normalize_step_mechanics(
    step: NewStepDraft,
    *,
    step_index: int,
) -> NewStepDraft:
    updates: dict[str, Any] = {}
    step = resolve_omitted_input_source(step, step_index=step_index)
    input_source = require_resolved_input_source(step)
    positional_input_source = derive_position_input_source(step_index)

    if input_source != positional_input_source and (
        step_index == 0 or input_source == InputSource.FLOW_INPUT
    ):
        input_source = positional_input_source
        updates["input_source"] = input_source

    if updates:
        step = step.model_copy(update=updates)
    step = normalize_new_step_input_shape(step, step_index=step_index)
    input_type = step.input_type
    output_type = step.output_type
    updates = {}

    if (
        step.document_delivery_mode == "template_fill"
        and output_type != OutputType.DOCX
    ):
        # DOCX is the only template-fill runtime; other document outputs are generated.
        updates["document_delivery_mode"] = (
            "generated" if output_type in _DOCUMENT_OUTPUT_TYPES else "not_applicable"
        )
    elif (
        step.document_delivery_mode != "not_applicable"
        and output_type not in _DOCUMENT_OUTPUT_TYPES
    ):
        updates["document_delivery_mode"] = "not_applicable"

    if step.citations_requested and (
        output_type != OutputType.TEXT or input_type == InputType.AUDIO
    ):
        updates["citations_requested"] = False

    return step.model_copy(update=updates) if updates else step


def _require_valid_previous_field_refs(
    *,
    steps: list[NewStepDraft],
    step_index: int,
    refs: list[PreviousFieldRef],
) -> list[PreviousFieldRef]:
    valid_refs: list[PreviousFieldRef] = []
    seen: set[tuple[int, str]] = set()
    for field_ref in refs:
        target_index = field_ref.from_step - 1
        if target_index < 0 or target_index >= step_index:
            raise _invalid_previous_ref_error(
                reason="previous_field_step_not_prior",
                ref_kind="uses_previous_fields",
                step_index=step_index,
                from_step=field_ref.from_step,
                field_path=field_ref.field_path,
            )

        target_step = steps[target_index]
        if target_step.output_type != OutputType.JSON:
            raise _invalid_previous_ref_error(
                reason="previous_field_source_not_json",
                ref_kind="uses_previous_fields",
                step_index=step_index,
                from_step=field_ref.from_step,
                field_path=field_ref.field_path,
                source_output_type=target_step.output_type,
            )
        if target_step.output_fields is None:
            raise _invalid_previous_ref_error(
                reason="previous_field_source_missing_output_fields",
                ref_kind="uses_previous_fields",
                step_index=step_index,
                from_step=field_ref.from_step,
                field_path=field_ref.field_path,
                source_output_type=target_step.output_type,
            )
        if missing_draft_field_path(target_step.output_fields, field_ref.field_path):
            raise _invalid_previous_ref_error(
                reason="unknown_previous_field_path",
                ref_kind="uses_previous_fields",
                step_index=step_index,
                from_step=field_ref.from_step,
                field_path=field_ref.field_path,
                source_output_type=target_step.output_type,
            )

        key = (field_ref.from_step, field_ref.field_path)
        if key in seen:
            continue
        seen.add(key)
        valid_refs.append(field_ref)
    return valid_refs


def _require_valid_previous_output_refs(
    *,
    steps: list[NewStepDraft],
    step_index: int,
    refs: list[PreviousOutputRef],
) -> list[PreviousOutputRef]:
    valid_refs: list[PreviousOutputRef] = []
    seen: set[int] = set()
    for output_ref in refs:
        target_index = output_ref.from_step - 1
        if target_index < 0 or target_index >= step_index:
            raise _invalid_previous_ref_error(
                reason="previous_output_step_not_prior",
                ref_kind="uses_previous_outputs",
                step_index=step_index,
                from_step=output_ref.from_step,
            )
        target_step = steps[target_index]
        if target_step.output_type != OutputType.TEXT:
            raise _invalid_previous_ref_error(
                reason="previous_output_source_not_text",
                ref_kind="uses_previous_outputs",
                step_index=step_index,
                from_step=output_ref.from_step,
                source_output_type=target_step.output_type,
            )
        if output_ref.from_step in seen:
            continue
        seen.add(output_ref.from_step)
        valid_refs.append(output_ref)
    return valid_refs


def _invalid_previous_ref_error(
    *,
    reason: _PreviousRefFailureReason,
    ref_kind: _PreviousRefKind,
    step_index: int,
    from_step: int,
    field_path: str | None = None,
    source_output_type: OutputType | None = None,
) -> AIBuilderArchitectureError:
    return AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail=f"AI Builder create dataflow emitted invalid {ref_kind}: {reason}.",
        log_context={
            "reason": reason,
            "ref_kind": ref_kind,
            "current_step": step_index + 1,
            "from_step": from_step,
            "field_path": field_path,
            "source_output_type": (
                source_output_type.value if source_output_type is not None else None
            ),
        },
    )


def auto_bind_targeted_underlag_for_text_composer(
    steps: list[NewStepDraft],
    *,
    flow_name: str,
    flow_description: str | None,
    aggregation_intent: "AggregationIntent",
) -> list[NewStepDraft]:
    """Bind composer underlag from backend-owned draft mechanics.

    Source-material labeling stays owned by ai_builder_source_material; this
    pass owns only the targeted field/output refs that keep composers from
    reading broad structured JSON blobs.
    """
    rewritten_steps = steps
    # Source detection must run after the first mechanics pass so source_ref
    # indexes match the step snapshot that targeted-underlag binding rewrites.
    source_ref = primary_source_material_ref_for_steps(
        steps=steps,
        flow_name=flow_name,
        flow_description=flow_description,
    )
    returns_material_report = create_steps_return_material_report(steps)
    # Capture candidates before rewrites because each pass mutates input_source.
    terminal_renderer_candidate_indexes = set(
        _terminal_renderer_rewrite_indexes_for_steps(rewritten_steps)
    )
    all_previous_candidate_indexes = set(
        _targeted_underlag_rewrite_indexes_for_steps(
            rewritten_steps,
            aggregation_intent=aggregation_intent,
        )
    )
    final_assembler_candidate_indexes = set(
        _final_assembler_rewrite_indexes_for_steps(
            rewritten_steps,
            aggregation_intent=aggregation_intent,
        )
    )
    changed = False
    if terminal_renderer_candidate_indexes:
        updated_steps = _bind_terminal_renderers_to_previous_composer(
            rewritten_steps,
            renderer_indexes=terminal_renderer_candidate_indexes,
        )
        if updated_steps is not rewritten_steps:
            rewritten_steps = updated_steps
            changed = True
    if aggregation_intent == "compare":
        return rewritten_steps if changed else steps
    for composer_index in range(len(rewritten_steps)):
        if composer_index in final_assembler_candidate_indexes:
            updated_steps = _bind_final_assembler_prior_outputs(
                rewritten_steps,
                composer_index=composer_index,
            )
            if updated_steps is not rewritten_steps:
                rewritten_steps = updated_steps
                changed = True
                continue
        binding_mode = _targeted_underlag_binding_mode(
            steps=rewritten_steps,
            composer_index=composer_index,
            all_previous_candidate_indexes=all_previous_candidate_indexes,
            primary_source_ref=source_ref,
            returns_material_report=returns_material_report,
            aggregation_intent=aggregation_intent,
        )
        if binding_mode == "skip":
            continue
        updated_steps = _bind_targeted_underlag_for_composer(
            rewritten_steps,
            composer_index=composer_index,
            primary_source_ref=source_ref,
            returns_material_report=returns_material_report,
            include_text_priors=binding_mode == "with_text_priors",
            allow_priority_fallback=binding_mode == "with_text_priors",
        )
        if updated_steps is not rewritten_steps:
            rewritten_steps = updated_steps
            changed = True

    return rewritten_steps if changed else steps


def _terminal_renderer_rewrite_indexes_for_steps(
    steps: list[NewStepDraft],
) -> tuple[int, ...]:
    return terminal_renderer_rewrite_indexes(
        _underlag_step_signals_for_steps(steps),
    )


def _targeted_underlag_rewrite_indexes_for_steps(
    steps: list[NewStepDraft],
    *,
    aggregation_intent: "AggregationIntent",
) -> tuple[int, ...]:
    return targeted_underlag_rewrite_indexes(
        _underlag_step_signals_for_steps(steps),
        aggregation_intent=aggregation_intent,
    )


def _final_assembler_rewrite_indexes_for_steps(
    steps: list[NewStepDraft],
    *,
    aggregation_intent: "AggregationIntent",
) -> tuple[int, ...]:
    return final_assembler_rewrite_indexes(
        _underlag_step_signals_for_steps(steps),
        aggregation_intent=aggregation_intent,
    )


def _underlag_step_signals_for_steps(
    steps: list[NewStepDraft],
) -> tuple[TargetedUnderlagStepSignal, ...]:
    """Create-step mode has no compiled question, so it cannot count refs."""
    return tuple(
        TargetedUnderlagStepSignal(
            input_source=require_resolved_input_source(step),
            input_type=step.input_type,
            output_type=step.output_type,
            is_renderer=_is_renderer_draft(step),
            has_structured_json_output=(
                step.output_type == OutputType.JSON and bool(step.output_fields)
            ),
            already_targets_previous_fields=bool(step.uses_previous_fields),
            question_targets_prior_structured_field=False,
            is_source_surfacing_text=is_source_surfacing_text(
                input_source=require_resolved_input_source(step),
                input_type=step.input_type,
                output_type=step.output_type,
            ),
        )
        for step in steps
    )


def _bind_terminal_renderers_to_previous_composer(
    steps: list[NewStepDraft],
    *,
    renderer_indexes: set[int],
) -> list[NewStepDraft]:
    """Reset terminal renderers to read only the previous composed text body."""
    rewritten_steps = list(steps)
    changed = False
    for renderer_index in sorted(renderer_indexes):
        renderer = rewritten_steps[renderer_index]
        rewritten_steps[renderer_index] = renderer.model_copy(
            update={
                "input_source": InputSource.PREVIOUS_STEP,
                "uses_previous_fields": [],
                "uses_previous_outputs": [],
            }
        )
        changed = True
    return rewritten_steps if changed else steps


def _targeted_underlag_binding_mode(
    *,
    steps: list[NewStepDraft],
    composer_index: int,
    all_previous_candidate_indexes: set[int],
    primary_source_ref: PreviousOutputRef | None,
    returns_material_report: bool,
    aggregation_intent: "AggregationIntent",
) -> _TargetedUnderlagBindingMode:
    """Choose whether to add structured fields, prior text outputs, or neither."""
    composer = steps[composer_index]
    if _is_renderer_draft(composer):
        return "skip"
    if aggregation_intent == "compare":
        return "skip"

    priors = _targeted_underlag_prior_steps(steps, composer_index=composer_index)
    if not priors:
        return "skip"

    json_priors = _targeted_underlag_json_priors(priors)
    if not json_priors:
        return "skip"
    if composer.uses_previous_fields:
        if _prebound_broad_composer_missing_json_prior(
            composer=composer,
            priors=priors,
            json_priors=json_priors,
        ):
            return "with_text_priors"
        return "skip"

    if composer.input_source == InputSource.ALL_PREVIOUS_STEPS:
        return (
            "with_text_priors"
            if composer_index in all_previous_candidate_indexes
            else "skip"
        )
    if composer.input_source != InputSource.PREVIOUS_STEP:
        return "skip"
    if composer.input_type not in {InputType.JSON, InputType.TEXT}:
        return "skip"

    text_priors_count = sum(
        1 for _, step in priors if step.output_type == OutputType.TEXT
    )
    if (
        composer.output_type == OutputType.TEXT
        and _looks_like_always_broad_underlag_composer(composer)
    ):
        return (
            "with_text_priors"
            if text_priors_count <= TARGETED_UNDERLAG_SOFT_CAP
            else "fields_only"
        )

    if composer.output_type == OutputType.TEXT and _json_section_writer_chain(
        steps=steps,
        composer_index=composer_index,
        json_priors=json_priors,
    ):
        return "fields_only"

    if text_priors_count > TARGETED_UNDERLAG_SOFT_CAP:
        return "skip"
    if len(json_priors) >= 2:
        return "with_text_priors"
    if _single_json_prior_needs_source_material(
        steps=steps,
        composer_index=composer_index,
        primary_source_ref=primary_source_ref,
        returns_material_report=returns_material_report,
    ):
        return "with_text_priors"
    return "skip"


def _single_json_prior_needs_source_material(
    *,
    steps: list[NewStepDraft],
    composer_index: int,
    primary_source_ref: PreviousOutputRef | None,
    returns_material_report: bool,
) -> bool:
    if primary_source_ref is None or not returns_material_report:
        return False
    if composer_index == 0 or primary_source_ref.from_step >= composer_index + 1:
        return False

    # The composer consumes structured-only output from the immediate JSON
    # predecessor; include the source text so the original material is not lost.
    return steps[composer_index - 1].output_type == OutputType.JSON


def _bind_final_assembler_prior_outputs(
    steps: list[NewStepDraft],
    *,
    composer_index: int,
) -> list[NewStepDraft]:
    composer = steps[composer_index]
    output_refs: list[PreviousOutputRef] = list(composer.uses_previous_outputs)
    seen_output_steps = {ref.from_step for ref in output_refs}

    for predecessor_index, predecessor in enumerate(steps[:composer_index]):
        if _is_renderer_draft(predecessor):
            continue
        if predecessor.output_type != OutputType.TEXT:
            continue
        if is_source_surfacing_text(
            input_source=require_resolved_input_source(predecessor),
            input_type=predecessor.input_type,
            output_type=predecessor.output_type,
        ):
            continue
        step_number = predecessor_index + 1
        if step_number in seen_output_steps:
            continue
        seen_output_steps.add(step_number)
        output_refs.append(
            PreviousOutputRef(
                from_step=step_number,
                label=predecessor.name or f"Steg {step_number}",
            )
        )

    if not output_refs:
        return steps

    rewritten = composer.model_copy(
        update={
            "input_source": InputSource.PREVIOUS_STEP,
            "uses_previous_outputs": output_refs,
        }
    )
    new_steps = list(steps)
    new_steps[composer_index] = rewritten
    return new_steps


def _prebound_broad_composer_missing_json_prior(
    *,
    composer: NewStepDraft,
    priors: list[tuple[int, NewStepDraft]],
    json_priors: list[tuple[int, NewStepDraft]],
) -> bool:
    """Refill broad composers when planner-supplied field refs missed a JSON prior."""
    if not _looks_like_broad_underlag_composer(composer):
        return False
    if composer.input_source != InputSource.PREVIOUS_STEP:
        return False
    if composer.input_type not in {InputType.JSON, InputType.TEXT}:
        return False
    text_priors_count = sum(
        1 for _, step in priors if step.output_type == OutputType.TEXT
    )
    if text_priors_count > TARGETED_UNDERLAG_SOFT_CAP:
        return False
    json_prior_steps = {predecessor_index + 1 for predecessor_index, _ in json_priors}
    covered_steps = {field_ref.from_step for field_ref in composer.uses_previous_fields}
    return bool(json_prior_steps - covered_steps)


def _json_section_writer_chain(
    *,
    steps: list[NewStepDraft],
    composer_index: int,
    json_priors: list[tuple[int, NewStepDraft]],
) -> bool:
    if not json_priors:
        return False
    if not _looks_like_section_or_document_composer(steps[composer_index]):
        return False
    json_index = min(index for index, _json_step in json_priors)
    if composer_index <= json_index:
        return False
    downstream_text_composers = [
        index
        for index, step in enumerate(steps[json_index + 1 :], start=json_index + 1)
        if step.output_type == OutputType.TEXT and not _is_renderer_draft(step)
    ]
    return composer_index in downstream_text_composers and (
        len(downstream_text_composers) >= 2
    )


def _bind_targeted_underlag_for_composer(
    steps: list[NewStepDraft],
    *,
    composer_index: int,
    primary_source_ref: PreviousOutputRef | None,
    returns_material_report: bool,
    include_text_priors: bool,
    allow_priority_fallback: bool,
) -> list[NewStepDraft]:
    composer = steps[composer_index]

    priors = _targeted_underlag_prior_steps(steps, composer_index=composer_index)
    json_priors = _targeted_underlag_json_priors(priors)

    new_field_refs = _select_targeted_underlag_field_refs(
        composer=composer,
        json_priors=json_priors,
        allow_priority_fallback=allow_priority_fallback,
    )
    if not new_field_refs:
        return steps
    new_field_refs = _merge_previous_field_refs(
        composer.uses_previous_fields,
        new_field_refs,
    )

    new_output_refs: list[PreviousOutputRef] = list(composer.uses_previous_outputs)
    seen_output_steps = {ref.from_step for ref in new_output_refs}
    added_primary_source_ref = False
    if include_text_priors:
        for predecessor_index, predecessor in priors:
            if predecessor.output_type != OutputType.TEXT:
                continue
            if predecessor_index + 1 in seen_output_steps:
                continue
            seen_output_steps.add(predecessor_index + 1)
            label = predecessor.name or f"Steg {predecessor_index + 1}"
            if (
                primary_source_ref is not None
                and primary_source_ref.from_step == predecessor_index + 1
            ):
                label = primary_source_ref.label
                added_primary_source_ref = True
            new_output_refs.append(
                PreviousOutputRef(
                    from_step=predecessor_index + 1,
                    label=label,
                )
            )

    updates: dict[str, object] = {
        "input_source": InputSource.PREVIOUS_STEP,
        "uses_previous_fields": new_field_refs,
        "uses_previous_outputs": new_output_refs,
    }
    if added_primary_source_ref and _single_json_prior_needs_source_material(
        steps=steps,
        composer_index=composer_index,
        primary_source_ref=primary_source_ref,
        returns_material_report=returns_material_report,
    ):
        updates["input_type"] = InputType.TEXT

    rewritten = composer.model_copy(
        update=updates,
    )
    new_steps = list(steps)
    new_steps[composer_index] = rewritten
    return new_steps


def _merge_previous_field_refs(
    existing_refs: list[PreviousFieldRef],
    candidate_refs: list[PreviousFieldRef],
) -> list[PreviousFieldRef]:
    merged = list(existing_refs)
    seen = {(ref.from_step, ref.field_path) for ref in merged}
    for candidate in candidate_refs:
        key = (candidate.from_step, candidate.field_path)
        if key in seen:
            continue
        merged.append(candidate)
        seen.add(key)
    return merged


def _targeted_underlag_prior_steps(
    steps: list[NewStepDraft],
    *,
    composer_index: int,
) -> list[tuple[int, NewStepDraft]]:
    return [
        (index, step)
        for index, step in enumerate(steps[:composer_index])
        if not _is_renderer_draft(step)
    ]


def _targeted_underlag_json_priors(
    priors: list[tuple[int, NewStepDraft]],
) -> list[tuple[int, NewStepDraft]]:
    return [
        (index, step)
        for index, step in priors
        if step.output_type == OutputType.JSON and step.output_fields
    ]


def _select_targeted_underlag_field_refs(
    *,
    composer: NewStepDraft,
    json_priors: list[tuple[int, NewStepDraft]],
    allow_priority_fallback: bool,
) -> list[PreviousFieldRef]:
    """Select schema-aware underlag: broad, semantic, summary, floor, fallback."""
    ordered_priors = [
        (
            predecessor_index,
            _ordered_targeted_underlag_fields(predecessor),
        )
        for predecessor_index, predecessor in json_priors
    ]
    ordered_priors = [(index, fields) for index, fields in ordered_priors if fields]
    if not ordered_priors:
        return []

    if _looks_like_always_broad_underlag_composer(composer):
        return _select_broad_underlag_field_refs(ordered_priors)

    matched_refs = _select_semantic_underlag_field_refs(
        composer=composer,
        ordered_priors=ordered_priors,
    )
    if matched_refs:
        if allow_priority_fallback:
            return _ensure_each_json_prior_has_underlag_ref(
                matched_refs=matched_refs,
                ordered_priors=ordered_priors,
            )
        return matched_refs
    if _looks_like_broad_underlag_composer(composer):
        return _select_broad_underlag_field_refs(ordered_priors)
    source_summary_refs = _select_source_summary_underlag_field_refs(ordered_priors)
    if source_summary_refs:
        return source_summary_refs
    if not allow_priority_fallback:
        return _select_source_floor_underlag_field_refs(ordered_priors)
    return _select_priority_fallback_underlag_field_refs(ordered_priors)


def _looks_like_broad_underlag_composer(composer: NewStepDraft) -> bool:
    return _contains_underlag_marker_phrase(
        f"{composer.name} {composer.instructions or ''}",
        _UNDERLAG_BROAD_COMPOSER_MARKERS,
    )


def _looks_like_always_broad_underlag_composer(composer: NewStepDraft) -> bool:
    return _contains_underlag_marker_phrase(
        f"{composer.name} {composer.instructions or ''}",
        _UNDERLAG_ALWAYS_BROAD_COMPOSER_MARKERS,
    )


def _looks_like_section_or_document_composer(composer: NewStepDraft) -> bool:
    marker_tokens = set(
        _underlag_marker_tokens(f"{composer.name} {composer.instructions or ''}")
    )
    return bool(
        marker_tokens.intersection(
            {
                "avsnitt",
                "beskriv",
                "dokument",
                "protokoll",
                "rapport",
                "rubrik",
                "sammanstall",
                "skriv",
                "slutlig",
                "word",
            }
        )
    )


def _contains_underlag_marker_phrase(
    value: str,
    markers: tuple[str, ...],
) -> bool:
    value_tokens = _underlag_marker_tokens(value)
    for marker in markers:
        marker_tokens = _underlag_marker_tokens(marker)
        if not marker_tokens:
            continue
        if len(marker_tokens) == 1:
            if _underlag_marker_token_matches(value_tokens, marker_tokens[0]):
                return True
            continue
        if _contains_underlag_marker_sequence(value_tokens, marker_tokens):
            return True
    return False


def _underlag_marker_token_matches(
    value_tokens: tuple[str, ...],
    marker_token: str,
) -> bool:
    return any(
        marker_token in _underlag_token_variants(token) for token in value_tokens
    )


def _contains_underlag_marker_sequence(
    value_tokens: tuple[str, ...],
    marker_tokens: tuple[str, ...],
) -> bool:
    marker_length = len(marker_tokens)
    return any(
        all(
            marker_token in _underlag_token_variants(value_tokens[index + offset])
            for offset, marker_token in enumerate(marker_tokens)
        )
        for index in range(len(value_tokens) - marker_length + 1)
    )


def _underlag_marker_tokens(value: str) -> tuple[str, ...]:
    normalized = normalize_discovery_text(
        value.replace("_", " ").replace("-", " ").replace("/", " ")
    )
    ascii_normalized = _normalize_swedish_ascii(normalized)
    return tuple(token for token in ascii_normalized.split() if len(token) >= 2)


def _select_broad_underlag_field_refs(
    ordered_priors: list[tuple[int, list[StructuredFieldDraft]]],
) -> list[PreviousFieldRef]:
    return _round_robin_underlag_field_refs(
        ordered_priors,
        cap=TARGETED_UNDERLAG_BROAD_FIELD_CAP,
    )


def _round_robin_underlag_field_refs(
    ordered_priors: list[tuple[int, list[StructuredFieldDraft]]],
    *,
    cap: int,
) -> list[PreviousFieldRef]:
    selected: list[PreviousFieldRef] = []
    positions = [0 for _ in ordered_priors]

    while len(selected) < cap:
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
            if len(selected) >= cap:
                break
        if not advanced:
            break
    return selected


def _ensure_each_json_prior_has_underlag_ref(
    *,
    matched_refs: list[PreviousFieldRef],
    ordered_priors: list[tuple[int, list[StructuredFieldDraft]]],
) -> list[PreviousFieldRef]:
    effective_total_cap = max(
        TARGETED_UNDERLAG_TOTAL_FIELD_CAP,
        len(ordered_priors),
    )
    selected = list(matched_refs)
    seen = {(ref.from_step, ref.field_path) for ref in selected}
    covered_prior_steps = {ref.from_step for ref in selected}
    for predecessor_index, fields in ordered_priors:
        prior_step_number = predecessor_index + 1
        if prior_step_number in covered_prior_steps:
            continue
        for field in fields:
            key = (prior_step_number, field.name)
            if key in seen:
                continue
            selected.append(_field_ref_from_draft_field(predecessor_index, field))
            seen.add(key)
            covered_prior_steps.add(prior_step_number)
            break
        if len(selected) >= effective_total_cap:
            break
    return selected[:effective_total_cap]


def _select_source_floor_underlag_field_refs(
    ordered_priors: list[tuple[int, list[StructuredFieldDraft]]],
) -> list[PreviousFieldRef]:
    return [
        _field_ref_from_draft_field(predecessor_index, fields[0])
        for predecessor_index, fields in ordered_priors
        if fields
    ][:TARGETED_UNDERLAG_TOTAL_FIELD_CAP]


def _select_priority_fallback_underlag_field_refs(
    ordered_priors: list[tuple[int, list[StructuredFieldDraft]]],
) -> list[PreviousFieldRef]:
    return _round_robin_underlag_field_refs(
        ordered_priors,
        cap=max(
            TARGETED_UNDERLAG_TOTAL_FIELD_CAP,
            len(ordered_priors),
        ),
    )


def _select_semantic_underlag_field_refs(
    *,
    composer: NewStepDraft,
    ordered_priors: list[tuple[int, list[StructuredFieldDraft]]],
) -> list[PreviousFieldRef]:
    composer_tokens = _underlag_match_tokens(
        f"{composer.name} {composer.instructions or ''}"
    )
    if not composer_tokens:
        return []

    scored: list[tuple[int, int, int, int, StructuredFieldDraft]] = []
    for prior_position, (predecessor_index, fields) in enumerate(ordered_priors):
        for field_position, field in enumerate(fields):
            score = _underlag_field_match_score(composer_tokens, field)
            if score <= 0:
                continue
            scored.append(
                (
                    -score,
                    prior_position,
                    field_position,
                    predecessor_index,
                    field,
                )
            )

    if not scored:
        return []

    selected: list[PreviousFieldRef] = []
    per_prior_count: dict[int, int] = {}
    seen: set[tuple[int, str]] = set()
    for _score, _prior_position, _field_position, predecessor_index, field in sorted(
        scored
    ):
        key = (predecessor_index, field.name)
        if key in seen:
            continue
        prior_count = per_prior_count.get(predecessor_index, 0)
        if prior_count >= TARGETED_UNDERLAG_FIELDS_PER_JSON_PRIOR_CAP:
            continue
        selected.append(_field_ref_from_draft_field(predecessor_index, field))
        seen.add(key)
        per_prior_count[predecessor_index] = prior_count + 1
        if len(selected) >= TARGETED_UNDERLAG_TOTAL_FIELD_CAP:
            break
    return selected


def _select_source_summary_underlag_field_refs(
    ordered_priors: list[tuple[int, list[StructuredFieldDraft]]],
) -> list[PreviousFieldRef]:
    selected: list[PreviousFieldRef] = []
    for predecessor_index, fields in ordered_priors:
        for field in fields:
            field_tokens = _underlag_match_tokens(f"{field.name} {field.description}")
            if not field_tokens.intersection(_UNDERLAG_SOURCE_SUMMARY_TOKENS):
                continue
            selected.append(_field_ref_from_draft_field(predecessor_index, field))
            break
        if len(selected) >= TARGETED_UNDERLAG_TOTAL_FIELD_CAP:
            break
    return selected


def _underlag_field_match_score(
    composer_tokens: set[str],
    field: StructuredFieldDraft,
) -> int:
    field_tokens = _underlag_match_tokens(f"{field.name} {field.description}")
    score = 0
    for composer_token in composer_tokens:
        for field_token in field_tokens:
            if composer_token == field_token:
                score += 3
            elif _underlag_token_contains(composer_token, field_token):
                score += 2
            elif _underlag_token_prefix_matches(composer_token, field_token):
                score += 1
    return score


def _underlag_match_tokens(value: str) -> set[str]:
    normalized = normalize_discovery_text(
        value.replace("_", " ").replace("-", " ").replace("/", " ")
    )
    ascii_normalized = _normalize_swedish_ascii(normalized)
    tokens: set[str] = set()
    for token in ascii_normalized.split():
        if len(token) < 3 or token in _UNDERLAG_MATCH_STOPWORDS:
            continue
        tokens.update(_underlag_token_variants(token))
    return tokens


def _underlag_token_variants(token: str) -> set[str]:
    variants = {token}
    for suffix in _UNDERLAG_SWEDISH_SUFFIXES:
        if len(token) <= len(suffix) + _UNDERLAG_MIN_TOKEN_PREFIX:
            continue
        if token.endswith(suffix):
            variants.add(token[: -len(suffix)])
    expanded = set(variants)
    for variant in variants:
        if len(variant) > 6 and variant.startswith("tids"):
            expanded.add(f"tid{variant[4:]}")
    return {
        variant
        for variant in expanded
        if len(variant) >= 3 and variant not in _UNDERLAG_MATCH_STOPWORDS
    }


def _normalize_swedish_ascii(value: str) -> str:
    return value.replace("å", "a").replace("ä", "a").replace("ö", "o").replace("é", "e")


def _underlag_token_contains(first: str, second: str) -> bool:
    if (
        len(first) < _UNDERLAG_MIN_TOKEN_PREFIX
        or len(second) < _UNDERLAG_MIN_TOKEN_PREFIX
    ):
        return False
    return first in second or second in first


def _underlag_token_prefix_matches(first: str, second: str) -> bool:
    return (
        len(first) >= _UNDERLAG_MIN_TOKEN_PREFIX
        and len(second) >= _UNDERLAG_MIN_TOKEN_PREFIX
        and first[:_UNDERLAG_MIN_TOKEN_PREFIX] == second[:_UNDERLAG_MIN_TOKEN_PREFIX]
    )


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


def _is_renderer_draft(step: NewStepDraft) -> bool:
    return is_document_renderer(
        output_type=step.output_type,
        document_delivery_mode=step.document_delivery_mode,
    )


__all__ = [
    "TARGETED_UNDERLAG_BROAD_FIELD_CAP",
    "TARGETED_UNDERLAG_FIELDS_PER_JSON_PRIOR_CAP",
    "TARGETED_UNDERLAG_TOTAL_FIELD_CAP",
    "auto_bind_targeted_underlag_for_text_composer",
    "normalize_create_step_mechanics",
]
