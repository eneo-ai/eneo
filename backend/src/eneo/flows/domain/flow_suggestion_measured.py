"""Suggestions measured from recent runs: the cost of what the definition
proves, and the findings only runs can show.

Pure functions over the draft's reads (``DraftReads``) and the content-free
``RunEvidence``. Measured facts map to draft steps by step id, and to a
read by where it is written: an edge whose ``binding_ref`` is the read's
site and whose producer is the read's producer. A measurement attaches only
to a suggestion the draft still proves, and only through edges the draft
still reads, so a number never outlives its premise. A step that differs
from the step in the measured version says so (``step_changed_since``).

- Impact on the static rules: ``duplicate_read`` measures its redundant
  reads; ``per_item_prompt_read`` the copies of the prompt read beyond the
  first item's; ``unread_result`` everything the step was billed. The other
  static rules name no part whose cost the runs measure, and keep their
  impact from the definition.
- ``identical_inputs``: two edges of one attempt carry the same value
  although the definition reads different producers.
- ``context_headroom``: the step's model came close to its input limit, or
  the step failed the inline cap.
- ``format_fallback``: the step often needed a second call because its
  model did not take the structured format.
- The forwarding facts' findings (``flow_suggestion_forwarding``):
  ``model_relay``, ``overlapping_inputs`` (folded into the static
  suggestion about the same two reads where there is one) and
  ``deterministic_candidate``.
- ``oversized_reasoning`` (``flow_suggestion_model_fit``): high reasoning
  effort on a step whose calls were a small structured extraction.

Tokens per run is an edge's ``byte_size`` times the tokens per byte of each
call that sent it (``num_tokens_input`` over the bytes of the call's edges),
averaged over the runs that have it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from eneo.flows.domain.flow_suggestion_evidence import (
    INLINE_CAP_FAILURE_CODE,
    RESPONSE_FORMAT_FALLBACK_REASON,
    EvidenceAttempt,
    EvidenceEdge,
    MeasuredValue,
    RunEvidence,
    average_over_runs,
)
from eneo.flows.domain.flow_suggestion_forwarding import forwarding_suggestions
from eneo.flows.domain.flow_suggestion_model import (
    DraftReads,
    FlowSuggestion,
    FlowSuggestionCode,
    FlowSuggestionFix,
    FlowSuggestionImpact,
    FlowSuggestionLevel,
    SuggestionStep,
    describe_read,
    make_suggestion,
    read_site_kind,
    uses_completion_model,
)
from eneo.flows.domain.flow_suggestion_model_fit import oversized_reasoning
from eneo.flows.step_lineage import StepRead

# `context_headroom`: the largest measured input reached this share of the
# completion model's input token limit.
CONTEXT_HEADROOM_SHARE = 0.85
# `format_fallback`: at least this share of the runs in which the step
# called its model needed a fallback call.
FORMAT_FALLBACK_MIN_SHARE = 0.5
# `identical_inputs`: a value shorter than this is not reported as sent
# twice (an empty or one-word result is identical by chance, and costs
# nothing).
IDENTICAL_INPUTS_MIN_BYTES = 256

FAILED_STEP_STATUS = "failed"

_DUPLICATE_CODES = frozenset(
    {
        FlowSuggestionCode.DUPLICATE_READ,
        FlowSuggestionCode.IDENTICAL_INPUTS,
        FlowSuggestionCode.OVERLAPPING_INPUTS,
    }
)


def measure_suggestions(
    draft: DraftReads,
    suggestions: Sequence[FlowSuggestion],
    evidence: RunEvidence,
) -> list[FlowSuggestion]:
    """``suggestions`` with their impact measured where the runs measure it,
    followed by the measured rules' findings."""
    measured = [_with_measured_impact(item, evidence) for item in suggestions]
    measured.extend(identical_inputs(draft, evidence))
    measured = forwarding_suggestions(draft, measured, evidence)
    measured.extend(context_headroom(draft, evidence, related=measured))
    measured.extend(format_fallback(draft, evidence))
    measured.extend(oversized_reasoning(draft, evidence))
    return measured


