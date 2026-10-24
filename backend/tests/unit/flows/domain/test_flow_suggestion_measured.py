"""Suggestions measured from recent runs: the cost attached to what the
draft proves, the three measured rules and their thresholds, and the order
of a measured answer."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

from eneo.flows.domain.flow_suggestion_evidence import (
    EvidenceAttempt,
    EvidenceCall,
    EvidenceEdge,
    EvidenceRun,
    RunEvidence,
    StepDefinitionFacts,
)
from eneo.flows.domain.flow_suggestion_measured import (
    CONTEXT_HEADROOM_SHARE,
    IDENTICAL_INPUTS_MIN_BYTES,
)
from eneo.flows.domain.flow_suggestions import (
    FlowSuggestion,
    FlowSuggestionCode,
    SuggestionFlow,
    SuggestionStep,
    analyze_flow,
)
from eneo.flows.enums import FlowInputSource, FlowOutputMode

_IDS = [UUID(int=index) for index in range(1, 20)]
_MODEL = UUID(int=900)
_PROMPT_READ = "assistant_prompt:step_1.output.text"


def _step(
    order: int,
    *,
    prompt_text: str | None = "Gör uppgiften.",
    output_mode: FlowOutputMode = FlowOutputMode.PASS_THROUGH,
    input_source: FlowInputSource = FlowInputSource.PREVIOUS_STEP,
) -> SuggestionStep:
    return SuggestionStep(
        id=_IDS[order],
        step_order=order,
        user_description=f"Steg {order}",
        input_source=FlowInputSource.FLOW_INPUT if order == 1 else input_source,
        input_type="text",
        input_bindings=None,
        input_config=None,
        output_mode=output_mode,
        output_type="text",
        output_contract=None,
        output_config=None,
        prompt_text=prompt_text,
        assistant_id=uuid4(),
    )


def _edge(ref: str, producer: int, *, size: int = 1000, sha: str = "a") -> EvidenceEdge:
    return EvidenceEdge(
        binding_ref=ref,
        source_step_id=_IDS[producer],
        selector=("output", "text"),
        byte_size=size,
        sha256=sha * 64,
    )


def _call(
    tokens: int | None,
    indexes: Sequence[int],
    *,
    reason: str = "initial",
    output: int | None = 50,
) -> EvidenceCall:
    return EvidenceCall(
        status="completed",
        call_reason=reason,
        num_tokens_input=tokens,
        num_tokens_output=output if tokens is not None else None,
        edge_indexes=tuple(indexes),
    )


def _attempt(
    order: int,
    edges: Sequence[EvidenceEdge] = (),
    calls: Sequence[EvidenceCall] = (),
    *,
    status: str = "completed",
    error_code: str | None = None,
) -> EvidenceAttempt:
    return EvidenceAttempt(
        step_id=_IDS[order],
        step_order=order,
        status=status,
        error_code=error_code,
        edges=tuple(edges),
        calls=tuple(calls),
    )


def _facts(
    *, model: UUID | None = _MODEL, definition: str = "same"
) -> StepDefinitionFacts:
    return StepDefinitionFacts(
        definition_hash=definition, completion_model_id=model, output_type="text"
    )


def _evidence(
    steps: Sequence[SuggestionStep],
    runs: Sequence[Sequence[EvidenceAttempt]],
    *,
    version: int = 3,
    limit: int | None = None,
    published: dict[UUID, StepDefinitionFacts] | None = None,
) -> RunEvidence:
    """``runs`` newest first, all of ``version``, whose steps have the
    draft's facts unless ``published`` says otherwise."""
    draft = {step.id: _facts() for step in steps}
    return RunEvidence(
        runs=tuple(
            EvidenceRun(run_id=uuid4(), version=version, attempts=tuple(attempts))
            for attempts in runs
        ),
        published_steps={
            (version, step_id): facts
            for step_id, facts in {**draft, **(published or {})}.items()
        },
        draft_steps=draft,
        model_input_limits={_MODEL: limit} if limit is not None else {},
    )


