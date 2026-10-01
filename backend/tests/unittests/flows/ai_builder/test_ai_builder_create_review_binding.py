"""Create binds a requested structured-result review to the step the plan
declares, through every assembly transform, or fails naming that step."""

from __future__ import annotations

from typing import Any

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    CreateCompileContext,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    CreateFlowIntent,
    ProposalIntentArgumentError,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.planning_state import CheckpointIntent, ReportDisposition
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy

EDIT = FlowStepReviewMode.EDIT


def _structured_review(
    mode: FlowStepReviewMode = EDIT,
) -> tuple[CheckpointIntent, ...]:
    return (
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="structured_result",
            operation="set",
            mode=mode,
            confidence="high",
            evidence=["quote:user_message:1:Let me check and correct it first."],
        ),
    )


def _step(
    name: str,
    *,
    fields: tuple[str, ...] = (),
    review_mode: object = None,
    declare: bool = False,
) -> dict[str, Any]:
    step: dict[str, Any] = {"name": name, "instructions": f"{name}."}
    if fields:
        step["output_fields"] = [
            {"name": field, "field_type": "string", "description": f"{field}."}
            for field in fields
        ]
    if declare:
        step["review_mode"] = review_mode
    return step


def _intent(*steps: dict[str, Any]) -> CreateFlowIntent:
    return parse_create_flow_intent_arguments(
        {
            "flow_name": "Reviewed comparison",
            "plan_rationale": "Compare, decide, write.",
            "steps": list(steps),
        }
    )


def _reviewed(spec: FlowDraftSpecCore) -> list[tuple[str, FlowStepReviewPolicy]]:
    return [
        (step.name, step.review_policy)
        for step in spec.steps
        if step.review_policy is not None
    ]


_TEXT_LETTER = CreateCompileContext(
    runtime_input_type=InputType.TEXT,
    final_output_type=OutputType.TEXT,
    checkpoint_intents=_structured_review(),
)


def test_review_sits_on_the_declared_earlier_comparison() -> None:
    """Two JSON producers then delivery; the person reviews the earlier one."""

    compiled = compile_create_intent_to_spec(
        _intent(
            _step(
                "Compare offers",
                fields=("comparison",),
                declare=True,
                review_mode="edit",
            ),
            _step("Decide grant", fields=("decision",)),
            _step("Write letter"),
        ),
        context=_TEXT_LETTER,
    )

    assert _reviewed(compiled) == [("Compare offers", FlowStepReviewPolicy(mode=EDIT))]
    comparison, decision = compiled.steps[0], compiled.steps[1]
    assert comparison.output_type is OutputType.JSON
    # The decision reads the reviewed comparison, so an edit reaches delivery.
    assert decision.input_source is InputSource.PREVIOUS_STEP
    assert decision.input_type is InputType.JSON


def test_template_flow_reviews_the_declared_comparison() -> None:
    compiled = compile_create_intent_to_spec(
        _intent(
            _step(
                "Compare offers",
                fields=("comparison",),
                declare=True,
                review_mode="edit",
            ),
            _step("Prepare decision", fields=("decision_text",)),
        ),
        context=CreateCompileContext(
            runtime_input_type=InputType.JSON,
            final_output_type=OutputType.DOCX,
            final_output_mode=OutputMode.TEMPLATE_FILL,
            pattern_ids=("json_to_artifact_report",),
            selected_template_count=1,
            selected_template_placeholders=("decision_text",),
            checkpoint_intents=_structured_review(),
        ),
    )

    assert _reviewed(compiled) == [("Compare offers", FlowStepReviewPolicy(mode=EDIT))]
    assert compiled.steps[1].name == "Prepare decision"
    assert compiled.steps[1].input_source is InputSource.PREVIOUS_STEP