# --- Impact on the static rules ---------------------------------------------

AttemptCost = Callable[[EvidenceAttempt], float | None]


def _with_measured_impact(
    suggestion: FlowSuggestion, evidence: RunEvidence
) -> FlowSuggestion:
    cost = _cost_of(suggestion)
    if cost is None or not suggestion.steps:
        return suggestion
    step_id = suggestion.steps[0]
    values: list[MeasuredValue] = []
    for run in evidence.runs:
        attempt = run.attempt(step_id)
        if attempt is None:
            continue
        value = cost(attempt)
        if value is not None:
            values.append((value, run.version))
    measurement = average_over_runs(values)
    if measurement is None:
        return suggestion
    return suggestion.model_copy(
        update={
            "impact": FlowSuggestionImpact(
                basis="runs",
                level=suggestion.impact.level,
                tokens_per_run=round(measurement.average),
                run_count=measurement.run_count,
                version=measurement.version,
                step_changed_since=evidence.step_changed_since(
                    step_id, measurement.version
                ),
            )
        }
    )


def _cost_of(suggestion: FlowSuggestion) -> AttemptCost | None:
    """How one attempt measures the suggestion's cost, None for a code the
    runs do not measure."""
    params = suggestion.params
    if suggestion.code is FlowSuggestionCode.DUPLICATE_READ:
        reads = params["reads"]
        sites = [str(reads[index]["site"]) for index in params["redundant_reads"]]
        producer = _uuid_or_none(params.get("producer_step_id"))
        return lambda attempt: _reads_cost(attempt, sites, producer)
    if suggestion.code is FlowSuggestionCode.PER_ITEM_PROMPT_READ:
        sites = [str(read["site"]) for read in params["reads"]]
        producer = _uuid_or_none(params.get("producer_step_id"))
        return lambda attempt: _reads_cost(
            attempt, sites, producer, beyond_first_call=True
        )
    if suggestion.code is FlowSuggestionCode.UNREAD_RESULT:
        return _billed

    return None


def _billed(attempt: EvidenceAttempt) -> float | None:
    billed = attempt.billed_tokens()
    return float(billed) if billed is not None else None


def _reads_cost(
    attempt: EvidenceAttempt,
    sites: Sequence[str],
    producer: UUID | None,
    *,
    beyond_first_call: bool = False,
) -> float | None:
    """What the edges of the reads at ``sites`` of ``producer`` cost in the
    attempt; with ``beyond_first_call``, only the copies after the first
    call's. None when the attempt has no measured edge for one of them."""
    total = 0.0
    for site in sites:
        indexes = edges_of_read(attempt.edges, site=site, producer=producer)
        if not indexes:
            return None
        for index in indexes:
            cost = attempt.edge_tokens(index)
            if cost is None:
                return None
            tokens, calls = cost
            total += tokens * (1 - 1 / calls) if beyond_first_call else tokens
    return total


def edges_of_read(
    edges: Sequence[EvidenceEdge], *, site: str, producer: UUID | None
) -> list[int]:
    """The indexes of the edges a read made: written at ``site`` and read
    from ``producer`` (the run input when None)."""
    return [
        index
        for index, edge in enumerate(edges)
        if edge.binding_ref == site
        and (edge.source_step_id == producer if producer else edge.run_input)
    ]


def _uuid_or_none(value: object) -> UUID | None:
    return UUID(str(value)) if value else None


# --- identical_inputs ---------------------------------------------------------


@dataclass
class _Sighting:
    """One pair of edges carrying the same value, over the runs it was seen."""

    first: tuple[str, UUID]
    second: tuple[str, UUID]
    byte_size: int
    runs: list[tuple[float | None, int]] = field(
        default_factory=lambda: list[tuple[float | None, int]]()
    )


