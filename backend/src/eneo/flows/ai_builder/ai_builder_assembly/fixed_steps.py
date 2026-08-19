from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_assembly.plan import PlannedStep
from eneo.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from eneo.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode


def template_variable_reader_step(
    *,
    runtime_input_type: InputType,
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
) -> PlannedStep:
    if _uses_english(ui_language):
        name = "Extract template variables"
        instructions = (
            "Extract the stable fields and source facts needed before filling "
            "the DOCX template."
        )
    else:
        name = "Extrahera mallvariabler"
        instructions = (
            "Extrahera stabila fält och källfakta som behövs innan DOCX-mallen fylls."
        )
    return PlannedStep(
        role="reader",
        name=name,
        instructions=instructions,
        input_source=InputSource.FLOW_INPUT,
        input_type=runtime_input_type,
        output_type=OutputType.JSON,
        output_mode=OutputMode.PASS_THROUGH,
        underlag_channel="flow_input",
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        output_fields=tuple(_default_template_source_fields()),
    )


def template_fill_step(*, ui_language: str | None) -> PlannedStep:
    if _uses_english(ui_language):
        name = "Fill DOCX template"
        instructions = (
            "Fill the DOCX template from the prepared content. Preserve the "
            "user's requested scope and terminology."
        )
    else:
        name = "Fyll DOCX-mall"
        instructions = (
            "Fyll DOCX-mallen med det förberedda innehållet. Bevara användarens "
            "önskade omfattning och terminologi."
        )
    return PlannedStep(
        role="template_fill",
        name=name,
        instructions=instructions,
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        output_type=OutputType.DOCX,
        output_mode=OutputMode.TEMPLATE_FILL,
        underlag_channel="implicit_previous",
        document_delivery_mode="template_fill",
    )


def fixed_audio_transcription_step(
    *,
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
    name: str | None = None,
    instructions: str | None = None,
    review_mode: FlowStepReviewMode | None = None,
) -> PlannedStep:
    if _uses_english(ui_language):
        default_name = "Transcribe audio"
        default_instructions = (
            "Transcribe the uploaded audio into text before downstream analysis "
            "or artifact generation."
        )
    else:
        default_name = "Transkribera ljud"
        default_instructions = (
            "Transkribera det uppladdade ljudet till text innan analys "
            "eller artefaktgenerering."
        )
    return PlannedStep(
        role="transcription",
        name=name or default_name,
        instructions=instructions or default_instructions,
        input_source=InputSource.FLOW_INPUT,
        input_type=InputType.AUDIO,
        output_type=OutputType.TEXT,
        output_mode=OutputMode.TRANSCRIBE_ONLY,
        underlag_channel="flow_input",
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        review_mode=review_mode,
    )


def render_verbatim_step(
    *,
    output_type: OutputType,
    ui_language: str | None,
) -> PlannedStep:
    output_label = output_type.value.upper()
    display_copy = (
        f"Render {output_label}"
        if _uses_english(ui_language)
        else f"Rendera {output_label}"
    )
    return PlannedStep(
        role="renderer",
        name=display_copy,
        instructions=display_copy,
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        output_type=output_type,
        output_mode=OutputMode.RENDER_VERBATIM,
        underlag_channel="implicit_previous",
        document_delivery_mode="generated",
    )


def _default_template_source_fields() -> list[StructuredFieldDraft]:
    return [
        StructuredFieldDraft(
            name="source_facts",
            field_type="array",
            description="Important source facts extracted from the input material.",
            item_fields=[
                StructuredFieldDraft(
                    name="fact",
                    field_type="string",
                    description="A concise source fact.",
                ),
                StructuredFieldDraft(
                    name="source_note",
                    field_type="string",
                    description="Where the fact came from or why it matters.",
                    required=False,
                ),
            ],
        ),
        StructuredFieldDraft(
            name="uncertainties",
            field_type="array",
            description="Missing, ambiguous, or uncertain information.",
            item_fields=[
                StructuredFieldDraft(
                    name="issue",
                    field_type="string",
                    description="A missing or uncertain point.",
                )
            ],
            required=False,
        ),
    ]


def _uses_english(ui_language: str | None) -> bool:
    return ui_language is not None and ui_language.casefold().startswith("en")