def test_template_keeps_a_reviewed_validation_step_with_its_checkpoint() -> None:
    """Approve the validation result before filling the document."""

    compiled = compile_create_intent_to_spec(
        _intent(
            _step("Prepare decision", fields=("decision_text",)),
            _step(
                "Validate decision",
                fields=("validation_note",),
                declare=True,
                review_mode="edit",
            ),
        ),
        context=CreateCompileContext(
            runtime_input_type=InputType.JSON,
            final_output_type=OutputType.DOCX,
            final_output_mode=OutputMode.TEMPLATE_FILL,
            pattern_ids=("json_to_artifact_report",),
            selected_template_count=1,
            selected_template_placeholders=("decision_text",),
            checkpoint_intents=_structured_review(),
        ),
    )

    assert _reviewed(compiled) == [
        ("Validate decision", FlowStepReviewPolicy(mode=EDIT))
    ]
    assert compiled.steps[-1].output_mode is OutputMode.TEMPLATE_FILL


def test_unreviewed_unused_template_predecessor_is_still_dropped() -> None:
    compiled = compile_create_intent_to_spec(
        _intent(
            _step(
                "Prepare decision",
                fields=("decision_text",),
                declare=True,
                review_mode="edit",
            ),
            _step("Prepare runtime date", fields=("datum",)),
        ),
        context=CreateCompileContext(
            runtime_input_type=InputType.JSON,
            final_output_type=OutputType.DOCX,
            final_output_mode=OutputMode.TEMPLATE_FILL,
            pattern_ids=("json_to_artifact_report",),
            selected_template_count=1,
            selected_template_placeholders=("decision_text",),
            checkpoint_intents=_structured_review(),
        ),
    )

    assert [step.name for step in compiled.steps][:-1] == ["Prepare decision"]
    assert _reviewed(compiled) == [
        ("Prepare decision", FlowStepReviewPolicy(mode=EDIT))
    ]


def test_undeclared_review_among_several_results_names_them() -> None:
    with pytest.raises(AIBuilderArchitectureError) as raised:
        compile_create_intent_to_spec(
            _intent(
                _step("Compare offers", fields=("comparison",)),
                _step("Decide grant", fields=("decision",)),
                _step("Write letter"),
            ),
            context=_TEXT_LETTER,
        )

    assert raised.value.repair_disposition == "model_correctable"
    assert raised.value.failure_code == "assembly_structured_review_target_ambiguous"
    assert "'Compare offers'" in raised.value.detail
    assert "'Decide grant'" in raised.value.detail
    assert "review_mode" in raised.value.detail


def test_undeclared_review_with_one_result_is_inferred() -> None:
    compiled = compile_create_intent_to_spec(
        _intent(
            _step("Compare offers", fields=("comparison",)),
            _step("Write letter"),
        ),
        context=_TEXT_LETTER,
    )

    assert _reviewed(compiled) == [("Compare offers", FlowStepReviewPolicy(mode=EDIT))]


_PDF_LETTER = CreateCompileContext(
    runtime_input_type=InputType.TEXT,
    final_output_type=OutputType.PDF,
    final_output_mode=OutputMode.RENDER_VERBATIM,
    ui_language="en",
    checkpoint_intents=_structured_review(),
)


@pytest.mark.parametrize(
    ("steps", "context", "named"),
    [
        (
            (
                _step(
                    "Write decision",
                    fields=("decision",),
                    declare=True,
                    review_mode="edit",
                ),
            ),
            _TEXT_LETTER,
            "step 1 'Write decision'",
        ),
        (
            (
                _step("Write the letter text"),
                _step("Render PDF", declare=True, review_mode="edit"),
            ),
            _PDF_LETTER,
            "step 2 'Render PDF'",
        ),
        (
            (
                _step("Compare", fields=("comparison",)),
                _step("Write the letter text"),
                _step("Render PDF", declare=True, review_mode="edit"),
            ),
            _PDF_LETTER,
            "step 3 'Render PDF'",
        ),
    ],
    ids=["sole-step-folded", "dropped-render-helper", "dropped-helper-other-json"],
)
def test_a_lost_declaration_always_names_the_declared_step(
    steps: tuple[dict[str, Any], ...],
    context: CreateCompileContext,
    named: str,
) -> None:
    with pytest.raises(AIBuilderArchitectureError) as raised:
        compile_create_intent_to_spec(_intent(*steps), context=context)

    assert raised.value.repair_disposition == "model_correctable"
    assert named in raised.value.detail