def identical_inputs(draft: DraftReads, evidence: RunEvidence) -> list[FlowSuggestion]:
    """``identical_inputs``: in a run, two edges of a model step's attempt
    carry the same value (equal ``sha256``, at least
    ``IDENTICAL_INPUTS_MIN_BYTES``) although they are read from two
    different earlier steps, for example a step and a copy of it. Reported
    while the draft still makes both reads; ``tokens_per_run`` is the cost
    of the second edge."""

    suggestions: list[FlowSuggestion] = []
    for step in draft.steps:
        if not uses_completion_model(step):
            continue
        reads = draft.model_reads(step)
        sightings: dict[tuple[tuple[str, UUID], tuple[str, UUID]], _Sighting] = {}
        step_runs = 0
        for run in evidence.runs:
            attempt = run.attempt(step.id)
            if attempt is None or not attempt.edges:
                continue
            step_runs += 1
            for sighting_key, (index, size) in _identical_pairs(
                draft, reads, attempt
            ).items():
                cost = attempt.edge_tokens(index)
                sighting = sightings.setdefault(
                    sighting_key,
                    _Sighting(
                        first=sighting_key[0], second=sighting_key[1], byte_size=size
                    ),
                )
                sighting.runs.append(
                    (cost[0] if cost is not None else None, run.version)
                )
        for sighting in sightings.values():
            suggestion = _identical_suggestion(
                draft, step, reads, sighting, evidence, step_runs=step_runs
            )
            if suggestion is not None:
                suggestions.append(suggestion)
    return suggestions


def _identical_pairs(
    draft: DraftReads, reads: Sequence[StepRead], attempt: EvidenceAttempt
) -> dict[tuple[tuple[str, UUID], tuple[str, UUID]], tuple[int, int]]:
    """Each pair of edges of the attempt with the same value from different
    producers, both read by the draft, as (site, producer) of the first and
    the second, with the second's index and the value's size."""
    first_by_hash: dict[str, list[int]] = {}
    for index, edge in enumerate(attempt.edges):
        if (
            edge.sha256 is None
            or edge.source_step_id is None
            or (edge.byte_size or 0) < IDENTICAL_INPUTS_MIN_BYTES
            or _draft_read_of(draft, reads, edge) is None
        ):
            continue
        first_by_hash.setdefault(edge.sha256, []).append(index)
    pairs: dict[tuple[tuple[str, UUID], tuple[str, UUID]], tuple[int, int]] = {}
    for indexes in first_by_hash.values():
        first = attempt.edges[indexes[0]]
        assert first.source_step_id is not None
        for index in indexes[1:]:
            edge = attempt.edges[index]
            assert edge.source_step_id is not None
            if edge.source_step_id == first.source_step_id:
                continue
            key = (
                (first.binding_ref, first.source_step_id),
                (edge.binding_ref, edge.source_step_id),
            )
            pairs.setdefault(key, (index, edge.byte_size or 0))
    return pairs


def _draft_read_of(
    draft: DraftReads, reads: Sequence[StepRead], edge: EvidenceEdge
) -> StepRead | None:
    """The draft's model read that made ``edge``: the same site, read from
    the same step."""
    return draft.edge_read(
        reads, binding_ref=edge.binding_ref, source_step_id=edge.source_step_id
    )


