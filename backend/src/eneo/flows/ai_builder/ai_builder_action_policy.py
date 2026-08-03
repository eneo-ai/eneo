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
from eneo.flows.ai_builder.ai_builder_discovery_priority import (
    discovery_issue_priority,
)
from eneo.flows.ai_builder.ai_builder_discovery_questions import (
    question_suggestion_for_id,
)
from eneo.flows.ai_builder.planning_state import PlanningState

_CORE_ARCHITECTURAL_SLOTS: frozenset[str] = frozenset(
    {"primary_runtime_input", "terminal_output"}
)
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
    unresolved_core_slots = _compute_unresolved_core_slots(session_state)
    derived_commit = derive_architecture_commit_draft(session_state)
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
    ask_targets = _ordered_ask_targets(
        selected_discovery_question_ids=selected_discovery_question_ids,
        architecture_required_slots=(
            frozenset() if architecture_committed else unresolved_core_slots
        ),
        commit_grade_slot_names=commit_grade_slot_names,
    )

    allowed: list[PlannerActionKind] = []

    if ask_targets:
        allowed.append("ask_question")

    if (
        not architecture_committed
        and not unresolved_core_slots
        and derived_commit is not None
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


def _compute_unresolved_core_slots(
    planning_state: PlanningState,
) -> frozenset[str]:
    """Core slots that lack evidence strong enough to close discovery."""

    return _CORE_ARCHITECTURAL_SLOTS - _commit_grade_slot_names(planning_state)


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
    commit_grade_slot_names: frozenset[str],
) -> tuple[str, ...]:
    """Order hard core gaps and discovery-selected questions in one place."""

    selected: list[str] = []
    seen: set[str] = set()

    def normalized_target(raw_target: str) -> str | None:
        target = canonical_question_id(raw_target)
        suggestion = question_suggestion_for_id(target, language="en")
        if suggestion is None or suggestion.exposure != "user_requirement":
            return None
        if target in commit_grade_slot_names:
            return None
        return target

    for raw_target in selected_discovery_question_ids:
        target = normalized_target(raw_target)
        if target is None or target in seen:
            continue
        selected.append(target)
        seen.add(target)

    missing_core: list[str] = []
    for raw_target in architecture_required_slots:
        target = normalized_target(raw_target)
        if target is not None and target not in seen:
            missing_core.append(target)
    missing_core.sort(
        key=lambda target: (discovery_issue_priority(target), target),
    )
    return tuple(missing_core) + tuple(selected)


__all__ = [
    "PlannerActionKind",
    "PlannerActionPolicy",
    "build_planner_action_policy",
]
