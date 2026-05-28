from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_create_compiler import (
    OutlineCompileContext,
    compile_create_draft,
    compile_outline_to_create_draft,
)
from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_create_outline import (
    parse_outline_flow_arguments,
)
from intric.flows.ai_builder.ai_builder_step_skeleton import (
    _LEGAL_STEP_SKELETON_POLICIES,
    StepSkeleton,
    StepSkeletonSemanticContent,
    default_structured_output_fields,
    materialize_step_skeleton,
)
from intric.flows.ai_builder.pattern_registry import (
    ANALYSIS_OR_QUALITY_REVIEW_STEP,
    EXTRACT_TEMPLATE_VARIABLES_STEP,
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    PATTERN_REGISTRY,
    STRUCTURED_EXTRACTION_STEP,
    TEMPLATE_FILL_DOCX_STEP,
    TERMINAL_ARTIFACT_STEP,
)
from intric.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)


def test_step_skeleton_rejects_illegal_policy_combinations() -> None:
    with pytest.raises(ValueError, match="Illegal StepSkeleton policy tuple"):
        StepSkeleton(
            slot_ordinal=0,
            slot_id=FLOW_INPUT_AUDIO_TRANSCRIPTION,
            role="backend_fixed",
            mechanics_policy="fill_missing",
            semantic_policy="backend_default",
            chain_token=FLOW_INPUT_AUDIO_TRANSCRIPTION,
            default_name="Transcribe audio",
            default_instructions="Transcribe the uploaded audio.",
            input_source=InputSource.FLOW_INPUT,
            input_type=InputType.AUDIO,
            output_type=OutputType.TEXT,
            output_mode=OutputMode.TRANSCRIBE_ONLY,
            document_delivery_mode="not_applicable",
            runtime_upload=True,
            runtime_required=True,
            runtime_max_files=None,
        )


def test_step_skeleton_rejects_runtime_fields_after_first_slot() -> None:
    with pytest.raises(ValueError, match="Only the first skeleton slot"):
        StepSkeleton(
            slot_ordinal=1,
            slot_id="semantic",
            role="semantic_required",
            mechanics_policy="fill_missing",
            semantic_policy="required_from_outline",
            chain_token=None,
            default_name="Analyze",
            default_instructions="Analyze the previous output.",
            input_source=InputSource.PREVIOUS_STEP,
            input_type=InputType.TEXT,
            output_type=OutputType.TEXT,
            output_mode=OutputMode.PASS_THROUGH,
            document_delivery_mode="not_applicable",
            runtime_upload=True,
            runtime_required=True,
            runtime_max_files=None,
        )


def test_step_skeleton_policy_combinations_are_closed() -> None:
    assert _LEGAL_STEP_SKELETON_POLICIES == frozenset(
        {
            ("backend_fixed", "locked", "backend_default"),
            ("semantic_required", "fill_missing", "required_from_outline"),
            ("semantic_optional", "reject_if_conflicting", "optional_from_outline"),
        }
    )


def test_materialize_audio_text_transcribe_only_skeleton() -> None:
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.AUDIO,
        final_output_type=OutputType.TEXT,
        final_output_mode=OutputMode.TRANSCRIBE_ONLY,
        pattern_ids=("audio_transcription",),
        chain_steps=(),
    )
    skeleton = plan.minimum_slots

    assert [
        (slot.role, slot.input_type.value, slot.output_mode.value) for slot in skeleton
    ] == [("semantic_required", "audio", "transcribe_only")]
    assert skeleton[0].input_source == InputSource.FLOW_INPUT
    assert skeleton[0].output_type == OutputType.TEXT
    assert skeleton[0].runtime_upload is True
    assert skeleton[0].runtime_required is True


def test_materialize_audio_artifact_skeleton() -> None:
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.AUDIO,
        final_output_type=OutputType.PDF,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("audio_to_artifact_report",),
        chain_steps=_chain_steps("audio_to_artifact_report"),
    )
    skeleton = plan.minimum_slots

    assert [slot.role for slot in skeleton] == [
        "backend_fixed",
        "semantic_required",
        "backend_fixed",
    ]
    assert [slot.chain_token for slot in skeleton] == [
        FLOW_INPUT_AUDIO_TRANSCRIPTION,
        None,
        TERMINAL_ARTIFACT_STEP,
    ]
    assert _skeleton_type_modes(skeleton) == [
        ("audio", "text", "transcribe_only"),
        ("text", "text", "pass_through"),
        ("text", "pdf", "pass_through"),
    ]
    assert skeleton[0].runtime_upload is True
    assert skeleton[0].runtime_required is True
    assert skeleton[2].document_delivery_mode == "generated"


