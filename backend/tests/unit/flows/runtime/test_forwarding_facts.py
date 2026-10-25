from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from eneo.flows.domain.forwarding_facts import (
    FORWARDING_FACTS_MAX_CANONICAL_BYTES,
    ForwardingEdgeFacts,
    ForwardingFacts,
    parse_forwarding_facts,
)
from eneo.flows.flow_run_provenance import FLOW_RESOLVED_INPUT_MAX_EDGES
from eneo.flows.runtime import forwarding_facts as forwarding_facts_module
from eneo.flows.runtime.forwarding_facts import (
    MAX_UNSAMPLED_BYTES,
    ForwardingSegment,
    measure_forwarding_facts,
    normalized_words,
    sample_every_for,
)


def _words(prefix: str, count: int) -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def _edge(facts: ForwardingFacts, index: int) -> ForwardingEdgeFacts:
    return next(edge for edge in facts.edges if edge.edge_index == index)


def test_known_overlap_between_two_inputs_maps_to_the_shared_words() -> None:
    shared = _words("shared", 50)
    first = f"{shared} {_words('first', 50)}"
    second = f"{_words('second', 100)} {shared}"

    facts = measure_forwarding_facts(
        segments=(
            ForwardingSegment(edge_index=0, text=first),
            ForwardingSegment(edge_index=1, text=second),
        ),
        output_text=_words("fresh", 20),
    )

    assert facts.measured is True
    first_facts, second_facts = _edge(facts, 0), _edge(facts, 1)
    assert first_facts.byte_size == len(first.encode("utf-8"))
    # Half of the first input's words, a third of the second's.
    assert first_facts.repeated_bytes == round(first_facts.byte_size * 50 / 100)
    assert second_facts.repeated_bytes == round(second_facts.byte_size * 50 / 150)
    assert first_facts.copied_to_output_ratio == 0.0
    assert facts.output_verbatim_ratio == 0.0


def test_unrelated_inputs_repeat_nothing() -> None:
    facts = measure_forwarding_facts(
        segments=(
            ForwardingSegment(edge_index=0, text=_words("a", 40)),
            ForwardingSegment(edge_index=1, text=_words("b", 40)),
        ),
        output_text=_words("c", 40),
    )

    assert [edge.repeated_bytes for edge in facts.edges] == [0, 0]


def test_an_identical_segment_read_twice_is_repeated_in_full() -> None:
    transcript = _words("word", 200)

    facts = measure_forwarding_facts(
        segments=(
            ForwardingSegment(edge_index=0, text=transcript),
            ForwardingSegment(edge_index=3, text=transcript),
        ),
        output_text=_words("summary", 30),
    )

    size = len(transcript.encode("utf-8"))
    assert [(edge.edge_index, edge.repeated_bytes) for edge in facts.edges] == [
        (0, size),
        (3, size),
    ]


def test_repetition_inside_one_segment_is_not_counted() -> None:
    paragraph = _words("p", 20)

    facts = measure_forwarding_facts(
        segments=(
            ForwardingSegment(edge_index=0, text=f"{paragraph} {paragraph}"),
            ForwardingSegment(edge_index=1, text=_words("other", 20)),
        ),
        output_text="",
    )

    assert _edge(facts, 0).repeated_bytes == 0


def test_an_output_that_copies_its_input() -> None:
    source = _words("source", 120)
    other = _words("other", 120)
    # The output repeats the first 60 words of the source and adds nothing.
    copied = _words("source", 60)

    facts = measure_forwarding_facts(
        segments=(
            ForwardingSegment(edge_index=0, text=source),
            ForwardingSegment(edge_index=1, text=other),
        ),
        output_text=copied,
    )

    assert facts.output_verbatim_ratio == 1.0
    assert _edge(facts, 0).copied_to_output_ratio == 1.0
    assert _edge(facts, 1).copied_to_output_ratio == 0.0
    assert facts.output_byte_size == len(copied.encode("utf-8"))
    assert facts.output_shingle_count == 60 - 7


def test_an_output_that_quotes_half_of_its_input() -> None:
    source = _words("source", 100)
    output = f"{_words('source', 50)} {_words('own', 50)}"

    facts = measure_forwarding_facts(
        segments=(ForwardingSegment(edge_index=0, text=source),),
        output_text=output,
    )

    # 43 of the output's 93 shingles lie inside the quoted words.
    assert facts.output_verbatim_ratio == round(43 / 93, 6)


