"""Suggestions from the forwarding facts the worker records for each model
step attempt: how much of one call's input repeats across its inputs, and
how much of its output repeats them verbatim.

Pure functions over the draft's reads (``DraftReads``) and the content-free
``RunEvidence``. The facts are shares, sizes and edge indexes, never text
(``domain.forwarding_facts``; how they are measured is in
``runtime.forwarding_facts``).

- ``model_relay``: most of a model step's output is one earlier result
  copied verbatim, and a later step reads it from there.
- ``overlapping_inputs``: two inputs of one call share much of their text
  without being identical (a transcript and a summary that quotes it at
  length). Folded into the ``duplicate_read`` or
  ``broad_all_previous_steps`` the draft already proves about the same two
  reads.
- ``deterministic_candidate``: a model step whose output is its inputs
  copied verbatim with little of its own, which a ``compose_text`` step puts
  together without a model.

What a run counts for: a finding counts the runs whose attempt of the step
has facts the worker measured (``measured: true``) for what it judges: an
edge measured and at least one shingle long, and for the rules about the
output, an output at least one shingle long from the attempt's only model
call that returned output (the facts describe the first call; with more, the
step's result is not that call's output). Facts that record no measurement,
facts that do not parse and edges in ``unmeasured_edge_indexes`` never count
as zero: the run is left out of that finding's count. A finding is reported
when its threshold holds in ``FORWARDING_MIN_RUN_SHARE`` or more of the runs
it counts, as ``format_fallback`` counts, and only over runs whose version
gave the step the model and output type it has now.

Edges map to the draft's reads as in ``flow_suggestion_measured``: by
``binding_ref`` and producer (``DraftReads.edge_read``), so a measurement
attaches only through reads the draft still makes. Fingerprints name steps
by id and reads by ``read_premise``, never a measured number.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Generic, TypeVar
from uuid import UUID

from eneo.flows.domain.canonical_json_hash import canonical_json_hash
from eneo.flows.domain.flow_suggestion_evidence import (
    EvidenceAttempt,
    EvidenceEdge,
    EvidenceRun,
    RunEvidence,
)
from eneo.flows.domain.flow_suggestion_model import (
    DraftReads,
    FlowSuggestion,
    FlowSuggestionCode,
    FlowSuggestionFix,
    FlowSuggestionImpact,
    FlowSuggestionLevel,
    SuggestionStep,
    describe_read,
    join_descriptions,
    make_suggestion,
    read_payload,
    read_premises,
    uses_completion_model,
)
from eneo.flows.domain.forwarding_facts import ForwardingEdgeFacts, ForwardingFacts
from eneo.flows.enums import FlowOutputMode, FlowOutputType
from eneo.flows.step_lineage import INPUT_SOURCE_READ_SITE, StepRead

# A finding is reported when its threshold holds in at least this share of
# the runs that measured it.
FORWARDING_MIN_RUN_SHARE = 0.5
# A copy or an overlap shorter than this is not reported: a shared heading,
# a name or a short quote costs next to nothing (as for `identical_inputs`).
FORWARDING_MIN_REPEATED_BYTES = 256

# `model_relay`: at least this share of the output's shingles are found in
# one input (its `copied_to_output_ratio`) ...
MODEL_RELAY_MIN_COPIED_SHARE = 0.6
# ... and that copy is at least this share of the input (the output's bytes
# times the copied share, over the input's bytes): the step passes the input
# on, rather than quoting the part of it it was asked to find, which a later
# step reading the original would not replace.
MODEL_RELAY_MIN_INPUT_SHARE = 0.6

# `overlapping_inputs`: two inputs share at least this share of the smaller
# one's bytes (`repeated_bytes` against its `byte_size`).
OVERLAPPING_INPUTS_MIN_SHARE = 0.5

# `deterministic_candidate`: at least this share of the output's shingles
# are found in the call's inputs (`output_verbatim_ratio`) ...
DETERMINISTIC_MIN_VERBATIM_RATIO = 0.9
# ... and what is left, the output's bytes times one minus that share, is
# short: at most this many bytes. Short is what a compose_text template's
# own text holds. The share counts eight-word shingles, so each seam between
# fixed text and a copied value breaks up to eight shingles that occur in no
# input: a template with a heading and a few labels measures as some 150 to
# 250 bytes of the output's own although the model wrote none of it. 400
# leaves room for that and a sentence of fixed text, and is less than a
# paragraph the model writes.
DETERMINISTIC_MAX_OWN_BYTES = 400
# ... and the copy is nearly all of the inputs it is copied from (the
# output's verbatim bytes over theirs): whole results put together, which a
# template renders, rather than a selection from them, which takes a model.
DETERMINISTIC_MIN_INPUT_SHARE = 0.9

_T = TypeVar("_T")


@dataclass
class _Tally(Generic[_T]):
    """One finding over the runs that measured it: the version of each,
    and what was measured in those where its threshold held."""

    versions: list[int] = field(default_factory=lambda: list[int]())
    held: list[_T] = field(default_factory=lambda: list[_T]())

    def count(self, version: int, held: _T | None) -> None:
        self.versions.append(version)
        if held is not None:
            self.held.append(held)

    def fires(self) -> bool:
        return bool(self.held) and len(self.held) >= FORWARDING_MIN_RUN_SHARE * len(
            self.versions
        )

    @property
    def run_count(self) -> int:
        return len(self.versions)

    @property
    def version(self) -> int:
        return max(self.versions)


@dataclass(frozen=True, slots=True)
class _Measured:
    """A run's attempt of a step whose forwarding facts count: measured, in
    a version that gave the step its current model and output type."""

    run: EvidenceRun
    attempt: EvidenceAttempt
    facts: ForwardingFacts

    @property
    def measures_output(self) -> bool:
        """Whether the facts measure the step's output: the attempt's only
        model call that returned output, at least one shingle long."""
        return self.facts.call_count == 1 and self.facts.output_shingle_count > 0

    def edge(self, facts: ForwardingEdgeFacts) -> EvidenceEdge | None:
        """The attempt's edge the edge facts describe; None when the attempt
        has no such edge, or one of another size (then it is not the value
        the worker measured)."""
        index = facts.edge_index
        if not 0 <= index < len(self.attempt.edges):
            return None
        edge = self.attempt.edges[index]
        if edge.byte_size is not None and edge.byte_size != facts.byte_size:
            return None
        return edge

    def edges(self) -> list[tuple[ForwardingEdgeFacts, EvidenceEdge]]:
        """The measured edges at least one shingle long, with the attempt's
        edge each describes."""
        return [
            (facts, edge)
            for facts in self.facts.edges
            if facts.shingle_count > 0 and (edge := self.edge(facts)) is not None
        ]


def _measured(step: SuggestionStep, evidence: RunEvidence) -> list[_Measured]:
    measured: list[_Measured] = []
    for run in evidence.runs:
        attempt = run.attempt(step.id)
        facts = attempt.measured_forwarding() if attempt is not None else None
        if (
            attempt is None
            or facts is None
            or not evidence.same_model_and_output(step.id, run.version)
        ):
            continue
        measured.append(_Measured(run=run, attempt=attempt, facts=facts))
    return measured


def forwarding_suggestions(
    draft: DraftReads,
    suggestions: Sequence[FlowSuggestion],
    evidence: RunEvidence,
) -> list[FlowSuggestion]:
    """``suggestions`` with each overlap the runs measured folded into the
    one about the same two reads, followed by the forwarding rules' own
    findings."""
    folded, overlaps = overlapping_inputs(draft, suggestions, evidence)
    return [
        *folded,
        *overlaps,
        *model_relays(draft, evidence),
        *deterministic_candidates(draft, evidence),
    ]


def _impact(
    step: SuggestionStep,
    tally: _Tally[Any],
    evidence: RunEvidence,
    *,
    level: FlowSuggestionLevel,
    tokens: Sequence[float | None],
) -> FlowSuggestionImpact:
    """A measured impact: ``tokens_per_run`` is the average of the held
    runs' ``tokens`` that are known, None when none is."""
    known = [value for value in tokens if value is not None]
    return FlowSuggestionImpact(
        basis="runs",
        level=level,
        tokens_per_run=round(sum(known) / len(known)) if known else None,
        run_count=tally.run_count,
        version=tally.version,
        step_changed_since=evidence.step_changed_since(step.id, tally.version),
    )


