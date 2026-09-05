from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from eneo.flows.ai_builder.ai_builder_flow_review import (
    FlowReviewCohort,
    FlowReviewOmittedRuns,
    FlowReviewPacket,
    StepShareFact,
)
from eneo.flows.ai_builder.ai_builder_flow_review_sample import (
    FlowReviewSample,
    ReviewSampleBudget,
    ReviewSampleExcerpt,
    ReviewSampleRun,
    ReviewSampleStep,
)
from eneo.flows.ai_builder.ai_builder_flow_review_suggestions import (
    MAX_SUGGESTION_STEPS,
    build_review_suggestions_messages,
    parse_review_suggestions,
    render_review_sample,
    sample_summary,
)


def _sample() -> FlowReviewSample:
    run_a, run_b = uuid4(), uuid4()
    step_id = uuid4()
    packet = FlowReviewPacket(
        flow_id=uuid4(),
        flow_version=4,
        definition_checksum="sum-4",
        generated_at=datetime.now(timezone.utc),
        evidence_classification_level=2,
        steps=[],
        cohort=FlowReviewCohort(
            completed_run_ids=[run_a],
            failed_run_ids=[run_b],
            omitted=FlowReviewOmittedRuns(),
        ),
        facts=[
            StepShareFact(
                finding_id="f1f1f1f1f1f1f1f1",
                kind="token_share",
                step_id=step_id,
                step_order=2,
                share=0.8,
                run_count=3,
            )
        ],
    )
    steps = [
        ReviewSampleStep(
            step_order=order,
            label=f"Steg {order}",
            input_source="flow_input" if order == 1 else "previous_step",
            input_type="document" if order == 1 else "text",
            output_type="text",
            output_mode="pass_through",
            binding_summary=None,
            output_contract_fields=[],
            review_mode=None,
        )
        for order in (1, 2)
    ]
    excerpts = [
        ReviewSampleExcerpt(
            run_id=run_a,
            step_order=1,
            field="output",
            availability="included",
            text="Sammanfattning av ärendet: tre punkter.",
            recorded_chars=39,
        ),
        ReviewSampleExcerpt(
            run_id=run_a,
            step_order=2,
            field="prompt",
            availability="included",
            text="Sammanfatta ärendet i tre punkter.",
            recorded_chars=34,
        ),
        ReviewSampleExcerpt(
            run_id=run_a,
            step_order=2,
            field="output",
            availability="omitted_by_budget",
            recorded_chars=5000,
        ),
        ReviewSampleExcerpt(
            run_id=run_b, step_order=1, field="output", availability="not_recorded"
        ),
    ]
    return FlowReviewSample(
        packet=packet,
        generated_at=datetime.now(timezone.utc),
        evidence_classification_level=2,
        steps=steps,
        runs=[
            ReviewSampleRun(
                run_id=run_a, status="completed", evidence_classification_level=2
            ),
            ReviewSampleRun(
                run_id=run_b, status="failed", evidence_classification_level=1
            ),
        ],
        excerpts=excerpts,
        budget=ReviewSampleBudget(
            per_excerpt_chars=1500, total_excerpt_chars=30000, used_excerpt_chars=73
        ),
    )


def _answer(*suggestions: dict) -> str:
    return json.dumps({"suggestions": list(suggestions)}, ensure_ascii=False)


def test_prompt_names_every_excerpt_by_source_id_and_marks_what_cannot_be_read():
    sample = _sample()
    rendered = render_review_sample(sample)
    assert "[run1.step1.output]" in rendered
    assert "Sammanfattning av ärendet: tre punkter." in rendered
    assert "[run1.step2.output] (utelämnad av budgetskäl" in rendered
    assert "[run2.step1.output] (inte inspelad" in rendered
    assert "[f1f1f1f1f1f1f1f1]" in rendered
    messages = build_review_suggestions_messages(sample, ui_language="sv")
    assert (
        messages[0]["role"] == "system" and "duplicated_work" in messages[0]["content"]
    )


def test_summary_counts_excerpts_by_availability():
    summary = sample_summary(_sample())
    assert (summary.excerpts_included, summary.excerpts_omitted_by_budget) == (2, 1)
    assert summary.excerpts_not_recorded == 1