def test_text_shorter_than_one_shingle_has_no_ratio() -> None:
    facts = measure_forwarding_facts(
        segments=(ForwardingSegment(edge_index=0, text="Anna Svensson"),),
        output_text="OK",
    )

    edge = _edge(facts, 0)
    assert (edge.shingle_count, edge.repeated_bytes) == (0, 0)
    assert edge.copied_to_output_ratio is None
    assert facts.output_verbatim_ratio is None


def test_unicode_normalization_casefold_and_whitespace() -> None:
    source = "Straße ﬁle Ｆｕｌｌｗｉｄｔｈ ÉCOLE café naïve résumé déjà vu encore"
    # Casefolded, compatibility forms decomposed, other spacing and markup.
    output = (
        "**STRASSE**  file\tfullwidth\n\nécole CAFÉ / naïve, résumé; déjà vu encore"
    )

    facts = measure_forwarding_facts(
        segments=(ForwardingSegment(edge_index=0, text=source),),
        output_text=output,
    )

    assert normalized_words(source) == normalized_words(output)
    assert facts.output_verbatim_ratio == 1.0


def test_composed_and_decomposed_accents_match() -> None:
    composed = "Mötet beslutade att kommunen ska införa en ny rutin för ärenden"
    decomposed = composed.replace("ö", "ö").replace("ä", "ä")

    assert normalized_words(composed) == normalized_words(decomposed)