def _average(values: Iterable[float], digits: int = 2) -> float:
    items = list(values)
    return round(sum(items) / len(items), digits)


def _percent(share: float) -> int:
    return round(100 * share)


def _steps_phrase(orders: Sequence[int]) -> str:
    if len(orders) == 1:
        return f"step {orders[0]}"
    return "steps " + join_descriptions([str(order) for order in orders])


# --- model_relay ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Relay:
    copied_share: float
    input_share: float
    copied_bytes: float
    output_tokens: float | None

    @property
    def holds(self) -> bool:
        return (
            self.copied_share >= MODEL_RELAY_MIN_COPIED_SHARE
            and self.input_share >= MODEL_RELAY_MIN_INPUT_SHARE
            and self.copied_bytes >= FORWARDING_MIN_REPEATED_BYTES
        )


def model_relays(draft: DraftReads, evidence: RunEvidence) -> list[FlowSuggestion]:
    """``model_relay``: a model step whose output is, for
    ``MODEL_RELAY_MIN_COPIED_SHARE`` or more, one earlier step's result
    copied verbatim, a copy of ``MODEL_RELAY_MIN_INPUT_SHARE`` or more of
    that result, while a later step of the draft reads the step and the
    step still reads that result. The fix: the later step reads the
    original, and the step stops repeating it. ``tokens_per_run`` is the
    measured call's output tokens times the copied share: what the model
    was billed for writing the copy."""

    suggestions: list[FlowSuggestion] = []
    for step in draft.steps:
        readers = draft.readers_of(step.step_order)
        if not uses_completion_model(step) or not readers:
            continue
        reads = draft.model_reads(step)
        tallies: dict[int, _Tally[_Relay]] = {}
        for measured in _measured(step, evidence):
            if not measured.measures_output:
                continue
            best: dict[int, _Relay] = {}
            for edge_facts, edge in measured.edges():
                read = draft.edge_read(
                    reads,
                    binding_ref=edge.binding_ref,
                    source_step_id=edge.source_step_id,
                )
                if read is None or edge_facts.copied_to_output_ratio is None:
                    continue
                relay = _relay(measured, edge_facts)
                current = best.get(read.step_order)
                if current is None or (relay.holds, relay.copied_share) > (
                    current.holds,
                    current.copied_share,
                ):
                    best[read.step_order] = relay
            for producer_order, relay in best.items():
                tallies.setdefault(producer_order, _Tally[_Relay]()).count(
                    measured.run.version, relay if relay.holds else None
                )
        for producer_order, tally in sorted(tallies.items()):
            if tally.fires():
                suggestions.append(
                    _relay_suggestion(
                        draft, step, producer_order, tally, readers, evidence
                    )
                )
    return suggestions


