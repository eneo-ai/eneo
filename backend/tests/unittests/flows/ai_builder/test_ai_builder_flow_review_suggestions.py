from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_flow_review import (
    FlowReviewCohort,
    FlowReviewEvidence,
    FlowReviewOmittedRuns,
    FlowReviewPacket,
    StepShareFact,
    render_review_evidence,
)
from eneo.flows.ai_builder.ai_builder_flow_review_sample import (
    FlowReviewSample,
    ReviewSampleExcerpt,
    ReviewSampleRun,
    ReviewSampleStep,
    quoted_excerpt,
    review_prompt_groups,
)
from eneo.flows.ai_builder.ai_builder_flow_review_suggestions import (
    MAX_SUGGESTION_STEPS,
    build_review_suggestions_messages,
    parse_review_suggestions,
    render_review_sample,
    sample_summary,
)
from eneo.tokens.token_utils import measure_provider_input_reserve


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


def test_unknown_kind_unverifiable_source_or_foreign_fact_refuses_that_suggestion():
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
        # The envelope is fine; the one suggestion in it is refused by code.
        assert parsed.outcome == "valid", label
        assert parsed.suggestions == (), label
        assert len(parsed.problems) == 1, label
        # Diagnostics are codes with positions, never the model's own text.
        assert all(":" in problem for problem in parsed.problems), label
        assert "rename_step" not in " ".join(parsed.problems)


def test_a_quote_across_line_breaks_still_resolves_in_the_excerpt():
    """Markdown outputs wrap; a quote with the same words in one line is the
    same evidence. Different words are not."""
    base = _sample()
    wrapped = base.model_copy(
        update={
            "excerpts": [
                base.excerpts[0].model_copy(
                    update={"text": "Sammanfattning av ärendet:\n\n- tre  punkter.\n"}
                ),
                *base.excerpts[1:],
            ]
        }
    )
    suggestion = {
        "kind": "duplicated_work",
        "step_orders": [1],
        "rationale": "x",
        "sources": [
            {"source_id": "run1.step1.output", "quote": "ärendet: - tre punkter"}
        ],
    }
    parsed = parse_review_suggestions(_answer(suggestion), sample=wrapped)
    assert [item.sources[0].quote for item in parsed.suggestions] == [
        "ärendet: - tre punkter"
    ]
    other = {
        **suggestion,
        "sources": [{"source_id": "run1.step1.output", "quote": "fyra punkter"}],
    }
    assert list(parse_review_suggestions(_answer(other), sample=wrapped).problems) == [
        "suggestion_1:source_1:quote_not_in_excerpt"
    ]