@pytest.mark.parametrize(
    "disposition", ["synthesized_overview", "per_source_sections", "both"]
)
def test_one_authored_step_report_infers_its_review_past_generated_writers(
    disposition: ReportDisposition,
) -> None:
    """Generated section and overview writers are not results a plan can
    declare, so a single authored step stays unambiguous."""

    compiled = compile_create_intent_to_spec(
        _intent(_step("Summarise the case", fields=("case_summary",))),
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            report_disposition=disposition,
            ui_language="en",
            checkpoint_intents=_structured_review(),
        ),
    )

    reviewed = [step for step in compiled.steps if step.review_policy is not None]
    assert reviewed == [compiled.steps[0]]


def test_an_ambiguous_report_names_only_authored_steps() -> None:
    with pytest.raises(AIBuilderArchitectureError) as raised:
        compile_create_intent_to_spec(
            _intent(
                _step("Read documents", fields=("summary",)),
                _step("Analyse risks", fields=("risks",)),
                _step("Assemble report"),
            ),
            context=CreateCompileContext(
                runtime_input_type=InputType.DOCUMENT,
                final_output_type=OutputType.PDF,
                final_output_mode=OutputMode.RENDER_VERBATIM,
                report_disposition="both",
                ui_language="en",
                checkpoint_intents=_structured_review(),
            ),
        )

    assert "('Read documents', 'Analyse risks')" in raised.value.detail


_DOCX_LETTER = CreateCompileContext(
    runtime_input_type=InputType.DOCUMENT,
    final_output_type=OutputType.DOCX,
    final_output_mode=OutputMode.RENDER_VERBATIM,
    ui_language="en",
    checkpoint_intents=_structured_review(),
)


def _lost_declaration_detail(
    steps: tuple[dict[str, Any], ...], context: CreateCompileContext
) -> str:
    with pytest.raises(AIBuilderArchitectureError) as raised:
        compile_create_intent_to_spec(_intent(*steps), context=context)
    return raised.value.detail


_GENERIC = (
    "sets review_mode but its result does not stay a structured JSON result "
    "after the flow is assembled; compute and review the figures in an earlier "
    "step that returns structured fields."
)


def _report_context(disposition: ReportDisposition) -> CreateCompileContext:
    return CreateCompileContext(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.PDF,
        final_output_mode=OutputMode.RENDER_VERBATIM,
        report_disposition=disposition,
        ui_language="en",
        checkpoint_intents=_structured_review(),
    )


_DECLARED = {"declare": True, "review_mode": "edit"}
_REPORT_DISPOSITIONS = ("synthesized_overview", "both", "per_source_sections")