def _relay(measured: _Measured, edge: ForwardingEdgeFacts) -> _Relay:
    copied_share = edge.copied_to_output_ratio or 0.0
    copied_bytes = measured.facts.output_byte_size * copied_share
    call = measured.attempt.measured_call()
    output_tokens = call.num_tokens_output if call is not None else None
    return _Relay(
        copied_share=copied_share,
        input_share=min(1.0, copied_bytes / edge.byte_size) if edge.byte_size else 0.0,
        copied_bytes=copied_bytes,
        output_tokens=(
            output_tokens * copied_share if output_tokens is not None else None
        ),
    )


def _relay_suggestion(
    draft: DraftReads,
    step: SuggestionStep,
    producer_order: int,
    tally: _Tally[_Relay],
    readers: Sequence[tuple[SuggestionStep, StepRead]],
    evidence: RunEvidence,
) -> FlowSuggestion:
    producer = draft.step_at(producer_order)
    assert producer is not None, "a read of a step names a step of the draft"
    producer_reads = [
        read for read in draft.model_reads(step) if read.step_order == producer_order
    ]
    by_reader: dict[UUID, tuple[SuggestionStep, list[str]]] = {}
    for reader, read in readers:
        by_reader.setdefault(reader.id, (reader, []))[1].append(read.site)
    reader_steps = sorted(by_reader.values(), key=lambda item: item[0].step_order)
    copied_share = _average(relay.copied_share for relay in tally.held)
    reader_orders = [reader.step_order for reader, _ in reader_steps]
    return make_suggestion(
        FlowSuggestionCode.MODEL_RELAY,
        steps=(step.id, producer.id, *(reader.id for reader, _ in reader_steps)),
        identity_steps=(step.id, producer.id),
        premise={
            "producer": draft.producer_key(producer_order),
            "reads": read_premises(producer_reads),
        },
        params={
            "producer_step_order": producer_order,
            "producer_step_id": str(producer.id),
            "reads": [read_payload(read) for read in producer_reads],
            "readers": [
                {
                    "step_order": reader.step_order,
                    "step_id": str(reader.id),
                    "sites": sites,
                }
                for reader, sites in reader_steps
            ],
            "copied_share": copied_share,
            "input_share": _average(relay.input_share for relay in tally.held),
            "copied_bytes": round(_average(relay.copied_bytes for relay in tally.held)),
            "run_count": tally.run_count,
            "held_runs": len(tally.held),
        },
        message=(
            f"In {len(tally.held)} of the last {tally.run_count} runs, "
            f"{_percent(copied_share)} % of step {step.step_order}'s output was "
            f"step {producer_order}'s result copied word for word, and "
            f"{_steps_phrase(reader_orders)} "
            f"{'reads' if len(reader_orders) == 1 else 'read'} it from step "
            f"{step.step_order}; reading step {producer_order} directly spares "
            "the model writing the copy."
        ),
        level="high",
        fix=FlowSuggestionFix(kind="assisted"),
        impact=_impact(
            step,
            tally,
            evidence,
            level="high",
            tokens=[relay.output_tokens for relay in tally.held],
        ),
    )