def test_valid_answer_is_admitted_with_resolved_sources_and_facts():
    sample = _sample()
    parsed = parse_review_suggestions(
        _answer(
            {
                "kind": "duplicated_work",
                "step_orders": [2, 1],
                "rationale": "Steg 2 sammanfattar det steg 1 redan sammanfattade.",
                "sources": [
                    {"source_id": "run1.step1.output", "quote": "tre punkter"},
                    {"source_id": "run1.step2.prompt", "quote": "Sammanfatta ärendet"},
                ],
                "fact_ids": ["f1f1f1f1f1f1f1f1"],
            }
        ),
        sample=sample,
    )
    assert parsed.outcome == "valid"
    (suggestion,) = parsed.suggestions
    assert suggestion.step_orders == [1, 2]
    assert suggestion.sources[0].run_id == sample.runs[0].run_id
    assert suggestion.sources[0].field == "output"
    assert suggestion.fact_ids == ["f1f1f1f1f1f1f1f1"]


def test_empty_answer_is_valid_and_distinct_from_invalid_output():
    sample = _sample()
    assert parse_review_suggestions(_answer(), sample=sample).outcome == "valid"
    assert parse_review_suggestions("not json", sample=sample).outcome == "invalid"
    assert parse_review_suggestions("[]", sample=sample).outcome == "invalid"


def test_unknown_kind_unverifiable_source_or_foreign_fact_invalidates_the_answer():
    sample = _sample()
    base = {
        "step_orders": [1],
        "rationale": "x",
        "sources": [{"source_id": "run1.step1.output", "quote": "tre punkter"}],
    }
    cases = {
        "unknown kind": {**base, "kind": "rename_step"},
        "step not in definition": {**base, "kind": "missing_check", "step_orders": [9]},
        "quote not in excerpt": {
            **base,
            "kind": "missing_check",
            "sources": [{"source_id": "run1.step1.output", "quote": "fyra punkter"}],
        },
        "source without readable text": {
            **base,
            "kind": "missing_check",
            "sources": [{"source_id": "run1.step2.output", "quote": "x"}],
        },
        "unknown source": {
            **base,
            "kind": "missing_check",
            "sources": [{"source_id": "run3.step1.output", "quote": "x"}],
        },
        "foreign fact": {**base, "kind": "missing_check", "fact_ids": ["nope"]},
        "no sources": {**base, "kind": "missing_check", "sources": []},
    }
    for label, suggestion in cases.items():
        parsed = parse_review_suggestions(_answer(suggestion), sample=sample)
        assert parsed.outcome == "invalid", label
        assert parsed.problems, label
        # Diagnostics are codes with positions, never the model's own text.
        assert all(":" in problem for problem in parsed.problems), label
        assert "rename_step" not in " ".join(parsed.problems)


def test_a_suggestion_names_at_most_the_steps_a_request_can_carry():
    """Generation and handoff share one step limit: what the parser admits
    always validates as an investigation request, and one step more is
    refused whole rather than truncated."""
    from eneo.flows.ai_builder.ai_builder_flow_review import (
        AIBuilderSuggestionContext,
    )

    base = _sample()
    wide = base.model_copy(
        update={
            "steps": [
                base.steps[1].model_copy(update={"step_order": order})
                for order in range(1, MAX_SUGGESTION_STEPS + 2)
            ]
        }
    )
    suggestion = {
        "kind": "duplicated_work",
        "rationale": "x",
        "sources": [{"source_id": "run1.step1.output", "quote": "tre punkter"}],
    }

    admitted = parse_review_suggestions(
        _answer(
            {**suggestion, "step_orders": list(range(1, MAX_SUGGESTION_STEPS + 1))}
        ),
        sample=wide,
    )
    assert admitted.outcome == "valid"
    AIBuilderSuggestionContext(
        flow_version=wide.packet.flow_version,
        definition_checksum=wide.packet.definition_checksum,
        sample_run_ids=[run.run_id for run in wide.runs],
        suggestion_kind=admitted.suggestions[0].kind,
        step_orders=admitted.suggestions[0].step_orders,
    )

    refused = parse_review_suggestions(
        _answer(
            {**suggestion, "step_orders": list(range(1, MAX_SUGGESTION_STEPS + 2))}
        ),
        sample=wide,
    )
    assert refused.outcome == "invalid"
    assert list(refused.problems) == ["suggestion_1:too_many_steps"]