@pytest.mark.parametrize(
    ("steps", "context", "declared"),
    [
        (
            (
                _step("Extract case data", fields=("income", "rent")),
                _step(
                    "Calculate and write",
                    fields=("calculation", "decision"),
                    **_DECLARED,
                ),
            ),
            _DOCX_LETTER,
            "step 2 'Calculate and write'",
        ),
        (
            (
                _step("Compare", fields=("comparison",)),
                _step("Write decision", fields=("decision",), **_DECLARED),
            ),
            _TEXT_LETTER,
            "step 2 'Write decision'",
        ),
        (
            (
                _step("Compare", fields=("comparison",)),
                _step("Write the letter text", **_DECLARED),
                _step("Render PDF"),
            ),
            _PDF_LETTER,
            "step 2 'Write the letter text'",
        ),
        (
            (
                _step("Analyse", fields=("a",)),
                _step("Analyse", fields=("b",)),
                _step("Analyse", fields=("c",), **_DECLARED),
            ),
            _DOCX_LETTER,
            "step 3 'Analyse'",
        ),
        (
            (_step("Write the letter text"), _step("Create the PDF", **_DECLARED)),
            _PDF_LETTER,
            "step 2 'Create the PDF'",
        ),
        *(
            (
                (
                    _step("Read documents", fields=("summary",)),
                    _step(name, **_DECLARED),
                ),
                _report_context(disposition),
                f"step 2 '{name}'",
            )
            for disposition in _REPORT_DISPOSITIONS
            for name in ("Render PDF", "Write report", "Write overview")
        ),
    ],
)
def test_a_lost_declaration_names_only_the_declared_step_and_a_generic_cause(
    steps: tuple[dict[str, Any], ...],
    context: CreateCompileContext,
    declared: str,
) -> None:
    """No cause and no other step is inferred from names: assembly merges,
    renames and adds steps, so a name match proves nothing."""

    detail = _lost_declaration_detail(steps, context)

    assert detail.endswith(f"{declared} {_GENERIC}")
    assert detail.count("'") == 2


def test_a_lost_declaration_fails_naming_the_step_and_never_rebinds() -> None:
    """The declared terminal folds to text; the other JSON step stays unreviewed."""

    with pytest.raises(AIBuilderArchitectureError) as raised:
        compile_create_intent_to_spec(
            _intent(
                _step("Compare offers", fields=("comparison",)),
                _step(
                    "Write decision",
                    fields=("decision",),
                    declare=True,
                    review_mode="edit",
                ),
            ),
            context=_TEXT_LETTER,
        )

    assert raised.value.repair_disposition == "model_correctable"
    assert "step 2 'Write decision'" in raised.value.detail


def test_a_declared_result_survives_terminal_field_completion() -> None:
    compiled = compile_create_intent_to_spec(
        _intent(
            _step("Compare offers", fields=("comparison",)),
            _step(
                "Decide grant", fields=("decision",), declare=True, review_mode="edit"
            ),
        ),
        context=CreateCompileContext(
            runtime_input_type=InputType.TEXT,
            final_output_type=OutputType.JSON,
            result_contract_output_fields=(
                StructuredFieldDraft(
                    name="follow_up", field_type="string", description="Follow-up."
                ),
            ),
            checkpoint_intents=_structured_review(),
        ),
    )

    assert _reviewed(compiled) == [("Decide grant", FlowStepReviewPolicy(mode=EDIT))]
    assert compiled.steps[-1].output_contract is not None
    assert "follow_up" in compiled.steps[-1].output_contract["properties"]


def test_a_replaced_section_writer_hands_its_declaration_to_its_replacement() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document report",
            "plan_rationale": "Read sources, write sections and the report.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Read every document.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One entry per document.",
                            "children": [
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Summary.",
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Write report sections",
                    "instructions": "Write one section per document.",
                    "output_fields": [
                        {
                            "name": "section_text",
                            "field_type": "string",
                            "description": "Section text.",
                        }
                    ],
                    "review_mode": "edit",
                },
                {"name": "Assemble report", "instructions": "Assemble the report."},
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.PASS_THROUGH,
            runtime_max_files=4,
            aggregation_intent="aggregate",
            ui_language="en",
            report_disposition="per_source_sections",
            checkpoint_intents=_structured_review(),
        ),
    )

    reviewed = _reviewed(compiled)
    assert len(reviewed) == 1
    section_writer = next(
        step for step in compiled.steps if step.review_policy is not None
    )
    assert section_writer.output_type is OutputType.JSON
    assert section_writer is compiled.steps[1]
    assert "Write one section per document." in (
        section_writer.assistant_spec.instructions
    )