# --- overlapping_inputs -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Text:
    """One distinct value among a measured call's edges (edges with the
    same hash carry the same text), with what its facts say and the draft
    reads that made its edges."""

    byte_size: int
    repeated_bytes: int
    shingle_count: int
    edge_indexes: tuple[int, ...]
    reads: frozenset[StepRead]

    @property
    def producer_order(self) -> int | None:
        """The one step its reads read, None when they read several."""
        orders = {read.step_order for read in self.reads}
        return next(iter(orders)) if len(orders) == 1 else None


_Side = tuple[tuple[int, str, tuple[str, ...]], ...]
_PairKey = tuple[_Side, _Side]
_Sides = tuple[frozenset[StepRead], frozenset[StepRead]]


@dataclass(frozen=True, slots=True)
class _Overlap:
    shared_bytes: float
    shared_share: float
    tokens: float | None

    @property
    def holds(self) -> bool:
        return (
            self.shared_share >= OVERLAPPING_INPUTS_MIN_SHARE
            and self.shared_bytes >= FORWARDING_MIN_REPEATED_BYTES
        )


@dataclass
class _PairTally:
    sides: _Sides
    tally: _Tally[_Overlap] = field(default_factory=lambda: _Tally[_Overlap]())


def overlapping_inputs(
    draft: DraftReads,
    suggestions: Sequence[FlowSuggestion],
    evidence: RunEvidence,
) -> tuple[list[FlowSuggestion], list[FlowSuggestion]]:
    """``overlapping_inputs``: two inputs of a model step's call share
    ``OVERLAPPING_INPUTS_MIN_SHARE`` or more of the smaller one's bytes,
    and at least ``FORWARDING_MIN_REPEATED_BYTES``, without carrying the
    same value (that is ``identical_inputs``), while the draft still makes
    both reads.

    ``repeated_bytes`` says how much of an input recurs in any other input
    of the call, not in which. It is the overlap of two inputs when they are
    the only ones of the call that share anything (an input that repeats
    nothing shares nothing with any other): measured from the smaller one,
    or from the larger one when the smaller is read twice (then its
    ``repeated_bytes`` is all of it). Two inputs of a call in which more
    share text are not measured in that run.

    Returns ``suggestions`` with each finding about the same two reads as a
    ``duplicate_read`` (two reads of one step) or a
    ``broad_all_previous_steps`` (two of its earlier steps) folded into
    that suggestion's ``params["measured_overlaps"]``, its fingerprint
    unchanged, and the other findings as suggestions of their own.
    ``tokens_per_run`` is the shared bytes times the tokens per byte of
    each completed call that sent both inputs."""

    updated = list(suggestions)
    found: list[FlowSuggestion] = []
    for step in draft.steps:
        if not uses_completion_model(step):
            continue
        reads = draft.model_reads(step)
        pairs: dict[_PairKey, _PairTally] = {}
        for measured in _measured(step, evidence):
            texts = _texts(draft, reads, measured)
            repeating = [text for text in texts if text.repeated_bytes > 0]
            readable = [
                text
                for text in texts
                if text.shingle_count > 0
                and text.reads
                and text.producer_order is not None
            ]
            # A pair of reads counts once per run: when two values came
            # through the same read, the one that overlaps most.
            in_run: dict[_PairKey, tuple[_Sides, _Overlap]] = {}
            for first, second in combinations(readable, 2):
                shared = _shared_bytes(first, second, repeating=len(repeating))
                if shared is None:
                    continue
                key, sides = _pair(first, second)
                smaller = min(first.byte_size, second.byte_size)
                overlap = _Overlap(
                    shared_bytes=shared,
                    shared_share=min(1.0, shared / smaller) if smaller else 0.0,
                    tokens=_overlap_tokens(measured.attempt, first, second, shared),
                )
                seen = in_run.get(key)
                if seen is None or overlap.shared_share > seen[1].shared_share:
                    in_run[key] = (sides, overlap)
            for key, (sides, overlap) in in_run.items():
                pairs.setdefault(key, _PairTally(sides=sides)).tally.count(
                    measured.run.version, overlap if overlap.holds else None
                )
        for _, pair in sorted(pairs.items()):
            if not pair.tally.fires():
                continue
            measurement = _overlap_measurement(draft, step, pair, evidence)
            index = _fold_target(draft, step, pair, updated)
            if index is None:
                found.append(_overlap_suggestion(draft, step, pair, evidence))
                continue
            target = updated[index]
            overlaps = [*target.params.get("measured_overlaps", []), measurement]
            updated[index] = target.model_copy(
                update={"params": {**target.params, "measured_overlaps": overlaps}}
            )
    return updated, found


