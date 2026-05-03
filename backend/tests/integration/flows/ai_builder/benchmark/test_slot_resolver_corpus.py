from __future__ import annotations

from collections import Counter

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_slot_classifier import UNKNOWN_SLOT_VALUE
from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from intric.flows.ai_builder.question_catalog import legal_slot_values
from tests.integration.flows.ai_builder.benchmark.cases import (
    BENCHMARK_CASES,
    RELIABILITY_CORPUS_CASES,
    SLOT_RESOLVER_CORPUS_CASES,
    SlotCoverageTag,
    SlotResolverCorpusCase,
)
from tests.integration.flows.ai_builder.benchmark.slot_resolver_scoring import (
    observations_from_resolved_slots,
    score_expected_slots,
    summarize_slot_scores,
)

MINIMUM_SLOT_RESOLVER_CASES = 80
MINIMUM_CASES_PER_COVERAGE_TAG = 5
KEYWORD_PRIOR_OBSERVED_FLOOR = 0.70
DOMAIN_SPECIFIC_DENYLIST = (
    "tjänsteskrivelse",
    "ärende",
    "nämnd",
    "remiss",
    "handläggare",
    "beslutsunderlag",
)


def _slot_match_score(corpus_case: SlotResolverCorpusCase) -> tuple[int, int]:
    state = build_planning_state_from_conversation(
        [ConversationMessage(role="user", content=corpus_case.prompt)]
    )
    summary = summarize_slot_scores(
        score_expected_slots(
            corpus_case.expected_slots,
            observations_from_resolved_slots(state.resolved_slots),
        )
    )
    return summary.matching_slots, summary.expected_slots


def test_case_count_and_ids_are_stable() -> None:
    case_ids = [case.case_id for case in SLOT_RESOLVER_CORPUS_CASES]
    existing_case_ids = {
        case.case_id for case in (*BENCHMARK_CASES, *RELIABILITY_CORPUS_CASES)
    }

    assert len(SLOT_RESOLVER_CORPUS_CASES) >= MINIMUM_SLOT_RESOLVER_CASES
    assert len(case_ids) == len(set(case_ids))
    assert set(case_ids).isdisjoint(existing_case_ids)


def test_cases_are_swedish_with_non_empty_prompts_and_slots() -> None:
    assert {case.ui_language for case in SLOT_RESOLVER_CORPUS_CASES} == {"sv"}
    for corpus_case in SLOT_RESOLVER_CORPUS_CASES:
        assert corpus_case.prompt.strip()
        assert corpus_case.expected_slots
        assert corpus_case.coverage_tags


def test_expected_slots_use_question_catalog_values_or_unknown() -> None:
    for corpus_case in SLOT_RESOLVER_CORPUS_CASES:
        slot_names = [slot.name for slot in corpus_case.expected_slots]
        assert len(slot_names) == len(set(slot_names))
        assert set(slot_names) <= KNOWN_REQUIREMENT_SLOT_NAMES
        for expected_slot in corpus_case.expected_slots:
            assert expected_slot.value in legal_slot_values(expected_slot.name) | {
                UNKNOWN_SLOT_VALUE
            }


def test_coverage_tags_have_minimum_distribution() -> None:
    coverage_counts: Counter[SlotCoverageTag] = Counter()
    for corpus_case in SLOT_RESOLVER_CORPUS_CASES:
        coverage_counts.update(corpus_case.coverage_tags)

    assert set(coverage_counts) == set(SlotCoverageTag)
    for tag in SlotCoverageTag:
        assert coverage_counts[tag] >= MINIMUM_CASES_PER_COVERAGE_TAG


def test_prompts_remain_domain_neutral() -> None:
    for corpus_case in SLOT_RESOLVER_CORPUS_CASES:
        prompt = corpus_case.prompt.casefold()
        assert not any(token in prompt for token in DOMAIN_SPECIFIC_DENYLIST), (
            f"{corpus_case.case_id} contains a domain-specific token"
        )


def test_keyword_prior_baseline_is_measured_through_planning_state_builder() -> None:
    matching_slots = 0
    expected_slots = 0
    for corpus_case in SLOT_RESOLVER_CORPUS_CASES:
        case_matches, case_total = _slot_match_score(corpus_case)
        matching_slots += case_matches
        expected_slots += case_total

    score = matching_slots / expected_slots
    assert score >= KEYWORD_PRIOR_OBSERVED_FLOOR, (
        "Keyword-prior baseline floor failed. This is a baseline floor, not "
        f"the final Batch 11.2 resolver target; score={score:.3f}, "
        f"floor={KEYWORD_PRIOR_OBSERVED_FLOOR:.3f}."
    )