def _identical_suggestion(
    draft: DraftReads,
    step: SuggestionStep,
    reads: Sequence[StepRead],
    sighting: _Sighting,
    evidence: RunEvidence,
    *,
    step_runs: int,
) -> FlowSuggestion | None:
    (first_site, first_id), (second_site, second_id) = sighting.first, sighting.second
    first_read = next(
        (r for r in reads if r.site == first_site and _is(draft, r, first_id)), None
    )
    second_read = next(
        (r for r in reads if r.site == second_site and _is(draft, r, second_id)), None
    )
    if first_read is None or second_read is None:
        return None
    pair = sorted(
        ((first_read, first_id), (second_read, second_id)),
        key=lambda item: item[0].step_order,
    )
    measured = [tokens for tokens, _ in sighting.runs if tokens is not None]
    version = max(version for _, version in sighting.runs)
    observed = len(sighting.runs)
    described = " and ".join(
        f"step {read.step_order} {describe_read(read, step)}" for read, _ in pair
    )
    return make_suggestion(
        FlowSuggestionCode.IDENTICAL_INPUTS,
        steps=(step.id, *(producer for _, producer in pair)),
        premise={
            "reads": sorted(
                [str(producer), read_site_kind(read.site)] for read, producer in pair
            )
        },
        params={
            "producer_step_ids": [str(producer) for _, producer in pair],
            "producer_step_orders": [read.step_order for read, _ in pair],
            "sites": [read.site for read, _ in pair],
            "byte_size": sighting.byte_size,
            "observed_runs": observed,
            "step_runs": step_runs,
        },
        message=(
            f"In {observed} of the last {step_runs} runs, step {step.step_order} "
            f"received the same text from {described}, so its model read it "
            "twice."
        ),
        level="high",
        fix=FlowSuggestionFix(kind="assisted"),
        impact=FlowSuggestionImpact(
            basis="runs",
            level="high",
            tokens_per_run=round(sum(measured) / len(measured)) if measured else None,
            run_count=observed,
            version=version,
            step_changed_since=evidence.step_changed_since(step.id, version),
        ),
    )


def _is(draft: DraftReads, read: StepRead, producer: UUID) -> bool:
    return draft.producer_key(read.step_order) == str(producer)


# --- context_headroom ---------------------------------------------------------


def context_headroom(
    draft: DraftReads,
    evidence: RunEvidence,
    *,
    related: Sequence[FlowSuggestion] = (),
) -> list[FlowSuggestion]:
    """``context_headroom``: a model step whose largest measured input
    reached ``CONTEXT_HEADROOM_SHARE`` of its completion model's input token
    limit, or that failed the inline cap, in the counted runs. Only when the
    catalogue knows the limit of the draft step's model, and only over runs
    whose version gave the step the model and output type it has now.
    ``params`` link the duplicate suggestions on the step (``related``) and
    the share of the peak they account for."""

    suggestions: list[FlowSuggestion] = []
    for step in draft.steps:
        if not uses_completion_model(step):
            continue
        facts = evidence.draft_steps.get(step.id)
        model_id = facts.completion_model_id if facts is not None else None
        limit = evidence.model_input_limits.get(model_id) if model_id else None
        if limit is None or limit <= 0:
            continue
        peak: int | None = None
        failures = 0
        versions: list[int] = []
        for run in evidence.runs:
            attempt = run.attempt(step.id)
            if attempt is None or not evidence.same_model_and_output(
                step.id, run.version
            ):
                continue
            versions.append(run.version)
            attempt_peak = attempt.peak_input_tokens()
            if attempt_peak is not None:
                peak = attempt_peak if peak is None else max(peak, attempt_peak)
            if (
                attempt.status == FAILED_STEP_STATUS
                and attempt.error_code == INLINE_CAP_FAILURE_CODE
            ):
                failures += 1
        near_limit = peak is not None and peak >= CONTEXT_HEADROOM_SHARE * limit
        if not versions or not (near_limit or failures):
            continue
        duplicates = [
            item
            for item in related
            if item.code in _DUPLICATE_CODES and item.steps[:1] == (step.id,)
        ]
        duplicated = sum(
            item.impact.tokens_per_run or 0
            for item in duplicates
            if item.impact.basis == "runs"
        )
        version = max(versions)
        level: FlowSuggestionLevel = "high"
        suggestions.append(
            make_suggestion(
                FlowSuggestionCode.CONTEXT_HEADROOM,
                steps=(step.id,),
                premise={},
                params={
                    "peak_input_tokens": peak,
                    "token_limit": limit,
                    "limit_share": round(peak / limit, 2) if peak is not None else None,
                    "inline_cap_failures": failures,
                    "duplicated_tokens_per_run": duplicated or None,
                    "duplicated_share": (
                        round(duplicated / peak, 2) if peak and duplicated else None
                    ),
                    "related_fingerprints": [item.fingerprint for item in duplicates],
                    "step_runs": len(versions),
                },
                message=_headroom_message(
                    step, peak, limit, failures, runs=len(versions)
                ),
                level=level,
                fix=FlowSuggestionFix(kind="advice"),
                impact=FlowSuggestionImpact(
                    basis="runs",
                    level=level,
                    run_count=len(versions),
                    version=version,
                    step_changed_since=evidence.step_changed_since(step.id, version),
                ),
            )
        )
    return suggestions


