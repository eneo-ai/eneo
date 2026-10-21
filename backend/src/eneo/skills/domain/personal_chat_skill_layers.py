"""The personal chat's two Skill layers, and whether the personal one runs.

The organisation layer (the personal chat policy) always runs. The personal
layer (the person's own Skills) runs exactly as configured, or not at all, and
may never weaken the organisation layer. One pure assessment decides it for
saves, preflight, configuration reads and turns alike
(docs/adr/personal-chat-skill-layers.md, section 5).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from uuid import UUID

from eneo.completion_models.domain.skill_activation import (
    SkillActivationCandidateAssessment,
)
from eneo.files.attachment_budget import prompt_and_files_fit_context
from eneo.files.file_models import File
from eneo.skills.domain.skill import (
    PersonalSkillLayerDecision,
    PersonalSkillLayerReason,
    PersonalSkillLayerRejectedError,
    PersonalSkillLayerStatus,
    ResolvedSkillBinding,
    SkillActivationFallbackReason,
    SkillActivationMode,
    SkillActivationRejectionReason,
    SkillRuntimePolicy,
    SkillRuntimeResolution,
    SkillTurnEffectiveMode,
    SkillTurnPlan,
)


def compose_layers(
    *, organisation: SkillRuntimeResolution, personal: SkillRuntimeResolution
) -> SkillRuntimeResolution:
    """Organisation Skills first, then the person's, with contiguous positions.

    Positions are unique per resource across eligible and blocked bindings,
    and the two layers come from different resources, so both are renumbered
    over their union before being split back.
    """
    blocked_ids = {
        binding.skill_id for binding in (*organisation.blocked, *personal.blocked)
    }
    ordered = [
        *_by_position((*organisation.eligible, *organisation.blocked)),
        *_by_position((*personal.eligible, *personal.blocked)),
    ]
    renumbered = [
        replace(binding, position=position) for position, binding in enumerate(ordered)
    ]
    return SkillRuntimeResolution(
        eligible=tuple(b for b in renumbered if b.skill_id not in blocked_ids),
        blocked=tuple(b for b in renumbered if b.skill_id in blocked_ids),
    )


def assess_personal_skill_layer(
    *,
    base_instructions: str,
    organisation: SkillRuntimeResolution,
    personal: SkillRuntimeResolution,
    policy: SkillRuntimePolicy,
    holds_permission: bool,
    model_route: str,
    max_input_tokens: int,
    supports_tool_calling: bool,
    prompt_files: Sequence[File],
) -> PersonalSkillLayerDecision:
    """Decide whether the personal layer runs, from the existing calculators.

    Blocked bindings count as they will after release, as save validation
    does, so lifting a block can never reveal an invalid combination. The
    checks cover the persistent configuration; turn-time guards for history,
    uploads and live tool narrowing stay with the turn.
    """
    personal_bindings = (*personal.eligible, *personal.blocked)
    if not personal_bindings:
        return PersonalSkillLayerDecision(status=PersonalSkillLayerStatus.EMPTY)

    def suspended(
        reason: PersonalSkillLayerReason,
        detail: SkillActivationFallbackReason
        | SkillActivationRejectionReason
        | None = None,
    ) -> PersonalSkillLayerDecision:
        return PersonalSkillLayerDecision(
            status=PersonalSkillLayerStatus.SUSPENDED,
            reason=reason,
            detail=detail,
            bindings=personal.eligible,
        )

    if not holds_permission:
        return suspended(PersonalSkillLayerReason.PERMISSION_MISSING)
    attached = len(organisation.eligible) + len(organisation.blocked)
    if attached + len(personal_bindings) > policy.max_attached_skills:
        return suspended(PersonalSkillLayerReason.ATTACHMENT_LIMIT_EXCEEDED)

    def runtime(resolution: SkillRuntimeResolution):
        return (
            SkillTurnPlan.create(
                base_instructions=base_instructions,
                resolution=resolution,
                policy=policy,
            )
            .for_full_save_validation()
            .to_activation_runtime(
                selected_model_route=model_route,
                max_input_tokens=max_input_tokens,
                supports_tool_calling=supports_tool_calling,
            )
        )

    baseline = runtime(organisation)
    combined = runtime(compose_layers(organisation=organisation, personal=personal))

    if not prompt_and_files_fit_context(
        max_input_tokens=max_input_tokens,
        model_name=model_route,
        prompt_text=combined.prompt,
        files=prompt_files,
    ):
        return suspended(PersonalSkillLayerReason.MODEL_CONTEXT_EXCEEDED)

    personal_on_demand = _on_demand_ids(personal_bindings)
    combined_snapshot = combined.snapshot()
    if combined_snapshot.effective_mode is not SkillTurnEffectiveMode.SELECTIVE:
        if personal_on_demand:
            return suspended(
                PersonalSkillLayerReason.ON_DEMAND_UNAVAILABLE,
                combined_snapshot.fallback_reason,
            )
        if baseline.snapshot().effective_mode is SkillTurnEffectiveMode.SELECTIVE:
            return suspended(
                PersonalSkillLayerReason.ORGANISATION_SKILL_CROWDED_OUT,
                combined_snapshot.fallback_reason,
            )
        return _applied(personal)

    def rejection(
        assessment: SkillActivationCandidateAssessment,
    ) -> SkillActivationRejectionReason | None:
        """Why one activated candidate cannot run: its Skill allowance, or the
        whole prompt with the persistent files outgrowing the model window."""
        if assessment.rejection_reason is not None:
            return assessment.rejection_reason
        if not prompt_and_files_fit_context(
            max_input_tokens=max_input_tokens,
            model_name=model_route,
            prompt_text=assessment.prompt,
            files=prompt_files,
        ):
            return SkillActivationRejectionReason.MODEL_CONTEXT_LIMIT_EXCEEDED
        return None

    for assessment in combined.assess_on_demand_candidates(personal_on_demand):
        if (reason := rejection(assessment)) is not None:
            return suspended(
                PersonalSkillLayerReason.PERSONAL_SKILL_DOES_NOT_FIT, reason
            )

    organisation_on_demand = _on_demand_ids(
        (*organisation.eligible, *organisation.blocked)
    )
    admitted_alone = frozenset(
        assessment.skill_id
        for assessment in baseline.assess_on_demand_candidates(organisation_on_demand)
        if rejection(assessment) is None
    )
    for assessment in combined.assess_on_demand_candidates(admitted_alone):
        if (reason := rejection(assessment)) is not None:
            return suspended(
                PersonalSkillLayerReason.ORGANISATION_SKILL_CROWDED_OUT, reason
            )
    return _applied(personal)


def plan_personal_chat_turn(
    *,
    base_instructions: str,
    organisation: SkillRuntimeResolution,
    personal: SkillRuntimeResolution,
    policy: SkillRuntimePolicy,
    holds_permission: bool,
    model_route: str,
    max_input_tokens: int,
    supports_tool_calling: bool,
    prompt_files: Sequence[File],
) -> SkillTurnPlan:
    """The personal chat's turn plan, carrying the layer decision.

    An applied personal layer composes after the organisation layer; any
    other outcome plans the organisation layer alone.
    """
    decision = assess_personal_skill_layer(
        base_instructions=base_instructions,
        organisation=organisation,
        personal=personal,
        policy=policy,
        holds_permission=holds_permission,
        model_route=model_route,
        max_input_tokens=max_input_tokens,
        supports_tool_calling=supports_tool_calling,
        prompt_files=prompt_files,
    )
    return SkillTurnPlan.create(
        base_instructions=base_instructions,
        resolution=(
            compose_layers(organisation=organisation, personal=personal)
            if decision.applies
            else organisation
        ),
        policy=policy,
        personal_layer=decision,
    )


@dataclass(frozen=True)
class PersonalSkillLayerSave:
    """What a personal chat save changes, for the save transition rule."""

    before: PersonalSkillLayerDecision | None
    bindings_changed: bool
    removal_only: bool


def assert_personal_skill_layer_save(
    save: PersonalSkillLayerSave, after: PersonalSkillLayerDecision | None
) -> None:
    """Refuse a save whose own Skills would not run as configured.

    Switching the last Skill off and removing Skills are always allowed, so a
    person can recover after an administrator lowers a limit. A change that
    leaves the own Skills alone (a model switch, for instance) is refused only
    when it would break a layer that runs now; a layer already paused, or
    paused for a missing permission, never blocks it.
    """
    if after is None or after.status is not PersonalSkillLayerStatus.SUSPENDED:
        return
    if save.bindings_changed:
        if save.removal_only:
            return
        raise PersonalSkillLayerRejectedError(after)
    if (
        save.before is not None
        and save.before.applies
        and after.reason is not PersonalSkillLayerReason.PERMISSION_MISSING
    ):
        raise PersonalSkillLayerRejectedError(after)


def _applied(personal: SkillRuntimeResolution) -> PersonalSkillLayerDecision:
    return PersonalSkillLayerDecision(
        status=PersonalSkillLayerStatus.APPLIED, bindings=personal.eligible
    )


def _by_position(
    bindings: Iterable[ResolvedSkillBinding],
) -> list[ResolvedSkillBinding]:
    return sorted(bindings, key=lambda binding: binding.position)


def _on_demand_ids(bindings: Iterable[ResolvedSkillBinding]) -> frozenset[UUID]:
    return frozenset(
        binding.skill_id
        for binding in bindings
        if binding.activation_mode is SkillActivationMode.ON_DEMAND
    )


__all__ = [
    "PersonalSkillLayerDecision",
    "PersonalSkillLayerSave",
    "assert_personal_skill_layer_save",
    "PersonalSkillLayerReason",
    "PersonalSkillLayerStatus",
    "assess_personal_skill_layer",
    "compose_layers",
    "plan_personal_chat_turn",
]
