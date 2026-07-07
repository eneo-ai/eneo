from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_token_prefix,
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

_SOURCE_READER_INPUT_TYPES = frozenset({InputType.DOCUMENT, InputType.FILE})
_ARTIFACT_RENDER_ONLY_PREFIXES = (
    "render",
    "rendera",
    "format",
    "formattera",
    "convert",
    "konvertera",
)
TARGETED_UNDERLAG_TOTAL_FIELD_CAP = 8
_TargetedUnderlagBindingMode = Literal["skip", "with_text_priors"]
_PreviousRefKind = Literal["uses_previous_fields", "uses_previous_outputs"]
_PreviousRefFailureReason = Literal[
    "previous_field_step_not_prior",
    "previous_field_source_not_json",
    "previous_field_source_missing_output_fields",
    "unknown_previous_field_path",
    "previous_output_step_not_prior",
    "previous_output_source_not_text",
]

logger = logging.getLogger(__name__)


def normalize_create_step_mechanics(
    *,
    steps: list[NewStepDraft],
    form_fields: list[FormFieldSpec],
    aggregation_intent: "AggregationIntent" = "linear",
    ui_language: str | None = None,
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
    normalized_steps = _fold_adjacent_source_json_refinements(
        normalized_steps,
        aggregation_intent=aggregation_intent,
    )
    normalized_steps = _fold_redundant_artifact_text_render_helper(normalized_steps)
    rebound_steps = auto_bind_targeted_underlag_for_text_composer(
        normalized_steps,
        aggregation_intent=aggregation_intent,
        ui_language=ui_language,
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
        # Previous-step refs are explicit create-contract refs or backend floor refs.
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
            "generated"
            if is_document_renderer(output_type=output_type)
            else "not_applicable"
        )
    elif step.document_delivery_mode != "not_applicable" and not is_document_renderer(
        output_type=output_type
    ):
        updates["document_delivery_mode"] = "not_applicable"

    if step.citations_requested and (
        output_type != OutputType.TEXT or input_type == InputType.AUDIO
    ):
        updates["citations_requested"] = False

    return step.model_copy(update=updates) if updates else step


def _fold_adjacent_source_json_refinements(
    steps: list[NewStepDraft],
    *,
    aggregation_intent: "AggregationIntent",
) -> list[NewStepDraft]:
    if aggregation_intent != "linear":
        return steps

    folded_steps: list[NewStepDraft] = []
    original_to_current_step: dict[int, int] = {}
    changed = False
    index = 0
    while index < len(steps):
        step = steps[index]
        if _is_source_json_reader(step):
            current_step_number = len(folded_steps) + 1
            merged_step = step
            next_index = index + 1
            while next_index < len(steps) and _is_foldable_json_refinement(
                steps[next_index],
                source_step_number=current_step_number,
            ):
                merged_step = merged_step.model_copy(
                    update={
                        "output_fields": _merge_structured_field_lists(
                            merged_step.output_fields or [],
                            steps[next_index].output_fields or [],
                        )
                    }
                )
                original_to_current_step[next_index + 1] = current_step_number
                next_index += 1
                changed = True
            folded_steps.append(merged_step)
            original_to_current_step[index + 1] = current_step_number
            index = next_index
            continue

        current_step_number = len(folded_steps) + 1
        folded_steps.append(
            _remap_previous_refs(
                step,
                original_to_current_step=original_to_current_step,
                current_step_number=current_step_number,
            )
        )
        original_to_current_step[index + 1] = current_step_number
        index += 1

    return folded_steps if changed else steps


def _fold_redundant_artifact_text_render_helper(
    steps: list[NewStepDraft],
) -> list[NewStepDraft]:
    if len(steps) < 3:
        return steps

    body_step = steps[-3]
    helper_step = steps[-2]
    terminal_step = steps[-1]
    if not _is_generated_document_renderer(terminal_step):
        return steps
    if body_step.output_type != OutputType.TEXT:
        return steps
    if not _is_redundant_artifact_text_render_helper(
        helper_step,
        final_output_type=terminal_step.output_type,
    ):
        return steps

    folded_terminal = terminal_step.model_copy(
        update={
            "instructions": _join_step_instructions(
                terminal_step.instructions,
                helper_step.instructions,
            )
        }
    )
    return [*steps[:-2], folded_terminal]


def _is_generated_document_renderer(step: NewStepDraft) -> bool:
    return (
        step.input_source == InputSource.PREVIOUS_STEP
        and step.input_type == InputType.TEXT
        and is_document_renderer(
            output_type=step.output_type,
            document_delivery_mode=step.document_delivery_mode,
        )
        and step.document_delivery_mode in {"generated", "not_applicable"}
    )


def _is_redundant_artifact_text_render_helper(
    step: NewStepDraft,
    *,
    final_output_type: OutputType,
) -> bool:
    if step.input_source not in {
        InputSource.PREVIOUS_STEP,
        InputSource.ALL_PREVIOUS_STEPS,
    }:
        return False
    if step.input_type != InputType.TEXT or step.output_type != OutputType.TEXT:
        return False
    if (
        step.uses_form_fields
        or step.knowledge_refs
        or step.mcp_server_refs
        or step.mcp_tool_refs
        or step.citations_requested
        or step.review_mode is not None
        or step.output_fields is not None
    ):
        return False

    text = normalize_discovery_text(f"{step.name} {step.instructions or ''}")
    if not contains_any_token_prefix(text, _ARTIFACT_RENDER_ONLY_PREFIXES):
        return False
    return final_output_type.value in text


def _join_step_instructions(
    first: str | None,
    second: str | None,
) -> str | None:
    parts = [part.strip() for part in (first, second) if part and part.strip()]
    return "\n\n".join(parts) if parts else None


def _is_source_json_reader(step: NewStepDraft) -> bool:
    return (
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type in _SOURCE_READER_INPUT_TYPES
        and step.output_type == OutputType.JSON
    )


def _is_foldable_json_refinement(
    step: NewStepDraft,
    *,
    source_step_number: int,
) -> bool:
    return (
        step.input_source == InputSource.PREVIOUS_STEP
        and step.input_type == InputType.JSON
        and step.output_type == OutputType.JSON
        and bool(step.output_fields)
        and not step.uses_form_fields
        and _previous_field_refs_only_source_reader(
            step.uses_previous_fields,
            source_step_number=source_step_number,
        )
        and not step.uses_previous_outputs
        and not step.knowledge_refs
        and not step.mcp_server_refs
        and not step.mcp_tool_refs
        and not step.citations_requested
        and step.review_mode is None
    )


def _previous_field_refs_only_source_reader(
    refs: list[PreviousFieldRef],
    *,
    source_step_number: int,
) -> bool:
    return all(ref.from_step == source_step_number for ref in refs)


def _remap_previous_refs(
    step: NewStepDraft,
    *,
    original_to_current_step: dict[int, int],
    current_step_number: int,
) -> NewStepDraft:
    if not step.uses_previous_fields and not step.uses_previous_outputs:
        return step
    field_refs = _remap_previous_field_refs(
        step.uses_previous_fields,
        original_to_current_step=original_to_current_step,
        current_step_number=current_step_number,
    )
    output_refs = _remap_previous_output_refs(
        step.uses_previous_outputs,
        original_to_current_step=original_to_current_step,
        current_step_number=current_step_number,
    )
    if (
        field_refs == step.uses_previous_fields
        and output_refs == step.uses_previous_outputs
    ):
        return step
    return step.model_copy(
        update={
            "uses_previous_fields": field_refs,
            "uses_previous_outputs": output_refs,
        }
    )


def _remap_previous_field_refs(
    refs: list[PreviousFieldRef],
    *,
    original_to_current_step: dict[int, int],
    current_step_number: int,
) -> list[PreviousFieldRef]:
    remapped: list[PreviousFieldRef] = []
    for ref in refs:
        source_step = original_to_current_step.get(ref.from_step)
        if source_step is None or source_step >= current_step_number:
            continue
        remapped.append(ref.model_copy(update={"from_step": source_step}))
    return remapped


def _remap_previous_output_refs(
    refs: list[PreviousOutputRef],
    *,
    original_to_current_step: dict[int, int],
    current_step_number: int,
) -> list[PreviousOutputRef]:
    remapped: list[PreviousOutputRef] = []
    for ref in refs:
        source_step = original_to_current_step.get(ref.from_step)
        if source_step is None or source_step >= current_step_number:
            continue
        remapped.append(ref.model_copy(update={"from_step": source_step}))
    return remapped


def _merge_structured_field_lists(
    base_fields: list[StructuredFieldDraft],
    incoming_fields: list[StructuredFieldDraft],
) -> list[StructuredFieldDraft]:
    merged = list(base_fields)
    indexes_by_name = {
        field.name.casefold(): index for index, field in enumerate(merged)
    }
    for incoming in incoming_fields:
        index = indexes_by_name.get(incoming.name.casefold())
        if index is None:
            indexes_by_name[incoming.name.casefold()] = len(merged)
            merged.append(incoming)
            continue
        merged[index] = _merge_structured_field(merged[index], incoming)
    return merged


def _merge_structured_field(
    base: StructuredFieldDraft,
    incoming: StructuredFieldDraft,
) -> StructuredFieldDraft:
    if base.field_type != incoming.field_type:
        logger.warning(
            "ai_builder_create_dataflow_structured_field_type_conflict",
            extra={
                "field_name": base.name,
                "base_field_type": base.field_type,
                "incoming_field_type": incoming.field_type,
            },
        )
        return base
    if base.field_type == "object":
        return base.model_copy(
            update={
                "fields": _merge_structured_field_lists(
                    base.fields or [],
                    incoming.fields or [],
                )
            }
        )
    if base.field_type == "array":
        return base.model_copy(
            update={
                "item_fields": _merge_structured_field_lists(
                    base.item_fields or [],
                    incoming.item_fields or [],
                )
            }
        )
    return base


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
    aggregation_intent: "AggregationIntent",
    ui_language: str | None = None,
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
        ui_language=ui_language,
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
                updated_steps = _bind_final_assembler_structured_fields(
                    updated_steps,
                    composer_index=composer_index,
                )
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
    """Choose whether omitted refs need source-floor field and text-prior binding."""
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
    if _previous_field_refs_cover_required_json_priors(
        steps=steps,
        composer_index=composer_index,
        refs=composer.uses_previous_fields,
        json_priors=json_priors,
    ):
        return "skip"

    text_priors_count = sum(
        1 for _, step in priors if step.output_type == OutputType.TEXT
    )
    if text_priors_count > TARGETED_UNDERLAG_SOFT_CAP:
        input_source_value = (
            composer.input_source.value if composer.input_source is not None else None
        )
        logger.warning(
            "ai_builder_create_dataflow_targeted_underlag_soft_cap_bound",
            extra={
                "soft_cap": TARGETED_UNDERLAG_SOFT_CAP,
                "composer_index": composer_index,
                "text_prior_count": text_priors_count,
                "json_prior_count": len(json_priors),
                "input_source": input_source_value,
            },
        )
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


def _bind_final_assembler_structured_fields(
    steps: list[NewStepDraft],
    *,
    composer_index: int,
) -> list[NewStepDraft]:
    composer = steps[composer_index]
    priors = _targeted_underlag_prior_steps(steps, composer_index=composer_index)
    json_priors = _targeted_underlag_json_priors(priors)
    if len(json_priors) < 2:
        return steps
    new_field_refs = _select_targeted_underlag_field_refs(
        json_priors=json_priors,
    )
    if not new_field_refs:
        return steps
    new_field_refs = _merge_previous_field_refs(
        composer.uses_previous_fields,
        new_field_refs,
    )
    if new_field_refs == composer.uses_previous_fields:
        return steps

    rewritten = composer.model_copy(update={"uses_previous_fields": new_field_refs})
    new_steps = list(steps)
    new_steps[composer_index] = rewritten
    return new_steps


def _bind_targeted_underlag_for_composer(
    steps: list[NewStepDraft],
    *,
    composer_index: int,
    primary_source_ref: PreviousOutputRef | None,
    returns_material_report: bool,
    include_text_priors: bool,
) -> list[NewStepDraft]:
    composer = steps[composer_index]

    priors = _targeted_underlag_prior_steps(steps, composer_index=composer_index)
    json_priors = _targeted_underlag_json_priors(priors)

    new_field_refs = _select_targeted_underlag_field_refs(
        json_priors=json_priors,
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


def _previous_field_refs_cover_required_json_priors(
    *,
    steps: list[NewStepDraft],
    composer_index: int,
    refs: list[PreviousFieldRef],
    json_priors: list[tuple[int, NewStepDraft]],
) -> bool:
    if not refs:
        return False
    required_distinct_steps = min(2, len(json_priors))
    json_prior_step_numbers = {index + 1 for index, _ in json_priors}
    referenced_json_steps = {
        ref.from_step for ref in refs if ref.from_step in json_prior_step_numbers
    }
    # The compiler keeps an implicit whole-structured ref to the immediate
    # previous JSON step unless an explicit field ref to that same step
    # suppresses it. Count that ref so dataflow does not duplicate it.
    implicit_previous_step = _implicit_previous_json_source_step_number(
        steps=steps,
        composer_index=composer_index,
        refs=refs,
        json_prior_step_numbers=json_prior_step_numbers,
    )
    if implicit_previous_step is not None:
        referenced_json_steps.add(implicit_previous_step)
    return len(referenced_json_steps) >= required_distinct_steps


def _implicit_previous_json_source_step_number(
    *,
    steps: list[NewStepDraft],
    composer_index: int,
    refs: list[PreviousFieldRef],
    json_prior_step_numbers: set[int],
) -> int | None:
    # Keep this aligned with compile_step_input_bindings: previous_step over a
    # JSON predecessor emits {{ step_x.output.structured }} as source material.
    composer = steps[composer_index]
    if composer.input_source != InputSource.PREVIOUS_STEP or composer_index == 0:
        return None
    immediate_step_number = composer_index
    if immediate_step_number not in json_prior_step_numbers:
        return None
    if steps[composer_index - 1].output_type != OutputType.JSON:
        return None
    if any(ref.from_step == immediate_step_number for ref in refs):
        return None
    return immediate_step_number


def _select_targeted_underlag_field_refs(
    *,
    json_priors: list[tuple[int, NewStepDraft]],
) -> list[PreviousFieldRef]:
    ordered_priors = [
        (
            predecessor_index,
            _ordered_targeted_underlag_fields(predecessor),
        )
        for predecessor_index, predecessor in json_priors
    ]
    ordered_priors = [(index, fields) for index, fields in ordered_priors if fields]
    selected_refs: list[PreviousFieldRef] = []
    max_field_count = max((len(fields) for _, fields in ordered_priors), default=0)
    for field_index in range(max_field_count):
        # Interleave so the cap preserves breadth across source steps first.
        for predecessor_index, fields in ordered_priors:
            if field_index >= len(fields):
                continue
            field = fields[field_index]
            selected_refs.append(_field_ref_from_draft_field(predecessor_index, field))
            if len(selected_refs) == TARGETED_UNDERLAG_TOTAL_FIELD_CAP:
                logger.warning(
                    "ai_builder_create_dataflow_targeted_underlag_field_cap_bound",
                    extra={
                        "field_cap": TARGETED_UNDERLAG_TOTAL_FIELD_CAP,
                        "available_field_count": sum(
                            len(fields) for _, fields in ordered_priors
                        ),
                        "json_prior_count": len(ordered_priors),
                    },
                )
                return selected_refs
    return selected_refs


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
    "TARGETED_UNDERLAG_TOTAL_FIELD_CAP",
    "auto_bind_targeted_underlag_for_text_composer",
    "normalize_create_step_mechanics",
]
