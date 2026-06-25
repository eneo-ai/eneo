"""Server-owned per-turn action policy for the AI Builder planner.

The LLM may choose wording and semantic intent, but it should not infer
which planner actions are legal for the current turn. This module is the
single source for the action menu consumed by the deterministic turn
controller and downstream server/proposal dispatch.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from intric.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from intric.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from intric.flows.ai_builder.planning_state import PlanningState
from intric.flows.ai_builder.question_catalog import slot_name_for_legacy_question_id

CORE_ARCHITECTURAL_SLOT_ORDER: tuple[str, ...] = (
    "primary_runtime_input",
    "terminal_output",
)
CORE_ARCHITECTURAL_SLOTS: frozenset[str] = frozenset(CORE_ARCHITECTURAL_SLOT_ORDER)

PlannerActionKind = Literal[
    "ask_question",
    "confirm_requirements",
    "commit_architecture",
    "propose_plan",
]


def _empty_blocked_action_reasons() -> dict[PlannerActionKind, str]:
    return {}


@dataclass(frozen=True, slots=True)
class PlannerActionPolicy:
    """Legal planner actions and question targets for one turn."""

    allowed_action_kinds: tuple[PlannerActionKind, ...]
    allowed_ask_question_targets: tuple[str, ...] = ()
    blocked_action_reasons: dict[PlannerActionKind, str] = field(
        default_factory=_empty_blocked_action_reasons
    )


def build_planner_action_policy(
    *,
    session_state: PlanningState,
    unresolved_architectural_choices: frozenset[str],
    selected_discovery_question_ids: tuple[str, ...],
    requirements_confirmed: bool = False,
) -> PlannerActionPolicy:
    """Compute the legal action surface from typed server state.

    `selected_discovery_question_ids` is the backend-selected non-core
    discovery surface for this turn. Already resolved slots are removed
    here so a model cannot legally ask the user for facts already present
    in `PlanningState.resolved_slots`.
    """

    resolved_slot_names = frozenset(session_state.resolved_slots.keys())
    unresolved_core_slots = compute_unresolved_core_slots(session_state)
    derived_commit = derive_architecture_commit_draft(session_state)
    unresolved_commit_slots = _unresolved_slots_for_derived_commit(
        session_state=session_state,
        resolved_slot_names=resolved_slot_names,
    )
    ask_targets: tuple[str, ...]
    if session_state.architecture_commit is not None:
        ask_targets = ()
    else:
        ask_targets = _ordered_ask_targets(
            selected_discovery_question_ids=selected_discovery_question_ids,
            architecture_required_slots=(
                unresolved_architectural_choices | unresolved_core_slots
            ),
            derived_commit_required_slots=unresolved_commit_slots,
            resolved_slot_names=resolved_slot_names,
        )

    blocked: dict[PlannerActionKind, str] = {}
    allowed: list[PlannerActionKind] = []

    if ask_targets:
        allowed.append("ask_question")
    else:
        blocked["ask_question"] = "no unresolved ask_question targets"

    if session_state.architecture_commit is not None:
        blocked["commit_architecture"] = "architecture is already committed"
    elif unresolved_architectural_choices - resolved_slot_names:
        blocked["commit_architecture"] = (
            "unresolved architecture choices: "
            + ", ".join(sorted(unresolved_architectural_choices - resolved_slot_names))
        )
    elif derived_commit is None:
        blocked["commit_architecture"] = (
            "architecture cannot be derived from resolved state"
        )
    elif unresolved_commit_slots:
        blocked["commit_architecture"] = (
            "derived architecture requires unresolved slots: "
            + ", ".join(sorted(unresolved_commit_slots))
        )
    else:
        allowed.append("commit_architecture")

    if session_state.architecture_commit is None:
        blocked["confirm_requirements"] = "architecture has not been committed"
        blocked["propose_plan"] = "architecture has not been committed"
    elif not requirements_confirmed:
        allowed.append("confirm_requirements")
        blocked["propose_plan"] = "requirements have not been confirmed"
    else:
        blocked["confirm_requirements"] = "requirements are already confirmed"
        allowed.append("propose_plan")

    allowed = _phase_priority(allowed)

    return PlannerActionPolicy(
        allowed_action_kinds=tuple(allowed),
        allowed_ask_question_targets=ask_targets,
        blocked_action_reasons=blocked,
    )


def compute_unresolved_core_slots(
    planning_state: PlanningState,
) -> frozenset[str]:
    """One predicate for prompt policy and commit eligibility checks."""

    resolved = frozenset(planning_state.resolved_slots.keys())
    return CORE_ARCHITECTURAL_SLOTS - resolved


def _phase_priority(candidates: list[PlannerActionKind]) -> list[PlannerActionKind]:
    """Expose one deterministic phase instead of a broad LLM action menu."""

    for action in (
        "ask_question",
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
    resolved_slot_names: frozenset[str],
) -> tuple[str, ...]:
    """Priority: discovery order, then core fallback, then derived requirements."""

    ordered: list[str] = []
    seen: set[str] = set()

    def append_target(raw_target: str) -> None:
        target = slot_name_for_legacy_question_id(raw_target)
        if (
            target not in KNOWN_REQUIREMENT_SLOT_NAMES
            or target in resolved_slot_names
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
    resolved_slot_names: frozenset[str],
) -> frozenset[str]:
    commit = derive_architecture_commit_draft(session_state)
    if commit is None:
        return frozenset()
    required_slots = frozenset(
        slot_name
        for pattern_id in commit.chosen_patterns
        if pattern_id in PATTERN_REGISTRY
        for slot_name in PATTERN_REGISTRY[pattern_id].required_architectural_slots
    )
    return required_slots - resolved_slot_names


__all__ = [
    "CORE_ARCHITECTURAL_SLOTS",
    "PlannerActionKind",
    "PlannerActionPolicy",
    "build_planner_action_policy",
    "compute_unresolved_core_slots",
]
