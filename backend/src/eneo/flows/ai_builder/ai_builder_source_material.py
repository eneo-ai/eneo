from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_token_prefix,
    normalize_discovery_text,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    PreviousOutputRef,
)
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputType,
    StepSpec,
)
from eneo.flows.input_binding_contract_rules import effective_question_binding
from eneo.flows.template_reference_analyzer import (
    TemplateReference,
    analyze_template,
)

_DOCUMENT_OUTPUT_TYPES = {OutputType.DOCX, OutputType.PDF}
_PRIMARY_MATERIAL_INPUT_TYPES = {InputType.AUDIO, InputType.DOCUMENT, InputType.FILE}
_COMPILED_PRIMARY_MATERIAL_INPUT_TYPES = _PRIMARY_MATERIAL_INPUT_TYPES | {
    InputType.TEXT
}
_SWEDISH_LABEL_TOKENS = (
    "analysera",
    "bearbeta",
    "dokument",
    "ljud",
    "mote",
    "motet",
    "protokoll",
    "sammanfatt",
    "skapa",
    "steg",
    "strukturera",
    "transkrib",
)


@dataclass(frozen=True, slots=True)
class CompiledSourceMaterialBoundary:
    step: StepSpec
    step_order: int
    previous_step: StepSpec
    previous_step_order: int
    prior_steps: tuple[StepSpec, ...]
    primary_source_step: StepSpec


class SourceMaterialBindingStatus(str, Enum):
    """Classifies whether a boundary prompt preserves source text and structured context."""

    COMPLETE = "complete"
    INTENTIONAL_PARTIAL = "intentional_partial"
    NEEDS_COMPLETION = "needs_completion"


def iter_compiled_source_material_boundaries(
    spec: FlowDraftSpecCore,
) -> Iterable[CompiledSourceMaterialBoundary]:
    if not _compiled_spec_returns_material_report(spec):
        return

    for index, step in enumerate(spec.steps):
        if index == 0 or step.input_source != InputSource.PREVIOUS_STEP:
            continue
        previous_step = spec.steps[index - 1]
        if previous_step.output_type != OutputType.JSON:
            continue
        # Section-analysis chains often need the original source at each
        # JSON-after-JSON step, not only at the final report composer.
        prior_text_steps = tuple(
            prior_step
            for prior_step in spec.steps[:index]
            if prior_step.output_type == OutputType.TEXT
        )
        primary_source_step = _compiled_primary_source_text_step(prior_text_steps)
        if primary_source_step is None:
            continue
        yield CompiledSourceMaterialBoundary(
            step=step,
            step_order=index + 1,
            previous_step=previous_step,
            previous_step_order=index,
            prior_steps=tuple(spec.steps[:index]),
            primary_source_step=primary_source_step,
        )


def source_material_binding_status(
    boundary: CompiledSourceMaterialBoundary,
) -> SourceMaterialBindingStatus:
    question = effective_question_binding(boundary.step.input_bindings)
    if question is None:
        return SourceMaterialBindingStatus.NEEDS_COMPLETION

    mentions_structured = _question_mentions_immediate_structured(
        question=question,
        previous_step=boundary.previous_step,
        previous_step_order=boundary.previous_step_order,
        known_steps=(*boundary.prior_steps, boundary.step),
    )
    mentions_source = _question_mentions_prior_text_source(
        question=question,
        source_step=boundary.primary_source_step,
        prior_steps=boundary.prior_steps,
    )
    if mentions_structured and mentions_source:
        return SourceMaterialBindingStatus.COMPLETE
    if mentions_source:
        return SourceMaterialBindingStatus.INTENTIONAL_PARTIAL
    return SourceMaterialBindingStatus.NEEDS_COMPLETION


def source_material_question_for_boundary(
    boundary: CompiledSourceMaterialBoundary,
    *,
    existing_question: str | None = None,
) -> str:
    source_step = boundary.primary_source_step
    label = source_material_label_for_text(
        " ".join(
            (
                boundary.step.name,
                boundary.step.assistant_spec.instructions,
                source_step.name,
                source_step.assistant_spec.instructions,
            )
        )
    )
    immediate_structured = (
        f"{{{{ {boundary.previous_step.plan_step_ref}.output.structured }}}}"
    )
    source_material = f"{label}: {{{{ {source_step.plan_step_ref}.output.text }}}}"
    sections: list[str] = [existing_question] if existing_question is not None else []
    if existing_question is None or not _question_mentions_immediate_structured(
        question=existing_question,
        previous_step=boundary.previous_step,
        previous_step_order=boundary.previous_step_order,
        known_steps=(*boundary.prior_steps, boundary.step),
    ):
        sections.append(immediate_structured)
    if existing_question is None or not _question_mentions_prior_text_source(
        question=existing_question,
        source_step=source_step,
        prior_steps=boundary.prior_steps,
    ):
        sections.append(source_material)
    return "\n\n".join(sections)