def _headroom_message(
    step: SuggestionStep, peak: int | None, limit: int, failures: int, *, runs: int
) -> str:
    parts: list[str] = []
    if peak is not None and peak >= CONTEXT_HEADROOM_SHARE * limit:
        parts.append(
            f"step {step.step_order}'s model received up to {peak} input "
            f"tokens, {round(100 * peak / limit)} % of its limit of {limit}"
        )
    if failures:
        parts.append(
            f"step {step.step_order} failed {failures} time"
            f"{'s' if failures > 1 else ''} because its input was over the "
            "inline limit"
        )
    return (
        f"In the last {runs} runs, " + ", and ".join(parts) + "; sending less to "
        "it leaves room for longer material."
    )


# --- format_fallback ------------------------------------------------------------


def format_fallback(draft: DraftReads, evidence: RunEvidence) -> list[FlowSuggestion]:
    """``format_fallback``: a model step that needed a
    ``response_format_fallback`` call in ``FORMAT_FALLBACK_MIN_SHARE`` or
    more of the counted runs in which it called its model, over runs whose
    version gave it the model and output type it has now: each such run
    pays two calls."""

    suggestions: list[FlowSuggestion] = []
    for step in draft.steps:
        if not uses_completion_model(step):
            continue
        versions: list[int] = []
        fallbacks = 0
        for run in evidence.runs:
            attempt = run.attempt(step.id)
            if (
                attempt is None
                or not attempt.calls
                or not evidence.same_model_and_output(step.id, run.version)
            ):
                continue
            versions.append(run.version)
            if any(
                call.call_reason == RESPONSE_FORMAT_FALLBACK_REASON
                for call in attempt.calls
            ):
                fallbacks += 1
        if not fallbacks or fallbacks < FORMAT_FALLBACK_MIN_SHARE * len(versions):
            continue
        version = max(versions)
        suggestions.append(
            make_suggestion(
                FlowSuggestionCode.FORMAT_FALLBACK,
                steps=(step.id,),
                premise={},
                params={"fallback_runs": fallbacks, "step_runs": len(versions)},
                message=(
                    f"In {fallbacks} of the last {len(versions)} runs, step "
                    f"{step.step_order} needed a second call because its model "
                    "did not accept the structured output format, so those runs "
                    "paid for two calls."
                ),
                level="medium",
                fix=FlowSuggestionFix(kind="advice"),
                impact=FlowSuggestionImpact(
                    basis="runs",
                    level="medium",
                    run_count=len(versions),
                    version=version,
                    step_changed_since=evidence.step_changed_since(step.id, version),
                ),
            )
        )
    return suggestions


__all__ = [
    "CONTEXT_HEADROOM_SHARE",
    "FORMAT_FALLBACK_MIN_SHARE",
    "IDENTICAL_INPUTS_MIN_BYTES",
    "context_headroom",
    "edges_of_read",
    "format_fallback",
    "identical_inputs",
    "measure_suggestions",
]