def test_a_single_step_report_keeps_one_declaration_on_its_reader() -> None:
    """The one authored step splits into a reader and a writer; with a
    synthesized overview the writer folds into a generated JSON step, which
    must not pick up a second review."""

    compiled = compile_create_intent_to_spec(
        _intent(
            _step(
                "Summarise the case",
                fields=("case_summary",),
                declare=True,
                review_mode="edit",
            )
        ),
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            report_disposition="synthesized_overview",
            ui_language="en",
            checkpoint_intents=_structured_review(),
        ),
    )

    reviewed = [step for step in compiled.steps if step.review_policy is not None]
    assert reviewed == [compiled.steps[0]]
    assert compiled.steps[0].output_type is OutputType.JSON


def test_create_admits_at_most_one_declared_result() -> None:
    two = _intent(
        _step(
            "Compare offers", fields=("comparison",), declare=True, review_mode="edit"
        ),
        _step("Decide grant", fields=("decision",), declare=True, review_mode="edit"),
    )
    with pytest.raises(ProposalIntentArgumentError) as raised:
        compile_create_intent_to_spec(two, context=_TEXT_LETTER)
    assert any("steps.1.review_mode" in issue for issue in raised.value.issues)
    assert any("steps.2.review_mode" in issue for issue in raised.value.issues)


@pytest.mark.parametrize(
    "checkpoint_intents",
    [None, (), _structured_review(FlowStepReviewMode.VIEW)],
    ids=["no-intents", "no-structured-intent", "other-mode"],
)
def test_create_refuses_a_declaration_nobody_requested(
    checkpoint_intents: tuple[CheckpointIntent, ...] | None,
) -> None:
    declared = _intent(
        _step(
            "Compare offers", fields=("comparison",), declare=True, review_mode="edit"
        ),
        _step("Write letter"),
    )
    with pytest.raises(ProposalIntentArgumentError) as raised:
        compile_create_intent_to_spec(
            declared,
            context=CreateCompileContext(
                runtime_input_type=InputType.TEXT,
                final_output_type=OutputType.TEXT,
                checkpoint_intents=checkpoint_intents,
            ),
        )
    assert any("steps.1.review_mode" in issue for issue in raised.value.issues)


@pytest.mark.parametrize("value", ["none", "", "approve", True, 1, {}, []])
def test_create_parse_refuses_a_review_mode_outside_the_modes(value: object) -> None:
    with pytest.raises(ProposalIntentArgumentError):
        _intent(
            _step(
                "Compare offers",
                fields=("comparison",),
                declare=True,
                review_mode=value,
            )
        )


def test_null_review_mode_is_no_declaration() -> None:
    intent = _intent(
        _step("Compare offers", fields=("comparison",), declare=True, review_mode=None)
    )
    assert intent.steps[0].review_mode is None


def test_another_missing_checkpoint_producer_never_blames_the_declared_step() -> None:
    """The structured result stays bound; the report review has no text
    producer, so the error names that producer kind, not the declared step."""

    report_review = CheckpointIntent(
        evidence_level="explicit",
        producer_kind="report_text",
        operation="set",
        mode=EDIT,
        confidence="high",
        evidence=["quote:user_message:1:Let me edit the letter text too."],
    )
    with pytest.raises(AIBuilderArchitectureError) as raised:
        compile_create_intent_to_spec(
            _intent(
                _step(
                    "Compare offers",
                    fields=("comparison",),
                    declare=True,
                    review_mode="edit",
                ),
                _step("Prepare decision", fields=("decision_text",)),
            ),
            context=CreateCompileContext(
                runtime_input_type=InputType.JSON,
                final_output_type=OutputType.DOCX,
                final_output_mode=OutputMode.TEMPLATE_FILL,
                pattern_ids=("json_to_artifact_report",),
                selected_template_count=1,
                selected_template_placeholders=("decision_text",),
                checkpoint_intents=(*_structured_review(), report_review),
            ),
        )

    assert raised.value.repair_disposition == "model_correctable"
    assert "Compare offers" not in raised.value.detail
    assert "report_text" in raised.value.detail
