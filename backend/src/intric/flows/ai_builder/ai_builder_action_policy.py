"""Server-owned per-turn action policy for the AI Builder planner.

The LLM may choose wording and semantic intent, but it should not infer
which planner actions are legal for the current turn. This module is the
single source for the action menu shown in the prompt and enforced by the
orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from intric.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from intric.flows.ai_builder.ai_builder_ask_question_contract import (
    format_ask_question_targets,
)
from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from intric.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from intric.flows.ai_builder.planning_state import PlanningState

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
    selected_discovery_question_ids: frozenset[str],
    requirements_confirmed: bool = False,
) -> PlannerActionPolicy:
    """Compute the legal action surface from typed server state.

    `selected_discovery_question_ids` is the backend-selected non-core
    discovery surface for this turn. Already resolved slots are removed
    here so a model cannot legally ask the user for facts already present
    in `PlanningState.resolved_slots`.
    """

    resolved_slot_names = frozenset(session_state.resolved_slots.keys())
    derived_commit = derive_architecture_commit_draft(session_state)
    unresolved_commit_slots = _unresolved_slots_for_derived_commit(
        session_state=session_state,
        resolved_slot_names=resolved_slot_names,
    )
    ask_target_set: frozenset[str]
    if session_state.architecture_commit is not None:
        ask_target_set = frozenset()
    else:
        ask_target_set = _normalize_ask_targets(
            unresolved_architectural_choices
            | selected_discovery_question_ids
            | _missing_core_architecture_slots(resolved_slot_names)
            | unresolved_commit_slots
        )
    ask_targets = tuple(sorted(ask_target_set - resolved_slot_names))

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


_LEGACY_QUESTION_TO_SLOT_TARGET: dict[str, str] = {
    "input_material_mode": "primary_runtime_input",
    "flow_input_architecture": "primary_runtime_input",
    "final_output_mode": "terminal_output",
    "final_pdf_type": "terminal_output",
}


def _normalize_ask_targets(targets: frozenset[str]) -> frozenset[str]:
    return frozenset(
        normalized
        for target in targets
        if (normalized := _LEGACY_QUESTION_TO_SLOT_TARGET.get(target, target))
        in KNOWN_REQUIREMENT_SLOT_NAMES
    )


def _missing_core_architecture_slots(
    resolved_slot_names: frozenset[str],
) -> frozenset[str]:
    """Core architecture slots must be explicit before the server can commit.

    Discovery heuristics may fail to infer input or output format from a
    prompt. The action policy is the final deterministic gate: if a core slot
    is missing, ask for it instead of falling through to an unsafe default.
    """

    return frozenset({"primary_runtime_input", "terminal_output"} - resolved_slot_names)


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


def render_action_policy_prompt_block(policy: PlannerActionPolicy) -> str:
    """Render the policy as one compact LLM-facing contract."""

    visible_allowed_kinds = tuple(
        kind for kind in policy.allowed_action_kinds if kind != "propose_plan"
    )
    allowed = ", ".join(f"`{kind}`" for kind in visible_allowed_kinds)
    ask_targets = format_ask_question_targets(policy.allowed_ask_question_targets)
    lines = [
        "## Allowed Planner Actions This Turn",
        "",
        f"Allowed actions: {allowed}.",
        f"Allowed `ask_question` targets this turn: {ask_targets}.",
        (
            "Do not ask about resolved slots. Use the values already present "
            "in PlanningState instead."
        ),
    ]

    if policy.blocked_action_reasons:
        lines.extend(["", "Blocked actions:"])
        for action, reason in sorted(policy.blocked_action_reasons.items()):
            if action == "propose_plan":
                continue
            lines.append(f"- `{action}` is not allowed: {reason}.")

    return "\n".join(lines)


__all__ = [
    "PlannerActionKind",
    "PlannerActionPolicy",
    "build_planner_action_policy",
    "render_action_policy_prompt_block",
]
