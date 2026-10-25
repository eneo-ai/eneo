"""Measure how one model call forwards its inputs: overlap between the inputs,
and how much of the output repeats them verbatim.

Pure functions over text already in memory: no I/O, and nothing here keeps,
logs or returns text. The result is a ``ForwardingFacts`` of numbers and edge
indexes.

Method:

- Each text is normalized with Unicode NFKC, casefolded and its whitespace
  collapsed. Its words are then the runs of letters and digits, so punctuation
  and markup (a bullet, a bold marker, a JSON quote or escape) do not split a
  match.
- A shingle is eight consecutive words, hashed to 64 bits (blake2b,
  ``digest_size=8``).
- A text over ``MAX_UNSAMPLED_BYTES`` is sampled: only every k-th shingle is
  measured, ``k = ceil(byte_size / MAX_UNSAMPLED_BYTES)``, and the facts
  record k.

Mapping overlap back to bytes: a measured shingle that also occurs in another
edge covers its eight words (with sampling, the k positions it stands for and
their words). ``repeated_bytes`` is the edge's byte size times the share of its
words so covered, rounded. The ratios count shingles: the share of the
output's measured shingles found in an edge, or in any edge.

Bounds: the whole measurement shares one CPU budget (50 ms by default, read
from ``time.perf_counter``); past it the facts record ``measured: false`` with
``cpu_budget_exceeded``. Any failure inside records ``computation_failed`` and
is logged without content. Nothing raises to the caller.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from eneo.flows.domain.forwarding_facts import (
    FORWARDING_FACTS_SCHEMA_VERSION,
    FORWARDING_FACTS_SHINGLE_WORDS,
    ForwardingEdgeFacts,
    ForwardingFacts,
    not_measured_forwarding_facts,
)

logger = logging.getLogger(__name__)

FORWARDING_FACTS_CPU_BUDGET_SECONDS: Final = 0.050
MAX_UNSAMPLED_BYTES: Final = 2 * 1024 * 1024
# How many shingles are hashed between two reads of the clock.
_BUDGET_CHECK_INTERVAL: Final = 512

_WORD = re.compile(r"\w+")
_WHITESPACE = re.compile(r"\s+")

Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class ForwardingSegment:
    """The text one input edge of a model call carried."""

    edge_index: int
    text: str


class _BudgetExceeded(Exception):
    pass


@dataclass(slots=True)
class _Budget:
    clock: Clock
    deadline: float

    def check(self) -> None:
        if self.clock() > self.deadline:
            raise _BudgetExceeded


@dataclass(frozen=True, slots=True)
class _Profile:
    """The measured shingles of one text."""

    byte_size: int
    word_count: int
    sample_every: int
    positions: tuple[int, ...]
    hashes: tuple[bytes, ...]
    hash_set: frozenset[bytes]


def normalized_words(text: str) -> list[str]:
    normalized = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text).casefold())
    return _WORD.findall(normalized)


def sample_every_for(byte_size: int) -> int:
    if byte_size <= MAX_UNSAMPLED_BYTES:
        return 1
    return math.ceil(byte_size / MAX_UNSAMPLED_BYTES)


def _profile(text: str, budget: _Budget) -> _Profile:
    byte_size = len(text.encode("utf-8"))
    sample_every = sample_every_for(byte_size)
    # Each word is encoded once; a shingle is its eight words joined by spaces.
    words = [word.encode("utf-8") for word in normalized_words(text)]
    budget.check()
    width = FORWARDING_FACTS_SHINGLE_WORDS
    positions = range(0, max(len(words) - width + 1, 0), sample_every)
    hashes: list[bytes] = []
    blake2b = hashlib.blake2b
    join = b" ".join
    for count, position in enumerate(positions):
        if count % _BUDGET_CHECK_INTERVAL == 0:
            budget.check()
        hashes.append(
            blake2b(join(words[position : position + width]), digest_size=8).digest()
        )
    return _Profile(
        byte_size=byte_size,
        word_count=len(words),
        sample_every=sample_every,
        positions=tuple(positions),
        hashes=tuple(hashes),
        hash_set=frozenset(hashes),
    )


def _covered_words(
    profile: _Profile, matched: Callable[[bytes], bool], budget: _Budget
) -> int:
    """Words covered by the measured shingles that ``matched`` accepts.

    A shingle at position p covers words p to p + 7; a sampled one stands for
    the k positions up to the next sample, so it covers p to p + k + 6.
    Positions ascend, so overlapping spans merge in one pass.
    """
    span = FORWARDING_FACTS_SHINGLE_WORDS + profile.sample_every - 1
    covered = 0
    run_start = run_end = 0
    for count, (position, shingle) in enumerate(
        zip(profile.positions, profile.hashes, strict=True)
    ):
        if count % _BUDGET_CHECK_INTERVAL == 0:
            budget.check()
        if not matched(shingle):
            continue
        end = min(position + span, profile.word_count)
        if position > run_end:
            covered += run_end - run_start
            run_start = position
        run_end = max(run_end, end)
    return covered + run_end - run_start


def _share(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _measure(
    *,
    segments: Sequence[ForwardingSegment],
    output_text: str,
    unmeasured_edge_indexes: Sequence[int],
    call_count: int,
    budget: _Budget,
) -> ForwardingFacts:
    # Identical texts (one producer read twice) are profiled once.
    profiles_by_text: dict[str, _Profile] = {}
    ordered = sorted(segments, key=lambda segment: segment.edge_index)
    segment_profiles: list[tuple[int, _Profile]] = []
    for segment in ordered:
        profile = profiles_by_text.get(segment.text)
        if profile is None:
            profile = _profile(segment.text, budget)
            profiles_by_text[segment.text] = profile
        segment_profiles.append((segment.edge_index, profile))
    output = _profile(output_text, budget)

    # How many edges of the call hold each shingle.
    edges_holding: Counter[bytes] = Counter()
    for _, profile in segment_profiles:
        edges_holding.update(profile.hash_set)
        budget.check()

    covered_by_profile: dict[int, int] = {}
    copied_by_profile: dict[int, int] = {}
    edges: list[ForwardingEdgeFacts] = []
    for edge_index, profile in segment_profiles:
        key = id(profile)
        if key not in covered_by_profile:
            covered_by_profile[key] = _covered_words(
                profile, lambda shingle: edges_holding[shingle] >= 2, budget
            )
            copied_by_profile[key] = sum(
                1 for shingle in output.hashes if shingle in profile.hash_set
            )
            budget.check()
        covered = covered_by_profile[key]
        edges.append(
            ForwardingEdgeFacts(
                edge_index=edge_index,
                byte_size=profile.byte_size,
                shingle_count=len(profile.hashes),
                sample_every=profile.sample_every,
                repeated_bytes=(
                    round(profile.byte_size * covered / profile.word_count)
                    if profile.word_count
                    else 0
                ),
                copied_to_output_ratio=_share(
                    copied_by_profile[key], len(output.hashes)
                ),
            )
        )
    verbatim = sum(1 for shingle in output.hashes if shingle in edges_holding)
    budget.check()
    return ForwardingFacts(
        schema_version=FORWARDING_FACTS_SCHEMA_VERSION,
        measured=True,
        call_count=call_count,
        edges=tuple(edges),
        unmeasured_edge_indexes=tuple(sorted(set(unmeasured_edge_indexes))),
        output_byte_size=output.byte_size,
        output_shingle_count=len(output.hashes),
        output_sample_every=output.sample_every,
        output_verbatim_ratio=_share(verbatim, len(output.hashes)),
    )


def measure_forwarding_facts(
    *,
    segments: Sequence[ForwardingSegment],
    output_text: str,
    unmeasured_edge_indexes: Sequence[int] = (),
    call_count: int = 1,
    clock: Clock = time.perf_counter,
    budget_seconds: float = FORWARDING_FACTS_CPU_BUDGET_SECONDS,
) -> ForwardingFacts:
    """The forwarding facts of one model call. Never raises."""
    try:
        budget = _Budget(clock=clock, deadline=clock() + budget_seconds)
        return _measure(
            segments=segments,
            output_text=output_text,
            unmeasured_edge_indexes=unmeasured_edge_indexes,
            call_count=call_count,
            budget=budget,
        )
    except _BudgetExceeded:
        return not_measured_forwarding_facts(
            reason="cpu_budget_exceeded", call_count=call_count
        )
    except Exception as exc:
        logger.warning(
            "flow_forwarding_facts.computation_failed error_type=%s",
            type(exc).__name__,
        )
        return not_measured_forwarding_facts(
            reason="computation_failed", call_count=call_count
        )


__all__ = [
    "FORWARDING_FACTS_CPU_BUDGET_SECONDS",
    "MAX_UNSAMPLED_BYTES",
    "ForwardingSegment",
    "measure_forwarding_facts",
    "normalized_words",
    "sample_every_for",
]