def _texts(
    draft: DraftReads, reads: Sequence[StepRead], measured: _Measured
) -> list[_Text]:
    """The distinct values among the measured edges of the call, every one
    of them (an edge the draft does not read still decides what the others'
    ``repeated_bytes`` mean); each with the draft reads that made its
    edges."""
    groups: dict[str, list[tuple[ForwardingEdgeFacts, StepRead | None]]] = {}
    for edge_facts in measured.facts.edges:
        index = edge_facts.edge_index
        edge = measured.edge(edge_facts)
        read = (
            draft.edge_read(
                reads, binding_ref=edge.binding_ref, source_step_id=edge.source_step_id
            )
            if edge is not None
            else None
        )
        key = edge.sha256 if edge is not None and edge.sha256 else f"edge:{index}"
        groups.setdefault(key, []).append((edge_facts, read))
    texts: list[_Text] = []
    for group in groups.values():
        first = group[0][0]
        texts.append(
            _Text(
                byte_size=first.byte_size,
                repeated_bytes=first.repeated_bytes,
                shingle_count=first.shingle_count,
                edge_indexes=tuple(edge.edge_index for edge, _ in group),
                reads=frozenset(read for _, read in group if read is not None),
            )
        )
    return texts


def _shared_bytes(first: _Text, second: _Text, *, repeating: int) -> float | None:
    """The bytes two values of a call share, None when the facts cannot
    tell (``overlapping_inputs`` says when)."""
    if first.repeated_bytes == 0 or second.repeated_bytes == 0:
        return 0.0
    if repeating != 2:
        return None
    smaller, larger = sorted((first, second), key=lambda text: text.byte_size)
    if len(smaller.edge_indexes) == 1:
        return float(smaller.repeated_bytes)
    if len(larger.edge_indexes) == 1:
        return float(min(larger.repeated_bytes, smaller.byte_size))
    return None


def _side_key(reads: frozenset[StepRead]) -> _Side:
    return tuple(sorted((read.step_order, read.site, read.selector) for read in reads))


def _pair(first: _Text, second: _Text) -> tuple[_PairKey, _Sides]:
    """The pair of reads two values came through, in an order that does not
    depend on the run."""
    ordered = sorted((first.reads, second.reads), key=_side_key)
    return (_side_key(ordered[0]), _side_key(ordered[1])), (ordered[0], ordered[1])


def _overlap_tokens(
    attempt: EvidenceAttempt, first: _Text, second: _Text, shared: float
) -> float | None:
    total: float | None = None
    for call in attempt.calls:
        if not (
            set(call.edge_indexes) & set(first.edge_indexes)
            and set(call.edge_indexes) & set(second.edge_indexes)
        ):
            continue
        per_byte = attempt.tokens_per_byte(call)
        if per_byte is not None:
            total = (total or 0.0) + shared * per_byte
    return total