def _of(
    suggestions: Sequence[FlowSuggestion], code: FlowSuggestionCode
) -> list[FlowSuggestion]:
    return [item for item in suggestions if item.code is code]


# --- Measured impact ------------------------------------------------------


def _duplicate_flow() -> list[SuggestionStep]:
    return [_step(1), _step(2, prompt_text="Sammanfatta.\n{{ step_1.output.text }}")]


def _duplicate_attempt(tokens: int, *, producer: int = 1) -> EvidenceAttempt:
    # Step 2 got step 1 as its input (edge 0) and again in its prompt (edge 1).
    return _attempt(
        2,
        [_edge("input_source", 1), _edge(_PROMPT_READ, producer)],
        [_call(tokens, (0, 1))],
    )


def test_a_duplicate_costs_its_redundant_edge_averaged_over_the_runs() -> None:
    steps = _duplicate_flow()
    # 2000 bytes for 600 and 800 tokens: the prompt read's 1000 bytes cost
    # 300 and 400 tokens.
    evidence = _evidence(steps, [[_duplicate_attempt(600)], [_duplicate_attempt(800)]])

    (duplicate,) = _of(
        analyze_flow(SuggestionFlow(steps=steps), evidence),
        FlowSuggestionCode.DUPLICATE_READ,
    )

    assert duplicate.impact.basis == "runs"
    assert duplicate.impact.level == "high"
    assert duplicate.impact.tokens_per_run == 350
    assert duplicate.impact.run_count == 2
    assert duplicate.impact.version == 3
    assert duplicate.impact.step_changed_since is False


def test_the_fingerprint_does_not_change_with_a_measurement() -> None:
    steps = _duplicate_flow()
    static = analyze_flow(SuggestionFlow(steps=steps))
    measured = analyze_flow(
        SuggestionFlow(steps=steps), _evidence(steps, [[_duplicate_attempt(600)]])
    )

    assert [item.fingerprint for item in static] == [
        item.fingerprint for item in measured
    ]


def test_an_edge_the_draft_does_not_read_attaches_no_measurement() -> None:
    steps = _duplicate_flow()
    # In the run, the prompt read named another step than the draft's.
    evidence = _evidence(steps, [[_duplicate_attempt(600, producer=3)]])

    (duplicate,) = _of(
        analyze_flow(SuggestionFlow(steps=steps), evidence),
        FlowSuggestionCode.DUPLICATE_READ,
    )

    assert duplicate.impact.basis == "definition"
    assert duplicate.impact.tokens_per_run is None


def test_a_step_changed_since_the_measured_version_says_so() -> None:
    steps = _duplicate_flow()
    evidence = _evidence(
        steps,
        [[_duplicate_attempt(600)]],
        published={_IDS[2]: _facts(definition="before")},
    )

    (duplicate,) = _of(
        analyze_flow(SuggestionFlow(steps=steps), evidence),
        FlowSuggestionCode.DUPLICATE_READ,
    )

    assert duplicate.impact.step_changed_since is True


def test_an_unread_result_costs_what_the_step_was_billed() -> None:
    steps = [_step(1), _step(2, input_source=FlowInputSource.FLOW_INPUT), _step(3)]
    evidence = _evidence(
        steps,
        [[_attempt(1, [_edge("input_source", 1)], [_call(400, (0,), output=100)])]],
    )

    (unread,) = _of(
        analyze_flow(SuggestionFlow(steps=steps), evidence),
        FlowSuggestionCode.UNREAD_RESULT,
    )

    assert unread.steps == (_IDS[1],)
    assert unread.impact.tokens_per_run == 500


# --- identical_inputs -----------------------------------------------------


def _copy_flow(
    *, prompt: str = "Jämför.\n{{ step_1.output.text }}"
) -> list[SuggestionStep]:
    """Step 2 copies step 1; step 3 reads step 2 as its input and step 1 in
    its prompt: two producers, the same text."""
    return [
        _step(1),
        _step(2, prompt_text=None, output_mode=FlowOutputMode.COPY_INPUT),
        _step(3, prompt_text=prompt),
    ]


