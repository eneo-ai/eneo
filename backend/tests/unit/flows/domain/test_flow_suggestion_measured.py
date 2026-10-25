"""Suggestions measured from recent runs: the cost attached to what the
draft proves, the measured rules and their thresholds (those from the
forwarding facts among them), and the order of a measured answer."""

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
from eneo.flows.domain.flow_suggestion_forwarding import (
    DETERMINISTIC_MAX_OWN_BYTES,
    FORWARDING_MIN_REPEATED_BYTES,
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
from eneo.flows.domain.forwarding_facts import (
    ForwardingEdgeFacts,
    ForwardingFacts,
    not_measured_forwarding_facts,
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
    output_type: str = "text",
    step_id: UUID | None = None,
) -> SuggestionStep:
    return SuggestionStep(
        id=step_id or _IDS[order],
        step_order=order,
        user_description=f"Steg {order}",
        input_source=FlowInputSource.FLOW_INPUT if order == 1 else input_source,
        input_type="text",
        input_bindings=None,
        input_config=None,
        output_mode=output_mode,
        output_type=output_type,
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
    forwarding: ForwardingFacts | None = None,
) -> EvidenceAttempt:
    return EvidenceAttempt(
        step_id=_IDS[order],
        step_order=order,
        status=status,
        error_code=error_code,
        edges=tuple(edges),
        calls=tuple(calls),
        forwarding=forwarding,
    )


def _facts(
    *,
    model: UUID | None = _MODEL,
    definition: str = "same",
    output_type: str = "text",
) -> StepDefinitionFacts:
    return StepDefinitionFacts(
        definition_hash=definition, completion_model_id=model, output_type=output_type
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


# --- Forwarding facts -----------------------------------------------------


def _edge_facts(
    index: int,
    *,
    size: int = 1000,
    repeated: int = 0,
    copied: float | None = 0.0,
    shingles: int = 150,
) -> ForwardingEdgeFacts:
    return ForwardingEdgeFacts(
        edge_index=index,
        byte_size=size,
        shingle_count=shingles,
        sample_every=1,
        repeated_bytes=repeated,
        copied_to_output_ratio=copied,
    )


def _forwarding(
    edges: Sequence[ForwardingEdgeFacts],
    *,
    output: int = 1000,
    verbatim: float | None = None,
    calls: int = 1,
    unmeasured: Sequence[int] = (),
) -> ForwardingFacts:
    return ForwardingFacts(
        schema_version=1,
        measured=True,
        call_count=calls,
        edges=tuple(edges),
        unmeasured_edge_indexes=tuple(unmeasured),
        output_byte_size=output,
        output_shingle_count=120,
        output_verbatim_ratio=(
            verbatim
            if verbatim is not None
            else max((edge.copied_to_output_ratio or 0.0) for edge in edges)
        ),
    )


def _analyzed(
    steps: Sequence[SuggestionStep],
    runs: Sequence[Sequence[EvidenceAttempt]],
    code: FlowSuggestionCode,
    **kwargs,
) -> list[FlowSuggestion]:
    return _of(
        analyze_flow(SuggestionFlow(steps=steps), _evidence(steps, runs, **kwargs)),
        code,
    )


# --- model_relay ----------------------------------------------------------


def _relay_flow() -> list[SuggestionStep]:
    """Step 2 reads step 1; step 3 reads step 2."""
    return [_step(1), _step(2), _step(3)]


def _relay_attempt(
    copied: float | None = 0.8,
    *,
    output: int = 1000,
    size: int = 1000,
    facts: ForwardingFacts | None = None,
) -> EvidenceAttempt:
    # Step 2's one call sent step 1's 1000 bytes and wrote 300 tokens.
    return _attempt(
        2,
        [_edge("input_source", 1, size=size)],
        [_call(400, (0,), output=300)],
        forwarding=facts
        or _forwarding([_edge_facts(0, size=size, copied=copied)], output=output),
    )


def _relays(
    runs: Sequence[Sequence[EvidenceAttempt]],
    steps: Sequence[SuggestionStep] | None = None,
    **kwargs,
) -> list[FlowSuggestion]:
    return _analyzed(
        steps or _relay_flow(), runs, FlowSuggestionCode.MODEL_RELAY, **kwargs
    )


def test_a_step_whose_output_copies_its_input_for_a_later_reader_is_a_relay() -> None:
    (item,) = _relays([[_relay_attempt()]])

    assert item.steps == (_IDS[2], _IDS[1], _IDS[3])
    assert item.params["producer_step_order"] == 1
    assert item.params["producer_step_id"] == str(_IDS[1])
    assert item.params["readers"] == [
        {"step_order": 3, "step_id": str(_IDS[3]), "sites": ["input_source"]}
    ]
    assert item.params["copied_share"] == 0.8
    assert item.params["input_share"] == 0.8
    assert item.params["copied_bytes"] == 800
    assert (item.params["run_count"], item.params["held_runs"]) == (1, 1)
    assert item.impact.basis == "runs"
    assert item.impact.level == "high"
    # 80 % of the call's 300 output tokens wrote the copy.
    assert item.impact.tokens_per_run == 240
    assert item.impact.run_count == 1
    assert item.impact.step_changed_since is False
    assert item.fix.kind == "assisted"
    assert item.message.startswith(
        "In 1 of the last 1 runs, 80 % of step 2's output was step 1's result "
        "copied word for word, and step 3 reads it from step 2"
    )


def test_a_relay_needs_most_of_the_output_and_most_of_the_input_copied() -> None:
    assert len(_relays([[_relay_attempt(0.6)]])) == 1
    assert _relays([[_relay_attempt(0.59)]]) == []
    # The copy (800 bytes) must be 60 % of the input. Less is an excerpt that
    # a later step reading the original would get whole.
    assert len(_relays([[_relay_attempt(0.8, size=1333)]])) == 1
    assert _relays([[_relay_attempt(0.8, size=1334)]]) == []
    assert _relays([[_relay_attempt(0.9, size=10_000)]]) == []
    # A short copy costs next to nothing.
    least = FORWARDING_MIN_REPEATED_BYTES
    assert len(_relays([[_relay_attempt(1.0, output=least, size=least)]])) == 1
    assert _relays([[_relay_attempt(1.0, output=least - 1, size=least - 1)]]) == []


def test_a_relay_holds_in_half_of_the_runs_that_measured_it() -> None:
    (item,) = _relays([[_relay_attempt()], [_relay_attempt(0.1)]])

    assert (item.params["run_count"], item.params["held_runs"]) == (2, 1)
    assert item.impact.run_count == 2

    assert (
        _relays([[_relay_attempt()], [_relay_attempt(0.1)], [_relay_attempt(0.1)]])
        == []
    )


def test_facts_that_measured_nothing_do_not_count_as_runs() -> None:
    unmeasured = [
        # Facts the worker could not measure, none at all, the edge to step 1
        # unmeasured, a step that called its model twice, and facts of an
        # edge whose size is not the attempt's.
        _relay_attempt(
            facts=not_measured_forwarding_facts(reason="cpu_budget_exceeded")
        ),
        _attempt(2, [_edge("input_source", 1)], [_call(400, (0,))]),
        _relay_attempt(facts=_forwarding([], verbatim=0.0, unmeasured=(0,))),
        _relay_attempt(facts=_forwarding([_edge_facts(0, copied=0.1)], calls=2)),
        _relay_attempt(facts=_forwarding([_edge_facts(0, size=900, copied=0.8)])),
    ]

    (item,) = _relays([[_relay_attempt()], *([attempt] for attempt in unmeasured)])

    assert (item.params["run_count"], item.params["held_runs"]) == (1, 1)


def test_a_relay_lapses_when_the_draft_no_longer_relays_with_that_model() -> None:
    no_reader = [_step(1), _step(2), _step(3, input_source=FlowInputSource.FLOW_INPUT)]
    no_read = [_step(1), _step(2, input_source=FlowInputSource.FLOW_INPUT), _step(3)]

    assert _relays([[_relay_attempt()]], steps=no_reader) == []
    assert _relays([[_relay_attempt()]], steps=no_read) == []
    assert (
        _relays([[_relay_attempt()]], published={_IDS[2]: _facts(model=UUID(int=901))})
        == []
    )
    assert (
        _relays([[_relay_attempt()]], published={_IDS[2]: _facts(output_type="json")})
        == []
    )


def test_a_relay_keeps_its_fingerprint_across_renumbering_and_measurements() -> None:
    (first,) = _relays([[_relay_attempt(0.7)]])
    # A step inserted before them: step 2 becomes step 3, and so on.
    renumbered = [
        _step(1, step_id=UUID(int=500)),
        _step(2, step_id=_IDS[1], input_source=FlowInputSource.FLOW_INPUT),
        _step(3, step_id=_IDS[2]),
        _step(4, step_id=_IDS[3]),
    ]
    (second,) = _relays([[_relay_attempt(0.9)]], steps=renumbered)

    assert second.params["producer_step_order"] == 2
    assert second.fingerprint == first.fingerprint


# --- overlapping_inputs ---------------------------------------------------


def _overlap_flow(*, prompt: str = "Jämför.\n{{ step_1.output.text }}"):
    """Step 3 reads step 2 as its input and step 1 in its prompt: two
    producers, two different texts."""
    return [
        _step(1),
        _step(2, input_source=FlowInputSource.FLOW_INPUT),
        _step(3, prompt_text=prompt),
    ]


def _overlap_attempt(
    repeated: int = 700, *, third: ForwardingEdgeFacts | None = None, sha: str = "b"
) -> EvidenceAttempt:
    # The summary from step 2 (1000 bytes) repeats ``repeated`` bytes of the
    # transcript from step 1 (4000 bytes); one call, 1000 tokens for 5000
    # bytes.
    edges = [
        _edge("input_source", 2, size=1000, sha=sha),
        _edge(_PROMPT_READ, 1, size=4000),
    ]
    facts = [
        _edge_facts(0, size=1000, repeated=repeated),
        _edge_facts(1, size=4000, repeated=repeated),
    ]
    if third is not None:
        # The run's own input, which the prompt also interpolates.
        edges.append(
            EvidenceEdge(
                binding_ref="assistant_prompt:flow_input.text",
                source_step_id=None,
                selector=("text",),
                byte_size=third.byte_size,
                sha256="c" * 64,
                run_input=True,
            )
        )
        facts.append(third)
    return _attempt(
        3,
        edges,
        [_call(1000, tuple(range(len(edges))))],
        forwarding=_forwarding(facts, verbatim=0.0),
    )


def _overlaps(runs, steps=None, **kwargs) -> list[FlowSuggestion]:
    return _analyzed(
        steps or _overlap_flow(), runs, FlowSuggestionCode.OVERLAPPING_INPUTS, **kwargs
    )


def test_two_inputs_that_share_half_of_the_smaller_one_overlap() -> None:
    (item,) = _overlaps([[_overlap_attempt()]])

    assert item.steps == (_IDS[3], _IDS[1], _IDS[2])
    assert item.params["inputs"] == [
        {"step_order": 1, "step_id": str(_IDS[1]), "sites": [_PROMPT_READ]},
        {"step_order": 2, "step_id": str(_IDS[2]), "sites": ["input_source"]},
    ]
    assert item.params["shared_bytes"] == 700
    assert item.params["shared_share"] == 0.7
    assert (item.params["run_count"], item.params["held_runs"]) == (1, 1)
    assert item.impact.level == "medium"
    # 700 shared bytes at 0.2 tokens per byte.
    assert item.impact.tokens_per_run == 140
    assert item.fix.kind == "assisted"
    assert "which shared 70 % of the shorter one's text" in item.message


def test_an_overlap_needs_half_of_the_smaller_input_and_different_values() -> None:
    assert len(_overlaps([[_overlap_attempt(500)]])) == 1
    assert _overlaps([[_overlap_attempt(499)]]) == []
    # The same value twice is `identical_inputs`, not an overlap.
    assert _overlaps([[_overlap_attempt(1000, sha="a")]]) == []


def test_an_overlap_short_of_the_minimum_bytes_is_not_reported() -> None:
    steps = _overlap_flow()
    small = FORWARDING_MIN_REPEATED_BYTES - 1
    attempt = _attempt(
        3,
        [
            _edge("input_source", 2, size=small, sha="b"),
            _edge(_PROMPT_READ, 1, size=4000),
        ],
        [_call(1000, (0, 1))],
        forwarding=_forwarding(
            [
                _edge_facts(0, size=small, repeated=small),
                _edge_facts(1, size=4000, repeated=small),
            ],
            verbatim=0.0,
        ),
    )

    assert _overlaps([[attempt]], steps=steps) == []


def test_an_overlap_among_three_repeating_inputs_is_not_measured() -> None:
    # A third input repeats text too: the facts cannot tell which two share
    # it, so the run does not count, though the draft reads no step there.
    # One that repeats nothing changes nothing.
    ambiguous = _overlap_attempt(third=_edge_facts(2, size=500, repeated=200))
    unrelated = _overlap_attempt(third=_edge_facts(2, size=500, repeated=0))

    assert _overlaps([[ambiguous]]) == []
    (item,) = _overlaps([[unrelated], [ambiguous]])
    assert item.params["run_count"] == 1


def test_an_overlap_lapses_when_the_draft_no_longer_reads_both() -> None:
    assert (
        _overlaps([[_overlap_attempt()]], steps=_overlap_flow(prompt="Jämför.")) == []
    )


def test_an_overlap_of_a_duplicate_reads_adds_to_it_with_its_fingerprint() -> None:
    # Step 2 reads step 1 as its input and its title in its prompt.
    steps = [
        _step(1),
        _step(2, prompt_text="Titel: {{ step_1.output.structured.title }}"),
    ]
    attempt = _attempt(
        2,
        [
            _edge("input_source", 1, size=3000),
            _edge(
                "assistant_prompt:step_1.output.structured.title", 1, size=600, sha="b"
            ),
        ],
        [_call(900, (0, 1))],
        forwarding=_forwarding(
            [
                _edge_facts(0, size=3000, repeated=600),
                _edge_facts(1, size=600, repeated=600),
            ],
            verbatim=0.0,
        ),
    )
    (static,) = _of(
        analyze_flow(SuggestionFlow(steps=steps)), FlowSuggestionCode.DUPLICATE_READ
    )

    suggestions = analyze_flow(
        SuggestionFlow(steps=steps), _evidence(steps, [[attempt]])
    )
    (duplicate,) = _of(suggestions, FlowSuggestionCode.DUPLICATE_READ)

    assert _of(suggestions, FlowSuggestionCode.OVERLAPPING_INPUTS) == []
    assert duplicate.fingerprint == static.fingerprint
    (overlap,) = duplicate.params["measured_overlaps"]
    assert overlap["shared_share"] == 1.0
    assert overlap["shared_bytes"] == 600
    # 600 bytes at 0.25 tokens per byte.
    assert overlap["tokens_per_run"] == 150
    assert (overlap["run_count"], overlap["held_runs"], overlap["version"]) == (1, 1, 3)
    assert overlap["step_changed_since"] is False


def test_an_overlap_of_derived_earlier_steps_adds_to_the_broad_input() -> None:
    # Step 3 takes all earlier steps; step 2 is derived from step 1.
    steps = [
        _step(1),
        _step(2),
        _step(3, input_source=FlowInputSource.ALL_PREVIOUS_STEPS),
    ]
    attempt = _attempt(
        3,
        [
            _edge("input_source", 1, size=4000),
            _edge("input_source", 2, size=1000, sha="b"),
        ],
        [_call(1000, (0, 1))],
        forwarding=_forwarding(
            [
                _edge_facts(0, size=4000, repeated=800),
                _edge_facts(1, size=1000, repeated=800),
            ],
            verbatim=0.0,
        ),
    )
    (static,) = _of(
        analyze_flow(SuggestionFlow(steps=steps)),
        FlowSuggestionCode.BROAD_ALL_PREVIOUS_STEPS,
    )

    suggestions = analyze_flow(
        SuggestionFlow(steps=steps), _evidence(steps, [[attempt]])
    )
    (broad,) = _of(suggestions, FlowSuggestionCode.BROAD_ALL_PREVIOUS_STEPS)

    assert _of(suggestions, FlowSuggestionCode.OVERLAPPING_INPUTS) == []
    assert broad.fingerprint == static.fingerprint
    assert broad.impact == static.impact
    (overlap,) = broad.params["measured_overlaps"]
    assert overlap["inputs"] == [
        {"step_order": 1, "step_id": str(_IDS[1]), "sites": ["input_source"]},
        {"step_order": 2, "step_id": str(_IDS[2]), "sites": ["input_source"]},
    ]
    assert overlap["shared_share"] == 0.8


def test_an_overlap_keeps_its_fingerprint_across_renumbering() -> None:
    (first,) = _overlaps([[_overlap_attempt(600)]])
    renumbered = [
        _step(1, step_id=UUID(int=500)),
        _step(2, step_id=_IDS[1], input_source=FlowInputSource.FLOW_INPUT),
        _step(3, step_id=_IDS[2], input_source=FlowInputSource.FLOW_INPUT),
        _step(4, step_id=_IDS[3], prompt_text="Jämför.\n{{ step_2.output.text }}"),
    ]
    moved = _attempt(
        4,
        [
            _edge("input_source", 2, size=1000, sha="b"),
            _edge("assistant_prompt:step_2.output.text", 1, size=4000),
        ],
        [_call(1000, (0, 1))],
        forwarding=_forwarding(
            [
                _edge_facts(0, size=1000, repeated=900),
                _edge_facts(1, size=4000, repeated=900),
            ],
            verbatim=0.0,
        ),
    )
    moved = EvidenceAttempt(
        step_id=_IDS[3],
        step_order=4,
        status=moved.status,
        error_code=None,
        edges=moved.edges,
        calls=moved.calls,
        forwarding=moved.forwarding,
    )

    (second,) = _overlaps([[moved]], steps=renumbered)

    assert second.fingerprint == first.fingerprint


# --- deterministic_candidate ----------------------------------------------


def _verbatim_attempt(
    ratio: float = 0.95,
    *,
    output: int = 2000,
    source: int | None = None,
    unmeasured: Sequence[int] = (),
) -> EvidenceAttempt:
    # Step 2's output copies step 1's text with a heading of its own.
    size = source if source is not None else round(output * ratio)
    return _attempt(
        2,
        [_edge("input_source", 1, size=size)],
        [_call(500, (0,), output=450)],
        forwarding=_forwarding(
            [_edge_facts(0, size=size, copied=ratio)],
            output=output,
            verbatim=ratio,
            unmeasured=unmeasured,
        ),
    )


def _candidates(runs, steps=None, **kwargs) -> list[FlowSuggestion]:
    return _analyzed(
        steps or [_step(1), _step(2), _step(3)],
        runs,
        FlowSuggestionCode.DETERMINISTIC_CANDIDATE,
        **kwargs,
    )


def test_a_step_whose_output_is_its_input_copied_is_a_deterministic_candidate() -> None:
    (item,) = _candidates([[_verbatim_attempt()]])

    assert item.steps == (_IDS[2],)
    assert item.params == {
        "output_verbatim_ratio": 0.95,
        "own_bytes": 100,
        "input_share": 1.0,
        "run_count": 1,
        "held_runs": 1,
    }
    assert item.impact.level == "medium"
    # Everything the step was billed: a compose_text step calls no model.
    assert item.impact.tokens_per_run == 950
    assert item.fix.kind == "assisted"
    assert "a compose_text step puts that together without a model" in item.message


def test_a_deterministic_candidate_needs_a_verbatim_output_with_little_of_its_own() -> (
    None
):
    assert len(_candidates([[_verbatim_attempt(0.9)]])) == 1
    assert _candidates([[_verbatim_attempt(0.89)]]) == []
    at_limit = DETERMINISTIC_MAX_OWN_BYTES / 0.05
    assert len(_candidates([[_verbatim_attempt(output=round(at_limit))]])) == 1
    assert _candidates([[_verbatim_attempt(output=round(at_limit) + 40)]]) == []


def test_a_verbatim_excerpt_of_a_longer_input_is_no_deterministic_candidate() -> None:
    # Choosing what to quote from a long text is the model's work.
    assert _candidates([[_verbatim_attempt(source=20_000)]]) == []


def test_a_deterministic_candidate_counts_only_fully_measured_calls() -> None:
    # A call with an input the worker did not hold (a file) does not count.
    with_file = _verbatim_attempt(unmeasured=(1,))

    assert _candidates([[with_file]]) == []
    (item,) = _candidates([[_verbatim_attempt()], [with_file]])
    assert item.params["run_count"] == 1


def test_a_deterministic_candidate_is_a_text_step_with_the_same_model() -> None:
    json_step = [_step(1), _step(2, output_type="json"), _step(3)]

    assert _candidates([[_verbatim_attempt()]], steps=json_step) == []
