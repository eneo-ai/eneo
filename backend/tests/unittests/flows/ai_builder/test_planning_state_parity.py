"""Parity between the legacy per-turn resolver and PlanningState.

`build_resolved_requirements_state` is the pre-existing deterministic
discovery path. `build_planning_state_from_conversation` is the new
persisted-state path. Until the cutover ships, the two must produce
identical slot outcomes for every benchmark prompt. A divergence here
would mean the new persisted path misses (or invents) discovery state
that the planner today treats as load-bearing.

The test walks every `BenchmarkCase` as a single-user-turn conversation
and asserts slot equivalence by name/value/source/confidence/evidence.
"""

from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_resolved_requirements import (
    build_resolved_requirements_state,
)
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from tests.integration.flows.ai_builder.benchmark.cases import (
    BENCHMARK_CASES,
    BenchmarkCase,
)


def _conversation_for(case: BenchmarkCase) -> list[ConversationMessage]:
    return [ConversationMessage(role="user", content=case.prompt)]


@pytest.mark.parametrize(
    "case",
    BENCHMARK_CASES,
    ids=[case.case_id for case in BENCHMARK_CASES],
)
class TestResolvedSlotsParity:
    def test_slot_names_match_legacy(self, case: BenchmarkCase) -> None:
        conversation = _conversation_for(case)
        legacy = build_resolved_requirements_state(conversation)
        derived = build_planning_state_from_conversation(conversation)
        legacy_names = {slot.name for slot in legacy.slots}
        derived_names = set(derived.resolved_slots)
        assert legacy_names == derived_names, (
            f"{case.case_id}: slot name set diverged "
            f"(legacy={sorted(legacy_names)}, derived={sorted(derived_names)})"
        )

    def test_slot_values_match_legacy(self, case: BenchmarkCase) -> None:
        conversation = _conversation_for(case)
        legacy = build_resolved_requirements_state(conversation)
        derived = build_planning_state_from_conversation(conversation)
        for slot in legacy.slots:
            derived_slot = derived.resolved_slots[slot.name]
            assert derived_slot.value == slot.value, (
                f"{case.case_id}: slot {slot.name!r} value diverged "
                f"(legacy={slot.value!r}, derived={derived_slot.value!r})"
            )

    def test_slot_sources_match_legacy(self, case: BenchmarkCase) -> None:
        conversation = _conversation_for(case)
        legacy = build_resolved_requirements_state(conversation)
        derived = build_planning_state_from_conversation(conversation)
        for slot in legacy.slots:
            derived_slot = derived.resolved_slots[slot.name]
            assert derived_slot.source == slot.source, (
                f"{case.case_id}: slot {slot.name!r} source diverged "
                f"(legacy={slot.source!r}, derived={derived_slot.source!r})"
            )

    def test_slot_confidence_matches_legacy(self, case: BenchmarkCase) -> None:
        conversation = _conversation_for(case)
        legacy = build_resolved_requirements_state(conversation)
        derived = build_planning_state_from_conversation(conversation)
        for slot in legacy.slots:
            derived_slot = derived.resolved_slots[slot.name]
            assert derived_slot.confidence == slot.confidence, (
                f"{case.case_id}: slot {slot.name!r} confidence diverged "
                f"(legacy={slot.confidence!r}, "
                f"derived={derived_slot.confidence!r})"
            )

    def test_slot_evidence_matches_legacy(self, case: BenchmarkCase) -> None:
        conversation = _conversation_for(case)
        legacy = build_resolved_requirements_state(conversation)
        derived = build_planning_state_from_conversation(conversation)
        for slot in legacy.slots:
            derived_slot = derived.resolved_slots[slot.name]
            assert tuple(derived_slot.evidence) == slot.evidence, (
                f"{case.case_id}: slot {slot.name!r} evidence diverged "
                f"(legacy={slot.evidence!r}, derived={derived_slot.evidence!r})"
            )


class TestDerivedPlanningStateShape:
    """Contract checks on the derived state that do not require the
    legacy comparator."""

    def test_empty_conversation_stays_in_awaiting_input(self) -> None:
        state = build_planning_state_from_conversation([])
        assert state.phase == "awaiting_input"
        assert state.resolved_slots == {}

    def test_evidence_tracks_stable_message_ids(self) -> None:
        conversation = [
            ConversationMessage(role="user", content="hello"),
            ConversationMessage(role="assistant", content="hi"),
        ]
        state = build_planning_state_from_conversation(conversation)
        assert state.evidence.conversation_message_ids == [
            conversation[0].message_id,
            conversation[1].message_id,
        ]

    def test_phase_shifts_to_discovering_when_slots_resolve(self) -> None:
        case = next(
            c
            for c in BENCHMARK_CASES
            if c.archetype == "rich" and c.ui_language == "sv"
        )
        conversation = _conversation_for(case)
        state = build_planning_state_from_conversation(conversation)
        assert state.phase == "discovering"
        assert state.resolved_slots, (
            f"Expected rich prompt {case.case_id} to resolve at least one slot"
        )