def _side_payload(draft: DraftReads, reads: frozenset[StepRead]) -> dict[str, object]:
    ordered = sorted(reads, key=lambda read: (read.step_order, read.site))
    producer = draft.step_at(ordered[0].step_order)
    return {
        "step_order": ordered[0].step_order,
        "step_id": str(producer.id) if producer is not None else None,
        "sites": [read.site for read in ordered],
    }


def _overlap_params(draft: DraftReads, pair: _PairTally) -> dict[str, Any]:
    held = pair.tally.held
    return {
        "inputs": [_side_payload(draft, side) for side in pair.sides],
        "shared_bytes": round(_average(item.shared_bytes for item in held)),
        "shared_share": _average(item.shared_share for item in held),
        "run_count": pair.tally.run_count,
        "held_runs": len(held),
    }


def _overlap_measurement(
    draft: DraftReads, step: SuggestionStep, pair: _PairTally, evidence: RunEvidence
) -> dict[str, Any]:
    """An overlap as it is folded into another suggestion's params: its
    params with the impact a suggestion of its own would have."""
    impact = _impact(
        step,
        pair.tally,
        evidence,
        level="medium",
        tokens=[item.tokens for item in pair.tally.held],
    )
    return {
        **_overlap_params(draft, pair),
        "tokens_per_run": impact.tokens_per_run,
        "version": impact.version,
        "step_changed_since": impact.step_changed_since,
    }


def _fold_target(
    draft: DraftReads,
    step: SuggestionStep,
    pair: _PairTally,
    suggestions: Sequence[FlowSuggestion],
) -> int | None:
    """The index of the static suggestion about the same two reads: a
    ``duplicate_read`` on the step whose reads hold both (two reads of one
    step), or a ``broad_all_previous_steps`` on the step when both are
    earlier steps it takes as its input."""
    reads = pair.sides[0] | pair.sides[1]
    producers = {draft.producer_key(read.step_order) for read in reads}
    sites = {read.site for read in reads}
    for index, suggestion in enumerate(suggestions):
        if suggestion.steps[:1] != (step.id,):
            continue
        if suggestion.code is FlowSuggestionCode.DUPLICATE_READ:
            named = {str(read["site"]) for read in suggestion.params.get("reads", [])}
            if producers == {str(suggestion.params.get("producer_step_id"))} and (
                sites <= named
            ):
                return index
        if suggestion.code is FlowSuggestionCode.BROAD_ALL_PREVIOUS_STEPS and sites == {
            INPUT_SOURCE_READ_SITE
        }:
            return index
    return None


def _overlap_suggestion(
    draft: DraftReads, step: SuggestionStep, pair: _PairTally, evidence: RunEvidence
) -> FlowSuggestion:
    params = _overlap_params(draft, pair)
    first, second = (
        sorted(side, key=lambda read: (read.step_order, read.site))[0]
        for side in pair.sides
    )
    producer_ids = list(
        dict.fromkeys(
            producer.id
            for read in (first, second)
            if (producer := draft.step_at(read.step_order)) is not None
        )
    )
    described = " and ".join(
        f"step {read.step_order} {describe_read(read, step)}"
        for read in (first, second)
    )
    return make_suggestion(
        FlowSuggestionCode.OVERLAPPING_INPUTS,
        steps=(step.id, *producer_ids),
        premise={
            "inputs": sorted(
                (
                    {
                        "producer": draft.producer_key(next(iter(side)).step_order),
                        "reads": read_premises(list(side)),
                    }
                    for side in pair.sides
                ),
                key=canonical_json_hash,
            )
        },
        params=params,
        message=(
            f"In {params['held_runs']} of the last {params['run_count']} runs, "
            f"step {step.step_order} received {described}, which shared "
            f"{_percent(params['shared_share'])} % of the shorter one's text, so "
            "its model read that part twice."
        ),
        level="medium",
        fix=FlowSuggestionFix(kind="assisted"),
        impact=_impact(
            step,
            pair.tally,
            evidence,
            level="medium",
            tokens=[item.tokens for item in pair.tally.held],
        ),
    )


# --- deterministic_candidate ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Candidate:
    verbatim_ratio: float
    # Bytes are whole: rounding keeps a share's float error off the limit.
    own_bytes: int
    input_share: float
    billed_tokens: float | None


