from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_token_prefix,
    normalize_discovery_text,
)
from intric.flows.ai_builder.ai_builder_domain_models import StepSpec
from intric.flows.ai_builder.ai_builder_models import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputType,
)
from intric.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    PreviousOutputRef,
)

_DOCUMENT_OUTPUT_TYPES = {OutputType.DOCX, OutputType.PDF}
_PRIMARY_MATERIAL_INPUT_TYPES = {InputType.AUDIO, InputType.DOCUMENT, InputType.FILE}
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
    previous_step: StepSpec
    prior_text_steps: tuple[StepSpec, ...]


def normalize_create_draft_source_material(draft: FlowCreateDraft) -> FlowCreateDraft:
    if not _draft_returns_document_artifact(draft):
        return draft

    source_ref = _primary_source_material_ref(draft)
    if source_ref is None:
        return draft

    updated_steps = list(draft.steps)
    changed = False
    for step_index, step in enumerate(draft.steps):
        if not _draft_step_needs_source_material_ref(
            draft=draft,
            step_index=step_index,
            source_ref=source_ref,
        ):
            continue
        updated_steps[step_index] = step.model_copy(
            update={
                "input_type": InputType.TEXT,
                "uses_previous_outputs": [*step.uses_previous_outputs, source_ref],
            }
        )
        changed = True

    if not changed:
        return draft
    return draft.model_copy(update={"steps": updated_steps})


def iter_compiled_source_material_boundaries(
    spec: FlowDraftSpecCore,
) -> Iterable[CompiledSourceMaterialBoundary]:
    if not _compiled_spec_returns_document_artifact(spec):
        return

    for index, step in enumerate(spec.steps):
        if index == 0 or step.input_source != InputSource.PREVIOUS_STEP:
            continue
        previous_step = spec.steps[index - 1]
        if previous_step.output_type != OutputType.JSON:
            continue
        prior_text_steps = tuple(
            prior_step
            for prior_step in spec.steps[:index]
            if prior_step.output_type == OutputType.TEXT
        )
        if not prior_text_steps:
            continue
        yield CompiledSourceMaterialBoundary(
            step=step,
            previous_step=previous_step,
            prior_text_steps=prior_text_steps,
        )


def source_material_binding_is_complete(
    boundary: CompiledSourceMaterialBoundary,
) -> bool:
    question = question_binding(boundary.step.input_bindings)
    if question is None:
        return False
    return question_mentions_immediate_structured(
        question=question,
        previous_step=boundary.previous_step,
    ) and question_mentions_prior_text_source(
        question=question,
        prior_text_steps=boundary.prior_text_steps,
    )


def source_material_question_for_boundary(
    boundary: CompiledSourceMaterialBoundary,
    *,
    existing_question: str | None = None,
) -> str:
    source_step = _compiled_primary_source_text_step(boundary.prior_text_steps)
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
    sections: list[str] = []
    if existing_question is None or not question_mentions_immediate_structured(
        question=existing_question,
        previous_step=boundary.previous_step,
    ):
        sections.append(immediate_structured)
    if existing_question is None or not question_mentions_prior_text_source(
        question=existing_question,
        prior_text_steps=boundary.prior_text_steps,
    ):
        sections.append(source_material)
    if existing_question is not None:
        sections.append(existing_question)
    return "\n\n".join(sections)


def question_mentions_immediate_structured(
    *,
    question: str,
    previous_step: StepSpec,
) -> bool:
    return f"{{{{ {previous_step.plan_step_ref}.output.structured }}}}" in question


def question_mentions_prior_text_source(
    *,
    question: str,
    prior_text_steps: Sequence[StepSpec],
) -> bool:
    if not prior_text_steps:
        return False
    source_step = _compiled_primary_source_text_step(prior_text_steps)
    return f"{{{{ {source_step.plan_step_ref}.output.text }}}}" in question


def question_binding(input_bindings: object) -> str | None:
    if not isinstance(input_bindings, Mapping):
        return None
    mapping = cast(Mapping[object, object], input_bindings)
    question = mapping.get("question")
    if isinstance(question, str) and question.strip():
        return question
    return None


def source_material_label_for_text(text: str) -> str:
    if any(character in text.casefold() for character in ("å", "ä", "ö")):
        return "Källmaterial"
    normalized = normalize_discovery_text(text)
    if contains_any_token_prefix(normalized, _SWEDISH_LABEL_TOKENS):
        return "Källmaterial"
    return "Source material"


def _draft_returns_document_artifact(draft: FlowCreateDraft) -> bool:
    return any(step.output_type in _DOCUMENT_OUTPUT_TYPES for step in draft.steps)


def _compiled_spec_returns_document_artifact(spec: FlowDraftSpecCore) -> bool:
    return any(step.output_type in _DOCUMENT_OUTPUT_TYPES for step in spec.steps)


def _primary_source_material_ref(
    draft: FlowCreateDraft,
) -> PreviousOutputRef | None:
    source_step = _draft_primary_source_text_step(draft)
    if source_step is None:
        return None
    step_index, step = source_step
    return PreviousOutputRef(
        from_step=step_index,
        label=source_material_label_for_text(
            " ".join(
                (
                    draft.flow_name,
                    draft.flow_description or "",
                    step.name,
                    step.instructions or "",
                )
            )
        )
    )


def _draft_primary_source_text_step(
    draft: FlowCreateDraft,
) -> tuple[int, NewStepDraft] | None:
    for step_index, step in enumerate(draft.steps, start=1):
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
) -> StepSpec:
    return next(
        (
            step
            for step in prior_text_steps
            if step.input_source == InputSource.FLOW_INPUT
            and step.input_type in _PRIMARY_MATERIAL_INPUT_TYPES
            and step.output_type == OutputType.TEXT
        ),
        prior_text_steps[0],
    )


def _draft_step_needs_source_material_ref(
    *,
    draft: FlowCreateDraft,
    step_index: int,
    source_ref: PreviousOutputRef,
) -> bool:
    step = draft.steps[step_index]
    if step.input_source != InputSource.PREVIOUS_STEP:
        return False
    if step_index == 0:
        return False
    if source_ref.from_step >= step_index + 1:
        return False
    previous_step = draft.steps[step_index - 1]
    if previous_step.output_type != OutputType.JSON:
        return False
    if any(
        output_ref.from_step == source_ref.from_step
        for output_ref in step.uses_previous_outputs
    ):
        return False
    return True


__all__ = [
    "CompiledSourceMaterialBoundary",
    "iter_compiled_source_material_boundaries",
    "normalize_create_draft_source_material",
    "question_binding",
    "question_mentions_immediate_structured",
    "question_mentions_prior_text_source",
    "source_material_binding_is_complete",
    "source_material_label_for_text",
    "source_material_question_for_boundary",
]
