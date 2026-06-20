from scripts.flow_ai_builder_live_eval import (
    ExpectedOutcome,
    ExpectedQuestionBinding,
    JsonObject,
    LiveEvalCase,
    _cases,
    _evaluate_plan_case,
)


def _plan_with_question(question: str) -> JsonObject:
    return {
        "plan_id": "plan-1",
        "status": "draft",
        "proposal": {
            "spec": {
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Transkribera ljud",
                        "input_type": "audio",
                        "output_type": "text",
                    },
                    {
                        "plan_step_ref": "step_b",
                        "name": "Extrahera kontext",
                        "input_type": "text",
                        "output_type": "json",
                    },
                    {
                        "plan_step_ref": "step_c",
                        "name": "Förbered rapport",
                        "input_type": "text",
                        "output_type": "text",
                        "input_bindings": {"question": question},
                    },
                    {
                        "plan_step_ref": "step_d",
                        "name": "Skapa DOCX",
                        "input_type": "text",
                        "output_type": "docx",
                    },
                ]
            }
        },
    }


def _case() -> LiveEvalCase:
    return LiveEvalCase(
        case_id="C3_audio_to_docx_report",
        title="Audio meeting transcription to DOCX report",
        prompt="Create a DOCX meeting report from audio.",
        expected=ExpectedOutcome(
            terminal_output="docx_document",
            expected_question_bindings=(
                ExpectedQuestionBinding(
                    step_role="writing_or_materialization",
                    require_text_ref=True,
                    require_structured_field_ref=True,
                    forbid_broad_structured_ref=True,
                ),
            ),
        ),
    )


def test_live_eval_accepts_selected_structured_field_and_source_text_refs() -> None:
    verdict, reasons, *_ = _evaluate_plan_case(
        _case(),
        plan=_plan_with_question(
            "Möteskontext: {{ step_b.output.structured.meeting_context }}\n\n"
            "Källmaterial: {{ step_a.output.text }}"
        ),
        events=[],
        requirements_summary=None,
    )

    assert verdict == "pass"
    assert reasons == []


def test_live_eval_rejects_broad_structured_blob_for_underlag() -> None:
    verdict, reasons, *_ = _evaluate_plan_case(
        _case(),
        plan=_plan_with_question(
            "Möteskontext: {{ step_b.output.structured }}\n\n"
            "Källmaterial: {{ step_a.output.text }}"
        ),
        events=[],
        requirements_summary=None,
    )

    assert verdict == "fail"
    assert any("broad structured" in reason for reason in reasons)


def test_live_eval_requires_underlag_refs_on_same_target_step() -> None:
    plan = _plan_with_question("Källmaterial: {{ step_a.output.text }}")
    steps = plan["proposal"]["spec"]["steps"]
    assert isinstance(steps, list)
    final_step = steps[-1]
    assert isinstance(final_step, dict)
    final_step["input_bindings"] = {
        "question": "Möteskontext: {{ step_b.output.structured.meeting_context }}"
    }

    verdict, reasons, *_ = _evaluate_plan_case(
        _case(),
        plan=plan,
        events=[],
        requirements_summary=None,
    )

    assert verdict == "fail"
    assert any("Missing required source text" in reason for reason in reasons)


def test_live_eval_c3_answers_structured_analysis_question_without_rewriting_prompt() -> (
    None
):
    c3 = next(case for case in _cases() if case.case_id == "C3_audio_to_docx_report")

    assert c3.prompt == (
        "Create a flow that transcribes meeting audio, extracts ten topic "
        "sections, and produces a DOCX meeting report."
    )
    assert c3.question_answers["structured_analysis_need"] == (
        "use_structured_analysis",
    )
    assert c3.max_turns >= 3