def deterministic_candidates(
    draft: DraftReads, evidence: RunEvidence
) -> list[FlowSuggestion]:
    """``deterministic_candidate``: a text step whose model's output is
    ``DETERMINISTIC_MIN_VERBATIM_RATIO`` or more found verbatim in its
    inputs, with at most ``DETERMINISTIC_MAX_OWN_BYTES`` of its own, and
    whose verbatim part is ``DETERMINISTIC_MIN_INPUT_SHARE`` or more of the
    inputs it copies from: a compose_text step puts that together without
    a model. Only for a ``pass_through`` step with text output (what
    compose_text writes), and only over calls whose every input was
    measured (an input the worker did not hold, such as a file, may be what
    the model's own part came from). ``tokens_per_run`` is what the step
    was billed: a compose_text step calls no model."""

    suggestions: list[FlowSuggestion] = []
    for step in draft.steps:
        if (
            not uses_completion_model(step)
            or FlowOutputMode(step.output_mode) is not FlowOutputMode.PASS_THROUGH
            or FlowOutputType(step.output_type) is not FlowOutputType.TEXT
        ):
            continue
        tally = _Tally[_Candidate]()
        for measured in _measured(step, evidence):
            facts = measured.facts
            ratio = facts.output_verbatim_ratio
            if (
                not measured.measures_output
                or ratio is None
                or facts.unmeasured_edge_indexes
            ):
                continue
            candidate = _candidate(measured, ratio)
            holds = (
                candidate.verbatim_ratio >= DETERMINISTIC_MIN_VERBATIM_RATIO
                and candidate.own_bytes <= DETERMINISTIC_MAX_OWN_BYTES
                and candidate.input_share >= DETERMINISTIC_MIN_INPUT_SHARE
            )
            tally.count(measured.run.version, candidate if holds else None)
        if tally.fires():
            suggestions.append(_candidate_suggestion(step, tally, evidence))
    return suggestions


def _candidate(measured: _Measured, ratio: float) -> _Candidate:
    facts = measured.facts
    verbatim_bytes = facts.output_byte_size * ratio
    sources: dict[str, int] = {}
    for edge_facts, edge in measured.edges():
        if edge_facts.copied_to_output_ratio:
            sources.setdefault(
                edge.sha256 or f"edge:{edge_facts.edge_index}", edge_facts.byte_size
            )
    source_bytes = sum(sources.values())
    billed = measured.attempt.billed_tokens()
    return _Candidate(
        verbatim_ratio=ratio,
        own_bytes=round(facts.output_byte_size * (1 - ratio)),
        input_share=min(1.0, verbatim_bytes / source_bytes) if source_bytes else 0.0,
        billed_tokens=float(billed) if billed is not None else None,
    )


def _candidate_suggestion(
    step: SuggestionStep, tally: _Tally[_Candidate], evidence: RunEvidence
) -> FlowSuggestion:
    ratio = _average(item.verbatim_ratio for item in tally.held)
    own_bytes = round(_average(item.own_bytes for item in tally.held))
    return make_suggestion(
        FlowSuggestionCode.DETERMINISTIC_CANDIDATE,
        steps=(step.id,),
        premise={},
        params={
            "output_verbatim_ratio": ratio,
            "own_bytes": own_bytes,
            "input_share": _average(item.input_share for item in tally.held),
            "run_count": tally.run_count,
            "held_runs": len(tally.held),
        },
        message=(
            f"In {len(tally.held)} of the last {tally.run_count} runs, "
            f"{_percent(ratio)} % of step {step.step_order}'s output was its "
            f"input copied word for word, with about {own_bytes} bytes of its "
            "own; a compose_text step puts that together without a model."
        ),
        level="medium",
        fix=FlowSuggestionFix(kind="assisted"),
        impact=_impact(
            step,
            tally,
            evidence,
            level="medium",
            tokens=[item.billed_tokens for item in tally.held],
        ),
    )


__all__ = [
    "DETERMINISTIC_MAX_OWN_BYTES",
    "DETERMINISTIC_MIN_INPUT_SHARE",
    "DETERMINISTIC_MIN_VERBATIM_RATIO",
    "FORWARDING_MIN_REPEATED_BYTES",
    "FORWARDING_MIN_RUN_SHARE",
    "MODEL_RELAY_MIN_COPIED_SHARE",
    "MODEL_RELAY_MIN_INPUT_SHARE",
    "OVERLAPPING_INPUTS_MIN_SHARE",
    "deterministic_candidates",
    "forwarding_suggestions",
    "model_relays",
    "overlapping_inputs",
]