def test_absence_claims_need_complete_evidence_for_their_sources_and_steps():
    sample = _sample()
    # run1.step2.output is omitted by budget: step 2 has no complete output, and
    # the only readable source for it is the prompt.
    absence_on_incomplete_step = {
        "kind": "missing_check",
        "step_orders": [2],
        "rationale": "Ingen kontroll av datum sker i steg 2.",
        "sources": [{"source_id": "run1.step2.prompt", "quote": "Sammanfatta ärendet"}],
    }
    parsed = parse_review_suggestions(
        _answer(absence_on_incomplete_step), sample=sample
    )
    assert parsed.outcome == "invalid"
    assert parsed.problems == (
        "suggestion_1:absence_claim_without_complete_step_output",
    )

    # Step 1 has a complete output in run 1: a missing_check on step 1 may cite it.
    absence_on_complete_step = {
        "kind": "missing_check",
        "step_orders": [1],
        "rationale": "Ingen kontroll av datum sker i steg 1.",
        "sources": [{"source_id": "run1.step1.output", "quote": "tre punkter"}],
    }
    assert (
        parse_review_suggestions(
            _answer(absence_on_complete_step), sample=sample
        ).outcome
        == "valid"
    )

    # The same claim resting on a truncated excerpt is refused.
    truncated_sample = sample.model_copy(
        update={
            "excerpts": [
                excerpt.model_copy(update={"availability": "truncated"})
                if excerpt.step_order == 1 and excerpt.field == "output"
                else excerpt
                for excerpt in sample.excerpts
            ]
        }
    )
    parsed = parse_review_suggestions(
        _answer(absence_on_complete_step), sample=truncated_sample
    )
    assert parsed.outcome == "invalid"
    assert parsed.problems[0].endswith("absence_claim_cites_incomplete_source")
    # A drift claim on the same truncated excerpt is still admissible.
    drift = {**absence_on_complete_step, "kind": "instruction_outcome_drift"}
    assert (
        parse_review_suggestions(_answer(drift), sample=truncated_sample).outcome
        == "valid"
    )


def test_prompt_states_the_wire_shape_in_every_mode():
    messages = build_review_suggestions_messages(_sample(), ui_language="sv")
    system = messages[0]["content"]
    for key in (
        '"suggestions"',
        '"kind"',
        '"step_orders"',
        '"rationale"',
        '"sources"',
        '"source_id"',
        '"quote"',
        '"fact_ids"',
    ):
        assert key in system
    assert '{"suggestions": []}' in system


def test_a_complete_output_in_another_run_does_not_rescue_an_absence_claim():
    sample = _sample()
    run_b = sample.runs[1].run_id
    # run2 gets a complete output for step 2; run1's step 2 output stays omitted.
    rescued = sample.model_copy(
        update={
            "excerpts": [
                *sample.excerpts,
                ReviewSampleExcerpt(
                    run_id=run_b,
                    step_order=2,
                    field="output",
                    availability="included",
                    text="Tre punkter utan datum.",
                    recorded_chars=23,
                ),
            ]
        }
    )
    claim = {
        "kind": "missing_check",
        "step_orders": [2],
        "rationale": "Ingen kontroll av datum sker i steg 2.",
        "sources": [{"source_id": "run1.step2.prompt", "quote": "Sammanfatta ärendet"}],
    }
    parsed = parse_review_suggestions(_answer(claim), sample=rescued)
    assert parsed.outcome == "invalid"
    assert parsed.problems == (
        "suggestion_1:absence_claim_without_complete_step_output",
    )

    # Citing run2's own complete output makes the same claim admissible.
    claim_on_run2 = {
        **claim,
        "sources": [{"source_id": "run2.step2.output", "quote": "utan datum"}],
    }
    assert (
        parse_review_suggestions(_answer(claim_on_run2), sample=rescued).outcome
        == "valid"
    )
