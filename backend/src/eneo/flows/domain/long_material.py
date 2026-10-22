"""Long material: step input larger than the step's model can read at once.

A completion step opts in with ``input_config.long_material = {"mode":
"digest"}``. When its packaged input does not fit the model's input capacity,
the runtime reads the input in segments with the bounded map-reduce core
(``eneo.completion_models.application.map_reduce``): each segment gets notes,
the notes are merged until they fit one request, and the step's own call
answers over them under its own output contract. Input that fits is never
digested.

This module holds the decisions that need no I/O: which sources the input was
assembled from, the budgets the measured request sizes allow, how many calls a
plan needs at least, when the digest stops so the final call keeps its share
of the step's time, what the coverage record says, and whether partial
coverage fails the step or goes to its review.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from eneo.completion_models.application.map_reduce import (
    DigestBudgets,
    DigestItem,
    DigestPlan,
    DigestResult,
    map_prompt,
)
from eneo.flows.domain.provider_call import DigestCallInput
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import sum_complete_token_counts
from eneo.main.exceptions import TypedIOValidationException

LONG_MATERIAL_KEY: Final = "long_material"


class LongMaterialMode(StrEnum):
    DIGEST = "digest"


LONG_MATERIAL_MODE_DESCRIPTION: Final = (
    "`digest`: when the step's input exceeds its model's input capacity, read "
    "it in segments with the step's own model and assistant, merge the notes, "
    "and write the answer over them under the step's output contract. The "
    "step result records the coverage in `input_payload_json.long_material`. "
    "Partial coverage fails the step with `flow_long_material_partial_coverage`, "
    "or, on a step with a review policy, completes with a warning for the "
    "reviewer. Input that fits is sent unchanged. Needs a completion step "
    "(`pass_through` or `http_post`) without `text_processing`, `item_map` or "
    "per-source runtime input, and the organization's mapped provider-call "
    "ceiling bounds the calls."
)


class LongMaterialConfig(BaseModel):
    """How a step reads input that does not fit its model in one request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: LongMaterialMode = Field(description=LONG_MATERIAL_MODE_DESCRIPTION)


def long_material_config(
    input_config: dict[str, Any] | None,
) -> LongMaterialConfig | None:
    value = (input_config or {}).get(LONG_MATERIAL_KEY)
    return LongMaterialConfig.model_validate(value) if value is not None else None


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
WHOLE_INPUT_TITLE: Final = "Step input"
REMAINDER_TITLE: Final = "Other step input"
_TITLE_MAX_CHARS: Final = 120


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    """A source the step input was assembled from, as its text appears there."""

    title: str
    text: str
    reference: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class DigestSource:
    """One source of the step input, as a span of the exact input text."""

    index: int
    title: str
    text: str
    start_char: int
    reference: dict[str, JsonValue]

    @property
    def key(self) -> str:
        return source_key(self.index)

    @property
    def end_char(self) -> int:
        return self.start_char + len(self.text)

    def item(self) -> DigestItem:
        return DigestItem(key=self.key, title=self.title, text=self.text)


def source_key(index: int) -> str:
    return f"S{index}"


def text_reference(kind: str, text: str) -> dict[str, JsonValue]:
    content = text.encode("utf-8")
    return {
        "kind": kind,
        "sha256": sha256(content).hexdigest(),
        "byte_size": len(content),
    }


def _clean_title(title: str, index: int) -> str:
    # Keys are cited in square brackets; a bracket in a title would read as one.
    cleaned = " ".join(title.replace("[", "(").replace("]", ")").split())
    return cleaned[:_TITLE_MAX_CHARS] or f"Source {index}"