def _copy_attempt(*, size: int = 1000, second_sha: str = "a") -> EvidenceAttempt:
    return _attempt(
        3,
        [
            _edge("input_source", 2, size=size),
            _edge(_PROMPT_READ, 1, size=size, sha=second_sha),
        ],
        [_call(600, (0, 1))],
    )


def test_the_same_text_from_two_producers_is_identical_inputs() -> None:
    steps = _copy_flow()
    evidence = _evidence(steps, [[_copy_attempt()], [_attempt(3)]])

    (item,) = _of(
        analyze_flow(SuggestionFlow(steps=steps), evidence),
        FlowSuggestionCode.IDENTICAL_INPUTS,
    )

    assert item.steps == (_IDS[3], _IDS[1], _IDS[2])
    assert item.params["producer_step_orders"] == [1, 2]
    assert item.params["observed_runs"] == 1
    assert item.params["step_runs"] == 1
    assert item.impact.basis == "runs"
    # The second edge's 1000 of 2000 bytes, at 600 tokens.
    assert item.impact.tokens_per_run == 300
    assert item.fix.kind == "assisted"
    assert "In 1 of the last 1 runs, step 3 received the same text" in item.message


def test_different_texts_or_a_short_text_are_not_identical_inputs() -> None:
    steps = _copy_flow()
    for attempt in (
        _copy_attempt(second_sha="b"),
        _copy_attempt(size=IDENTICAL_INPUTS_MIN_BYTES - 1),
    ):
        suggestions = analyze_flow(
            SuggestionFlow(steps=steps), _evidence(steps, [[attempt]])
        )
        assert _of(suggestions, FlowSuggestionCode.IDENTICAL_INPUTS) == []

    at_threshold = analyze_flow(
        SuggestionFlow(steps=steps),
        _evidence(steps, [[_copy_attempt(size=IDENTICAL_INPUTS_MIN_BYTES)]]),
    )
    assert len(_of(at_threshold, FlowSuggestionCode.IDENTICAL_INPUTS)) == 1


def test_identical_inputs_lapse_when_the_draft_no_longer_reads_both() -> None:
    steps = _copy_flow(prompt="Jämför.")

    suggestions = analyze_flow(
        SuggestionFlow(steps=steps), _evidence(steps, [[_copy_attempt()]])
    )

    assert _of(suggestions, FlowSuggestionCode.IDENTICAL_INPUTS) == []


# --- context_headroom -----------------------------------------------------


def _headroom(peak: int, *, limit: int | None = 1000, **kwargs) -> list[FlowSuggestion]:
    steps = [_step(1), _step(2)]
    attempt = _attempt(2, [_edge("input_source", 1)], [_call(peak, (0,))])
    return _of(
        analyze_flow(
            SuggestionFlow(steps=steps),
            _evidence(steps, [[attempt]], limit=limit, **kwargs),
        ),
        FlowSuggestionCode.CONTEXT_HEADROOM,
    )


def test_an_input_at_the_share_of_the_models_limit_is_headroom() -> None:
    (item,) = _headroom(int(CONTEXT_HEADROOM_SHARE * 1000))

    assert item.steps == (_IDS[2],)
    assert item.params["peak_input_tokens"] == 850
    assert item.params["token_limit"] == 1000
    assert item.params["limit_share"] == 0.85
    assert item.impact.basis == "runs"
    assert item.impact.tokens_per_run is None
    assert item.fix.kind == "advice"


def test_an_input_below_the_share_or_an_unknown_limit_is_not_headroom() -> None:
    assert _headroom(849) == []
    assert _headroom(990, limit=None) == []


def test_headroom_is_measured_only_while_the_step_keeps_its_model() -> None:
    assert _headroom(990, published={_IDS[2]: _facts(model=UUID(int=901))}) == []