def test_a_segment_over_the_size_bound_is_sampled() -> None:
    word = "ord"
    count = MAX_UNSAMPLED_BYTES // 4 + 2_000
    big = " ".join(f"{word}{index % 1000:03d}x{index}" for index in range(count))
    byte_size = len(big.encode("utf-8"))
    assert byte_size > MAX_UNSAMPLED_BYTES
    expected_k = sample_every_for(byte_size)
    assert expected_k > 1

    facts = measure_forwarding_facts(
        segments=(
            ForwardingSegment(edge_index=0, text=big),
            ForwardingSegment(edge_index=1, text=big),
        ),
        output_text=_words("x", 10),
        budget_seconds=60.0,
    )

    edge = _edge(facts, 0)
    assert edge.sample_every == expected_k
    total_shingles = count - 7
    assert edge.shingle_count == -(-total_shingles // expected_k)
    # The same text twice is still repeated (nearly) in full under sampling:
    # only the words after the last sampled shingle can stay uncovered.
    assert edge.repeated_bytes >= byte_size * 0.999


def test_sampling_starts_past_two_mebibytes() -> None:
    assert sample_every_for(MAX_UNSAMPLED_BYTES) == 1
    assert sample_every_for(MAX_UNSAMPLED_BYTES + 1) == 2
    assert sample_every_for(5 * MAX_UNSAMPLED_BYTES) == 5


def _ticking_clock(step: float) -> Iterator[float]:
    now = 0.0
    while True:
        yield now
        now += step


def test_the_cpu_budget_cuts_the_measurement_off() -> None:
    ticks = _ticking_clock(0.01)

    facts = measure_forwarding_facts(
        segments=(ForwardingSegment(edge_index=0, text=_words("w", 5_000)),),
        output_text=_words("w", 5_000),
        call_count=3,
        clock=lambda: next(ticks),
        budget_seconds=0.05,
    )

    assert facts.measured is False
    assert facts.not_measured_reason == "cpu_budget_exceeded"
    assert facts.call_count == 3
    assert facts.edges == ()
    assert facts.output_verbatim_ratio is None


def test_a_failure_inside_is_recorded_and_logged_without_content(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "confidential minutes of the closed session about the budget"

    def _fail(_text: str) -> list[str]:
        raise RuntimeError(secret)

    monkeypatch.setattr(forwarding_facts_module, "normalized_words", _fail)

    facts = measure_forwarding_facts(
        segments=(ForwardingSegment(edge_index=0, text=secret),),
        output_text=secret,
    )

    assert facts.measured is False
    assert facts.not_measured_reason == "computation_failed"
    assert "RuntimeError" in caplog.text
    assert secret not in caplog.text


def test_serialized_facts_hold_no_text() -> None:
    marker_words = [f"hemligt{index}" for index in range(30)]
    text = " ".join(marker_words)

    facts = measure_forwarding_facts(
        segments=(
            ForwardingSegment(edge_index=0, text=text),
            ForwardingSegment(edge_index=1, text=text),
        ),
        output_text=text,
        unmeasured_edge_indexes=(2,),
    )

    dumped = json.dumps(facts.model_dump(mode="json"))
    assert "hemligt" not in dumped
    assert facts.unmeasured_edge_indexes == (2,)

    def _strings(value: object) -> Iterator[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from _strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from _strings(item)

    allowed = set(ForwardingFacts.model_fields) | set(ForwardingEdgeFacts.model_fields)
    assert set(_strings(facts.model_dump(mode="json"))) <= allowed


def _edge_facts(index: int) -> ForwardingEdgeFacts:
    return ForwardingEdgeFacts(
        edge_index=index,
        byte_size=10_000_000,
        shingle_count=1_000_000,
        sample_every=1,
        repeated_bytes=9_999_999,
        copied_to_output_ratio=0.123456,
    )


def test_the_model_bounds_its_edges_and_size() -> None:
    every_edge = tuple(
        _edge_facts(index) for index in range(FLOW_RESOLVED_INPUT_MAX_EDGES)
    )
    facts = ForwardingFacts(
        schema_version=1, measured=True, call_count=1, edges=every_edge
    )
    size = len(json.dumps(facts.model_dump(mode="json")).encode("utf-8"))
    assert size < FORWARDING_FACTS_MAX_CANONICAL_BYTES

    with pytest.raises(ValidationError):
        ForwardingFacts(
            schema_version=1,
            measured=True,
            call_count=1,
            edges=(*every_edge, _edge_facts(0)),
        )


def test_the_model_rejects_inconsistent_facts() -> None:
    with pytest.raises(ValidationError):
        ForwardingFacts(schema_version=1, measured=False, call_count=1)
    with pytest.raises(ValidationError):
        ForwardingFacts(
            schema_version=1,
            measured=True,
            call_count=1,
            edges=(_edge_facts(1), _edge_facts(0)),
        )
    with pytest.raises(ValidationError):
        ForwardingEdgeFacts(
            edge_index=0,
            byte_size=10,
            shingle_count=0,
            sample_every=1,
            repeated_bytes=11,
            copied_to_output_ratio=None,
        )


def test_stored_facts_round_trip_and_unreadable_facts_read_as_none() -> None:
    facts = measure_forwarding_facts(
        segments=(ForwardingSegment(edge_index=0, text=_words("a", 20)),),
        output_text=_words("a", 20),
    )

    assert parse_forwarding_facts(facts.model_dump(mode="json")) == facts
    assert parse_forwarding_facts(None) is None
    assert parse_forwarding_facts({"schema_version": 2}) is None
    assert parse_forwarding_facts("not an object") is None


def _transcript(word_count: int) -> str:
    vocabulary = (
        "kommunen nämnden beslutade att ärendet ska utredas vidare och återkomma "
        "med ett förslag till budget för nästa år samt redovisa kostnaderna för "
        "verksamheten inom skolan omsorgen och kulturen i hela regionen"
    ).split()
    words = [
        f"{vocabulary[(index * 7) % len(vocabulary)]}{index % 97}"
        for index in range(word_count)
    ]
    lines = [" ".join(words[start : start + 12]) for start in range(0, word_count, 12)]
    return "\n".join(
        f"Talare {index % 4 + 1}: {line}" for index, line in enumerate(lines)
    )


def test_a_two_hour_transcript_and_its_summary_are_measured() -> None:
    transcript = _transcript(18_000)
    summary = " ".join(transcript.split()[:1_500])

    # The 50 ms budget is checked with an injected clock above; wall time on a
    # shared test machine is not asserted here (an idle worker takes about
    # 20 ms, see the benchmark in the change description).
    facts = measure_forwarding_facts(
        segments=(
            ForwardingSegment(edge_index=0, text=transcript),
            ForwardingSegment(edge_index=1, text=summary),
        ),
        output_text=summary,
        budget_seconds=5.0,
    )

    assert facts.measured is True
    assert facts.output_verbatim_ratio == 1.0
    assert facts.edges[1].repeated_bytes == facts.edges[1].byte_size