def test_a_drift_claim_is_one_step_in_one_run_with_its_instruction_and_complete_output():
    """Instruction-versus-outcome is judged for one step in one run, which the
    source limit can always hold: the claim must cite that step's instruction
    and its complete output. Several steps or runs, an instruction alone, an
    output alone, another step's output, or a cut output is refused by code."""
    base = _sample()
    # Give step 2 a complete output so a well-formed claim exists.
    sample = base.model_copy(
        update={
            "excerpts": [
                *base.excerpts[:2],
                base.excerpts[2].model_copy(
                    update={
                        "availability": "included",
                        "text": "Tre punkter om ärendet.",
                        "recorded_chars": 23,
                    }
                ),
                base.excerpts[3],
            ]
        }
    )
    drift = {"kind": "instruction_outcome_drift", "rationale": "x"}

    def problems(claim):
        return list(parse_review_suggestions(_answer(claim), sample=sample).problems)

    well_formed = {
        **drift,
        "step_orders": [2],
        "sources": [
            {"source_id": "run1.step2.prompt", "quote": "Sammanfatta ärendet"},
            {"source_id": "run1.step2.output", "quote": "Tre punkter"},
        ],
    }
    assert [
        item.kind
        for item in parse_review_suggestions(
            _answer(well_formed), sample=sample
        ).suggestions
    ] == ["instruction_outcome_drift"]

    # Every allowed drift shape fits the source limit: one step, one run,
    # two sources. Two steps are two suggestions, refused by rule, never by
    # the source cap.
    two_steps = {**well_formed, "step_orders": [1, 2]}
    assert problems(two_steps) == ["suggestion_1:drift_claim_names_several_steps"]
    # An instruction from one run and an output from another is not a pair:
    # the one-run rule is what stops the index below from combining them.
    two_runs = sample.model_copy(
        update={
            "excerpts": [
                *sample.excerpts,
                sample.excerpts[2].model_copy(update={"run_id": sample.runs[1].run_id}),
            ]
        }
    )
    split_across_runs = {
        **well_formed,
        "sources": [
            {"source_id": "run1.step2.prompt", "quote": "Sammanfatta ärendet"},
            {"source_id": "run2.step2.output", "quote": "Tre punkter"},
        ],
    }
    assert list(
        parse_review_suggestions(_answer(split_across_runs), sample=two_runs).problems
    ) == ["suggestion_1:drift_claim_cites_several_runs"]
    instruction_only = {**well_formed, "sources": well_formed["sources"][:1]}
    assert problems(instruction_only) == [
        "suggestion_1:drift_claim_without_output_source"
    ]
    output_only = {**well_formed, "sources": well_formed["sources"][1:]}
    assert problems(output_only) == [
        "suggestion_1:drift_claim_without_instruction_source"
    ]
    other_steps_output = {
        **well_formed,
        "sources": [
            {"source_id": "run1.step2.prompt", "quote": "Sammanfatta ärendet"},
            {"source_id": "run1.step1.output", "quote": "tre punkter"},
        ],
    }
    assert problems(other_steps_output) == [
        "suggestion_1:drift_claim_without_output_source"
    ]
    cut = sample.model_copy(
        update={
            "excerpts": [
                *sample.excerpts[:2],
                sample.excerpts[2].model_copy(update={"availability": "truncated"}),
                *sample.excerpts[3:],
            ]
        }
    )
    assert list(
        parse_review_suggestions(_answer(well_formed), sample=cut).problems
    ) == ["suggestion_1:drift_claim_cites_incomplete_output"]


def test_two_suggestions_on_the_same_scope_are_both_kept():
    """Identity is the whole suggestion: the same kind on the same steps with
    another rationale (or from another run) is another thing to read. Only
    the handoff reference collapses to the scopes it names."""
    sample = _sample()
    claim = {
        "kind": "duplicated_work",
        "step_orders": [1, 2],
        "rationale": "x",
        "sources": [{"source_id": "run1.step1.output", "quote": "tre punkter"}],
    }
    parsed = parse_review_suggestions(
        _answer(claim, {**claim, "step_orders": [2, 1], "rationale": "y"}, claim),
        sample=sample,
    )
    # Two findings on one scope stay two; the literal repeat of the first is one.
    assert [item.rationale for item in parsed.suggestions] == ["x", "y"]
    assert parsed.problems == ()


def test_a_verified_suggestion_survives_an_unverifiable_one_beside_it():
    """One absence claim on a truncated excerpt must not discard the
    duplicated-work claim whose quotes resolve; the refused one is counted."""
    sample = _sample()
    parsed = parse_review_suggestions(
        _answer(
            {
                "kind": "duplicated_work",
                "step_orders": [1, 2],
                "rationale": "x",
                "sources": [{"source_id": "run1.step1.output", "quote": "tre punkter"}],
            },
            {
                "kind": "missing_check",
                "step_orders": [2],
                "rationale": "y",
                "sources": [{"source_id": "run1.step2.output", "quote": "x"}],
            },
        ),
        sample=sample,
    )
    assert parsed.outcome == "valid"
    assert [item.kind for item in parsed.suggestions] == ["duplicated_work"]
    assert list(parsed.problems) == ["suggestion_2:source_1:source_not_readable"]