def test_an_inline_cap_failure_is_headroom_and_links_the_duplicates() -> None:
    steps = _duplicate_flow()
    failed = _attempt(2, status="failed", error_code="typed_io_input_too_large")
    evidence = _evidence(steps, [[failed], [_duplicate_attempt(600)]], limit=100_000)

    suggestions = analyze_flow(SuggestionFlow(steps=steps), evidence)
    (item,) = _of(suggestions, FlowSuggestionCode.CONTEXT_HEADROOM)
    (duplicate,) = _of(suggestions, FlowSuggestionCode.DUPLICATE_READ)

    assert item.params["inline_cap_failures"] == 1
    assert item.params["related_fingerprints"] == [duplicate.fingerprint]
    assert item.params["duplicated_tokens_per_run"] == 300
    assert item.params["duplicated_share"] == 0.5
    assert "failed 1 time because its input was over the inline limit" in item.message


# --- format_fallback ------------------------------------------------------


def _fallback(pattern: Sequence[bool]) -> list[FlowSuggestion]:
    steps = [_step(1), _step(2)]
    runs = [
        [
            _attempt(
                2,
                [_edge("input_source", 1)],
                [
                    _call(100, (0,)),
                    *(
                        [_call(100, (0,), reason="response_format_fallback")]
                        if fell_back
                        else []
                    ),
                ],
            )
        ]
        for fell_back in pattern
    ]
    return _of(
        analyze_flow(SuggestionFlow(steps=steps), _evidence(steps, runs)),
        FlowSuggestionCode.FORMAT_FALLBACK,
    )


def test_a_fallback_in_half_of_the_runs_is_format_fallback() -> None:
    (item,) = _fallback([True, False])

    assert item.params == {"fallback_runs": 1, "step_runs": 2}
    assert item.impact.level == "medium"
    assert item.impact.run_count == 2
    assert item.fix.kind == "advice"


def test_a_fallback_in_less_than_half_of_the_runs_is_not_reported() -> None:
    assert _fallback([True, False, False]) == []
    assert _fallback([False, False]) == []


# --- Ordering -------------------------------------------------------------


def test_measured_tokens_rank_before_level_and_step_order() -> None:
    # Step 2 reads step 1 twice (high, its prompt read unmeasured) and no
    # step reads step 2 (medium, measured): the measured one comes first.
    steps = [
        _step(1),
        _step(2, prompt_text="Sammanfatta.\n{{ step_1.output.text }}"),
        _step(3, input_source=FlowInputSource.FLOW_INPUT),
        _step(4),
    ]
    evidence = _evidence(
        steps,
        [[_attempt(2, [_edge("input_source", 1)], [_call(900, (0,))])]],
    )

    suggestions = analyze_flow(SuggestionFlow(steps=steps), evidence)

    assert suggestions[0].code is FlowSuggestionCode.UNREAD_RESULT
    assert suggestions[0].impact.tokens_per_run == 950
    later = [item for item in suggestions[1:] if item.impact.tokens_per_run]
    assert later == []
    assert suggestions[1].code is FlowSuggestionCode.DUPLICATE_READ


def test_more_measured_tokens_rank_first() -> None:
    steps = [
        _step(1),
        _step(2, input_source=FlowInputSource.FLOW_INPUT),
        _step(3, input_source=FlowInputSource.FLOW_INPUT),
        _step(4, input_source=FlowInputSource.FLOW_INPUT),
    ]
    evidence = _evidence(
        steps,
        [
            [
                _attempt(2, [_edge("input_source", 1)], [_call(100, (0,))]),
                _attempt(3, [_edge("input_source", 1)], [_call(700, (0,))]),
            ]
        ],
    )

    unread = _of(
        analyze_flow(SuggestionFlow(steps=steps), evidence),
        FlowSuggestionCode.UNREAD_RESULT,
    )

    assert [item.steps[0] for item in unread] == [_IDS[3], _IDS[2], _IDS[1]]
