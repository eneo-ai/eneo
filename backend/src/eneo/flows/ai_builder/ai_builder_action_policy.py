"""Server-owned per-turn action policy for the AI Builder planner.

The LLM may choose wording and semantic intent, but it should not infer
which planner actions are legal for the current turn. This module is the
single source for the action menu consumed by the deterministic turn
controller and downstream server/proposal dispatch.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_canonicalization import canonical_question_id
from eneo.flows.ai_builder.ai_builder_commit_invariance import (
    architecture_commit_draft_matches_pinned,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from eneo.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.ai_builder.question_catalog import QUESTION_CATALOG

CORE_ARCHITECTURAL_SLOT_ORDER: tuple[str, ...] = (
    "primary_runtime_input",
    "terminal_output",
)
CORE_ARCHITECTURAL_SLOTS: frozenset[str] = frozenset(CORE_ARCHITECTURAL_SLOT_ORDER)

PlannerActionKind = Literal[
    "ask_question",
    "confirm_requirements",
    "commit_architecture",
    "revise_architecture",
    "propose_plan",
]


@dataclass(frozen=True, slots=True)
class PlannerActionPolicy:
    """Legal planner actions and question targets for one turn."""

    allowed_action_kinds: tuple[PlannerActionKind, ...]
    allowed_ask_question_targets: tuple[str, ...] = ()


def build_planner_action_policy(
    *,
    session_state: PlanningState,
    selected_discovery_question_ids: tuple[str, ...],
    requirements_confirmed: bool = False,
) -> PlannerActionPolicy:
    """Compute the legal action surface from typed server state.

    `selected_discovery_question_ids` is the backend-selected non-core
    discovery surface for this turn. Already resolved slots are removed
    here so a model cannot legally ask the user for facts already present
    in `PlanningState.resolved_slots`.
    """

    commit_grade_slot_names = _commit_grade_slot_names(session_state)
    unresolved_core_slots = compute_unresolved_core_slots(session_state)
    derived_commit = derive_architecture_commit_draft(session_state)
    unresolved_commit_slots = _unresolved_slots_for_derived_commit(
        session_state=session_state,
        commit_grade_slot_names=commit_grade_slot_names,
    )
    architecture_committed = session_state.architecture_commit is not None
    pinned_commit_matches_current_slots = architecture_commit_draft_matches_pinned(
        before=session_state.architecture_commit,
        after=derived_commit,
    )
    architecture_drift_detected = (
        architecture_committed
        and derived_commit is not None
        and not pinned_commit_matches_current_slots
    )
    ask_targets: tuple[str, ...]
    if architecture_drift_detected and unresolved_core_slots:
        ask_targets = _ordered_ask_targets(
            selected_discovery_question_ids=(),
            architecture_required_slots=unresolved_core_slots,
            derived_commit_required_slots=frozenset(),
            commit_grade_slot_names=commit_grade_slot_names,
        )
    elif (
        architecture_drift_detected
        and not unresolved_core_slots
        and unresolved_commit_slots
    ):
        ask_targets = _ordered_ask_targets(
            selected_discovery_question_ids=(),
            architecture_required_slots=frozenset(),
            derived_commit_required_slots=unresolved_commit_slots,
            commit_grade_slot_names=commit_grade_slot_names,
        )
    elif architecture_committed:
        ask_targets = ()
    else:
        ask_targets = _ordered_ask_targets(
            selected_discovery_question_ids=selected_discovery_question_ids,
            architecture_required_slots=unresolved_core_slots,
            derived_commit_required_slots=unresolved_commit_slots,
            commit_grade_slot_names=commit_grade_slot_names,
        )

    allowed: list[PlannerActionKind] = []

    if ask_targets:
        allowed.append("ask_question")

    if (
        not architecture_committed
        and not unresolved_core_slots
        and derived_commit is not None
        and not unresolved_commit_slots
    ):
        allowed.append("commit_architecture")

    if (
        architecture_committed
        and not ask_targets
        and derived_commit is not None
        and architecture_drift_detected
    ):
        allowed.append("revise_architecture")

    if architecture_committed and not ask_targets and not architecture_drift_detected:
        if requirements_confirmed:
            allowed.append("propose_plan")
        else:
            allowed.append("confirm_requirements")

    allowed = _phase_priority(allowed)

    return PlannerActionPolicy(
        allowed_action_kinds=tuple(allowed),
        allowed_ask_question_targets=ask_targets,
    )


def compute_unresolved_core_slots(
    planning_state: PlanningState,
) -> frozenset[str]:
    """Core slots that lack evidence strong enough to close discovery."""

    return CORE_ARCHITECTURAL_SLOTS - _commit_grade_slot_names(planning_state)


def _commit_grade_slot_names(planning_state: PlanningState) -> frozenset[str]:
    return frozenset(
        name
        for name, slot in planning_state.resolved_slots.items()
        if slot.is_commit_grade
    )


def _phase_priority(candidates: list[PlannerActionKind]) -> list[PlannerActionKind]:
    """Expose one deterministic phase instead of a broad LLM action menu."""

    for action in (
        "ask_question",
        "revise_architecture",
        "commit_architecture",
        "confirm_requirements",
        "propose_plan",
    ):
        if action in candidates:
            return [action]
    return []


def _ordered_ask_targets(
    *,
    selected_discovery_question_ids: Sequence[str],
    architecture_required_slots: frozenset[str],
    derived_commit_required_slots: frozenset[str],
    commit_grade_slot_names: frozenset[str],
) -> tuple[str, ...]:
    """Priority: discovery order, then core fallback, then derived requirements."""

    ordered: list[str] = []
    seen: set[str] = set()

    def append_target(raw_target: str) -> None:
        target = canonical_question_id(raw_target)
        if (
            target not in KNOWN_REQUIREMENT_SLOT_NAMES
            or not _is_user_requirement_question(target)
            or target in commit_grade_slot_names
            or target in seen
        ):
            return
        ordered.append(target)
        seen.add(target)

    for target in selected_discovery_question_ids:
        append_target(target)
    for target in _order_slot_names(architecture_required_slots):
        append_target(target)
    for target in _order_slot_names(derived_commit_required_slots):
        append_target(target)

    return tuple(ordered)


def _order_slot_names(slot_names: frozenset[str]) -> tuple[str, ...]:
    core_slots = tuple(
        slot for slot in CORE_ARCHITECTURAL_SLOT_ORDER if slot in slot_names
    )
    remaining = tuple(
        slot for slot in sorted(slot_names) if slot not in CORE_ARCHITECTURAL_SLOTS
    )
    return core_slots + remaining


def _unresolved_slots_for_derived_commit(
    *,
    session_state: PlanningState,
    commit_grade_slot_names: frozenset[str],
) -> frozenset[str]:
    commit = derive_architecture_commit_draft(session_state)
    if commit is None:
        return frozenset()
    required_slots = frozenset(
        slot_name
        for pattern_id in commit.chosen_patterns
        if pattern_id in PATTERN_REGISTRY
        for slot_name in PATTERN_REGISTRY[pattern_id].required_architectural_slots
        if _is_user_requirement_question(slot_name)
    )
    return required_slots - commit_grade_slot_names


def _is_user_requirement_question(slot_name: str) -> bool:
    template = QUESTION_CATALOG.get(slot_name)
    return template is not None and template.exposure == "user_requirement"


__all__ = [
    "CORE_ARCHITECTURAL_SLOTS",
    "PlannerActionKind",
    "PlannerActionPolicy",
    "build_planner_action_policy",
    "compute_unresolved_core_slots",
]