def partition_digest_sources(
    question: str, candidates: Sequence[SourceCandidate]
) -> tuple[DigestSource, ...]:
    """Split the step input into the sources it was assembled from.

    Candidates are taken in the order their text first appears in the input.
    The text before a candidate (a source header, framing) belongs to it, and
    non-blank text after the last one is a source of its own, so the sources
    concatenate to exactly the input. When a candidate is not found verbatim
    (a template rewrote it), the whole input is one source.
    """
    whole = (
        DigestSource(
            index=1,
            title=WHOLE_INPUT_TITLE,
            text=question,
            start_char=0,
            reference=text_reference("step_input", question),
        ),
    )
    readable = [candidate for candidate in candidates if candidate.text.strip()]
    positions = [question.find(candidate.text) for candidate in readable]
    if any(position < 0 for position in positions):
        return whole
    ordered = [
        candidate
        for _, _, candidate in sorted(
            zip(positions, range(len(readable)), readable, strict=True)
        )
    ]
    spans: list[tuple[str, int, int, dict[str, JsonValue]]] = []
    cursor = 0
    for candidate in ordered:
        found = question.find(candidate.text, cursor)
        if found < 0:
            return whole
        end = found + len(candidate.text)
        spans.append((candidate.title, cursor, end, candidate.reference))
        cursor = end
    if not spans:
        return whole
    rest = question[cursor:]
    if rest.strip():
        spans.append(
            (
                REMAINDER_TITLE,
                cursor,
                len(question),
                text_reference("step_input", rest),
            )
        )
    else:
        title, start, _, reference = spans[-1]
        spans[-1] = (title, start, len(question), reference)
    return tuple(
        DigestSource(
            index=index,
            title=_clean_title(title, index),
            text=question[start:end],
            start_char=start,
            reference=reference,
        )
        for index, (title, start, end, reference) in enumerate(spans, start=1)
    )


# --------------------------------------------------------------------------- #
# Instruction and the final call's input
# --------------------------------------------------------------------------- #
DEFAULT_INSTRUCTION: Final = "Keep every fact the material states."
NOTES_PREAMBLE: Final = (
    "The step input was too long to read in one request. It was read in parts, "
    "and the notes below were taken from it for these instructions. Notes cite "
    "their source by its key in square brackets."
)
NOTHING_RELEVANT: Final = (
    "The step input was too long to read in one request, so it was read in "
    "parts. All of it was read, and no part of it was relevant to these "
    "instructions."
)


def digest_instruction(prompt: str, format_instructions: Sequence[str]) -> str:
    """The step's instructions for the notes, without its output format.

    The notes are free text; the output format (JSON rules, the schema) only
    applies to the step's own final call.
    """
    suffix = "\n".join(format_instructions)
    instruction = prompt
    if suffix:
        if instruction == suffix:
            instruction = ""
        else:
            instruction = instruction.removesuffix(f"\n\n{suffix}")
    return instruction.strip() or DEFAULT_INSTRUCTION


def final_question_frame(sources: Sequence[DigestSource]) -> str:
    """The text the final call's input carries before the notes."""
    listing = "\n".join(f"[{source.key}] {source.title}" for source in sources)
    return f"{NOTES_PREAMBLE}\n\nSources:\n{listing}\n\n"


def final_question(*, sources: Sequence[DigestSource], notes: str) -> str:
    """What the step's own call reads instead of the input: the source list
    and the merged notes, or the statement that nothing was relevant."""
    if not notes.strip():
        return NOTHING_RELEVANT
    return f"{final_question_frame(sources)}{notes.strip()}"


# --------------------------------------------------------------------------- #
# Budgets and admission
# --------------------------------------------------------------------------- #
MIN_SEGMENT_TOKENS: Final = 200
MIN_REDUCE_INPUT_TOKENS: Final = 400
MAX_SEGMENT_TOKENS: Final = 12_000
MAX_REDUCE_INPUT_TOKENS: Final = 60_000
# The planner counts text alone; the provider counts messages and framing.
COUNT_MARGIN: Final = 0.9
# Word caps and output reserves of every stage, before the rooms are known.
STAGE_DEFAULTS: Final = DigestBudgets(segment_tokens=1, reduce_input_tokens=1)


