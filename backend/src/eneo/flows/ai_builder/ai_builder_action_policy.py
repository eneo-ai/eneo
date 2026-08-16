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
    architecture_commit_hints_are_supported,
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

_CORE_ARCHITECTURAL_SLOTS: frozenset[str] = frozenset(
    {"primary_runtime_input", "terminal_output"}
)

# How many user-named result keys one create schema projects. Its own
# constant on purpose: the classifier's per-delta citation bound is a
# different contract, and obligations accumulate across turns while
# citations do not. The observed corpus maximum is 9.
NAMED_RESULT_PROJECTION_MAX_ITEMS = 12
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
    """The obligation keys this turn projects into the create tool schema.

    One rule, read by both admission and the schema builder, so the refusal
    the user sees before confirming and the schema the model later answers
    can never disagree about which names are in play. An exact declared
    output schema is already authoritative, and edit mode has no create
    schema to project into, so both stand down.
    """

    if is_edit_mode:
        return None
    if session_state.commit_grade_slot_value("terminal_output") != "structured_json":
        return None
    output_evidence = session_state.output_schema_evidence
    if output_evidence is not None and output_evidence.source == "declared_schema":
        return None
    keys = tuple(
        ObligatedResultKey(name=item.name, declared_shape=item.declared_shape)
        for item in session_state.named_result_evidence
        if item.is_commit_grade
    )
    return ProposalObligationProjection(keys=keys) if keys else None


def _named_result_projection_refusal_code(
    projection: ProposalObligationProjection | None,
) -> AIBuilderErrorCode | None:
    """Refuse a projection the create schema cannot express, before confirming.

    Both checks are about the stored spelling the user attested to. A name
    that only compiles after folding would reach the terminal contract under
    a different spelling than the one disclosed, so it is refused rather than
    quietly renamed.
    """

    if projection is None:
        return None
    if len(projection.keys) > NAMED_RESULT_PROJECTION_MAX_ITEMS:
        return AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED
    if any(
        not re.fullmatch(STRUCTURED_FIELD_NAME_PATTERN, key.name)
        for key in projection.keys
    ):
        return AIBuilderErrorCode.NAMED_RESULT_KEY_UNSUPPORTED
    if len(projection.keys) == 1 and projection.keys[0].declared_shape == "object":
        # An object must declare nested fields, and the only thing that can
        # nest inside a projected key is another projected key. A lone
        # declared object is therefore a grain no proposal can satisfy — it
        # would loop the repair path instead of failing — so it is refused
        # while the user can still say what belongs inside it. The name is
        # perfectly valid, so this is its own code: telling the user to fix
        # the spelling of a name that is already fine is worse than silence.
        return AIBuilderErrorCode.NAMED_RESULT_GRAIN_UNSUPPORTED
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
    unresolved_core_slots = _compute_unresolved_core_slots(session_state)
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
        architecture_refusal_code=architecture_refusal_code,
    )


def _architecture_refusal_code(
    session_state: PlanningState,
    *,
    derived_commit: ArchitectureCommitDraft | None,
    unresolved_core_slots: frozenset[str],
) -> AIBuilderErrorCode | None:
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
        "refuse_architecture_commit",
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
    ordered = missing_core + [
        target for target in selected if target not in missing_core
    ]
    # Purpose-first: when discovery selected the vague processing goal as its
    # top question it outranks every core gap except the primary runtime
    # input — asking for an output format before the purpose is backwards.
    if selected and selected[0] == "post_processing_goal":
        ordered.remove("post_processing_goal")
        insert_at = 1 if ordered and ordered[0] == "primary_runtime_input" else 0
        ordered.insert(insert_at, "post_processing_goal")
    return tuple(ordered)


__all__ = [
    "NAMED_RESULT_PROJECTION_MAX_ITEMS",
    "PlannerActionKind",
    "PlannerActionPolicy",
    "build_planner_action_policy",
    "named_result_projection",
]
