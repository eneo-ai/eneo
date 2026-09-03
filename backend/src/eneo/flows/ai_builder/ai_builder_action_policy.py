"""Server-owned per-turn action policy for the AI Builder planner.

The LLM may choose wording and semantic intent, but it should not infer
which planner actions are legal for the current turn. This module is the
single source for the action menu consumed by the deterministic turn
controller and downstream server/proposal dispatch.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    CORE_ARCHITECTURAL_SLOTS,
    architecture_commit_hints_are_supported,
    architecture_required_slot_names,
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_canonicalization import canonical_question_id
from eneo.flows.ai_builder.ai_builder_checkpoint_contract import (
    transcript_checkpoint_requires_audio,
)
from eneo.flows.ai_builder.ai_builder_commit_invariance import (
    architecture_commit_draft_matches_pinned,
)
from eneo.flows.ai_builder.ai_builder_discovery_priority import (
    discovery_issue_priority,
)
from eneo.flows.ai_builder.ai_builder_discovery_questions import (
    question_suggestion_for_id,
)
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorCode
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    STRUCTURED_FIELD_NAME_PATTERN,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ObligatedResultKey,
    ProposalObligationProjection,
)
from eneo.flows.ai_builder.ai_builder_template_attachment_contract import (
    selected_template_is_readable,
    template_attachment_selection_is_valid,
)
from eneo.flows.ai_builder.planning_state import ArchitectureCommitDraft, PlanningState
from eneo.flows.enums import FlowAuthoringOutputMode

PlannerActionKind = Literal[
    "ask_question",
    "confirm_requirements",
    "commit_architecture",
    "refuse_architecture_commit",
    "revise_architecture",
    "propose_plan",
]


@dataclass(frozen=True, slots=True)
class PlannerActionPolicy:
    """Legal planner actions and question targets for one turn."""

    allowed_action_kinds: tuple[PlannerActionKind, ...]
    allowed_ask_question_targets: tuple[str, ...] = ()
    architecture_refusal_code: AIBuilderErrorCode | None = None


def named_result_projection(
    session_state: PlanningState,
    *,
    is_edit_mode: bool = False,
) -> ProposalObligationProjection | None:
    """The user-attested result keys this turn holds the proposal to.

    One rule, read by the prompt, admission and the compiled postcondition,
    so the locations the model is told to declare and both verification arms
    can never disagree about which result paths are in play. An exact declared
    output schema is already authoritative, and edit mode has no create contract
    to verify, so both stand down.
    """

    if is_edit_mode:
        return None
    if session_state.commit_grade_slot_value("terminal_output") != "structured_json":
        return None
    output_evidence = session_state.output_schema_evidence
    if output_evidence is not None and output_evidence.source == "declared_schema":
        return None
    keys = tuple(
        ObligatedResultKey(
            name=item.name,
            placement=item.placement,
            declared_shape=item.declared_shape,
        )
        for item in session_state.named_result_evidence
        if item.is_commit_grade
    )
    return ProposalObligationProjection(keys=keys) if keys else None


def _named_result_projection_refusal_code(
    projection: ProposalObligationProjection | None,
) -> AIBuilderErrorCode | None:
    """Refuse a projection whose names cannot compile, before confirming.

    The check is about the stored spelling the user attested to: a name that
    only compiles after folding would reach the terminal contract under a
    different spelling than the one disclosed, so it is refused rather than
    quietly renamed. Count is not checked here: the attested contract no
    longer occupies schema space, and planning state's
    NAMED_RESULT_EVIDENCE_MAX_ITEMS is the single bound on how many named
    results a session can accumulate.
    """

    if projection is None:
        return None
    if any(
        not re.fullmatch(STRUCTURED_FIELD_NAME_PATTERN, key.name)
        for key in projection.keys
    ):
        return AIBuilderErrorCode.NAMED_RESULT_KEY_UNSUPPORTED
    return None


def build_planner_action_policy(
    *,
    session_state: PlanningState,
    selected_discovery_question_ids: tuple[str, ...],
    requirements_confirmed: bool = False,
    is_edit_mode: bool = False,
    schema_direction_pending: bool = False,
) -> PlannerActionPolicy:
    """Compute the legal action surface from typed server state.

    `selected_discovery_question_ids` is the backend-selected non-core
    discovery surface for this turn. Already resolved slots are removed
    here so a model cannot legally ask the user for facts already present
    in `PlanningState.resolved_slots`.
    """

    commit_grade_slot_names = _commit_grade_slot_names(session_state)
    unresolved_core_slots = _compute_unresolved_core_slots(
        session_state,
        is_edit_mode=is_edit_mode,
    )
    derived_commit = derive_architecture_commit_draft(session_state)
    architecture_refusal_code = _architecture_refusal_code(
        session_state,
        derived_commit=derived_commit,
        unresolved_core_slots=unresolved_core_slots,
    ) or (
        # An unresolved schema direction can still make the projection
        # inapplicable: selecting the attached schema as the output schema
        # stands the projection down entirely. Asking first is the only way
        # the refusal can be about the request the user actually made.
        None
        if schema_direction_pending
        else _named_result_projection_refusal_code(
            named_result_projection(session_state, is_edit_mode=is_edit_mode)
        )
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

    if architecture_refusal_code is not None:
        allowed.append("refuse_architecture_commit")

    if (
        not architecture_committed
        and not unresolved_core_slots
        and derived_commit is not None
    ):
        allowed.append("commit_architecture")

    if architecture_committed and architecture_drift_detected:
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
        architecture_refusal_code=architecture_refusal_code,
    )


def _architecture_refusal_code(
    session_state: PlanningState,
    *,
    derived_commit: ArchitectureCommitDraft | None,
    unresolved_core_slots: frozenset[str],
) -> AIBuilderErrorCode | None:
    if (
        session_state.commit_grade_slot_value("terminal_output") == "pdf_document"
        and session_state.commit_grade_slot_value("pdf_generation_mode")
        == "pdf_template_requested"
    ):
        return AIBuilderErrorCode.PDF_TEMPLATE_UNSUPPORTED
    if not unresolved_core_slots and derived_commit is None:
        return AIBuilderErrorCode.UNSUPPORTED_ARCHITECTURE

    architecture = derived_commit or session_state.architecture_commit
    if architecture is None:
        return None
    if not architecture_commit_hints_are_supported(architecture):
        return AIBuilderErrorCode.UNSUPPORTED_ARCHITECTURE

    runtime_input_type = (
        architecture.tuples_chain[0].input_type if architecture.tuples_chain else None
    )
    if transcript_checkpoint_requires_audio(
        session_state.checkpoint_intents,
        runtime_input_type=runtime_input_type,
    ):
        return AIBuilderErrorCode.TRANSCRIPT_CHECKPOINT_REQUIRES_AUDIO

    terminal_mode = (
        architecture.tuples_chain[-1].output_mode if architecture.tuples_chain else None
    )
    if terminal_mode is not FlowAuthoringOutputMode.TEMPLATE_FILL:
        return None
    selected_templates = [
        role for role in session_state.file_roles if role.role == "template"
    ]
    if not template_attachment_selection_is_valid(len(selected_templates)):
        return AIBuilderErrorCode.TEMPLATE_ATTACHMENT_SELECTION_INVALID
    if not selected_template_is_readable(selected_templates[0].template_placeholders):
        return AIBuilderErrorCode.TEMPLATE_ATTACHMENT_UNREADABLE
    return None


def _compute_unresolved_core_slots(
    planning_state: PlanningState,
    *,
    is_edit_mode: bool,
) -> frozenset[str]:
    """Architectural slots that lack evidence strong enough to close discovery.

    The create derivation owns which slots a new flow's architecture needs, so
    a slot it cannot commit without becomes a question here instead of a later
    failure. An edit inherits its topology from the existing flow, so only the
    two universal slots gate it.
    """

    required = (
        CORE_ARCHITECTURAL_SLOTS
        if is_edit_mode
        else architecture_required_slot_names(planning_state)
    )
    return required - _commit_grade_slot_names(planning_state)


def _commit_grade_slot_names(planning_state: PlanningState) -> frozenset[str]:
    return frozenset(
        name
        for name, slot in planning_state.resolved_slots.items()
        if slot.is_commit_grade
    )


def _phase_priority(candidates: list[PlannerActionKind]) -> list[PlannerActionKind]:
    """Expose one deterministic phase instead of a broad LLM action menu."""

    for action in (
        "refuse_architecture_commit",
        "revise_architecture",
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
    commit_grade_slot_names: frozenset[str],
) -> tuple[str, ...]:
    """Order hard core gaps and discovery-selected questions by one table."""

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

    for raw_target in sorted(architecture_required_slots):
        target = normalized_target(raw_target)
        if target is None or target in seen:
            continue
        selected.append(target)
        seen.add(target)
    # One order for gaps and discovery questions alike: the interaction policy
    # table, which puts the purpose before the input and output questions that
    # depend on it and every hard gate before any slot.
    ordered = sorted(
        selected,
        key=lambda target: (discovery_issue_priority(target), target),
    )
    return tuple(ordered)


__all__ = [
    "PlannerActionKind",
    "PlannerActionPolicy",
    "build_planner_action_policy",
    "named_result_projection",
]