def test_materialize_audio_document_without_pattern_infers_transcript_chain() -> None:
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.AUDIO,
        final_output_type=OutputType.PDF,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=(),
        chain_steps=(),
    )
    skeleton = plan.minimum_slots

    assert [slot.role for slot in skeleton] == [
        "backend_fixed",
        "semantic_required",
        "backend_fixed",
    ]
    assert [slot.chain_token for slot in skeleton] == [
        FLOW_INPUT_AUDIO_TRANSCRIPTION,
        None,
        TERMINAL_ARTIFACT_STEP,
    ]
    assert _skeleton_type_modes(skeleton) == [
        ("audio", "text", "transcribe_only"),
        ("text", "text", "pass_through"),
        ("text", "pdf", "pass_through"),
    ]


def test_materialize_template_fill_mode_without_pattern_uses_docx_chain() -> None:
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.TEMPLATE_FILL,
        pattern_ids=(),
        chain_steps=(),
    )
    skeleton = plan.minimum_slots

    assert [slot.chain_token for slot in skeleton] == [
        EXTRACT_TEMPLATE_VARIABLES_STEP,
        None,
        TEMPLATE_FILL_DOCX_STEP,
    ]
    assert _skeleton_type_modes(skeleton) == [
        ("document", "json", "pass_through"),
        ("json", "text", "pass_through"),
        ("text", "docx", "template_fill"),
    ]
    assert skeleton[0].output_fields
    assert skeleton[1].output_fields == ()
    assert skeleton[2].document_delivery_mode == "template_fill"


def test_materialize_structured_quality_skeleton() -> None:
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.PDF,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("multi_step_quality_chain",),
        chain_steps=_chain_steps("multi_step_quality_chain"),
    )
    skeleton = plan.minimum_slots

    assert [slot.chain_token for slot in skeleton] == [
        STRUCTURED_EXTRACTION_STEP,
        None,
        ANALYSIS_OR_QUALITY_REVIEW_STEP,
        TERMINAL_ARTIFACT_STEP,
    ]
    assert _skeleton_type_modes(skeleton) == [
        ("document", "json", "pass_through"),
        ("json", "text", "pass_through"),
        ("text", "text", "pass_through"),
        ("text", "pdf", "pass_through"),
    ]
    assert skeleton[0].output_fields
    assert skeleton[3].document_delivery_mode == "generated"


def test_materialize_structured_quality_skeleton_text_terminal_reads_previous_step() -> (
    None
):
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.TEXT,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("multi_step_quality_chain",),
        chain_steps=_chain_steps("multi_step_quality_chain"),
        aggregation_intent="compare",
    )
    skeleton = plan.minimum_slots

    assert [slot.chain_token for slot in skeleton] == [
        STRUCTURED_EXTRACTION_STEP,
        None,
        ANALYSIS_OR_QUALITY_REVIEW_STEP,
        TERMINAL_ARTIFACT_STEP,
    ]
    assert _skeleton_type_modes(skeleton) == [
        ("document", "json", "pass_through"),
        ("json", "text", "pass_through"),
        ("text", "text", "pass_through"),
        ("text", "text", "pass_through"),
    ]
    assert skeleton[2].input_source == InputSource.ALL_PREVIOUS_STEPS
    assert skeleton[-1].input_source == InputSource.PREVIOUS_STEP


@pytest.mark.parametrize("final_output_type", [OutputType.DOCX, OutputType.PDF])
@pytest.mark.parametrize("aggregation_intent", ["aggregate", "compare"])
def test_materialize_structured_quality_skeleton_document_terminal_keeps_fan_in(
    final_output_type: OutputType, aggregation_intent: str
) -> None:
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=final_output_type,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("multi_step_quality_chain",),
        chain_steps=_chain_steps("multi_step_quality_chain"),
        aggregation_intent=aggregation_intent,
    )
    skeleton = plan.minimum_slots

    assert skeleton[-1].chain_token == TERMINAL_ARTIFACT_STEP
    assert skeleton[-1].input_source == InputSource.ALL_PREVIOUS_STEPS
    assert skeleton[-1].output_type == final_output_type