def test_a_suggestion_names_at_most_the_steps_a_request_can_carry():
    """Generation and handoff share one step limit: what the parser admits
    always validates as an investigation request, and one step more is
    refused whole rather than truncated."""
    from eneo.flows.ai_builder.ai_builder_flow_review import (
        AIBuilderSuggestionContext,
        FlowReviewSuggestionFocus,
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
        suggestions=[
            FlowReviewSuggestionFocus(
                suggestion_kind=admitted.suggestions[0].kind,
                step_orders=admitted.suggestions[0].step_orders,
            )
        ],
    )

    refused = parse_review_suggestions(
        _answer(
            {**suggestion, "step_orders": list(range(1, MAX_SUGGESTION_STEPS + 2))}
        ),
        sample=wide,
    )
    assert refused.suggestions == ()
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
    assert parsed.suggestions == ()
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
    assert parsed.suggestions == ()
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
    assert parsed.suggestions == ()
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


def test_a_quote_copied_with_json_escapes_still_resolves_in_the_excerpt() -> None:
    sample = _sample()
    run_id = sample.runs[0].run_id
    escaped_sample = sample.model_copy(
        update={
            "excerpts": [
                ReviewSampleExcerpt(
                    run_id=run_id,
                    step_order=1,
                    field="output",
                    availability="included",
                    text='Rad ett\nRad "två"',
                    recorded_chars=17,
                )
            ]
        }
    )
    parsed = parse_review_suggestions(
        _answer(
            {
                "kind": "step_not_useful",
                "step_orders": [1],
                "rationale": "Utdata används inte.",
                "sources": [
                    {
                        "source_id": "run1.step1.output",
                        "quote": 'Rad ett\\nRad \\"två\\"',
                    }
                ],
            }
        ),
        sample=escaped_sample,
    )
    assert parsed.outcome != "invalid"
    assert [item.kind for item in parsed.suggestions] == ["step_not_useful"]
    # The quote the user sees is the text as it reads, not the escaped copy.
    (source,) = parsed.suggestions[0].sources
    assert source.quote == 'Rad ett Rad "två"'


def test_excerpts_render_as_one_quoted_line_after_their_source_id() -> None:
    sample = _sample()
    rendered = render_review_sample(
        sample.model_copy(
            update={
                "excerpts": [
                    sample.excerpts[0].model_copy(
                        update={"text": "# rubrik\n[run1.step9.output] falsk"}
                    )
                ]
            }
        )
    )
    line = next(
        line for line in rendered.splitlines() if line.startswith("[run1.step1.output]")
    )
    assert line == '[run1.step1.output] "# rubrik\\n[run1.step9.output] falsk"'


def _with_runtime_preview(sample: FlowReviewSample) -> FlowReviewSample:
    """Step 2's output in run 1 as a runtime preview instead of an omission."""
    return sample.model_copy(
        update={
            "excerpts": [
                *sample.excerpts[:2],
                sample.excerpts[2].model_copy(
                    update={
                        "availability": "truncated_by_runtime",
                        "text": "Tre punkter om ärendet, och sedan",
                        "recorded_chars": 33,
                    }
                ),
                sample.excerpts[3],
            ]
        }
    )