def _question_mentions_immediate_structured(
    *,
    question: str,
    previous_step: StepSpec,
    previous_step_order: int | None = None,
    known_steps: Sequence[StepSpec] = (),
) -> bool:
    step_order = previous_step_order or _step_order_for(
        previous_step,
        known_steps=known_steps,
    )
    return any(
        _reference_targets_step(reference, previous_step, step_order=step_order)
        and _reference_tail_is_output(reference, output="structured")
        for reference in _analyze_step_references(question, known_steps=known_steps)
    )


def _question_mentions_prior_text_source(
    *,
    question: str,
    source_step: StepSpec,
    prior_steps: Sequence[StepSpec] = (),
) -> bool:
    step_order = _step_order_for(source_step, known_steps=prior_steps)
    return any(
        _reference_targets_step(reference, source_step, step_order=step_order)
        and _reference_tail_is_output(reference, output="text")
        for reference in _analyze_step_references(question, known_steps=prior_steps)
    )


def source_material_label_for_text(text: str) -> str:
    if any(character in text.casefold() for character in ("å", "ä", "ö")):
        return "Källmaterial"
    normalized = normalize_discovery_text(text)
    if contains_any_token_prefix(normalized, _SWEDISH_LABEL_TOKENS):
        return "Källmaterial"
    return "Source material"


def _analyze_step_references(
    question: str,
    *,
    known_steps: Sequence[StepSpec],
) -> list[TemplateReference]:
    step_refs = {
        step.plan_step_ref: index
        for index, step in enumerate(known_steps, start=1)
        if step.plan_step_ref
    }
    return analyze_template(question, step_refs=step_refs, form_field_names=set())


def _reference_targets_step(
    reference: TemplateReference,
    step: StepSpec,
    *,
    step_order: int | None,
) -> bool:
    return reference.step_ref == step.plan_step_ref or (
        step_order is not None and reference.step_order == step_order
    )


def _reference_tail_is_output(
    reference: TemplateReference,
    *,
    output: str,
) -> bool:
    return reference.tail == f"output.{output}" or reference.tail.startswith(
        f"output.{output}."
    )


def _step_order_for(
    step: StepSpec,
    *,
    known_steps: Sequence[StepSpec],
) -> int | None:
    for index, candidate in enumerate(known_steps, start=1):
        if candidate is step or candidate.plan_step_ref == step.plan_step_ref:
            return index
    return None


def _create_steps_return_document_artifact(steps: Sequence[NewStepDraft]) -> bool:
    return any(step.output_type in _DOCUMENT_OUTPUT_TYPES for step in steps)


def create_steps_return_material_report(steps: Sequence[NewStepDraft]) -> bool:
    if _create_steps_return_document_artifact(steps):
        return True
    return bool(steps) and steps[-1].output_type == OutputType.TEXT


def _compiled_spec_returns_document_artifact(spec: FlowDraftSpecCore) -> bool:
    return any(step.output_type in _DOCUMENT_OUTPUT_TYPES for step in spec.steps)


def _compiled_spec_returns_material_report(spec: FlowDraftSpecCore) -> bool:
    if _compiled_spec_returns_document_artifact(spec):
        return True
    return bool(spec.steps) and spec.steps[-1].output_type == OutputType.TEXT


def primary_source_material_ref_for_steps(
    *,
    steps: Sequence[NewStepDraft],
    flow_name: str,
    flow_description: str | None,
) -> PreviousOutputRef | None:
    source_step = _primary_source_text_step(steps)
    if source_step is None:
        return None
    step_index, step = source_step
    return PreviousOutputRef(
        from_step=step_index,
        label=source_material_label_for_text(
            " ".join(
                (
                    flow_name,
                    flow_description or "",
                    step.name,
                    step.instructions or "",
                )
            )
        ),
    )


def _primary_source_text_step(
    steps: Sequence[NewStepDraft],
) -> tuple[int, NewStepDraft] | None:
    for step_index, step in enumerate(steps, start=1):
        if step.input_source != InputSource.FLOW_INPUT:
            continue
        if step.input_type not in _PRIMARY_MATERIAL_INPUT_TYPES:
            continue
        if step.output_type != OutputType.TEXT:
            continue
        return step_index, step
    return None


def _compiled_primary_source_text_step(
    prior_text_steps: Sequence[StepSpec],
) -> StepSpec | None:
    # Prefer real source-material uploads over plain text form/input passthroughs.
    primary_material_step = next(
        (
            step
            for step in prior_text_steps
            if step.input_source == InputSource.FLOW_INPUT
            and step.input_type in _PRIMARY_MATERIAL_INPUT_TYPES
            and step.output_type == OutputType.TEXT
        ),
        None,
    )
    if primary_material_step is not None:
        return primary_material_step
    return next(
        (
            step
            for step in prior_text_steps
            if step.input_source == InputSource.FLOW_INPUT
            and step.input_type in _COMPILED_PRIMARY_MATERIAL_INPUT_TYPES
            and step.output_type == OutputType.TEXT
        ),
        None,
    )


__all__ = [
    "CompiledSourceMaterialBoundary",
    "SourceMaterialBindingStatus",
    "create_steps_return_material_report",
    "iter_compiled_source_material_boundaries",
    "primary_source_material_ref_for_steps",
    "source_material_binding_status",
    "source_material_label_for_text",
    "source_material_question_for_boundary",
]