def test_materialize_structured_quality_skeleton_uses_swedish_fixed_step_names() -> (
    None
):
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.PDF,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("multi_step_quality_chain",),
        chain_steps=_chain_steps("multi_step_quality_chain"),
        ui_language="sv",
    )
    skeleton = plan.minimum_slots

    assert [slot.default_name for slot in skeleton] == [
        "Extrahera strukturerad grund",
        "Analysera strukturerat underlag",
        "Granska och färdigställ",
        "Skapa PDF",
    ]


def test_materialize_text_to_json_skeleton() -> None:
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.TEXT,
        final_output_type=OutputType.JSON,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("extract_structured_fields",),
        chain_steps=(),
    )
    skeleton = plan.minimum_slots

    assert len(skeleton) == 1
    assert skeleton[0].role == "semantic_required"
    assert skeleton[0].input_source == InputSource.FLOW_INPUT
    assert skeleton[0].input_type == InputType.TEXT
    assert skeleton[0].output_type == OutputType.JSON
    assert skeleton[0].output_fields == ()
    assert skeleton[0].runtime_upload is False


def test_materialize_linear_skeleton_expands_semantic_step_count() -> None:
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.TEXT,
        final_output_type=OutputType.JSON,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("extract_structured_fields",),
        chain_steps=(),
    )

    skeleton = plan.slots_for_semantic_count(3)

    assert _skeleton_type_modes(skeleton) == [
        ("text", "text", "pass_through"),
        ("text", "text", "pass_through"),
        ("text", "json", "pass_through"),
    ]
    assert [slot.input_source.value for slot in skeleton] == [
        "flow_input",
        "previous_step",
        "previous_step",
    ]


def test_linear_artifact_skeleton_keeps_backend_terminal_artifact_slot() -> None:
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=(),
        chain_steps=(),
    )
    skeleton = plan.slots_for_semantic_count(2)

    assert [slot.chain_token for slot in skeleton] == [
        None,
        None,
        TERMINAL_ARTIFACT_STEP,
    ]
    assert _skeleton_type_modes(skeleton) == [
        ("document", "text", "pass_through"),
        ("text", "text", "pass_through"),
        ("text", "docx", "pass_through"),
    ]
    assert skeleton[-1].document_delivery_mode == "generated"


def test_materialize_comparison_skeleton_places_fan_in_on_last_semantic() -> None:
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.TEXT,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("comparison",),
        chain_steps=(),
        aggregation_intent="compare",
    )
    two_step_skeleton = plan.slots_for_semantic_count(2)
    four_step_skeleton = plan.slots_for_semantic_count(4)

    assert [slot.input_source.value for slot in two_step_skeleton] == [
        "flow_input",
        "all_previous_steps",
    ]
    assert [slot.input_source.value for slot in four_step_skeleton] == [
        "flow_input",
        "previous_step",
        "previous_step",
        "all_previous_steps",
    ]
    assert two_step_skeleton[0].runtime_upload is True
    assert all(slot.runtime_upload is False for slot in two_step_skeleton[1:])


def test_skeleton_composition_records_output_type_drift() -> None:
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=(),
        chain_steps=(),
    )

    composition = plan.compose(
        [
            StepSkeletonSemanticContent(
                name="Draft report",
                instructions="Draft the report narrative.",
                requested_output_type=OutputType.PDF,
            )
        ]
    )

    assert [step.output_type.value for step in composition.steps] == ["text", "docx"]
    assert len(composition.output_type_drifts) == 1
    drift = composition.output_type_drifts[0]
    assert drift.slot_id == "final_response"
    assert drift.slot_ordinal == 0
    assert drift.requested_output_type == OutputType.PDF
    assert drift.enforced_output_type == OutputType.TEXT


def test_skeleton_composition_appends_terminal_text_after_structured_semantic() -> None:
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.TEXT,
        final_output_type=OutputType.TEXT,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=(),
        chain_steps=(),
    )

    composition = plan.compose(
        [
            StepSkeletonSemanticContent(
                name="Extract structure",
                instructions="Extract structured source data.",
                output_fields=tuple(default_structured_output_fields()),
            )
        ]
    )

    assert [step.output_type.value for step in composition.steps] == ["json", "text"]
    assert composition.steps[-1].name == "Create final answer"