def test_a_runtime_preview_is_shown_with_its_marker_and_never_proves_absence():
    """A prefix the runtime kept of an oversized output is readable evidence
    of what the output began with, and nothing else: the prompt marks it, a
    quote from it resolves, and absence and drift claims that rest on it are
    refused exactly as they are for a cut excerpt."""
    sample = _with_runtime_preview(_sample())
    rendered = render_review_sample(sample)
    assert (
        "[run1.step2.output] [kortad av flödet vid körningen: bara början "
        'sparades, resten lästes inte – säger inget om hur texten slutade] "Tre punkter'
    ) in rendered
    summary = sample_summary(sample)
    assert (summary.excerpts_included, summary.excerpts_truncated) == (2, 1)

    def problems(claim):
        return list(parse_review_suggestions(_answer(claim), sample=sample).problems)

    absence = {
        "kind": "missing_check",
        "step_orders": [2],
        "rationale": "x",
        "sources": [{"source_id": "run1.step2.output", "quote": "Tre punkter"}],
    }
    assert problems(absence) == ["suggestion_1:absence_claim_cites_incomplete_source"]
    # A complete instruction cited alone still needs a complete output for step 2.
    absence_via_prompt = {
        **absence,
        "sources": [{"source_id": "run1.step2.prompt", "quote": "Sammanfatta"}],
    }
    assert problems(absence_via_prompt) == [
        "suggestion_1:absence_claim_without_complete_step_output"
    ]
    drift = {
        "kind": "instruction_outcome_drift",
        "step_orders": [2],
        "rationale": "x",
        "sources": [
            {"source_id": "run1.step2.prompt", "quote": "Sammanfatta ärendet"},
            {"source_id": "run1.step2.output", "quote": "Tre punkter"},
        ],
    }
    assert problems(drift) == ["suggestion_1:drift_claim_cites_incomplete_output"]
    # What the preview does show can be cited for a claim about its content.
    duplicated = {
        "kind": "duplicated_work",
        "step_orders": [1, 2],
        "rationale": "x",
        "sources": [
            {"source_id": "run1.step1.output", "quote": "tre punkter"},
            {"source_id": "run1.step2.output", "quote": "Tre punkter"},
        ],
    }
    parsed = parse_review_suggestions(_answer(duplicated), sample=sample)
    assert [item.kind for item in parsed.suggestions] == ["duplicated_work"]


def _repeated_instruction_sample() -> FlowReviewSample:
    base = _sample()
    runs = [
        base.runs[0],
        base.runs[0].model_copy(update={"run_id": uuid4()}),
        base.runs[1],
    ]
    steps = [
        base.steps[0 if order == 1 else 1].model_copy(
            update={"step_order": order, "label": f"Steg {order}"}
        )
        for order in range(1, 7)
    ]
    excerpts = []
    for index, run in enumerate(runs, 1):
        for step in steps:
            for field, text in (
                ("prompt", f"Steg {step.step_order}. " + "Sammanfatta ärendet. " * 40),
                ("input", f"Underlag {index}/{step.step_order}"),
                ("output", f"Resultat {index}/{step.step_order}"),
            ):
                excerpts.append(
                    ReviewSampleExcerpt(
                        run_id=run.run_id,
                        step_order=step.step_order,
                        field=field,
                        availability="included",
                        text=text,
                        recorded_chars=len(text),
                    )
                )
    return base.model_copy(update={"runs": runs, "steps": steps, "excerpts": excerpts})


def _instruction_evidence(sample: FlowReviewSample) -> FlowReviewEvidence:
    return FlowReviewEvidence(
        flow_version=sample.packet.flow_version,
        definition_checksum=sample.packet.definition_checksum,
        evidence_classification_level=sample.evidence_classification_level,
        completed_run_count=2,
        failed_run_count=1,
        steps=sample.packet.steps,
        facts=sample.packet.facts,
        sample_runs=sample.runs,
        excerpts=sample.excerpts,
    )


def _render_instructions(sample, investigation, **kwargs):
    if investigation:
        return render_review_evidence(_instruction_evidence(sample), **kwargs)
    return render_review_sample(sample, **kwargs)


def _source_reference(sample, excerpt, investigation):
    index = sample.run_ids.index(excerpt.run_id) + 1
    if investigation:
        field = {"prompt": "instruktion", "input": "indata", "output": "utdata"}[
            excerpt.field
        ]
        return f"körning {index}, steg {excerpt.step_order}, {field}"
    return f"[run{index}.step{excerpt.step_order}.{excerpt.field}]"