def digest_budgets(
    *, map_room: int, reduce_room: int, final_room: int
) -> DigestBudgets | None:
    """Budgets from the measured room of a map, a merge and the final call.

    A room is the model's input allowance with the stage's output reserve,
    minus the measured overhead of that stage's request (prompt, assistant
    attachments, framing). Segments take a quarter of the map room, as the
    digest tools size them, so a segment's notes keep its detail. Merged
    notes must fit both a merge and the step's final call. None when the
    model cannot hold a useful segment or a useful merge.
    """
    usable_map = int(map_room * COUNT_MARGIN)
    usable_reduce = int(min(reduce_room, final_room) * COUNT_MARGIN)
    segment_tokens = min(MAX_SEGMENT_TOKENS, max(map_room // 4, MIN_SEGMENT_TOKENS))
    if segment_tokens > usable_map or usable_reduce < MIN_REDUCE_INPUT_TOKENS:
        return None
    return replace(
        STAGE_DEFAULTS,
        segment_tokens=segment_tokens,
        reduce_input_tokens=min(MAX_REDUCE_INPUT_TOKENS, usable_reduce),
    )


def without_direct_path(plan: DigestPlan) -> DigestPlan:
    """The plan with its single-call path closed.

    The step's own request already did not fit, so the material is read in
    segments even when the merge budget alone could hold it.
    """
    return replace(plan, direct_fits=False)


def minimum_digest_calls(plan: DigestPlan, *, fallback_call_possible: bool) -> int:
    """The provider calls the plan needs before any merge level: a note per
    segment, a merge per source with several segments, the step's own final
    call and, when the step may retry without native JSON, that retry. Fewer
    are sent only when segments hold nothing relevant."""
    merges = sum(1 for planned in plan.items if len(planned.segments) > 1)
    return plan.total_segments + merges + 1 + int(fallback_call_possible)


def minimum_digest_input_tokens(plan: DigestPlan, *, map_overhead_tokens: int) -> int:
    """The fewest input tokens the plan sends: every segment once, each with
    the map request's overhead."""
    return plan.total_tokens + plan.total_segments * map_overhead_tokens


def admit_digest(
    *,
    step_order: int,
    needed_calls: int,
    needed_input_tokens: int,
    call_ceiling: int | None,
    token_ceiling: int | None,
) -> None:
    """Refuse a digest the organization's mapped-execution policy cannot hold,
    with the codes a mapped step gets for the same limits."""
    if call_ceiling is None:
        raise TypedIOValidationException(
            f"Step {step_order}: the input exceeds the model's input capacity, "
            "and reading it in parts needs mapped provider calls, which the "
            "organization has turned off.",
            code=FlowApiErrorCode.MAPPED_PROVIDER_CALL_LIMIT_EXCEEDED.value,
        )
    if needed_calls > call_ceiling:
        raise TypedIOValidationException(
            f"Step {step_order}: reading the input in parts needs at least "
            f"{needed_calls} provider calls, exceeding the organization ceiling "
            f"of {call_ceiling} calls.",
            code=FlowApiErrorCode.MAPPED_PROVIDER_CALL_LIMIT_EXCEEDED.value,
        )
    if token_ceiling is not None and needed_input_tokens > token_ceiling:
        raise TypedIOValidationException(
            f"Step {step_order}: reading the input in parts sends at least about "
            f"{needed_input_tokens} input tokens, exceeding the organization "
            f"ceiling of {token_ceiling} tokens.",
            code=FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value,
        )


CALL_CEILING_REASON: Final = "call ceiling"
TOKEN_CEILING_REASON: Final = "token ceiling"


@dataclass
class DigestCallLimits:
    """The organization's ceilings, spent call by call during a digest.

    ``reserved_calls`` stay for the step's own final call (and its possible
    retry without native JSON), so the digest never takes them.
    """

    call_ceiling: int
    token_ceiling: int | None
    reserved_calls: int
    calls: int = 0
    input_tokens: int = 0
    refused: str | None = None

    def admit(self, input_tokens: int) -> bool:
        if self.calls + 1 + self.reserved_calls > self.call_ceiling:
            self.refused = self.refused or CALL_CEILING_REASON
            return False
        if (
            self.token_ceiling is not None
            and self.input_tokens + input_tokens > self.token_ceiling
        ):
            self.refused = self.refused or TOKEN_CEILING_REASON
            return False
        self.calls += 1
        self.input_tokens += input_tokens
        return True


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #
# The step's own final call over the notes keeps this share of the step's
# budget; no digest call starts inside it, and none runs into it.
FINAL_CALL_RESERVE_SHARE: Final = 0.25
# Of the time left to the digest, map admission stops when this share remains,
# so the merges get their turn.
REDUCE_RESERVE_SHARE: Final = 0.25


@dataclass(frozen=True, slots=True)
class DigestTimeLimits:
    deadline: float
    reduce_reserve_seconds: float


def digest_time_limits(
    *, now: float, expires_at: float, budget_seconds: float
) -> DigestTimeLimits:
    """When the digest stops, on the step deadline's clock.

    ``deadline`` is the step's expiry less the final call's reserve: no digest
    call starts after it, and a call still running then is cancelled, so the
    digest ends with partial coverage and the final call keeps its time.
    """
    deadline = expires_at - budget_seconds * FINAL_CALL_RESERVE_SHARE
    window = max(0.0, deadline - now)
    return DigestTimeLimits(
        deadline=deadline, reduce_reserve_seconds=window * REDUCE_RESERVE_SHARE
    )


# --------------------------------------------------------------------------- #
# What each call read
# --------------------------------------------------------------------------- #
_MAP_HEADER = re.compile(r"^\[(S\d+)\] .*\(segment (\d+) of (\d+)\)$")
_BRACKETED = re.compile(r"\[([^\[\]\n]{1,200})\]")
_KEY = re.compile(r"\bS\d+\b")

CallOutcome = Literal["ok", "cut", "failed"]


def is_map_call(system: str, *, instruction: str, budgets: DigestBudgets) -> bool:
    """Whether a call the core routes to its map function takes segment notes
    (the other kind merges one source's segment notes)."""
    return system == map_prompt(instruction, budgets.map_words)


def map_call_target(user: str, keys: dict[str, int]) -> DigestCallInput | None:
    """The source and segment a map call's input names in its first line."""
    match = _MAP_HEADER.match(user.split("\n", 1)[0])
    if match is None or match.group(1) not in keys:
        return None
    return DigestCallInput(
        stage="map",
        source_indexes=(keys[match.group(1)],),
        segment_index=int(match.group(2)),
        segment_count=int(match.group(3)),
    )


def cited_sources(text: str, keys: dict[str, int]) -> tuple[int, ...]:
    """Indexes of the sources whose keys the notes cite in square brackets,
    alone (``[S2]``) or listed (``[S1, S3]``)."""
    cited = {
        keys[key]
        for group in _BRACKETED.findall(text)
        for key in _KEY.findall(group)
        if key in keys
    }
    return tuple(sorted(cited))


def reduce_call(text: str, keys: dict[str, int]) -> DigestCallInput:
    return DigestCallInput(stage="reduce", source_indexes=cited_sources(text, keys))


def final_call(text: str, keys: dict[str, int]) -> DigestCallInput:
    return DigestCallInput(stage="final", source_indexes=cited_sources(text, keys))


@dataclass(frozen=True, slots=True)
class DigestCallRecord:
    """One provider call the digest sent, and what came of it."""

    call: DigestCallInput
    outcome: CallOutcome
    num_tokens_input: int | None = None
    num_tokens_output: int | None = None


# --------------------------------------------------------------------------- #
# Coverage record
# --------------------------------------------------------------------------- #
class LongMaterialSourceCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(description="The key the notes cite the source by.")
    index: int = Field(ge=1)
    title: str
    reference: dict[str, JsonValue] = Field(
        description="What the source is: its kind and the SHA-256 and size of its text."
    )
    start_char: int = Field(ge=0, description="Start of the source in the input.")
    end_char: int = Field(ge=0, description="End of the source in the input.")
    segments_planned: int = Field(ge=0)
    segments_read: tuple[int, ...] = Field(
        description="1-based segments whose notes came back."
    )
    segments_failed: tuple[int, ...] = Field(
        default=(), description="Segments sent whose notes did not come back."
    )
    segments_cut: tuple[int, ...] = Field(
        default=(), description="Segments whose notes the provider cut short."
    )
    segments_not_read: tuple[int, ...] = Field(
        default=(),
        description="Segments never sent: time, a ceiling or the run stopped them.",
    )
    not_relevant: bool = Field(
        default=False, description="Read in full; nothing in it was relevant."
    )
    excluded_at_reduce: bool = Field(
        default=False,
        description="Its notes, or part of them, did not fit the final request.",
    )
    complete: bool


class LongMaterialCoverage(BaseModel):
    """What a digest of long material covers, recorded on the step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["digest"] = "digest"
    coverage: Literal["complete", "partial", "cancelled"] = Field(
        description=(
            "`complete`: every segment was read and every source's notes reached "
            "the final call. `partial`: something was left out; `reasons` says "
            "why and `left_out` names the sources."
        )
    )
    reasons: tuple[str, ...] = ()
    left_out: tuple[str, ...] = Field(
        default=(), description="Keys of the sources not fully represented."
    )
    sources: tuple[LongMaterialSourceCoverage, ...]
    input_tokens_estimate: int = Field(
        ge=0, description="The input's size as the planner counted it."
    )
    refused_input_tokens: int | None = Field(
        default=None, description="The size of the step's own request that did not fit."
    )
    max_input_tokens: int | None = Field(
        default=None, description="The input allowance that request had."
    )
    segment_tokens: int = Field(ge=1)
    reduce_input_tokens: int = Field(ge=1)
    reduce_levels: int = Field(ge=0)
    map_calls: int = Field(ge=0)
    reduce_calls: int = Field(ge=0)
    failed_calls: int = Field(ge=0)
    num_tokens_input: int | None = Field(
        default=None, description="Input tokens of the digest calls that completed."
    )
    num_tokens_output: int | None = None
    notes_sha256: str | None = Field(
        default=None, description="SHA-256 of the notes the final call read."
    )
    notes_bytes: int | None = None

    @property
    def segments_read(self) -> int:
        return sum(len(source.segments_read) for source in self.sources)

    @property
    def segments_planned(self) -> int:
        return sum(source.segments_planned for source in self.sources)


def build_coverage(
    *,
    result: DigestResult,
    sources: Sequence[DigestSource],
    plan: DigestPlan,
    budgets: DigestBudgets,
    calls: Iterable[DigestCallRecord],
    extra_reasons: Sequence[str] = (),
    refused_input_tokens: int | None = None,
    max_input_tokens: int | None = None,
    notes: str | None = None,
) -> LongMaterialCoverage:
    """The record of what the digest read, from the core's account and the
    calls actually sent.

    The core's coverage is the floor: anything it calls partial stays partial,
    and a reason of this runtime's own (a ceiling) or a segment without notes
    makes complete coverage partial.
    """
    records = list(calls)
    map_outcomes: dict[tuple[int, int], CallOutcome] = {}
    for record in records:
        call = record.call
        if call.stage == "map" and call.segment_index is not None:
            map_outcomes[(call.source_indexes[0], call.segment_index)] = record.outcome
    partial_keys = set(result.partial_keys)
    planned_by_key = {planned.item.key: len(planned.segments) for planned in plan.items}
    source_records: list[LongMaterialSourceCoverage] = []
    for source in sources:
        planned = planned_by_key.get(source.key, 0)
        outcomes = {
            segment: map_outcomes.get((source.index, segment))
            for segment in range(1, planned + 1)
        }
        read = tuple(s for s, o in outcomes.items() if o in {"ok", "cut"})
        failed = tuple(s for s, o in outcomes.items() if o == "failed")
        cut = tuple(s for s, o in outcomes.items() if o == "cut")
        not_read = tuple(s for s, o in outcomes.items() if o is None)
        source_records.append(
            LongMaterialSourceCoverage(
                key=source.key,
                index=source.index,
                title=source.title,
                reference=source.reference,
                start_char=source.start_char,
                end_char=source.end_char,
                segments_planned=planned,
                segments_read=read,
                segments_failed=failed,
                segments_cut=cut,
                segments_not_read=not_read,
                not_relevant=source.key in result.not_relevant,
                excluded_at_reduce=source.key in result.excluded,
                complete=source.key not in partial_keys
                and not failed
                and not cut
                and not not_read,
            )
        )
    reasons = tuple(dict.fromkeys((*result.reasons, *extra_reasons)))
    coverage: Literal["complete", "partial", "cancelled"] = result.coverage
    if coverage == "complete" and (
        extra_reasons or not all(source.complete for source in source_records)
    ):
        coverage = "partial"
    left_out = tuple(source.key for source in source_records if not source.complete)
    completed = [record for record in records if record.outcome != "failed"]
    notes_bytes = notes.encode("utf-8") if notes is not None else None
    return LongMaterialCoverage(
        coverage=coverage,
        reasons=reasons,
        left_out=left_out,
        sources=tuple(source_records),
        input_tokens_estimate=plan.total_tokens,
        refused_input_tokens=refused_input_tokens,
        max_input_tokens=max_input_tokens,
        segment_tokens=budgets.segment_tokens,
        reduce_input_tokens=budgets.reduce_input_tokens,
        reduce_levels=result.levels,
        map_calls=sum(1 for record in records if record.call.stage == "map"),
        reduce_calls=sum(1 for record in records if record.call.stage == "reduce"),
        failed_calls=len(records) - len(completed),
        num_tokens_input=sum_complete_token_counts(
            record.num_tokens_input for record in completed
        ),
        num_tokens_output=sum_complete_token_counts(
            record.num_tokens_output for record in completed
        ),
        notes_sha256=sha256(notes_bytes).hexdigest()
        if notes_bytes is not None
        else None,
        notes_bytes=len(notes_bytes) if notes_bytes is not None else None,
    )


# --------------------------------------------------------------------------- #
# Partial coverage
# --------------------------------------------------------------------------- #
PartialCoverageOutcome = Literal["accept", "review", "fail"]
DIGEST_DIAGNOSTIC_CODE: Final = "long_material_digest"
PARTIAL_COVERAGE_DIAGNOSTIC_CODE: Final = "long_material_partial_coverage"


def partial_coverage_outcome(
    coverage: LongMaterialCoverage, *, review_configured: bool
) -> PartialCoverageOutcome:
    """Complete coverage is accepted. Partial coverage fails the step with a
    typed code, unless the step pauses for review anyway: then the reviewer
    sees the partial answer with its coverage and decides. A digest that read
    nothing has no answer to review."""
    if coverage.coverage == "complete":
        return "accept"
    if (
        coverage.coverage == "partial"
        and review_configured
        and coverage.segments_read > 0
    ):
        return "review"
    return "fail"


def _segment_ranges(segments: Sequence[int]) -> str:
    ranges: list[str] = []
    start = previous = None
    for segment in segments:
        if start is None or previous is None or segment != previous + 1:
            if start is not None and previous is not None:
                ranges.append(
                    str(start) if start == previous else f"{start}-{previous}"
                )
            start = segment
        previous = segment
    if start is not None and previous is not None:
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(ranges)


def describe_left_out(coverage: LongMaterialCoverage) -> str:
    parts: list[str] = []
    for source in coverage.sources:
        if source.complete:
            continue
        missing = sorted(
            {
                *source.segments_failed,
                *source.segments_cut,
                *source.segments_not_read,
            }
        )
        detail = (
            f"segments {_segment_ranges(missing)} of {source.segments_planned}"
            if missing
            else "notes left out of the final request"
        )
        parts.append(f"{source.key} '{source.title}' ({detail})")
    return "; ".join(parts)


def partial_coverage_error(
    *, step_order: int, coverage: LongMaterialCoverage
) -> TypedIOValidationException:
    reasons = ", ".join(coverage.reasons) or "unknown"
    left_out = describe_left_out(coverage)
    return TypedIOValidationException(
        f"Step {step_order}: the input was too long for the model and was read "
        f"in parts, but only partly ({reasons}). Left out: {left_out or 'none'}. "
        "Raise the step's timeout_seconds, choose a larger-context model, "
        "reduce the input, or add a review to the step to judge partial answers.",
        code=FlowApiErrorCode.LONG_MATERIAL_PARTIAL_COVERAGE.value,
        context={
            "completed_items": coverage.segments_read,
            "total_items": coverage.segments_planned,
        },
    )


def partial_coverage_message(*, step_order: int, coverage: LongMaterialCoverage) -> str:
    reasons = ", ".join(coverage.reasons) or "unknown"
    return (
        f"Step {step_order}: the input was too long for the model and was read "
        f"in parts, but only partly ({reasons}). The answer leaves out "
        f"{describe_left_out(coverage) or 'nothing listed'}."
    )


def digest_message(*, step_order: int, coverage: LongMaterialCoverage) -> str:
    return (
        f"Step {step_order}: the input (about {coverage.input_tokens_estimate} "
        "tokens) exceeded the model's input capacity and was read in "
        f"{coverage.segments_planned} segments from {len(coverage.sources)} "
        f"sources with {coverage.map_calls + coverage.reduce_calls} provider "
        "calls; the answer was written over the merged notes."
    )


__all__ = [
    "CALL_CEILING_REASON",
    "DIGEST_DIAGNOSTIC_CODE",
    "LONG_MATERIAL_KEY",
    "PARTIAL_COVERAGE_DIAGNOSTIC_CODE",
    "STAGE_DEFAULTS",
    "TOKEN_CEILING_REASON",
    "DigestCallLimits",
    "DigestCallRecord",
    "DigestSource",
    "DigestTimeLimits",
    "LongMaterialConfig",
    "LongMaterialCoverage",
    "LongMaterialMode",
    "LongMaterialSourceCoverage",
    "SourceCandidate",
    "admit_digest",
    "build_coverage",
    "cited_sources",
    "describe_left_out",
    "digest_budgets",
    "digest_instruction",
    "digest_message",
    "digest_time_limits",
    "final_call",
    "final_question",
    "final_question_frame",
    "is_map_call",
    "long_material_config",
    "map_call_target",
    "minimum_digest_calls",
    "minimum_digest_input_tokens",
    "partial_coverage_error",
    "partial_coverage_message",
    "partial_coverage_outcome",
    "partition_digest_sources",
    "reduce_call",
    "source_key",
    "text_reference",
    "without_direct_path",
]