def test_artifact_skeleton_keeps_final_semantic_body_text_when_fields_are_requested() -> (
    None
):
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.AUDIO,
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("audio_to_artifact_report",),
        chain_steps=_chain_steps("audio_to_artifact_report"),
        ui_language="sv",
    )

    composition = plan.compose(
        [
            StepSkeletonSemanticContent(
                name="Generera DOCX-dokument",
                instructions="Skapa dokumentets rubriker och textinnehåll.",
                output_fields=tuple(default_structured_output_fields()),
            )
        ]
    )

    assert [step.output_type.value for step in composition.steps] == [
        "text",
        "text",
        "docx",
    ]
    assert composition.steps[1].output_fields is None
    assert composition.steps[-1].input_source == InputSource.PREVIOUS_STEP
    assert composition.steps[-1].input_type == InputType.TEXT
    assert len(composition.output_type_drifts) == 1
    drift = composition.output_type_drifts[0]
    assert drift.requested_output_type == OutputType.JSON
    assert drift.enforced_output_type == OutputType.TEXT
    assert drift.dropped_output_fields is True


def test_docx_template_skeleton_keeps_template_body_text_when_fields_requested() -> (
    None
):
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.TEMPLATE_FILL,
        pattern_ids=("document_to_docx_template",),
        chain_steps=_chain_steps("document_to_docx_template"),
    )

    composition = plan.compose(
        [
            StepSkeletonSemanticContent(
                name="Prepare template body",
                instructions="Prepare text for the template.",
                output_fields=tuple(default_structured_output_fields()),
            )
        ]
    )

    assert [step.output_type.value for step in composition.steps] == [
        "json",
        "text",
        "docx",
    ]
    assert composition.steps[1].output_fields is None
    assert composition.steps[-1].document_delivery_mode == "template_fill"
    assert len(composition.output_type_drifts) == 1
    drift = composition.output_type_drifts[0]
    assert drift.requested_output_type == OutputType.JSON
    assert drift.enforced_output_type == OutputType.TEXT
    assert drift.dropped_output_fields is True


def test_backend_fixed_slots_keep_locked_input_type_after_structured_semantics() -> (
    None
):
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.PDF,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("multi_step_quality_chain",),
        chain_steps=_chain_steps("multi_step_quality_chain"),
    )

    composition = plan.compose(
        [
            StepSkeletonSemanticContent(
                name="Extract section data",
                instructions="Extract section data.",
                output_fields=tuple(default_structured_output_fields()),
            ),
            StepSkeletonSemanticContent(
                name="Extract risk data",
                instructions="Extract risk data.",
                output_fields=tuple(default_structured_output_fields()),
            ),
        ]
    )

    assert [step.name for step in composition.steps] == [
        "Extract structured foundation",
        "Extract section data",
        "Extract risk data",
        "Review and finalize",
        "Create PDF",
    ]
    assert composition.steps[2].output_type == OutputType.TEXT
    assert composition.steps[2].output_fields is None
    assert composition.steps[3].input_type == InputType.TEXT
    assert len(composition.output_type_drifts) == 1
    drift = composition.output_type_drifts[0]
    assert drift.slot_ordinal == 2
    assert drift.requested_output_type == OutputType.JSON
    assert drift.enforced_output_type == OutputType.TEXT
    assert drift.dropped_output_fields is True


@pytest.mark.parametrize("semantic_step_count", [1, 2, 3])
def test_audio_artifact_skeleton_matches_current_compiler_mechanics(
    semantic_step_count: int,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audio report",
            "plan_rationale": "Transcribe, summarize, and create a PDF.",
            "steps": [
                {
                    "name": f"Audio analysis step {index}",
                    "task": f"Analyze audio detail {index}.",
                }
                for index in range(1, semantic_step_count + 1)
            ],
        }
    )
    context = OutlineCompileContext(
        runtime_input_type=InputType.AUDIO,
        final_output_type=OutputType.PDF,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("audio_to_artifact_report",),
        pattern_chain_steps=_chain_steps("audio_to_artifact_report"),
    )

    draft = compile_outline_to_create_draft(outline, context=context)
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.AUDIO,
        final_output_type=OutputType.PDF,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=context.pattern_ids,
        chain_steps=context.pattern_chain_steps,
    )
    skeleton = plan.slots_for_semantic_count(len(outline.steps))

    assert _skeleton_mechanics(skeleton) == _draft_mechanics(draft)