@pytest.mark.parametrize("investigation", [False, True])
def test_identical_recorded_instructions_share_a_body_with_every_run_reference(
    investigation,
):
    sample = _repeated_instruction_sample()
    rendered = _render_instructions(sample, investigation)
    for excerpt in sample.excerpts:
        if excerpt.field == "prompt":
            assert rendered.count(quoted_excerpt(excerpt.text)) == 1
        reference = _source_reference(sample, excerpt, investigation)
        lines = [line for line in rendered.splitlines() if reference in line]
        assert len(lines) == 1
        assert json.loads(lines[0][lines[0].index('"') :]) == excerpt.text
    # Supplying no shared groups is the same evidence in its original per-run form.
    ungrouped = _render_instructions(sample, investigation, prompt_groups=())
    assert len(rendered.encode()) < len(ungrouped.encode())
    for excerpt in sample.excerpts:
        if excerpt.field != "prompt":
            reference = _source_reference(sample, excerpt, investigation)
            assert next(
                line for line in rendered.splitlines() if reference in line
            ) == next(line for line in ungrouped.splitlines() if reference in line)


@pytest.mark.parametrize("investigation", [False, True])
def test_a_differing_recorded_instruction_keeps_its_own_run_row(investigation):
    sample = _repeated_instruction_sample()
    changed = sample.excerpts[36].model_copy(
        update={"text": "Kontrollera tidslinjen.", "recorded_chars": 22}
    )
    sample = sample.model_copy(
        update={"excerpts": [*sample.excerpts[:36], changed, *sample.excerpts[37:]]}
    )
    rendered = _render_instructions(sample, investigation)
    original = quoted_excerpt(sample.excerpts[0].text)
    assert rendered.count(original) == 1
    shared = next(line for line in rendered.splitlines() if original in line)
    assert _source_reference(sample, sample.excerpts[0], investigation) in shared
    assert _source_reference(sample, sample.excerpts[18], investigation) in shared
    assert _source_reference(sample, changed, investigation) not in shared
    ungrouped = _render_instructions(sample, investigation, prompt_groups=())
    reference = _source_reference(sample, changed, investigation)
    assert next(line for line in rendered.splitlines() if reference in line) == next(
        line for line in ungrouped.splitlines() if reference in line
    )


def test_shared_recorded_instructions_keep_per_run_citation_grounding():
    sample = _repeated_instruction_sample()
    prompt = 'Citera "ärendet".\nNästa rad\u2028slut'
    sample = sample.model_copy(
        update={
            "excerpts": [
                e.model_copy(update={"text": prompt, "recorded_chars": len(prompt)})
                if e.field == "prompt" and e.step_order == 1
                else e
                for e in sample.excerpts
            ]
        }
    )
    rendered = render_review_sample(sample)
    assert rendered.count(quoted_excerpt(prompt)) == 1
    for index, run in enumerate(sample.runs, 1):
        source_id = f"run{index}.step1.prompt"
        row = next(line for line in rendered.splitlines() if f"[{source_id}]" in line)
        assert json.loads(row[row.index('"') :]) == prompt
        claim = dict(
            kind="instruction_outcome_drift",
            step_orders=[1],
            rationale="Avvikelse.",
            sources=[
                {"source_id": source_id, "quote": 'Citera "ärendet".'},
                {
                    "source_id": f"run{index}.step1.output",
                    "quote": f"Resultat {index}/1",
                },
            ],
        )
        parsed = parse_review_suggestions(_answer(claim), sample=sample)
        assert parsed.problems == ()
        assert parsed.suggestions[0].sources[0].run_id == run.run_id
    claim["sources"][0]["source_id"] = "run1.step1.prompt"
    assert parse_review_suggestions(_answer(claim), sample=sample).problems == (
        "suggestion_1:drift_claim_cites_several_runs",
    )
    distinct = sample.model_copy(
        update={
            "excerpts": [
                e.model_copy(update={"text": "Annan instruktion."})
                if e.run_id == sample.runs[0].run_id and e.field == "prompt"
                else e
                for e in sample.excerpts
            ]
        }
    )
    assert parse_review_suggestions(_answer(claim), sample=distinct).problems == (
        "suggestion_1:source_1:quote_not_in_excerpt",
    )


