"""Shared scoring for the AI Builder slot resolver corpus."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from intric.flows.ai_builder.ai_builder_slot_classifier import UNKNOWN_SLOT_VALUE
from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    LLM_RESOLVABLE_SLOT_NAMES,
)
from intric.flows.ai_builder.planning_state import ResolvedSlot
from tests.integration.flows.ai_builder.benchmark.cases import (
    ExpectedSlot,
    SlotResolverCorpusCase,
)


@dataclass(frozen=True, slots=True)
class SlotObservation:
    value: str
    source: str | None = None
    confidence: str | None = None


@dataclass(frozen=True, slots=True)
class SlotScore:
    slot_name: str
    expected_value: str
    observed_value: str | None
    observed_source: str | None
    observed_confidence: str | None
    matched: bool
    llm_resolvable: bool


@dataclass(frozen=True, slots=True)
class ScoreSummary:
    matching_slots: int
    expected_slots: int
    score: float | None


@dataclass(frozen=True, slots=True)
class SlotAgreementSummary:
    slot_name: str
    agreement_count: int
    disagreement_count: int
    unresolved_count: int


def observations_from_resolved_slots(
    resolved_slots: Mapping[str, ResolvedSlot],
) -> dict[str, SlotObservation]:
    return {
        slot_name: SlotObservation(
            value=slot.value,
            source=slot.source,
            confidence=slot.confidence,
        )
        for slot_name, slot in resolved_slots.items()
    }


def slot_matches(expected_value: str, observed_value: str | None) -> bool:
    if expected_value == UNKNOWN_SLOT_VALUE:
        return observed_value is None or observed_value == UNKNOWN_SLOT_VALUE
    return observed_value == expected_value


def score_expected_slots(
    expected_slots: Sequence[ExpectedSlot],
    observations: Mapping[str, SlotObservation],
) -> tuple[SlotScore, ...]:
    scores: list[SlotScore] = []
    for expected_slot in expected_slots:
        observation = observations.get(expected_slot.name)
        observed_value = observation.value if observation is not None else None
        scores.append(
            SlotScore(
                slot_name=expected_slot.name,
                expected_value=expected_slot.value,
                observed_value=observed_value,
                observed_source=observation.source if observation is not None else None,
                observed_confidence=observation.confidence
                if observation is not None
                else None,
                matched=slot_matches(expected_slot.value, observed_value),
                llm_resolvable=is_llm_resolvable_slot(expected_slot.name),
            )
        )
    return tuple(scores)


def summarize_slot_scores(
    scores: Iterable[SlotScore],
    *,
    llm_resolvable_only: bool = False,
) -> ScoreSummary:
    considered_scores = [
        score for score in scores if not llm_resolvable_only or score.llm_resolvable
    ]
    matching_slots = sum(int(score.matched) for score in considered_scores)
    expected_slots = len(considered_scores)
    return ScoreSummary(
        matching_slots=matching_slots,
        expected_slots=expected_slots,
        score=matching_slots / expected_slots if expected_slots else None,
    )


def agreement_by_slot_name(
    keyword_scores: Iterable[SlotScore],
    runtime_scores: Iterable[SlotScore],
) -> tuple[SlotAgreementSummary, ...]:
    keyword_by_slot = {score.slot_name: score for score in keyword_scores}
    runtime_by_slot = {score.slot_name: score for score in runtime_scores}
    slot_names = sorted(keyword_by_slot.keys() | runtime_by_slot.keys())
    summaries: list[SlotAgreementSummary] = []
    for slot_name in slot_names:
        keyword_value = _score_observed_value(keyword_by_slot.get(slot_name))
        runtime_value = _score_observed_value(runtime_by_slot.get(slot_name))
        unresolved_count = int(runtime_value in {None, UNKNOWN_SLOT_VALUE})
        summaries.append(
            SlotAgreementSummary(
                slot_name=slot_name,
                agreement_count=int(keyword_value == runtime_value),
                disagreement_count=int(keyword_value != runtime_value),
                unresolved_count=unresolved_count,
            )
        )
    return tuple(summaries)


def summarize_agreements(
    per_case_agreements: Iterable[Iterable[SlotAgreementSummary]],
) -> tuple[SlotAgreementSummary, ...]:
    agreement_counts: Counter[str] = Counter()
    disagreement_counts: Counter[str] = Counter()
    unresolved_counts: Counter[str] = Counter()
    slot_names: set[str] = set()
    for agreements in per_case_agreements:
        for agreement in agreements:
            slot_names.add(agreement.slot_name)
            agreement_counts[agreement.slot_name] += agreement.agreement_count
            disagreement_counts[agreement.slot_name] += agreement.disagreement_count
            unresolved_counts[agreement.slot_name] += agreement.unresolved_count
    return tuple(
        SlotAgreementSummary(
            slot_name=slot_name,
            agreement_count=agreement_counts[slot_name],
            disagreement_count=disagreement_counts[slot_name],
            unresolved_count=unresolved_counts[slot_name],
        )
        for slot_name in sorted(slot_names)
    )


def slot_resolver_corpus_hash(
    cases: Sequence[SlotResolverCorpusCase],
) -> str:
    payload = [
        {
            "case_id": corpus_case.case_id,
            "ui_language": corpus_case.ui_language,
            "prompt": corpus_case.prompt,
            "expected_slots": [
                {"name": slot.name, "value": slot.value}
                for slot in corpus_case.expected_slots
            ],
            "coverage_tags": sorted(tag.value for tag in corpus_case.coverage_tags),
        }
        for corpus_case in sorted(cases, key=lambda item: item.case_id)
    ]
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_llm_resolvable_slot(slot_name: str) -> bool:
    return slot_name in LLM_RESOLVABLE_SLOT_NAMES


def _score_observed_value(score: SlotScore | None) -> str | None:
    return score.observed_value if score is not None else None
