"""Suggestions from the forwarding facts the worker records for each model
call: ``model_relay``, ``overlapping_inputs`` (and its fold into the static
suggestion about the same two reads) and ``deterministic_candidate``, their
thresholds and how the runs that measured them are counted."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from eneo.flows.domain.flow_suggestion_evidence import EvidenceAttempt, EvidenceEdge
from eneo.flows.domain.flow_suggestion_forwarding import (
    DETERMINISTIC_MAX_OWN_BYTES,
    FORWARDING_MIN_REPEATED_BYTES,
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
from eneo.flows.enums import FlowInputSource
from tests.unit.flows.domain.suggestion_evidence_builders import (
    IDS,
    PROMPT_READ,
    analyzed,
    make_attempt,
    make_call,
    make_edge,
    make_evidence,
    make_facts,
    make_step,
    of_code,
)


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


# --- model_relay ----------------------------------------------------------


def _relay_flow() -> list[SuggestionStep]:
    """Step 2 reads step 1; step 3 reads step 2."""
    return [make_step(1), make_step(2), make_step(3)]


def _relay_attempt(
    copied: float | None = 0.8,
    *,
    output: int = 1000,
    size: int = 1000,
    facts: ForwardingFacts | None = None,
) -> EvidenceAttempt:
    # Step 2's one call sent step 1's 1000 bytes and wrote 300 tokens.
    return make_attempt(
        2,
        [make_edge("input_source", 1, size=size)],
        [make_call(400, (0,), output=300)],
        forwarding=facts
        or _forwarding([_edge_facts(0, size=size, copied=copied)], output=output),
    )


def _relays(
    runs: Sequence[Sequence[EvidenceAttempt]],
    steps: Sequence[SuggestionStep] | None = None,
    **kwargs,
) -> list[FlowSuggestion]:
    return analyzed(
        steps or _relay_flow(), runs, FlowSuggestionCode.MODEL_RELAY, **kwargs
    )


def test_a_step_whose_output_copies_its_input_for_a_later_reader_is_a_relay() -> None:
    (item,) = _relays([[_relay_attempt()]])

    assert item.steps == (IDS[2], IDS[1], IDS[3])
    assert item.params["producer_step_order"] == 1
    assert item.params["producer_step_id"] == str(IDS[1])
    assert item.params["readers"] == [
        {"step_order": 3, "step_id": str(IDS[3]), "sites": ["input_source"]}
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
        make_attempt(2, [make_edge("input_source", 1)], [make_call(400, (0,))]),
        _relay_attempt(facts=_forwarding([], verbatim=0.0, unmeasured=(0,))),
        _relay_attempt(facts=_forwarding([_edge_facts(0, copied=0.1)], calls=2)),
        _relay_attempt(facts=_forwarding([_edge_facts(0, size=900, copied=0.8)])),
    ]

    (item,) = _relays([[_relay_attempt()], *([attempt] for attempt in unmeasured)])

    assert (item.params["run_count"], item.params["held_runs"]) == (1, 1)


def test_a_relay_lapses_when_the_draft_no_longer_relays_with_that_model() -> None:
    no_reader = [
        make_step(1),
        make_step(2),
        make_step(3, input_source=FlowInputSource.FLOW_INPUT),
    ]
    no_read = [
        make_step(1),
        make_step(2, input_source=FlowInputSource.FLOW_INPUT),
        make_step(3),
    ]

    assert _relays([[_relay_attempt()]], steps=no_reader) == []
    assert _relays([[_relay_attempt()]], steps=no_read) == []
    assert (
        _relays(
            [[_relay_attempt()]], published={IDS[2]: make_facts(model=UUID(int=901))}
        )
        == []
    )
    assert (
        _relays(
            [[_relay_attempt()]], published={IDS[2]: make_facts(output_type="json")}
        )
        == []
    )


def test_a_relay_keeps_its_fingerprint_across_renumbering_and_measurements() -> None:
    (first,) = _relays([[_relay_attempt(0.7)]])
    # A step inserted before them: step 2 becomes step 3, and so on.
    renumbered = [
        make_step(1, step_id=UUID(int=500)),
        make_step(2, step_id=IDS[1], input_source=FlowInputSource.FLOW_INPUT),
        make_step(3, step_id=IDS[2]),
        make_step(4, step_id=IDS[3]),
    ]
    (second,) = _relays([[_relay_attempt(0.9)]], steps=renumbered)

    assert second.params["producer_step_order"] == 2
    assert second.fingerprint == first.fingerprint


# --- overlapping_inputs ---------------------------------------------------


def _overlap_flow(*, prompt: str = "Jämför.\n{{ step_1.output.text }}"):
    """Step 3 reads step 2 as its input and step 1 in its prompt: two
    producers, two different texts."""
    return [
        make_step(1),
        make_step(2, input_source=FlowInputSource.FLOW_INPUT),
        make_step(3, prompt_text=prompt),
    ]


def _overlap_attempt(
    repeated: int = 700, *, third: ForwardingEdgeFacts | None = None, sha: str = "b"
) -> EvidenceAttempt:
    # The summary from step 2 (1000 bytes) repeats ``repeated`` bytes of the
    # transcript from step 1 (4000 bytes); one call, 1000 tokens for 5000
    # bytes.
    edges = [
        make_edge("input_source", 2, size=1000, sha=sha),
        make_edge(PROMPT_READ, 1, size=4000),
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
    return make_attempt(
        3,
        edges,
        [make_call(1000, tuple(range(len(edges))))],
        forwarding=_forwarding(facts, verbatim=0.0),
    )


def _overlaps(runs, steps=None, **kwargs) -> list[FlowSuggestion]:
    return analyzed(
        steps or _overlap_flow(), runs, FlowSuggestionCode.OVERLAPPING_INPUTS, **kwargs
    )


def test_two_inputs_that_share_half_of_the_smaller_one_overlap() -> None:
    (item,) = _overlaps([[_overlap_attempt()]])

    assert item.steps == (IDS[3], IDS[1], IDS[2])
    assert item.params["inputs"] == [
        {"step_order": 1, "step_id": str(IDS[1]), "sites": [PROMPT_READ]},
        {"step_order": 2, "step_id": str(IDS[2]), "sites": ["input_source"]},
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
    attempt = make_attempt(
        3,
        [
            make_edge("input_source", 2, size=small, sha="b"),
            make_edge(PROMPT_READ, 1, size=4000),
        ],
        [make_call(1000, (0, 1))],
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
        make_step(1),
        make_step(2, prompt_text="Titel: {{ step_1.output.structured.title }}"),
    ]
    attempt = make_attempt(
        2,
        [
            make_edge("input_source", 1, size=3000),
            make_edge(
                "assistant_prompt:step_1.output.structured.title", 1, size=600, sha="b"
            ),
        ],
        [make_call(900, (0, 1))],
        forwarding=_forwarding(
            [
                _edge_facts(0, size=3000, repeated=600),
                _edge_facts(1, size=600, repeated=600),
            ],
            verbatim=0.0,
        ),
    )
    (static,) = of_code(
        analyze_flow(SuggestionFlow(steps=steps)), FlowSuggestionCode.DUPLICATE_READ
    )

    suggestions = analyze_flow(
        SuggestionFlow(steps=steps), make_evidence(steps, [[attempt]])
    )
    (duplicate,) = of_code(suggestions, FlowSuggestionCode.DUPLICATE_READ)

    assert of_code(suggestions, FlowSuggestionCode.OVERLAPPING_INPUTS) == []
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
        make_step(1),
        make_step(2),
        make_step(3, input_source=FlowInputSource.ALL_PREVIOUS_STEPS),
    ]
    attempt = make_attempt(
        3,
        [
            make_edge("input_source", 1, size=4000),
            make_edge("input_source", 2, size=1000, sha="b"),
        ],
        [make_call(1000, (0, 1))],
        forwarding=_forwarding(
            [
                _edge_facts(0, size=4000, repeated=800),
                _edge_facts(1, size=1000, repeated=800),
            ],
            verbatim=0.0,
        ),
    )
    (static,) = of_code(
        analyze_flow(SuggestionFlow(steps=steps)),
        FlowSuggestionCode.BROAD_ALL_PREVIOUS_STEPS,
    )

    suggestions = analyze_flow(
        SuggestionFlow(steps=steps), make_evidence(steps, [[attempt]])
    )
    (broad,) = of_code(suggestions, FlowSuggestionCode.BROAD_ALL_PREVIOUS_STEPS)

    assert of_code(suggestions, FlowSuggestionCode.OVERLAPPING_INPUTS) == []
    assert broad.fingerprint == static.fingerprint
    assert broad.impact == static.impact
    (overlap,) = broad.params["measured_overlaps"]
    assert overlap["inputs"] == [
        {"step_order": 1, "step_id": str(IDS[1]), "sites": ["input_source"]},
        {"step_order": 2, "step_id": str(IDS[2]), "sites": ["input_source"]},
    ]
    assert overlap["shared_share"] == 0.8


def test_an_overlap_keeps_its_fingerprint_across_renumbering() -> None:
    (first,) = _overlaps([[_overlap_attempt(600)]])
    renumbered = [
        make_step(1, step_id=UUID(int=500)),
        make_step(2, step_id=IDS[1], input_source=FlowInputSource.FLOW_INPUT),
        make_step(3, step_id=IDS[2], input_source=FlowInputSource.FLOW_INPUT),
        make_step(4, step_id=IDS[3], prompt_text="Jämför.\n{{ step_2.output.text }}"),
    ]
    moved = make_attempt(
        4,
        [
            make_edge("input_source", 2, size=1000, sha="b"),
            make_edge("assistant_prompt:step_2.output.text", 1, size=4000),
        ],
        [make_call(1000, (0, 1))],
        forwarding=_forwarding(
            [
                _edge_facts(0, size=1000, repeated=900),
                _edge_facts(1, size=4000, repeated=900),
            ],
            verbatim=0.0,
        ),
    )
    moved = EvidenceAttempt(
        step_id=IDS[3],
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
    return make_attempt(
        2,
        [make_edge("input_source", 1, size=size)],
        [make_call(500, (0,), output=450)],
        forwarding=_forwarding(
            [_edge_facts(0, size=size, copied=ratio)],
            output=output,
            verbatim=ratio,
            unmeasured=unmeasured,
        ),
    )


def _candidates(runs, steps=None, **kwargs) -> list[FlowSuggestion]:
    return analyzed(
        steps or [make_step(1), make_step(2), make_step(3)],
        runs,
        FlowSuggestionCode.DETERMINISTIC_CANDIDATE,
        **kwargs,
    )


def test_a_step_whose_output_is_its_input_copied_is_a_deterministic_candidate() -> None:
    (item,) = _candidates([[_verbatim_attempt()]])

    assert item.steps == (IDS[2],)
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
    json_step = [make_step(1), make_step(2, output_type="json"), make_step(3)]

    assert _candidates([[_verbatim_attempt()]], steps=json_step) == []