@pytest.mark.parametrize("semantic_step_count", [1, 2, 3])
def test_linear_skeleton_matches_current_compiler_mechanics(
    semantic_step_count: int,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Structured text",
            "plan_rationale": "Analyze document material and return JSON.",
            "runtime_input": {"input_type": "document", "required": True},
            "final_output_type": "json",
            "steps": [
                {
                    "name": f"Text step {index}",
                    "task": f"Analyze text part {index}.",
                }
                for index in range(1, semantic_step_count + 1)
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.JSON,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("document_to_structured_report",),
        chain_steps=(),
    )
    skeleton = plan.slots_for_semantic_count(len(outline.steps))

    assert _skeleton_mechanics(skeleton) == _draft_mechanics(draft)


def test_docx_template_skeleton_matches_current_compiler_mechanics() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Template report",
            "plan_rationale": "Fill a DOCX template from uploaded material.",
            "steps": [
                {
                    "name": "Prepare report content",
                    "task": "Prepare the content for the template.",
                }
            ],
        }
    )
    context = OutlineCompileContext(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.TEMPLATE_FILL,
        pattern_ids=("document_to_docx_template",),
        pattern_chain_steps=_chain_steps("document_to_docx_template"),
    )

    draft = compile_outline_to_create_draft(outline, context=context)
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.TEMPLATE_FILL,
        pattern_ids=context.pattern_ids,
        chain_steps=context.pattern_chain_steps,
    )
    skeleton = plan.slots_for_semantic_count(len(outline.steps))

    assert _skeleton_mechanics(skeleton) == _draft_mechanics(draft)


@pytest.mark.parametrize("semantic_step_count", [2, 3, 4])
def test_comparison_skeleton_matches_current_compiler_mechanics(
    semantic_step_count: int,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Comparison",
            "plan_rationale": "Analyze branches, then compare.",
            "steps": [
                {
                    "name": f"Comparison step {index}",
                    "task": f"Analyze comparison step {index}.",
                }
                for index in range(1, semantic_step_count + 1)
            ],
        }
    )
    context = OutlineCompileContext(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.TEXT,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=("comparison",),
        aggregation_intent="compare",
    )

    draft = compile_outline_to_create_draft(outline, context=context)
    plan = materialize_step_skeleton(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.TEXT,
        final_output_mode=OutputMode.PASS_THROUGH,
        pattern_ids=context.pattern_ids,
        chain_steps=context.pattern_chain_steps,
        aggregation_intent=context.aggregation_intent,
    )
    skeleton = plan.slots_for_semantic_count(len(outline.steps))

    assert _skeleton_mechanics(skeleton) == _draft_mechanics(draft)


def _chain_steps(pattern_id: str) -> tuple[str, ...]:
    return PATTERN_REGISTRY[pattern_id].chain_steps


def _skeleton_type_modes(
    skeleton: tuple[StepSkeleton, ...],
) -> list[tuple[str, str, str]]:
    return [
        (
            slot.input_type.value,
            slot.output_type.value,
            slot.output_mode.value,
        )
        for slot in skeleton
    ]


def _skeleton_mechanics(
    skeleton: tuple[StepSkeleton, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            slot.input_source.value,
            slot.input_type.value,
            slot.output_type.value,
            slot.output_mode.value,
            slot.document_delivery_mode,
            slot.runtime_upload,
            slot.runtime_required,
            slot.runtime_max_files,
            bool(slot.output_fields),
        )
        for slot in skeleton
    )


def _draft_mechanics(draft: FlowCreateDraft) -> tuple[tuple[object, ...], ...]:
    compiled = compile_create_draft(draft)
    return tuple(
        (
            draft_step.input_source.value,
            draft_step.input_type.value,
            draft_step.output_type.value,
            compiled_step.output_mode.value,
            draft_step.document_delivery_mode,
            draft_step.runtime_upload,
            draft_step.runtime_required,
            draft_step.runtime_max_files,
            bool(draft_step.output_fields),
        )
        for draft_step, compiled_step in zip(draft.steps, compiled.steps, strict=True)
    )