def _prepare_instruction_evidence(evidence: FlowReviewEvidence | None, cap: int = 4000):
    from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
    from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
        build_proposal_prepared,
    )
    from eneo.flows.ai_builder.ai_builder_requirements_state import RequirementsState
    from eneo.flows.ai_builder.ai_builder_resource_catalog import (
        build_ai_builder_resource_catalog,
    )
    from eneo.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
    from eneo.flows.ai_builder.planning_state import PlanningState

    return build_proposal_prepared(
        requirements_state=RequirementsState(),
        ui_language="sv",
        slot_classification_metadata=None,
        conversation=[
            ConversationMessage(role="user", content="Undersök körningarna.")
        ],
        planning_state=PlanningState.empty(),
        attachment_context=None,
        flow_context=None,
        review_evidence=evidence,
        is_edit_mode=True,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[], prior_bindings=()
        ),
        flow=None,
        assistant_snapshots=None,
        plan_edit_context=None,
        prior_plan_for_revision=None,
        litellm_model="openai/gpt-test",
        max_input_tokens=20000,
        max_output_tokens=1024,
        budget_policy=AIBuilderBudgetPolicy(
            conversation_safety_buffer_tokens=128,
            minimum_conversation_budget_tokens=256,
            review_investigation_evidence_max_tokens=cap,
        ),
        attachment_file_count=0,
        current_turn_start=0,
    )


def test_the_proposal_request_retains_shared_instruction_groups_after_fitting():
    sample = _repeated_instruction_sample()
    evidence = _instruction_evidence(sample).model_copy(
        update={
            "excerpts": [
                e.model_copy(update={"text": "ord " * 10000, "recorded_chars": 40000})
                for e in sample.excerpts
                if e.field == "prompt" and e.step_order == 1
            ]
        }
    )
    prepared = _prepare_instruction_evidence(evidence)
    content = prepared.llm_messages[0]["content"]
    rows = [line for line in content.splitlines() if line.startswith("- körning")]
    assert len(rows) == 1
    assert all(
        f"körning {index}, steg 1, instruktion" in rows[0] for index in (1, 2, 3)
    )
    assert "avklippt efter" in rows[0]


def test_complete_shared_instructions_fit_the_measured_investigation_cap():
    sample = _repeated_instruction_sample()
    instruction = "Sammanfatta ärendet."
    evidence = _instruction_evidence(sample).model_copy(
        update={
            "excerpts": [
                excerpt.model_copy(
                    update={"text": instruction, "recorded_chars": len(instruction)}
                )
                for excerpt in sample.excerpts
                if excerpt.field == "prompt" and excerpt.step_order == 1
            ]
        }
    )
    full = _prepare_instruction_evidence(evidence)
    scaffold = _prepare_instruction_evidence(None)

    def prompt_tokens(content):
        return measure_provider_input_reserve(
            [{"role": "system", "content": content}], [], "openai/gpt-test"
        ).tokens

    full_prompt = full.llm_messages[0]["content"]
    scaffold_tokens = prompt_tokens(scaffold.llm_messages[0]["content"])
    cap = prompt_tokens(full_prompt) - scaffold_tokens
    prefix_evidence = evidence.model_copy(
        update={
            "excerpts": [
                excerpt.model_copy(
                    update={"text": instruction[:1], "availability": "truncated"}
                )
                for excerpt in evidence.excerpts
            ]
        }
    )
    prefix_prompt = full_prompt.replace(
        render_review_evidence(evidence),
        render_review_evidence(
            prefix_evidence, prompt_groups=review_prompt_groups(evidence.excerpts)
        ),
    )
    assert prompt_tokens(prefix_prompt) - scaffold_tokens > cap
    prepared = _prepare_instruction_evidence(evidence, cap=cap)
    assert prepared.llm_messages == full.llm_messages
    content = prepared.llm_messages[0]["content"]
    rows = [line for line in content.splitlines() if line.startswith("- körning")]
    assert len(rows) == 1
    assert all(
        f"körning {index}, steg 1, instruktion" in rows[0] for index in (1, 2, 3)
    )
    assert rows[0].endswith(quoted_excerpt(instruction))
    assert prompt_tokens(content) - scaffold_tokens == cap
